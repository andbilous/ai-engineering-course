from __future__ import annotations

from typing import Any

AGENT_INFO = {
    "user": {"emoji": "👤", "name": "User", "sub": "ваш запит"},
    "synthesizer": {"emoji": "🧩", "name": "Synthesizer", "sub": "класифікація + відповідь"},
    "analyst": {"emoji": "📊", "name": "Analyst", "sub": "дані та факти"},
    "advisor": {"emoji": "💰", "name": "Advisor", "sub": "поради та безпека"},
    "baseline": {"emoji": "🤖", "name": "Baseline", "sub": "один агент + всі інструменти"},
}


def summarize_trace(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in result.get("trace", []):
        agent_key = event.get("agent", "baseline")
        info = AGENT_INFO.get(agent_key, AGENT_INFO["baseline"])
        tool_names = [call["tool"] for call in event.get("tool_calls", [])]
        rows.append(
            {
                "agent": f"{info['emoji']} {info['name']}",
                "phase": event.get("phase", ""),
                "route": event.get("route", ""),
                "tools": ", ".join(tool_names) if tool_names else "—",
                "answer_preview": event.get("answer", "")[:160],
            }
        )
    return rows


def usage_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    usage = result.get("usage", {})
    rows = []
    for agent, metrics in usage.get("by_agent", {}).items():
        info = AGENT_INFO.get(agent, {"emoji": "🤖", "name": agent, "sub": ""})
        rows.append(
            {
                "agent": f"{info['emoji']} {info['name']}",
                "calls": metrics["calls"],
                "tokens": metrics["total_tokens"],
                "cost_usd": metrics["cost_usd"],
                "latency_ms": metrics["latency_ms"],
            }
        )
    return rows
