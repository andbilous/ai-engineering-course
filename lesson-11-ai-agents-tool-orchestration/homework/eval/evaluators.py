from __future__ import annotations

import json
import re
from statistics import mean
from typing import Any, Callable

import pandas as pd

from eval.golden_set import GOLDEN_SET
from src.graph import run_baseline, run_crew
from src.judge import judge_single_answer

_ROUTE_ALLOWED_TOOLS = {
    "stats": {
        "query_transactions",
        "aggregate_by_category",
        "aggregate_by_merchant",
        "get_monthly_summary",
        "compare_periods",
        "detect_patterns",
    },
    "savings": {
        "query_transactions",
        "aggregate_by_category",
        "get_subscription_report",
        "detect_patterns",
        "detect_fraud",
    },
    "fraud": {"detect_fraud", "query_transactions"},
    "multi_step": {
        "query_transactions",
        "aggregate_by_category",
        "aggregate_by_merchant",
        "get_monthly_summary",
        "compare_periods",
        "get_subscription_report",
        "detect_patterns",
        "detect_fraud",
    },
    "out_of_scope": set(),
}
_GROUNDEDNESS_KEY_TOKENS = (
    "amount",
    "total",
    "income",
    "expense",
    "expenses",
    "net",
    "avg",
    "average",
    "estimate",
    "share",
    "pct",
    "count",
    "charge",
    "spent",
    "payment",
    "latency",
    "tokens",
    "cost",
)


def _extract_numbers(text: str) -> list[float]:
    values = []
    for raw in re.findall(r"-?\d+(?:\.\d+)?", text):
        values.append(float(raw))
    return values


def _extract_tool_numbers(value: Any, parent_key: str = "") -> list[float]:
    numbers: list[float] = []
    if isinstance(value, dict):
        for key, item in value.items():
            numbers.extend(_extract_tool_numbers(item, key))
        return numbers
    if isinstance(value, list):
        for item in value:
            numbers.extend(_extract_tool_numbers(item, parent_key))
        return numbers
    if isinstance(value, (int, float)):
        key_norm = parent_key.lower()
        if any(token in key_norm for token in _GROUNDEDNESS_KEY_TOKENS):
            numbers.append(float(value))
    return numbers


def groundedness(answer: str, tool_calls: list[dict[str, Any]]) -> float:
    answer_numbers = _extract_numbers(answer)
    if not answer_numbers:
        return 1.0

    tool_numbers: list[float] = []
    for call in tool_calls:
        tool_numbers.extend(_extract_tool_numbers(call.get("result", {})))

    if not tool_numbers:
        return 0.0

    matches = 0
    for value in answer_numbers:
        tolerance = max(abs(value) * 0.02, 1.0)
        if any(abs(value - candidate) <= tolerance for candidate in tool_numbers):
            matches += 1
    return round(matches / len(answer_numbers), 4)


def tool_selection_accuracy(
    expected_route: str,
    result: dict[str, Any],
    preferred_tools: list[str] | None = None,
) -> float:
    tool_calls = []
    for event in result.get("trace", []):
        tool_calls.extend(event.get("tool_calls", []))

    used = {call["tool"] for call in tool_calls}
    allowed = _ROUTE_ALLOWED_TOOLS.get(expected_route, set())
    preferred = set(preferred_tools or [])

    if expected_route == "out_of_scope":
        return 1.0 if not used else 0.0

    if not used:
        return 0.0

    allowed_score = 1.0 if used.issubset(allowed) else 0.5
    if not preferred:
        return allowed_score

    preferred_score = len(used & preferred) / len(preferred)
    return round((allowed_score + preferred_score) / 2, 4)


def inter_agent_overhead_pct(result: dict[str, Any]) -> float:
    usage = result.get("usage", {})
    total_tokens = usage.get("total_tokens", 0)
    if not total_tokens:
        return 0.0

    synth_tokens = 0
    for agent, metrics in usage.get("by_agent", {}).items():
        if str(agent).startswith("synthesizer"):
            synth_tokens += int(metrics["total_tokens"])
    return round((synth_tokens / total_tokens) * 100, 2)


def cost_breakdown_by_agent(result: dict[str, Any]) -> dict[str, float]:
    return {
        agent: round(float(metrics["cost_usd"]), 8)
        for agent, metrics in result.get("usage", {}).get("by_agent", {}).items()
    }


def _run_architecture(query: str, architecture: str, case_id: str) -> dict[str, Any]:
    if architecture == "crew":
        return run_crew(query, thread_id=f"eval-{case_id}")
    return run_baseline(query)


def evaluate_case(case: dict[str, Any], architecture: str) -> dict[str, Any]:
    result = _run_architecture(case["query"], architecture, case["id"])
    answer = result["answer"]
    tool_calls = []
    for event in result.get("trace", []):
        tool_calls.extend(event.get("tool_calls", []))

    judge = judge_single_answer(
        query=case["query"],
        answer=answer,
        expected_patterns=case.get("expected_patterns"),
    )
    usage = result.get("usage", {})
    return {
        "status": "ok",
        "error": None,
        "architecture": architecture,
        "case_id": case["id"],
        "query": case["query"],
        "expected_route": case["expected_route"],
        "predicted_route": result.get("route_decision", ""),
        "route_accuracy": float(result.get("route_decision", "") == case["expected_route"]),
        "difficulty": case["difficulty"],
        "answer": answer,
        "latency_ms": usage.get("total_latency_ms", 0),
        "cost_usd": usage.get("total_cost_usd", 0.0),
        "tokens": usage.get("total_tokens", 0),
        "judge_average": judge.get("average_score", 0),
        "judge_passed": bool(judge.get("passed", False)),
        "judge_verdict": judge.get("verdict", ""),
        "judge_error": judge.get("error"),
        "groundedness": groundedness(answer, tool_calls),
        "tool_selection_accuracy": tool_selection_accuracy(
            case["expected_route"],
            result,
            case.get("preferred_tools"),
        ),
        "inter_agent_overhead_pct": inter_agent_overhead_pct(result) if architecture == "crew" else 0.0,
        "cost_breakdown_by_agent": cost_breakdown_by_agent(result),
    }


def _error_row(case: dict[str, Any], architecture: str, error: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": error,
        "architecture": architecture,
        "case_id": case["id"],
        "query": case["query"],
        "expected_route": case["expected_route"],
        "predicted_route": "",
        "route_accuracy": 0.0,
        "difficulty": case["difficulty"],
        "answer": "",
        "latency_ms": 0,
        "cost_usd": 0.0,
        "tokens": 0,
        "judge_average": 0.0,
        "judge_passed": False,
        "judge_verdict": "runtime_error",
        "judge_error": None,
        "groundedness": 0.0,
        "tool_selection_accuracy": 0.0,
        "inter_agent_overhead_pct": 0.0,
        "cost_breakdown_by_agent": {},
    }


def _summary_from_df(df: pd.DataFrame) -> dict[str, Any]:
    valid_df = df[df["status"] == "ok"].reset_index(drop=True)
    summary: dict[str, Any] = {
        "tasks": int(len(df)),
        "completed_tasks": int(len(valid_df)),
        "failed_tasks": int(len(df) - len(valid_df)),
        "latency_p50_ms": float(valid_df["latency_ms"].median()) if not valid_df.empty else 0.0,
        "latency_p95_ms": float(valid_df["latency_ms"].quantile(0.95)) if not valid_df.empty else 0.0,
        "cost_per_task_usd": float(valid_df["cost_usd"].mean()) if not valid_df.empty else 0.0,
        "tokens_per_task": float(valid_df["tokens"].mean()) if not valid_df.empty else 0.0,
        "success_rate": float(valid_df["judge_passed"].mean()) if not valid_df.empty else 0.0,
        "route_accuracy": float(valid_df["route_accuracy"].mean()) if not valid_df.empty else 0.0,
        "tool_selection_accuracy": float(valid_df["tool_selection_accuracy"].mean()) if not valid_df.empty else 0.0,
        "groundedness": float(valid_df["groundedness"].mean()) if not valid_df.empty else 0.0,
    }
    if "inter_agent_overhead_pct" in valid_df:
        summary["inter_agent_overhead_pct"] = (
            float(valid_df["inter_agent_overhead_pct"].mean()) if not valid_df.empty else 0.0
        )

    breakdowns = {}
    for item in valid_df["cost_breakdown_by_agent"]:
        for agent, value in item.items():
            breakdowns.setdefault(agent, []).append(value)
    return summary


def _cost_breakdown_df(df: pd.DataFrame) -> pd.DataFrame:
    valid_df = df[df["status"] == "ok"].reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for architecture in sorted(valid_df["architecture"].unique()):
        subset = valid_df[valid_df["architecture"] == architecture]
        breakdowns: dict[str, list[float]] = {}
        for item in subset["cost_breakdown_by_agent"]:
            for agent, value in item.items():
                breakdowns.setdefault(agent, []).append(value)
        for agent, values in breakdowns.items():
            rows.append(
                {
                    "architecture": architecture,
                    "agent": agent,
                    "avg_cost_usd": round(mean(values), 8),
                }
            )
    return pd.DataFrame(rows)


def run_benchmark(
    cases: list[dict[str, Any]] | None = None,
    progress_callback: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    selected_cases = cases or GOLDEN_SET
    rows = []
    completed = 0
    total = len(selected_cases) * 2
    for architecture in ("crew", "baseline"):
        for case in selected_cases:
            try:
                row = evaluate_case(case, architecture)
            except Exception as exc:
                row = _error_row(case, architecture, str(exc))
            rows.append(row)
            completed += 1
            if progress_callback:
                progress_callback(completed, total, row)

    df = pd.DataFrame(rows)
    crew_df = df[df["architecture"] == "crew"].reset_index(drop=True)
    baseline_df = df[df["architecture"] == "baseline"].reset_index(drop=True)
    return {
        "cases": selected_cases,
        "results_df": df,
        "crew_df": crew_df,
        "baseline_df": baseline_df,
        "summary_df": pd.DataFrame(
            [
                {"architecture": "crew", **_summary_from_df(crew_df)},
                {"architecture": "baseline", **_summary_from_df(baseline_df)},
            ]
        ),
        "avg_cost_by_agent_df": _cost_breakdown_df(df),
        "failed_df": df[df["status"] == "error"].reset_index(drop=True),
    }


if __name__ == "__main__":
    benchmark = run_benchmark()
    print(benchmark["summary_df"].to_string(index=False))
