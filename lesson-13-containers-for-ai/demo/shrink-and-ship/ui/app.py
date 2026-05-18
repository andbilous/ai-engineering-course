"""Shrink & Ship — live Docker demo for урок 13."""

from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

import docker_runner as dr

DEMO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = DEMO_ROOT / ".env"


# --- page setup ---
st.set_page_config(page_title="Shrink & Ship · Live Demo", page_icon="📦", layout="wide")

st.markdown(
    """
    <style>
    .scoreboard table {width: 100%; border-collapse: collapse; font-family: ui-monospace,Menlo,monospace;}
    .scoreboard th, .scoreboard td {padding: 14px 16px; border-bottom: 1px solid #2a2f37; text-align: center; font-size: 18px;}
    .scoreboard th {color: #9aa3ad; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; font-size: 12px;}
    .scoreboard td.label {text-align: left; font-weight: 700; color: #fff;}
    .scoreboard td b {color: #fff; font-size: 22px;}
    .scoreboard .ok {color: #9be37c;}
    .scoreboard .warn {color: #ff7676;}
    .scoreboard .mid {color: #ffd166;}
    .stage-explain {padding: 12px; background: #1d2127; border-left: 3px solid #7cd1ff; border-radius: 6px; font-size: 13px; line-height: 1.6;}
    .small {color: #9aa3ad; font-size: 12px;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📦 Shrink & Ship — Live Demo")
st.caption("Один RAG сервіс · три стадії Dockerfile · реальні цифри на табло · урок 13")


# --- session state ---
def _init_state():
    if "metrics" not in st.session_state:
        st.session_state.metrics = {
            "stage0": {"image_size": "—", "image_size_bytes": 0, "build_s": None, "rebuild_s": None, "cold_start_s": None},
            "stage1": {"image_size": "—", "image_size_bytes": 0, "build_s": None, "rebuild_s": None, "cold_start_s": None},
            "stage2": {"image_size": "—", "image_size_bytes": 0, "build_s": None, "rebuild_s": None, "cold_start_s": None},
        }
    if "logs" not in st.session_state:
        st.session_state.logs = {"stage0": "", "stage1": "", "stage2": ""}
    if "last_ask" not in st.session_state:
        st.session_state.last_ask = None
    if "health_status" not in st.session_state:
        st.session_state.health_status = None
    if "active_stage" not in st.session_state:
        st.session_state.active_stage = None


_init_state()


# --- existing-image discovery on first load ---
def refresh_existing_sizes():
    for key, stage in dr.STAGES.items():
        size_str, size_b = dr.get_image_size(stage["image"])
        st.session_state.metrics[key]["image_size"] = size_str
        st.session_state.metrics[key]["image_size_bytes"] = size_b


if "_initial_scan" not in st.session_state:
    refresh_existing_sizes()
    st.session_state._initial_scan = True


# --- helpers ---
def fmt_seconds(s: float | None) -> str:
    if s is None:
        return "—"
    if s < 10:
        return f"{s:.2f}s"
    return f"{s:.1f}s"


def size_class(stage_key: str) -> str:
    """Color-code the size cell."""
    b = st.session_state.metrics[stage_key]["image_size_bytes"]
    if b == 0:
        return ""
    gb = b / (1024**3)
    if gb >= 1.0:
        return "warn"
    if gb >= 0.5:
        return "mid"
    return "ok"


def rebuild_class(stage_key: str) -> str:
    s = st.session_state.metrics[stage_key]["rebuild_s"]
    if s is None:
        return ""
    if s > 10:
        return "warn"
    if s > 3:
        return "mid"
    return "ok"


def render_scoreboard():
    m = st.session_state.metrics

    html = '<div class="scoreboard"><table>'
    html += "<tr><th>Stage</th><th>Image size</th><th>Build (cold)</th><th>Rebuild (code change)</th><th>Cold start</th></tr>"

    for key in ["stage0", "stage1", "stage2"]:
        st_m = m[key]
        label = dr.STAGES[key]["label"]
        html += f"<tr>"
        html += f'<td class="label">{label}</td>'
        html += f'<td><b class="{size_class(key)}">{st_m["image_size"]}</b></td>'
        html += f'<td><b>{fmt_seconds(st_m["build_s"])}</b></td>'
        html += f'<td><b class="{rebuild_class(key)}">{fmt_seconds(st_m["rebuild_s"])}</b></td>'
        html += f'<td><b>{fmt_seconds(st_m["cold_start_s"])}</b></td>'
        html += "</tr>"
    html += "</table></div>"
    st.markdown(html, unsafe_allow_html=True)


# --- sidebar controls ---
with st.sidebar:
    st.header("🎬 Demo controls")
    st.caption("Кнопки знизу запускають реальні `docker build` / `docker run`")

    st.divider()
    st.subheader("1️⃣ Build")
    cold_stage = st.selectbox(
        "Стадія для cold build",
        ["stage0", "stage1", "stage2"],
        format_func=lambda k: dr.STAGES[k]["label"],
    )
    build_btn = st.button("🔨 Build cold", use_container_width=True, key="build_cold")

    st.subheader("2️⃣ Rebuild test")
    rebuild_stage = st.selectbox(
        "Стадія для rebuild",
        ["stage0", "stage1", "stage2"],
        format_func=lambda k: dr.STAGES[k]["label"],
        key="rebuild_select",
    )
    rebuild_btn = st.button("🔁 Change code & rebuild", use_container_width=True, key="rebuild_btn")
    st.caption("Додає коментар у `app/main.py`, робить `docker build` без --no-cache, повертає файл назад.")

    st.subheader("3️⃣ Run final container")
    run_btn = st.button("🚀 Run stage 2 + curl /ask", use_container_width=True, key="run_btn", type="primary")

    st.divider()
    st.subheader("🧹 Cleanup")
    if st.button("Видалити всі images", use_container_width=True):
        for key in dr.STAGES:
            dr.remove_image(dr.STAGES[key]["image"])
        for key in dr.STAGES:
            st.session_state.metrics[key] = {
                "image_size": "—", "image_size_bytes": 0,
                "build_s": None, "rebuild_s": None, "cold_start_s": None,
            }
            st.session_state.logs[key] = ""
        st.success("Cleared.")
        time.sleep(0.5)
        st.rerun()


# --- main layout ---
st.subheader("📊 Scoreboard")
scoreboard_slot = st.empty()
with scoreboard_slot.container():
    render_scoreboard()

# Quick one-line diff between stages
st.markdown(
    """
##### ⚡ Чим стадії відрізняються

- **Stage 0 · Naive** — `FROM python:3.11` + `COPY . .` + `pip install`. **Все в купі**, без оптимізації. Baseline.
- **Stage 1 · Hygiene** — slim base + `.dockerignore` + `--no-cache-dir` + **окремий COPY для requirements перед кодом** (cache-friendly).
- **Stage 2 · Multi-stage** — все зі Stage 1 **плюс**: builder/runtime stages, non-root user (`USER app`), HEALTHCHECK що тестує `status: ok`. Production-ready.
"""
)

# Per-stage detail expanders right under the scoreboard — клікати на лекції
st.markdown("##### 📖 Що відбувається на кожній стадії (клікни щоб розгорнути)")
for key in ["stage0", "stage1", "stage2"]:
    stage = dr.STAGES[key]
    m = st.session_state.metrics[key]
    badge = f" · {m['image_size']}" if m['image_size'] != "—" else ""
    with st.expander(f"**{stage['label']}**{badge} — {stage['explainer'][:80]}..."):
        st.markdown(stage["details_md"])

st.divider()


# --- stage detail panels ---
tab0, tab1, tab2 = st.tabs([dr.STAGES[k]["label"] for k in ["stage0", "stage1", "stage2"]])

for tab, key in zip([tab0, tab1, tab2], ["stage0", "stage1", "stage2"]):
    with tab:
        stage = dr.STAGES[key]
        c1, c2 = st.columns([2, 1])
        with c1:
            df_path = DEMO_ROOT / stage["dockerfile"]
            st.code(df_path.read_text(), language="dockerfile")
        with c2:
            st.markdown(f'<div class="stage-explain">{stage["explainer"]}</div>', unsafe_allow_html=True)
            m = st.session_state.metrics[key]
            st.metric("Image size", m["image_size"])
            st.metric("Build (cold)", fmt_seconds(m["build_s"]))
            st.metric("Rebuild", fmt_seconds(m["rebuild_s"]))
            if m["cold_start_s"] is not None:
                st.metric("Cold start", fmt_seconds(m["cold_start_s"]))

        st.caption("Останній build лог:")
        log_area = st.empty()
        log_area.code(st.session_state.logs[key] or "(порожньо — натисни Build cold у sidebar)", language="text")


# --- action handlers ---
def execute_build(stage_key: str, is_rebuild: bool):
    stage = dr.STAGES[stage_key]
    st.session_state.active_stage = stage_key

    # show progress in main area
    with st.status(f"{'🔁 Rebuilding' if is_rebuild else '🔨 Building'} {stage['label']}...", expanded=True) as status:
        log_container = st.empty()
        accumulated = []

        if is_rebuild:
            dr.touch_main_py()  # change

        try:
            for event in dr.build_stage(stage_key, no_cache=not is_rebuild):
                if event["type"] == "log":
                    accumulated.append(event["line"])
                    # show last 30 lines
                    log_container.code("\n".join(accumulated[-30:]), language="text")
                elif event["type"] == "done":
                    if event["success"]:
                        if is_rebuild:
                            st.session_state.metrics[stage_key]["rebuild_s"] = event["duration_s"]
                        else:
                            st.session_state.metrics[stage_key]["build_s"] = event["duration_s"]
                            st.session_state.metrics[stage_key]["image_size"] = event["image_size"]
                            st.session_state.metrics[stage_key]["image_size_bytes"] = event["image_size_bytes"]
                        status.update(
                            label=f"✅ {stage['label']} done in {event['duration_s']:.1f}s ({event['image_size']})",
                            state="complete",
                        )
                    else:
                        status.update(label=f"❌ {stage['label']} build failed", state="error")
        finally:
            if is_rebuild:
                dr.touch_main_py()  # revert
            st.session_state.logs[stage_key] = "\n".join(accumulated)


def execute_run_final():
    image = dr.STAGES["stage2"]["image"]
    if dr.get_image_size(image)[1] == 0:
        st.error("❌ Stage 2 image ще не побудований. Натисни 'Build cold' зі stage2 у sidebar.")
        return
    if not ENV_FILE.exists():
        st.error(f"❌ {ENV_FILE} не існує. Потрібен OPENAI_API_KEY.")
        return

    with st.status("🚀 Запускаю stage 2 контейнер...", expanded=True) as status:
        cid = dr.run_container(image, "shrink-final", host_port=8010, env_file=ENV_FILE)
        if cid is None:
            status.update(label="❌ docker run failed", state="error")
            return
        st.write(f"Container started: `{cid[:12]}`")

        st.write("⏱️ Чекаю /health → ok ...")
        cold_s = dr.wait_for_health(8010, timeout_s=60)
        if cold_s is None:
            status.update(label="❌ /health timeout", state="error")
            dr.stop_container("shrink-final")
            return

        st.session_state.metrics["stage2"]["cold_start_s"] = cold_s
        st.write(f"✅ Сервіс готовий за **{cold_s:.2f}s**")

        st.write("🔍 Перевіряю HEALTHCHECK status...")
        time.sleep(12)  # дочекатись першого healthcheck тіку
        health = dr.healthcheck_status("shrink-final")
        st.session_state.health_status = health
        if health == "healthy":
            st.write(f"✅ HEALTHCHECK = **{health}**")
        else:
            st.write(f"⚠️ HEALTHCHECK = {health}")

        st.write("📡 Викликаю POST /ask...")
        result = dr.ask(8010, "What is multi-stage Docker build?")
        st.session_state.last_ask = result

        dr.stop_container("shrink-final")
        status.update(label="✅ Demo complete · container stopped", state="complete")

    if st.session_state.last_ask:
        st.subheader("💬 Відповідь /ask")
        if "error" in st.session_state.last_ask:
            st.error(st.session_state.last_ask["error"])
        else:
            st.success(st.session_state.last_ask.get("answer", "—"))
            with st.expander("Sources"):
                for s in st.session_state.last_ask.get("sources", []):
                    st.write(f"- ({s.get('score', 0):.2f}) **{s.get('question', '')}**")


# --- button dispatch ---
if build_btn:
    execute_build(cold_stage, is_rebuild=False)
    st.rerun()

if rebuild_btn:
    if dr.get_image_size(dr.STAGES[rebuild_stage]["image"])[1] == 0:
        st.warning(f"Спочатку зроби cold build для {dr.STAGES[rebuild_stage]['label']}.")
    else:
        execute_build(rebuild_stage, is_rebuild=True)
        st.rerun()

if run_btn:
    execute_run_final()
