from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.agents import advisor_agent, analyst_agent, synthesizer_agent
from src.llm import LLMUsage
from src.schemas import FinanceState


def _get_usage(config: RunnableConfig) -> LLMUsage:
    usage = config.get("configurable", {}).get("usage")
    if usage is None:
        raise ValueError("LLMUsage instance is missing from graph config.")
    return usage


def synthesizer_route_node(state: FinanceState, config: RunnableConfig) -> FinanceState:
    result = synthesizer_agent(
        query=state["query"],
        conversation_history=state.get("conversation_history"),
        usage=_get_usage(config),
    )
    return {
        "route_decision": result["route_decision"],
        "route_reason": result.get("reason", ""),
        "route_trace": {
            "agent": "synthesizer",
            "phase": "route",
            "route": result["route_decision"],
            "answer": result.get("reason", ""),
            "tool_calls": [],
        },
    }


def analyst_node(state: FinanceState, config: RunnableConfig) -> FinanceState:
    result = analyst_agent(
        query=state["query"],
        conversation_history=state.get("conversation_history"),
        usage=_get_usage(config),
    )
    return {
        "stats_result": result,
    }


def advisor_node(state: FinanceState, config: RunnableConfig) -> FinanceState:
    result = advisor_agent(
        query=state["query"],
        conversation_history=state.get("conversation_history"),
        usage=_get_usage(config),
    )
    if state["route_decision"] == "fraud":
        return {"fraud_result": result}
    return {"savings_result": result}


def synthesizer_final_node(state: FinanceState, config: RunnableConfig) -> FinanceState:
    result = synthesizer_agent(
        query=state["query"],
        conversation_history=state.get("conversation_history"),
        stats_result=state.get("stats_result"),
        savings_result=state.get("savings_result"),
        fraud_result=state.get("fraud_result"),
        route_decision=state.get("route_decision"),
        usage=_get_usage(config),
    )
    return {
        "final_answer": result["answer"],
        "final_trace": {
            "agent": "synthesizer",
            "phase": "final",
            "route": state.get("route_decision", ""),
            "answer": result["answer"],
            "tool_calls": [],
        },
    }


def route_after_synthesizer(state: FinanceState) -> list[str]:
    route = state["route_decision"]
    if route == "stats":
        return ["analyst"]
    if route in {"savings", "fraud"}:
        return ["advisor"]
    if route == "multi_step":
        return ["analyst", "advisor"]
    return ["synthesizer_final"]


def build_graph():
    graph = StateGraph(FinanceState)
    graph.add_node("synthesizer_route", synthesizer_route_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("advisor", advisor_node)
    graph.add_node("synthesizer_final", synthesizer_final_node)

    graph.add_edge(START, "synthesizer_route")
    graph.add_conditional_edges(
        "synthesizer_route",
        route_after_synthesizer,
        ["analyst", "advisor", "synthesizer_final"],
    )
    graph.add_edge("analyst", "synthesizer_final")
    graph.add_edge("advisor", "synthesizer_final")
    graph.add_edge("synthesizer_final", END)

    return graph.compile(checkpointer=MemorySaver())


GRAPH = build_graph()


def run_crew(
    query: str,
    thread_id: str = "finance-crew-thread",
    conversation_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    usage = LLMUsage()
    final_state = GRAPH.invoke(
        {
            "query": query,
            "thread_id": thread_id,
            "conversation_history": conversation_history or [],
            "route_decision": "",
            "route_reason": "",
            "stats_result": None,
            "savings_result": None,
            "fraud_result": None,
            "final_answer": "",
            "route_trace": None,
            "final_trace": None,
        },
        config={"configurable": {"thread_id": thread_id, "usage": usage}},
    )

    trace: list[dict[str, Any]] = []
    if final_state.get("route_trace"):
        trace.append(final_state["route_trace"])
    if final_state.get("stats_result"):
        trace.append(
            {
                "agent": "analyst",
                "phase": "specialist",
                "route": final_state.get("route_decision", ""),
                "answer": final_state["stats_result"].get("answer", ""),
                "tool_calls": final_state["stats_result"].get("tool_calls", []),
            }
        )
    if final_state.get("savings_result"):
        trace.append(
            {
                "agent": "advisor",
                "phase": "specialist",
                "route": final_state.get("route_decision", ""),
                "answer": final_state["savings_result"].get("answer", ""),
                "tool_calls": final_state["savings_result"].get("tool_calls", []),
            }
        )
    if final_state.get("fraud_result"):
        trace.append(
            {
                "agent": "advisor",
                "phase": "specialist",
                "route": "fraud",
                "answer": final_state["fraud_result"].get("answer", ""),
                "tool_calls": final_state["fraud_result"].get("tool_calls", []),
            }
        )
    if final_state.get("final_trace"):
        trace.append(final_state["final_trace"])

    return {
        "architecture": "crew",
        "answer": final_state.get("final_answer", ""),
        "route_decision": final_state.get("route_decision", ""),
        "stats_result": final_state.get("stats_result"),
        "savings_result": final_state.get("savings_result"),
        "fraud_result": final_state.get("fraud_result"),
        "usage": usage.to_dict(),
        "trace": trace,
    }


def graph_mermaid() -> str:
    return GRAPH.get_graph().draw_mermaid()
