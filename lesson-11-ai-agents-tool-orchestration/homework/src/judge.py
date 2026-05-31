from __future__ import annotations

import json
import re
from typing import Any

from src.llm import DEFAULT_MODEL, LLMUsage, call_llm


def _parse_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.DOTALL)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or start >= end:
            raise
        return json.loads(candidate[start : end + 1])


def _empty_judgement(
    usage: LLMUsage,
    verdict: str,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "scores": {
            "groundedness": 0,
            "specificity": 0,
            "actionability": 0,
            "tone": 0,
        },
        "average_score": 0.0,
        "passed": False,
        "verdict": verdict,
        "error": error,
        "usage": usage.to_dict(),
    }


def _normalize_judge_payload(result: dict[str, Any], usage: LLMUsage) -> dict[str, Any]:
    scores = result.get("scores")
    if not isinstance(scores, dict):
        scores = {}

    normalized_scores: dict[str, float] = {}
    for key in ("groundedness", "specificity", "actionability", "tone"):
        value = scores.get(key, 0)
        try:
            normalized_scores[key] = float(value)
        except (TypeError, ValueError):
            normalized_scores[key] = 0.0

    average_score = round(sum(normalized_scores.values()) / len(normalized_scores), 4)
    passed_value = result.get("passed")
    if isinstance(passed_value, bool):
        passed = passed_value
    else:
        passed = average_score >= 7.0

    return {
        "scores": normalized_scores,
        "average_score": average_score,
        "passed": passed,
        "verdict": str(result.get("verdict", "")).strip() or "ok",
        "error": result.get("error"),
        "usage": usage.to_dict(),
    }


def judge_single_answer(
    query: str,
    answer: str,
    expected_patterns: list[str] | None = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    usage = LLMUsage()
    prompt = f"""Оціни відповідь фінансового асистента за 4 критеріями від 0 до 10:
1. groundedness — чи спирається на дані без вигаданих чисел
2. specificity — чи є конкретика замість загальних фраз
3. actionability — чи є чіткий наступний крок, коли він доречний
4. tone — чи дружньо, емпатично і без менторства

Запит:
{query}

Відповідь:
{answer}

Очікувані патерни:
{json.dumps(expected_patterns or [], ensure_ascii=False)}

Поверни лише JSON:
{{
  "scores": {{
    "groundedness": 0,
    "specificity": 0,
    "actionability": 0,
    "tone": 0
  }},
  "average_score": 0,
  "passed": true,
  "verdict": "..."
}}"""
    try:
        response = call_llm(
            messages=[
                {"role": "system", "content": "Ти суворий, але справедливий LLM-as-judge."},
                {"role": "user", "content": prompt},
            ],
            agent_name="judge_single",
            usage=usage,
            model=model,
            temperature=0.0,
        )
        content = response.choices[0].message.content or "{}"
        result = _parse_json(content)
    except Exception as exc:
        return _empty_judgement(usage, verdict="judge_error", error=str(exc))
    return _normalize_judge_payload(result, usage)


def judge_pairwise(
    query: str,
    answer_a: str,
    answer_b: str,
    label_a: str = "crew",
    label_b: str = "baseline",
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    usage = LLMUsage()
    prompt = f"""Порівняй дві відповіді на один фінансовий запит.
Критерії: groundedness, specificity, actionability, tone.
Поверни лише JSON:
{{
  "winner": "{label_a}|{label_b}|tie",
  "reason": "...",
  "scores": {{
    "{label_a}": {{"groundedness": 0, "specificity": 0, "actionability": 0, "tone": 0}},
    "{label_b}": {{"groundedness": 0, "specificity": 0, "actionability": 0, "tone": 0}}
  }}
}}

Запит:
{query}

Відповідь {label_a}:
{answer_a}

Відповідь {label_b}:
{answer_b}"""
    try:
        response = call_llm(
            messages=[
                {"role": "system", "content": "Ти нейтральний judge для side-by-side порівняння."},
                {"role": "user", "content": prompt},
            ],
            agent_name="judge_pairwise",
            usage=usage,
            model=model,
            temperature=0.0,
        )
        result = _parse_json(response.choices[0].message.content or "{}")
    except Exception as exc:
        return {
            "winner": "tie",
            "reason": "judge_error",
            "error": str(exc),
            "scores": {
                label_a: {"groundedness": 0, "specificity": 0, "actionability": 0, "tone": 0},
                label_b: {"groundedness": 0, "specificity": 0, "actionability": 0, "tone": 0},
            },
            "usage": usage.to_dict(),
        }
    result["usage"] = usage.to_dict()
    return result
