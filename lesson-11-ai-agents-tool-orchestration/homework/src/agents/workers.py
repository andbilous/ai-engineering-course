from __future__ import annotations

import json
import re
from typing import Any

from src.llm import LLMUsage, call_llm
from src.tools import TOOL_REGISTRY, TOOL_SCHEMAS

_ANALYST_TOOLS = [
    "query_transactions",
    "aggregate_by_category",
    "aggregate_by_merchant",
    "get_monthly_summary",
    "compare_periods",
]
_ADVISOR_TOOLS = [
    "query_transactions",
    "aggregate_by_category",
    "get_subscription_report",
    "detect_patterns",
    "detect_fraud",
]


def _conversation_block(conversation_history: list[dict[str, str]] | None) -> str:
    if not conversation_history:
        return "Попереднього контексту немає."
    lines = []
    for message in conversation_history[-8:]:
        role = "Користувач" if message["role"] == "user" else "Асистент"
        lines.append(f"{role}: {message['content']}")
    return "\n".join(lines)


def _extract_text_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        return "\n".join(part for part in text_parts if part)
    return str(content)


def _load_json_response(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.DOTALL)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _normalize_route(query: str, raw_route: str | None) -> str:
    allowed = {"stats", "savings", "fraud", "multi_step", "out_of_scope"}
    if raw_route in allowed:
        return raw_route

    query_norm = query.lower()
    if any(token in query_norm for token in ["fraud", "booking.com", "aliexpress", "не робила", "підозр"]):
        return "fraud"
    if any(token in query_norm for token in ["купи", "купи мені", "акції", "заблокуй"]):
        return "out_of_scope"
    if any(token in query_norm for token in ["порівняй", "порівняти", "якщо", "буде", "рік", "сценар"]):
        return "multi_step"
    if any(token in query_norm for token in ["зеконом", "порада", "підпис", "кредитн"]):
        return "savings"
    return "stats"


def infer_route_from_query(query: str) -> str:
    return _normalize_route(query, None)


def _execute_tool_calls(
    tool_calls: list[Any],
    allowed_tool_names: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tool_messages: list[dict[str, Any]] = []
    tool_trace: list[dict[str, Any]] = []

    for tool_call in tool_calls:
        name = tool_call.function.name
        if name not in allowed_tool_names:
            raise ValueError(f"Tool '{name}' is not allowed for this agent.")

        arguments: dict[str, Any] = {}
        try:
            arguments = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError as exc:
            result = {"error": f"Invalid tool arguments JSON: {exc.msg}"}
        else:
            try:
                result = TOOL_REGISTRY[name](**arguments)
            except (TypeError, ValueError) as exc:
                result = {"error": str(exc)}

        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": name,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )
        tool_trace.append({"tool": name, "args": arguments, "result": result})

    return tool_messages, tool_trace


def _run_agent(
    agent_name: str,
    system_prompt: str,
    user_prompt: str,
    tool_names: list[str],
    usage: LLMUsage,
    max_iterations: int = 5,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    all_tool_calls: list[dict[str, Any]] = []
    relative_period_requested = any(
        token in user_prompt.lower()
        for token in [
            "last week",
            "this month",
            "last month",
            "this year",
            "last year",
            "минулого тижня",
            "цього місяця",
            "минулого місяця",
            "цього року",
            "минулого року",
        ]
    )
    fraud_requested = any(
        token in user_prompt.lower()
        for token in [
            "fraud",
            "booking.com",
            "aliexpress",
            "підозр",
            "не робила",
            "не робив",
            "списання",
        ]
    )

    for iteration in range(max_iterations):
        response = call_llm(
            messages=messages,
            agent_name=agent_name,
            usage=usage,
            tools=[tool for tool in TOOL_SCHEMAS if tool["function"]["name"] in tool_names],
        )
        assistant_message = response.choices[0].message
        assistant_payload: dict[str, Any] = {"role": "assistant"}
        if assistant_message.content is not None:
            assistant_payload["content"] = _extract_text_content(assistant_message.content)
        if assistant_message.tool_calls:
            assistant_payload["tool_calls"] = [
                call.model_dump(exclude_none=True) for call in assistant_message.tool_calls
            ]
        messages.append(assistant_payload)

        if assistant_message.tool_calls:
            tool_messages, tool_trace = _execute_tool_calls(assistant_message.tool_calls, tool_names)
            all_tool_calls.extend(tool_trace)
            messages.extend(tool_messages)
            continue

        answer_text = _extract_text_content(assistant_message.content).strip()
        if (
            relative_period_requested
            and not all_tool_calls
            and iteration < max_iterations - 1
            and (
                "точні дати" in answer_text.lower()
                or "я не знаю" in answer_text.lower()
                or "уточни" in answer_text.lower()
            )
        ):
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Нагадування: tools already support relative dates like "
                        "'last week', 'this month', 'минулого тижня'. "
                        "Не проси уточнення — виклич відповідний tool зараз."
                    ),
                }
            )
            continue

        if (
            fraud_requested
            and not all_tool_calls
            and iteration < max_iterations - 1
        ):
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Fraud query detected. Before answering you MUST call detect_fraud "
                        "and, if needed, query_transactions. Response must be grounded in tool output."
                    ),
                }
            )
            continue

        return {
            "agent": agent_name,
            "answer": answer_text,
            "tool_calls": all_tool_calls,
            "iterations": iteration + 1,
        }

    return {
        "agent": agent_name,
        "answer": "Не вдалося завершити відповідь в межах ліміту ітерацій.",
        "tool_calls": all_tool_calls,
        "iterations": max_iterations,
    }


def synthesizer_agent(
    query: str,
    conversation_history: list[dict[str, str]] | None,
    usage: LLMUsage,
    stats_result: dict[str, Any] | None = None,
    savings_result: dict[str, Any] | None = None,
    fraud_result: dict[str, Any] | None = None,
    route_decision: str | None = None,
) -> dict[str, Any]:
    history_block = _conversation_block(conversation_history)

    if stats_result is None and savings_result is None and fraud_result is None and route_decision is None:
        system_prompt = """Ти Synthesizer-router для Personal Finance Coach.
Класифікуй запит в один з маршрутів:
- stats: факти, суми, топ-категорії, останні транзакції
- savings: де зекономити, підписки, кредитка, оптимізація витрат
- fraud: підозрілі транзакції, disputed transactions, заперечення списання
- multi_step: порівняння періодів, прогнози, сценарії "якщо"
- out_of_scope: дії поза аналітикою та підтримкою (купити акції, виконати банківську дію)

Враховуй multi-turn контекст. Поверни ТІЛЬКИ JSON без markdown:
{"route_decision":"stats|savings|fraud|multi_step|out_of_scope","reason":"коротко"}"""
        user_prompt = (
            f"Попередній контекст:\n{history_block}\n\n"
            f"Новий запит користувача:\n{query}"
        )
        response = call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            agent_name="synthesizer_route",
            usage=usage,
        )
        parsed = _load_json_response(_extract_text_content(response.choices[0].message.content))
        route = _normalize_route(query, parsed.get("route_decision"))
        return {"route_decision": route, "reason": parsed.get("reason", "")}

    system_prompt = """Ти фінальний Synthesizer для Personal Finance Coach.
Пиши українською, дружньо, на "ти". Усі числа бери лише з наданих результатів інструментів.
Правила:
- без hallucinations і без вигаданих сум;
- якщо тема про fraud: співчутливо поясни, що треба звернутися в підтримку, не вдавай ніби вже заблокував картку;
- якщо запит out_of_scope: ввічливо відмов і запропонуй доступні фінансові аналітичні функції;
- якщо є конкретні способи зекономити, давай actionable-кроки з числами;
- якщо користувач ставить follow-up, враховуй попередній контекст.
Не згадуй внутрішні інструменти або маршрути."""

    specialist_payload = {
        "route_decision": route_decision,
        "stats_result": stats_result,
        "savings_result": savings_result,
        "fraud_result": fraud_result,
    }
    user_prompt = (
        f"Попередній контекст:\n{history_block}\n\n"
        f"Поточний запит:\n{query}\n\n"
        f"Результати спеціалістів:\n{json.dumps(specialist_payload, ensure_ascii=False, indent=2)}"
    )
    response = call_llm(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        agent_name="synthesizer_final",
        usage=usage,
    )
    return {
        "agent": "synthesizer",
        "answer": _extract_text_content(response.choices[0].message.content).strip(),
        "tool_calls": [],
        "iterations": 1,
    }


def analyst_agent(
    query: str,
    conversation_history: list[dict[str, str]] | None,
    usage: LLMUsage,
) -> dict[str, Any]:
    system_prompt = """Ти Financial Analyst.
Твоя задача: швидко і точно відповідати на запити про суми, періоди, категорії, мерчантів і порівняння.
Обов'язково використовуй інструменти для будь-яких чисел.
Dataset покриває грудень 2024 - листопад 2025. Якщо користувач каже "цей місяць", орієнтуйся на останній місяць у даних.
Інструменти вже вміють обробляти відносні періоди на кшталт "last week", "this month", "минулого тижня".
Лексичні варіанти на кшталт "кава/каву" відповідають категорії `coffee`, "доставка" відповідає `delivery`.
Не проси уточнення дати, якщо можна передати relative period прямо в tool.
Коли відповідь готова, сформулюй коротко українською."""
    user_prompt = (
        f"Попередній контекст:\n{_conversation_block(conversation_history)}\n\n"
        f"Поточний запит:\n{query}"
    )
    return _run_agent("analyst", system_prompt, user_prompt, _ANALYST_TOOLS, usage)


def advisor_agent(
    query: str,
    conversation_history: list[dict[str, str]] | None,
    usage: LLMUsage,
) -> dict[str, Any]:
    fraud_mode = any(
        token in query.lower()
        for token in ["fraud", "booking.com", "aliexpress", "підозр", "не робила", "списання"]
    )
    system_prompt = """Ти Savings Advisor.
Ти шукаєш конкретні шляхи економії, аналізуєш підписки, звички та ризикові транзакції.
Усі поради мають спиратися на реальні числа з інструментів.
Інструменти вже вміють обробляти відносні періоди на кшталт "last week", "this month", "минулого тижня".
Лексичні варіанти на кшталт "кава/каву" відповідають категорії `coffee`, "доставка" відповідає `delivery`.
Для fraud не вирішуй проблему самостійно — тільки опиши ризик і поради звернутися в підтримку.
Пиши українською, дружньо і без загальних фраз."""
    if fraud_mode:
        system_prompt += (
            "\nДля будь-якого suspicious/disputed transaction ти ЗОБОВ'ЯЗАНИЙ спочатку викликати "
            "`detect_fraud`, а потім спиратися на його результат."
        )
    user_prompt = (
        f"Попередній контекст:\n{_conversation_block(conversation_history)}\n\n"
        f"Поточний запит:\n{query}"
    )
    return _run_agent("advisor", system_prompt, user_prompt, _ADVISOR_TOOLS, usage)
