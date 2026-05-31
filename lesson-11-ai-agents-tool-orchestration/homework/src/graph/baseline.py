from __future__ import annotations

from typing import Any

from src.agents.workers import _conversation_block, _run_agent, infer_route_from_query
from src.llm import LLMUsage
from src.tools import TOOL_REGISTRY


def run_baseline(
    query: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    usage = LLMUsage()
    system_prompt = """Ти Personal Finance Coach у single-agent baseline режимі.
Ти вмієш:
- відповідати на factual spending запити;
- шукати шляхи економії та аналізувати підписки;
- робити multi-step порівняння та прості сценарії;
- розпізнавати fraud і скеровувати в підтримку;
- ввічливо відхиляти out-of-scope запити.

Правила:
- усі числа береш тільки з інструментів;
- інструменти вже вміють працювати з relative periods на кшталт "last week", "this month", "минулого тижня", тож не проси зайвих уточнень дат;
- слова на кшталт "кава/каву" — це категорія `coffee`, а "доставка" — категорія `delivery`;
- українська мова, дружній тон;
- якщо користувач просить виконати дію поза твоїми можливостями, поясни межі і запропонуй доступні функції;
- якщо тема про fraud, не вдавай що заблокував картку сам."""
    user_prompt = (
        f"Попередній контекст:\n{_conversation_block(conversation_history)}\n\n"
        f"Поточний запит:\n{query}"
    )
    result = _run_agent(
        agent_name="baseline",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        tool_names=list(TOOL_REGISTRY),
        usage=usage,
        max_iterations=8,
    )
    return {
        "architecture": "baseline",
        "answer": result["answer"],
        "route_decision": infer_route_from_query(query),
        "tool_calls": result["tool_calls"],
        "usage": usage.to_dict(),
        "trace": [
            {
                "agent": "baseline",
                "phase": "single_agent",
                "route": infer_route_from_query(query),
                "answer": result["answer"],
                "tool_calls": result["tool_calls"],
            }
        ],
    }


def baseline_mermaid() -> str:
    return "flowchart LR\n    user([User]) --> baseline[Baseline Agent + Tools]\n    baseline --> answer([Answer])"
