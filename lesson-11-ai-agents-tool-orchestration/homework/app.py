from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.golden_set import GOLDEN_SET
from eval.evaluators import run_benchmark
from src.graph import baseline_mermaid, graph_mermaid, run_baseline, run_crew
from src.judge import judge_pairwise
from src.llm import DEFAULT_MODEL
from src.viz import summarize_trace, usage_rows

st.set_page_config(page_title="Personal Finance Coach", layout="wide")


def _init_state() -> None:
    if "histories" not in st.session_state:
        st.session_state.histories = {"crew": [], "baseline": []}
    if "thread_ids" not in st.session_state:
        st.session_state.thread_ids = {
            "crew": f"crew-{uuid4()}",
            "baseline": f"baseline-{uuid4()}",
        }
    if "last_results" not in st.session_state:
        st.session_state.last_results = {}
    if "benchmark" not in st.session_state:
        st.session_state.benchmark = None


def _reset_context() -> None:
    st.session_state.histories = {"crew": [], "baseline": []}
    st.session_state.thread_ids = {
        "crew": f"crew-{uuid4()}",
        "baseline": f"baseline-{uuid4()}",
    }
    st.session_state.last_results = {}


def _append_history(arch: str, query: str, answer: str) -> None:
    st.session_state.histories[arch].append({"role": "user", "content": query})
    st.session_state.histories[arch].append({"role": "assistant", "content": answer})


def _render_result(title: str, result: dict) -> None:
    st.subheader(title)
    st.write(result["answer"])

    usage = result.get("usage", {})
    metric_cols = st.columns(4)
    metric_cols[0].metric("Route", result.get("route_decision", "—"))
    metric_cols[1].metric("Latency (ms)", usage.get("total_latency_ms", 0))
    metric_cols[2].metric("Tokens", usage.get("total_tokens", 0))
    metric_cols[3].metric("Cost ($)", f"{usage.get('total_cost_usd', 0.0):.6f}")

    with st.expander("Trace"):
        trace_rows = summarize_trace(result)
        if trace_rows:
            st.dataframe(pd.DataFrame(trace_rows), use_container_width=True, hide_index=True)
        for event in result.get("trace", []):
            label = f"{event.get('agent', 'agent')} · {event.get('phase', '')}"
            with st.expander(label):
                if event.get("tool_calls"):
                    st.json(event["tool_calls"], expanded=False)
                st.write(event.get("answer", ""))

        usage_table = usage_rows(result)
        if usage_table:
            st.caption("Розподіл latency / cost за агентами")
            st.dataframe(pd.DataFrame(usage_table), use_container_width=True, hide_index=True)


def _render_history(arch: str) -> None:
    history = st.session_state.histories.get(arch, [])
    if not history:
        return
    with st.expander(f"Контекст {arch}", expanded=False):
        for message in history[-8:]:
            st.markdown(f"**{message['role']}**: {message['content']}")


def _run_query(query: str, architecture: str) -> dict[str, dict]:
    results: dict[str, dict] = {}
    if architecture in {"crew", "both"}:
        crew_result = run_crew(
            query,
            thread_id=st.session_state.thread_ids["crew"],
            conversation_history=st.session_state.histories["crew"],
        )
        results["crew"] = crew_result
        _append_history("crew", query, crew_result["answer"])
    if architecture in {"baseline", "both"}:
        baseline_result = run_baseline(
            query,
            conversation_history=st.session_state.histories["baseline"],
        )
        results["baseline"] = baseline_result
        _append_history("baseline", query, baseline_result["answer"])
    st.session_state.last_results = results
    return results


_init_state()

st.title("Personal Finance Coach")
st.caption("Multi-agent orchestration homework · український demo UI")

architecture = st.sidebar.radio(
    "Архітектура",
    options=["crew", "baseline", "both"],
    format_func=lambda value: {
        "crew": "Crew (3 агенти)",
        "baseline": "Baseline (1 агент)",
        "both": "Обидві",
    }[value],
)
st.sidebar.caption(f"Модель: `{DEFAULT_MODEL}`")
st.sidebar.code(
    graph_mermaid() if architecture in {"crew", "both"} else baseline_mermaid(),
    language="mermaid",
)
if st.sidebar.button("Очистити контекст"):
    _reset_context()

query_tab, eval_tab = st.tabs(["Запит", "Оцінка"])

with query_tab:
    _render_history("crew")
    if architecture in {"baseline", "both"}:
        _render_history("baseline")

    query = st.text_area(
        "Фінансовий запит",
        placeholder="Наприклад: Де можна зекономити $200 цього місяця?",
        height=120,
    )
    if st.button("Submit", type="primary", use_container_width=True):
        if query.strip():
            with st.spinner("Запускаю агентів..."):
                results = _run_query(query.strip(), architecture)
            if architecture == "both" and {"crew", "baseline"} <= results.keys():
                with st.spinner("Порівнюю відповіді judge-ом..."):
                    st.session_state.last_results["judge"] = judge_pairwise(
                        query=query.strip(),
                        answer_a=results["crew"]["answer"],
                        answer_b=results["baseline"]["answer"],
                    )
        else:
            st.warning("Введи запит.")

    last_results = st.session_state.last_results
    if last_results:
        if "crew" in last_results and "baseline" in last_results:
            col1, col2 = st.columns(2)
            with col1:
                _render_result("Crew", last_results["crew"])
            with col2:
                _render_result("Baseline", last_results["baseline"])
            if "judge" in last_results:
                with st.expander("Judge comparison"):
                    st.json(last_results["judge"], expanded=False)
        elif "crew" in last_results:
            _render_result("Crew", last_results["crew"])
        elif "baseline" in last_results:
            _render_result("Baseline", last_results["baseline"])

with eval_tab:
    st.write(
        f"Golden set містить **{len(GOLDEN_SET)}** кейсів для side-by-side порівняння crew та baseline."
    )
    if st.button("Запустити golden set", use_container_width=True):
        progress_bar = st.progress(0, text="Починаю benchmark...")
        status_placeholder = st.empty()

        def _update_progress(completed: int, total: int, row: dict) -> None:
            progress_bar.progress(
                completed / total,
                text=f"{completed}/{total}: {row['architecture']} · {row['case_id']} · {row['status']}",
            )
            if row["status"] == "error":
                status_placeholder.warning(
                    f"{row['architecture']} · {row['case_id']} failed: {row['error']}"
                )
            else:
                status_placeholder.caption(
                    f"Останній кейс: {row['architecture']} · {row['case_id']} · route={row['predicted_route']}"
                )
        with st.spinner("Проганяю benchmark..."):
            st.session_state.benchmark = run_benchmark(progress_callback=_update_progress)
        progress_bar.progress(1.0, text="Benchmark завершено")

    benchmark = st.session_state.benchmark
    if benchmark is not None:
        st.subheader("Summary")
        st.dataframe(benchmark["summary_df"], use_container_width=True, hide_index=True)

        if not benchmark["avg_cost_by_agent_df"].empty:
            st.subheader("Average cost by agent")
            st.dataframe(benchmark["avg_cost_by_agent_df"], use_container_width=True, hide_index=True)

        if not benchmark["failed_df"].empty:
            st.subheader("Failed cases")
            st.dataframe(
                benchmark["failed_df"][["architecture", "case_id", "query", "error"]],
                use_container_width=True,
                hide_index=True,
            )

        st.subheader("Detailed results")
        details_df = benchmark["results_df"].drop(columns=["answer", "cost_breakdown_by_agent"])
        st.dataframe(details_df, use_container_width=True, hide_index=True)
