from __future__ import annotations

from typing import Any, TypedDict


class ToolTrace(TypedDict, total=False):
    tool: str
    args: dict[str, Any]
    result: dict[str, Any]


class AgentResult(TypedDict, total=False):
    agent: str
    answer: str
    tool_calls: list[ToolTrace]
    iterations: int


class TraceEvent(TypedDict, total=False):
    agent: str
    phase: str
    route: str
    answer: str
    tool_calls: list[ToolTrace]


class FinanceState(TypedDict, total=False):
    query: str
    thread_id: str
    conversation_history: list[dict[str, str]]
    route_decision: str
    route_reason: str
    stats_result: AgentResult | None
    savings_result: AgentResult | None
    fraud_result: AgentResult | None
    final_answer: str
    route_trace: TraceEvent | None
    final_trace: TraceEvent | None
