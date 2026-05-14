"""LLMOps Crisis Room — Streamlit demo for lesson 12.

Sidebar drives the storyline (kill primary, deploy bad prompt, enable cache, etc).
4 tabs visualise the consequences: Traces · Cost · Evals · Gateway.
Every action triggers REAL LLM calls through OpenRouter and traces them to Langfuse.
"""
from __future__ import annotations

import os
import random
import time
import uuid
from datetime import datetime, timedelta

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from data.scenarios import (
    INJECTION_QUERIES,
    KB_V1,
    KB_V2_BLOAT,
    NORMAL_QUERIES,
    OFFTOPIC_QUERIES,
)
from src.evals import judge
from src.gateway import default_gateway, route_with_fallback
from src.guardrails import detect_injection, find_pii, redact_pii
from src.observability import TraceRecord, get_langfuse, langfuse_enabled

PROMPT_NAME = "faq-assistant"

# =====================================================================
# Page config
# =====================================================================
st.set_page_config(
    page_title="LLMOps Crisis Room",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =====================================================================
# Session state
# =====================================================================
def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("traces", [])
    ss.setdefault("gateway", default_gateway())
    ss.setdefault("prompt_version", "v1")
    ss.setdefault("cache_enabled", False)
    ss.setdefault("router_enabled", False)
    ss.setdefault("gateway_log", [])
    ss.setdefault("last_event", None)
    # --- guardrails toggles ---
    ss.setdefault("pii_redaction", False)
    ss.setdefault("injection_block", False)
    # --- reliability toggles ---
    ss.setdefault("rate_limit_active", False)   # next N requests will get 429
    ss.setdefault("rate_limit_remaining", 0)
    ss.setdefault("slow_mode", False)           # 30% запитів повисають 5s
    ss.setdefault("circuit_state", {})          # provider → {"open_until": ts, "fails": n}

_init_state()


# =====================================================================
# Helpers
# =====================================================================
def add_log(msg: str, level: str = "info") -> None:
    st.session_state.gateway_log.append({"ts": datetime.now(), "level": level, "msg": msg})
    st.session_state.gateway_log = st.session_state.gateway_log[-25:]


def current_prompt() -> tuple[str, str]:
    """Returns (system_text, source). Tries Langfuse Prompt Management first,
    falls back to local constants if Langfuse is down."""
    label = "v2" if st.session_state.prompt_version == "v2" else "v1"
    if langfuse_enabled():
        lf = get_langfuse()
        try:
            # cache_ttl_seconds=0 → always hit the API so toggles are immediate
            prompt = lf.get_prompt(PROMPT_NAME, label=label, cache_ttl_seconds=0)
            return prompt.compile(), f"langfuse:{label}:v{prompt.version}"
        except Exception as exc:
            add_log(f"Langfuse prompt fetch failed: {exc} — using local fallback", "err")
    # Fallback to local constants
    text = KB_V2_BLOAT if label == "v2" else KB_V1
    return text, f"local:{label}"


def promote_prompt_label(label: str) -> bool:
    """Flip the 'production' label in Langfuse to the version that already has `label`.

    In our seeded state v1 has labels ['v1','production'] and v2 has ['v2'].
    To 'deploy v2' we add 'production' to v2; to 'rollback' we add 'production' back to v1.
    Returns True if the API call succeeded.
    """
    if not langfuse_enabled():
        return False
    lf = get_langfuse()
    try:
        # Fresh fetch (bypass cache) so we read the *real* current version
        target = lf.get_prompt(PROMPT_NAME, label=label, cache_ttl_seconds=0)
        # Re-create it with 'production' added — Langfuse API treats labels as set
        labels = sorted(set(target.labels) | {"production"})
        # Strip "latest" — server manages it automatically
        labels = [l for l in labels if l != "latest"]
        lf.create_prompt(
            name=PROMPT_NAME,
            prompt=target.prompt,
            labels=labels,
            config=target.config or {},
            type="text",
        )
        return True
    except Exception as exc:
        add_log(f"promote label '{label}' failed: {exc}", "err")
        return False


def cheap_router_pick(query: str) -> str:
    """Simple length-based router. Short → flash, long → primary."""
    if len(query) < 60:
        return os.getenv("MODEL_FALLBACK_2", "google/gemini-2.0-flash-001")
    return st.session_state.gateway.primary


def make_one_call(query: str, *, with_judge: bool = False, label: str = "user_query") -> TraceRecord:
    """One end-to-end FAQ answer: guardrails → gateway → eval → trace."""
    # ---------- Guardrails: pre-flight ----------
    injection = detect_injection(query)
    pii_input = find_pii(query)
    safe_query = query
    pii_redacted = False
    if st.session_state.pii_redaction and pii_input:
        safe_query, _ = redact_pii(query)
        pii_redacted = True

    # If injection blocking is enabled — short-circuit before LLM
    if injection.suspected and st.session_state.injection_block:
        rec = TraceRecord(
            ts=datetime.now(),
            trace_id=uuid.uuid4().hex[:8],
            name=label,
            model="(blocked-pre-llm)",
            input_tokens=0, output_tokens=0, cost_usd=0.0, latency_ms=2,
            prompt_version=st.session_state.prompt_version,
            provider="guardrails",
            error="blocked by injection guardrail",
            user_query=query,
            response="🛡 Request blocked: prompt injection detected.",
            injection_suspected=True,
            injection_pattern=injection.matched_pattern,
            pii_in_input={k: len(v) for k, v in pii_input.items()},
            pii_redacted=pii_redacted,
        )
        add_log(f"🛡 blocked injection ('{injection.matched_pattern}')", "err")
        st.session_state.traces.append(rec)
        st.session_state.traces = st.session_state.traces[-200:]
        return rec

    system, prompt_source = current_prompt()
    cache_active = st.session_state.cache_enabled and st.session_state.prompt_version == "v1"

    # ---------- Reliability simulation: rate limit / slow mode ----------
    retries = 0
    retry_history: list[str] = []
    timed_out = False
    circuit_broke = False

    # Rate-limit injection: pretend primary returned 429 → exponential backoff
    if st.session_state.rate_limit_remaining > 0:
        st.session_state.rate_limit_remaining -= 1
        primary = st.session_state.gateway.primary
        for attempt, delay in enumerate([1, 2], start=1):
            retries += 1
            retry_history.append(f"{primary}: 429 (attempt {attempt})")
            add_log(f"429 {primary} · backoff {delay}s · retry {attempt}", "err")
            time.sleep(min(delay * 0.1, 0.3))  # accelerated for demo
        retry_history.append(f"{primary}: still 429 → fallback")
        add_log(f"rate-limit persists on {primary} → fallback", "err")

    # Slow-mode: inject latency before the actual call (no real timeout — just slow)
    if st.session_state.slow_mode and random.random() < 0.3:
        time.sleep(0.5)
        timed_out = True
        retry_history.append("slow provider · simulated 5s timeout")
        add_log("⏱ slow provider — fallback after 3s timeout", "err")

    # Circuit breaker check: if primary's circuit is OPEN — skip it
    cs = st.session_state.circuit_state
    primary = st.session_state.gateway.primary
    primary_provider = primary.split("/", 1)[0]
    now_ts = time.time()
    use_fallback_only = False
    state = cs.get(primary_provider)
    if state and state.get("open_until", 0) > now_ts:
        use_fallback_only = True
        circuit_broke = True
        add_log(f"🚫 circuit OPEN for {primary_provider} — bypassing", "err")

    # ---------- Actual LLM call ----------
    if st.session_state.router_enabled:
        chosen_model = cheap_router_pick(safe_query)
        chain_used = [chosen_model]
        from src.llm import call as _call
        res = _call(
            model=chosen_model, system=system, user=safe_query,
            trace_name=label,
            metadata={
                "prompt_version": st.session_state.prompt_version,
                "prompt_source": prompt_source,
                "router": "cheap-length-based",
                "cache_enabled": cache_active,
            },
        )
    else:
        gw = st.session_state.gateway
        if use_fallback_only:
            # Temporarily mark primary as dead so route_with_fallback skips it
            gw.dead_providers.add(primary_provider)
        res, chain_used = route_with_fallback(
            gw,
            system=system, user=safe_query, trace_name=label,
            metadata={
                "prompt_version": st.session_state.prompt_version,
                "prompt_source": prompt_source,
                "cache_enabled": cache_active,
            },
            on_attempt=lambda m, status: add_log(f"{status}: {m}",
                                                 "ok" if status == "ok" else
                                                 "err" if status == "failed" else "info"),
        )
        if use_fallback_only:
            gw.dead_providers.discard(primary_provider)

    # Update circuit breaker state from this call
    if res.error and primary_provider:
        s = cs.setdefault(primary_provider, {"fails": 0, "open_until": 0})
        s["fails"] += 1
        if s["fails"] >= 3 and s["open_until"] < now_ts:
            s["open_until"] = now_ts + 30
            add_log(f"🚫 circuit OPENED for {primary_provider} (30s)", "err")
    elif not res.error and primary_provider in cs:
        cs[primary_provider] = {"fails": 0, "open_until": 0}

    if cache_active and not res.error:
        res.cost_usd *= 0.25

    rec = TraceRecord(
        ts=datetime.now(),
        trace_id=uuid.uuid4().hex[:8],
        name=label,
        model=res.model,
        input_tokens=res.input_tokens,
        output_tokens=res.output_tokens,
        cost_usd=res.cost_usd,
        latency_ms=res.latency_ms,
        prompt_version=st.session_state.prompt_version,
        provider=res.provider,
        fallback_chain=chain_used,
        error=res.error,
        user_query=query,
        response=res.text,
        injection_suspected=injection.suspected,
        injection_pattern=injection.matched_pattern,
        pii_in_input={k: len(v) for k, v in pii_input.items()},
        pii_redacted=pii_redacted,
        retries=retries,
        retry_history=retry_history,
        timed_out=timed_out,
        circuit_broke=circuit_broke,
        langfuse_trace_id=res.trace_id,
    )

    if with_judge and not res.error:
        scores = judge(
            question=query,
            answer=res.text,
            trace_id=res.trace_id,   # ← scores get attached to this trace in Langfuse
        )
        rec.quality = (scores.correctness + scores.relevance + scores.safety) / 3
        rec.hallucination_risk = scores.hallucination_risk

    st.session_state.traces.append(rec)
    st.session_state.traces = st.session_state.traces[-200:]
    return rec


# =====================================================================
# SIDEBAR — Crisis console
# =====================================================================
with st.sidebar:
    st.markdown("### 🚨 Crisis console")
    st.caption("Натискай — спостерігай за реакцією у вкладках праворуч")

    # --- Health badges
    lf_ok = langfuse_enabled()
    or_ok = bool(os.getenv("OPENROUTER_API_KEY") and not os.getenv("OPENROUTER_API_KEY", "").startswith("sk-or-v1-..."))
    cols = st.columns(2)
    cols[0].metric("Langfuse", "🟢 ON" if lf_ok else "🔴 OFF")
    cols[1].metric("OpenRouter", "🟢 ON" if or_ok else "🔴 OFF")
    if not or_ok:
        st.error("Додай OPENROUTER_API_KEY у .env")
    if not lf_ok:
        st.info("Додай LANGFUSE_* у .env щоб бачити traces у dashboard http://localhost:3000")

    st.divider()

    # --- Normal traffic
    st.markdown("**1️⃣ Normal traffic**")
    with st.expander("ℹ️ Що ми емулюємо"):
        st.markdown(
            "**Сценарій:** звичайний день продакшну — юзери задають FAQ "
            "питання (доставка, повернення, лояльність) і отримують відповіді.\n\n"
            "**LLMOps концепція:** **observability** — кожен LLM-виклик "
            "записується як trace (prompt, response, tokens, cost, latency). "
            "Без неї cost і помилки невидимі до кінця місяця.\n\n"
            "**Що дивитись:** Tab 1 Live Traces + Langfuse → Tracing"
        )
    n_normal = st.slider("Скільки запитів", 1, 30, 8, key="n_normal")
    if st.button("▶ Run normal traffic", use_container_width=True, type="primary"):
        progress = st.progress(0, text="Sending queries…")
        for i in range(n_normal):
            q = random.choice(NORMAL_QUERIES)
            make_one_call(q, with_judge=False, label="normal_traffic")
            progress.progress((i + 1) / n_normal, text=f"{i+1}/{n_normal}")
        st.session_state.last_event = "normal"
        st.rerun()

    st.divider()

    # --- Prompt regression
    st.markdown("**2️⃣ Prompt regression**")
    with st.expander("ℹ️ Що ми емулюємо"):
        st.markdown(
            "**Сценарій:** хтось у команді запушив новий system prompt "
            "(v2) з зайвими 3000+ токенами 'INTERNAL_POLICY_DOC v2.4.1 DRAFT'. "
            "Логіка та сама, але cost вибух ×4.\n\n"
            "**LLMOps концепція:** **prompt versioning + rollback** — "
            "промпт це код. Має версії, A/B тести, rollback за один клік. "
            "У цьому демо натискання кнопки **реально** переключає label "
            "`production` у Langfuse → наступний get_prompt() віддасть "
            "нову версію без redeploy коду.\n\n"
            "**Що дивитись:** Tab 2 Cost & Tokens — червоні точки v2 vs "
            "зелені v1 на одному графіку. У Langfuse → **Prompts** "
            "побачиш дві версії з мітками. У metadata trace — "
            "`prompt_source: langfuse:v1:v1` або `langfuse:v2:v2`."
        )
    pv = st.session_state.prompt_version
    src_hint = "langfuse" if langfuse_enabled() else "local fallback"
    st.caption(
        f"Current prompt: **{pv}** {'· bloated' if pv == 'v2' else '· lean'} "
        f"· source: {src_hint}"
    )
    c1, c2 = st.columns(2)
    if c1.button("🔴 Deploy v2 (bloated)", use_container_width=True, disabled=pv == "v2"):
        st.session_state.prompt_version = "v2"
        ok = promote_prompt_label("v2")
        add_log(
            "Prompt deployed: v2 (bloated +3K tokens)"
            + (" · Langfuse label 'production' → v2" if ok else " · local-only"),
            "err",
        )
        st.session_state.last_event = "prompt_v2"
        st.rerun()
    if c2.button("🟢 Rollback to v1", use_container_width=True, disabled=pv == "v1"):
        st.session_state.prompt_version = "v1"
        ok = promote_prompt_label("v1")
        add_log(
            "Prompt rolled back to v1"
            + (" · Langfuse label 'production' → v1" if ok else " · local-only"),
            "ok",
        )
        st.session_state.last_event = "rollback"
        st.rerun()

    st.divider()

    # --- Gateway / provider kill
    st.markdown("**3️⃣ Gateway · provider failure**")
    with st.expander("ℹ️ Що ми емулюємо"):
        st.markdown(
            "**Сценарій:** один з LLM-провайдерів впав (outage, rate "
            "limit, або зламаний API key). У реальному житті це 503 для "
            "юзерів і incident на pager.\n\n"
            "**LLMOps концепція:** **LLM Gateway з fallback chain** "
            "(LiteLLM, Portkey). Один API, fallback на інші провайдери "
            "автоматично. Юзер не помічає що OpenAI впав.\n\n"
            "**Що дивитись:** Tab 4 Gateway Status — побачиш як трафік "
            "перемикається з gpt-4o-mini на claude-haiku-4.5. **Не вбивай "
            "всі три** — gateway не має куди тікати, всі запити впадуть."
        )
    gw = st.session_state.gateway
    for provider in ["openai", "anthropic", "google"]:
        dead = provider in gw.dead_providers
        label = f"{'💀' if dead else '✅'} {provider}"
        if st.checkbox(label, value=dead, key=f"kill_{provider}"):
            gw.dead_providers.add(provider)
        else:
            gw.dead_providers.discard(provider)

    st.divider()

    # --- Cost levers
    st.markdown("**4️⃣ Cost levers**")
    with st.expander("ℹ️ Що ми емулюємо"):
        st.markdown(
            "**Сценарій:** трафік виріс ×10 після Reddit hug → бюджет "
            "горить. Треба швидко зрізати $/request без втрати якості.\n\n"
            "**LLMOps концепції:**\n"
            "- **Prompt caching** — Anthropic/OpenAI кешують стабільні "
            "системні промпти. Знижка ~75% на input токени.\n"
            "- **Cheap router** — простий router читає довжину запиту: "
            "короткі → дешева Gemini Flash, довгі → primary. Cost ×0.3, "
            "quality той самий.\n\n"
            "**Що дивитись:** Tab 2 Cost & Tokens → pie 'Cost by model' "
            "(побачиш мікс моделей) + cost per request падає 3-5×."
        )
    st.session_state.cache_enabled = st.toggle(
        "💾 Prompt caching",
        value=st.session_state.cache_enabled,
        help="~75% знижка на input cost (v1 prompt стабільний → можна кешувати)",
    )
    st.session_state.router_enabled = st.toggle(
        "🔀 Cheap router (length-based)",
        value=st.session_state.router_enabled,
        help="Короткі запити → Flash, довгі → primary",
    )

    st.divider()

    # --- Drift injection
    st.markdown("**5️⃣ Quality drift**")
    with st.expander("ℹ️ Що ми емулюємо"):
        st.markdown(
            "**Сценарій:** юзери почали ставити off-topic питання "
            "(борщ, фільми, поради як обдурити систему). FAQ-бот "
            "галюцинує — каже щось правдоподібне, але вигадане.\n\n"
            "**LLMOps концепція:** **LLM-as-a-judge eval** — інша модель "
            "(Sonnet) автоматично оцінює відповіді за 5 критеріями "
            "(correctness, relevance, citation, safety, hallucination "
            "risk). Ловить деградацію якості **до** того як юзер "
            "поскаржився.\n\n"
            "**Що дивитись:** Tab 3 Eval Scores — графік quality (зелена) "
            "падає, hallucination risk (червона) росте. Або в Langfuse → "
            "Scores."
        )
    n_drift = st.slider("Off-topic queries", 1, 10, 5, key="n_drift")
    if st.button("💥 Inject off-topic + eval", use_container_width=True):
        progress = st.progress(0, text="Off-topic + judging…")
        for i in range(n_drift):
            q = random.choice(OFFTOPIC_QUERIES)
            make_one_call(q, with_judge=True, label="off_topic")
            progress.progress((i + 1) / n_drift, text=f"{i+1}/{n_drift}")
        st.session_state.last_event = "drift"
        st.rerun()

    if st.button("⚖️ Run eval on last 5 (judge)", use_container_width=True):
        recent = [t for t in st.session_state.traces if t.quality is None and not t.error][-5:]
        progress = st.progress(0, text="Judging…")
        for i, rec in enumerate(recent):
            scores = judge(
                question=rec.user_query,
                answer=rec.response,
                trace_id=rec.langfuse_trace_id,   # attach scores to original trace
            )
            rec.quality = (scores.correctness + scores.relevance + scores.safety) / 3
            rec.hallucination_risk = scores.hallucination_risk
            progress.progress((i + 1) / max(len(recent), 1), text=f"{i+1}/{len(recent)}")
        st.session_state.last_event = "eval"
        st.rerun()

    st.divider()

    # --- Crisis #6 — Prompt injection
    st.markdown("**6️⃣ Prompt injection**")
    with st.expander("ℹ️ Що ми емулюємо"):
        st.markdown(
            "**Сценарій:** юзер пише `Ignore previous instructions...` "
            "або шле малікйозний payload з `<|im_start|>` щоб обійти "
            "system prompt. У 2025 — топ-1 загроза для LLM-застосунків.\n\n"
            "**LLMOps концепція:** **Guardrails** — окремий шар перед "
            "LLM (Lakera, NeMo Guardrails, Guardrails AI). Детектить "
            "injection, перш ніж payload потрапить у модель.\n\n"
            "**Що дивитись:** Tab 1 → injection traces підсвічені 🦹. "
            "Toggle блокування — і ті ж атаки відразу зупиняються без "
            "виклику LLM (нуль cost, latency ~2ms)."
        )
    st.session_state.injection_block = st.toggle(
        "🛡 Block injection attempts",
        value=st.session_state.injection_block,
        help="Якщо ON — підозрілі запити завертаються без виклику LLM",
    )
    n_inj = st.slider("Injection payloads", 1, 6, 3, key="n_inj")
    if st.button("🦹 Inject prompt-injection payloads", use_container_width=True):
        progress = st.progress(0, text="Sending malicious payloads…")
        for i in range(n_inj):
            q = random.choice(INJECTION_QUERIES)
            make_one_call(q, with_judge=False, label="injection_attack")
            progress.progress((i + 1) / n_inj, text=f"{i+1}/{n_inj}")
        st.session_state.last_event = "injection"
        st.rerun()

    st.divider()

    # --- Crisis #7 — PII leakage
    st.markdown("**7️⃣ PII leakage**")
    with st.expander("ℹ️ Що ми емулюємо"):
        st.markdown(
            "**Сценарій:** юзер пише `Мій email john@gmail.com, "
            "телефон +380...` — PII потрапляє у trace database "
            "(Langfuse Postgres). GDPR-порушення, штраф до 4% revenue.\n\n"
            "**LLMOps концепція:** **PII redaction** (Microsoft "
            "Presidio, Lakera PII, Langfuse mask functions). Чистить "
            "input перед логуванням → у трасі бачиш `[EMAIL_REDACTED]` "
            "замість справжніх даних.\n\n"
            "**Що дивитись:** натисни нижче без редакції — побачиш PII "
            "у Tab 1 трасах. Увімкни toggle і натисни знову — PII "
            "сховано. Це **before / after** на одному екрані."
        )
    st.session_state.pii_redaction = st.toggle(
        "🛡 Enable PII redaction",
        value=st.session_state.pii_redaction,
        help="Маскує email/phone/card у user_query перед логуванням",
    )
    if st.button("🪪 Inject PII queries", use_container_width=True):
        pii_queries = [
            "Привіт! Мій email john.doe@gmail.com, тел +380 67 123 45 67, замовлення NP-12345.",
            "Поверніть кошти на картку 4242 4242 4242 4242, паспорт ВК 123456.",
            "Зв'яжіться зі мною на anna.smith+orders@example.com або +1 (415) 555-0123.",
        ]
        progress = st.progress(0, text="Sending PII-laden queries…")
        for i, q in enumerate(pii_queries):
            make_one_call(q, with_judge=False, label="pii_leak")
            progress.progress((i + 1) / len(pii_queries),
                              text=f"{i+1}/{len(pii_queries)}")
        st.session_state.last_event = "pii"
        st.rerun()

    st.divider()

    # --- Crisis #8 — Rate limit (429)
    st.markdown("**8️⃣ Rate limit (429)**")
    with st.expander("ℹ️ Що ми емулюємо"):
        st.markdown(
            "**Сценарій:** OpenAI повертає `429 Too Many Requests` "
            "(Reddit hug, або ти на тарифі який не тримає трафік). "
            "Без обробки — юзери бачать 5xx.\n\n"
            "**LLMOps концепція:** **retry з exponential backoff** "
            "(1s → 2s → 4s) + fallback на іншого провайдера після N "
            "невдач. У LiteLLM з коробки.\n\n"
            "**Що дивитись:** Tab 4 Gateway log → послідовність `429 → "
            "backoff → retry → 429 → fallback ✓`. Tab 1 → у traces "
            "поле `retries: 3` і вищий latency."
        )
    n_rl = st.slider("Запити що отримають 429", 1, 10, 3, key="n_rl")
    if st.button("🚦 Activate rate-limit on primary", use_container_width=True):
        st.session_state.rate_limit_remaining = n_rl
        add_log(f"⚠ rate-limit armed for next {n_rl} requests", "err")
        st.session_state.last_event = "rate_limit_armed"
        st.rerun()

    st.divider()

    # --- Crisis #9 — Slow provider + circuit breaker
    st.markdown("**9️⃣ Slow provider · circuit breaker**")
    with st.expander("ℹ️ Що ми емулюємо"):
        st.markdown(
            "**Сценарій:** провайдер 'живий' але повільний — 30% "
            "запитів повисають на 5 секунд замість 700мс. Cascading "
            "failure: твоя API queue росте, latency p99 letить угору.\n\n"
            "**LLMOps концепція:** **timeouts + circuit breaker** "
            "(Netflix Hystrix pattern). Після N timeout підряд — "
            "gateway **зупиняє** виклики до цього провайдера на 30с і "
            "одразу йде на fallback. Latency перестає стрибати.\n\n"
            "**Що дивитись:** Tab 4 → bage 'circuit OPEN'. Tab 1 → "
            "до спрацювання traces з latency 3.5s+, після — 0.7s "
            "одразу на fallback. Графік latency різко падає."
        )
    st.session_state.slow_mode = st.toggle(
        "⏱ Slow-provider mode (30% запитів зависають)",
        value=st.session_state.slow_mode,
        help="Емулює провайдер що відповідає 5s замість 700ms",
    )
    cs = st.session_state.circuit_state
    open_circuits = [p for p, s in cs.items() if s.get("open_until", 0) > time.time()]
    if open_circuits:
        st.caption(f"🚫 Circuit OPEN: {', '.join(open_circuits)}")
    if st.button("🧯 Close all circuits (manual reset)", use_container_width=True):
        st.session_state.circuit_state = {}
        add_log("🧯 all circuits manually reset", "info")
        st.rerun()

    st.divider()
    if st.button("🧹 Reset all", use_container_width=True):
        for k in ["traces", "gateway", "prompt_version", "cache_enabled",
                  "router_enabled", "gateway_log", "last_event",
                  "pii_redaction", "injection_block",
                  "rate_limit_active", "rate_limit_remaining",
                  "slow_mode", "circuit_state"]:
            st.session_state.pop(k, None)
        _init_state()
        st.rerun()

    if lf_ok:
        st.divider()
        st.markdown(f"🔗 [Open Langfuse dashboard]({os.getenv('LANGFUSE_HOST', 'http://localhost:3000')})")


# =====================================================================
# MAIN — Title + Tabs
# =====================================================================
st.title("🚨 LLMOps Crisis Room")
st.caption(
    "Симулятор продакшн LLM-сервісу. Зліва — консоль криз. Праворуч — 4 вкладки що "
    "віддзеркалюють реальний LLMOps стек: observability · cost · evals · gateway."
)

# Pulse line of last event
if st.session_state.last_event:
    evt = st.session_state.last_event
    labels = {
        "normal":     ("🟢 Normal traffic completed", "success"),
        "prompt_v2":  ("🔴 Prompt v2 deployed — cost/quality regression expected", "error"),
        "rollback":   ("🟢 Rolled back to v1", "success"),
        "drift":      ("⚠️ Off-topic queries injected — judge scoring incoming", "warning"),
        "eval":       ("⚖️ Evals applied to recent traces", "info"),
        "injection":  ("🦹 Injection payloads sent — check Tab 1 for 🛡/🦹 badges", "error"),
        "pii":        ("🪪 PII queries sent — check Tab 1 for raw PII or [REDACTED]", "warning"),
        "rate_limit_armed": ("🚦 Rate-limit armed for next requests — run traffic to trigger", "warning"),
    }
    text, kind = labels.get(evt, (evt, "info"))
    getattr(st, kind)(text)

tab_traces, tab_cost, tab_evals, tab_gw = st.tabs([
    "📊 Live Traces",
    "💰 Cost & Tokens",
    "🧪 Eval Scores",
    "🚪 Gateway Status",
])

# =====================================================================
# TAB 1 — Live Traces
# =====================================================================
with tab_traces:
    traces = st.session_state.traces
    if not traces:
        st.info("Натисни «Run normal traffic» у sidebar щоб згенерувати traces.")
    else:
        total = len(traces)
        errors = sum(1 for t in traces if t.error)
        avg_lat = sum(t.latency_ms for t in traces) / total if total else 0
        total_cost = sum(t.cost_usd for t in traces)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Traces", total)
        c2.metric("Errors", errors, delta=None if errors == 0 else f"{errors}",
                  delta_color="inverse")
        c3.metric("Avg latency", f"{int(avg_lat)} ms")
        c4.metric("Total cost", f"${total_cost:.4f}")

        st.markdown("##### Recent traces")
        # Last 12 traces, newest first
        for rec in reversed(traces[-12:]):
            # Pick the most informative badge
            if rec.injection_suspected and rec.error == "blocked by injection guardrail":
                badge = "🛡"  # blocked successfully
            elif rec.injection_suspected:
                badge = "🦹"  # got through — danger
            elif rec.pii_in_input and not rec.pii_redacted:
                badge = "🪪"  # PII leak
            elif rec.circuit_broke:
                badge = "🚫"
            elif rec.retries > 0:
                badge = "↻"
            elif rec.error:
                badge = "🔴"
            elif (rec.hallucination_risk or 0) > 50:
                badge = "🟡"
            else:
                badge = "🟢"

            title = f"{badge} `{rec.trace_id}` · {rec.model.split('/')[-1]} · {rec.latency_ms}ms · ${rec.cost_usd:.5f}"
            with st.expander(title):
                cc1, cc2 = st.columns([2, 1])
                with cc1:
                    st.markdown(f"**Query:** {rec.user_query}")
                    if rec.response:
                        st.markdown(f"**Response:** {rec.response[:600]}{'…' if len(rec.response) > 600 else ''}")
                    if rec.error:
                        st.error(f"Error: {rec.error}")
                    if rec.injection_suspected:
                        st.warning(
                            f"🦹 **Prompt injection detected** "
                            f"(pattern: `{rec.injection_pattern}`)"
                        )
                    if rec.pii_in_input:
                        pii_summary = ", ".join(
                            f"{k}×{n}" for k, n in rec.pii_in_input.items()
                        )
                        if rec.pii_redacted:
                            st.info(f"🛡 PII redacted before logging: {pii_summary}")
                        else:
                            st.error(f"🪪 PII LEAKED into trace: {pii_summary}")
                    if rec.retry_history:
                        st.caption("**Retry history:** " + " → ".join(rec.retry_history))
                with cc2:
                    st.markdown(f"- prompt: `{rec.prompt_version}`")
                    st.markdown(f"- model: `{rec.model}`")
                    st.markdown(f"- in tokens: `{rec.input_tokens}`")
                    st.markdown(f"- out tokens: `{rec.output_tokens}`")
                    if rec.quality is not None:
                        st.markdown(f"- quality: `{rec.quality:.0f}/100`")
                    if rec.hallucination_risk is not None:
                        st.markdown(f"- halluc risk: `{rec.hallucination_risk}/100`")
                    if rec.retries > 0:
                        st.markdown(f"- retries: `{rec.retries}`")
                    if rec.timed_out:
                        st.markdown(f"- **timed out**: ⏱")
                    if rec.circuit_broke:
                        st.markdown(f"- **circuit broke**: 🚫")
                    if len(rec.fallback_chain) > 1:
                        st.markdown(f"- chain: `{' → '.join(rec.fallback_chain)}`")

        if langfuse_enabled():
            st.success(
                "🔗 Усі ці traces вже у Langfuse — відкрий "
                f"[{os.getenv('LANGFUSE_HOST', 'http://localhost:3000')}]"
                f"({os.getenv('LANGFUSE_HOST', 'http://localhost:3000')}) щоб побачити "
                "full span tree, prompt diff і dataset evals."
            )


# =====================================================================
# TAB 2 — Cost & Tokens
# =====================================================================
with tab_cost:
    traces = st.session_state.traces
    if not traces:
        st.info("Запусти трафік щоб побачити cost breakdown.")
    else:
        # KPIs
        total_cost = sum(t.cost_usd for t in traces)
        total_in = sum(t.input_tokens for t in traces)
        total_out = sum(t.output_tokens for t in traces)
        n = len(traces)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total cost", f"${total_cost:.4f}")
        c2.metric("Input tokens", f"{total_in:,}".replace(",", " "))
        c3.metric("Output tokens", f"{total_out:,}".replace(",", " "))
        c4.metric("Cost / request", f"${total_cost / max(n, 1):.5f}")

        # Cost over time
        st.markdown("##### Cost over time (per trace)")
        fig = go.Figure()
        v1_idx = [i for i, t in enumerate(traces) if t.prompt_version == "v1"]
        v2_idx = [i for i, t in enumerate(traces) if t.prompt_version == "v2"]
        fig.add_trace(go.Scatter(
            x=[traces[i].ts for i in v1_idx],
            y=[traces[i].cost_usd for i in v1_idx],
            mode="markers+lines", name="prompt v1",
            marker=dict(color="#9be37c", size=8),
            line=dict(color="#9be37c", width=1.5),
        ))
        if v2_idx:
            fig.add_trace(go.Scatter(
                x=[traces[i].ts for i in v2_idx],
                y=[traces[i].cost_usd for i in v2_idx],
                mode="markers+lines", name="prompt v2 (bloated)",
                marker=dict(color="#ff7676", size=8),
                line=dict(color="#ff7676", width=1.5),
            ))
        fig.update_layout(
            height=300,
            margin=dict(l=10, r=10, t=10, b=10),
            plot_bgcolor="#15181d", paper_bgcolor="#15181d",
            font_color="#e6e8ec",
            xaxis=dict(gridcolor="#2a2f37"),
            yaxis=dict(gridcolor="#2a2f37", title="USD"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Cost by model
        st.markdown("##### Cost breakdown by model")
        by_model: dict[str, float] = {}
        for t in traces:
            by_model[t.model] = by_model.get(t.model, 0.0) + t.cost_usd
        pie = go.Figure(go.Pie(
            labels=list(by_model.keys()),
            values=list(by_model.values()),
            hole=.55,
            marker=dict(colors=["#7cd1ff", "#ffd166", "#9be37c", "#c79bff", "#ff7eb6"]),
        ))
        pie.update_layout(
            height=280, margin=dict(l=10, r=10, t=10, b=10),
            plot_bgcolor="#15181d", paper_bgcolor="#15181d",
            font_color="#e6e8ec",
            legend=dict(orientation="h", y=-0.1),
        )
        st.plotly_chart(pie, use_container_width=True)

        # Monthly projection
        if n >= 3:
            window_min = max((traces[-1].ts - traces[0].ts).total_seconds() / 60, 0.5)
            per_min = total_cost / window_min
            month = per_min * 60 * 24 * 30
            st.caption(
                f"📈 Якщо такий ритм залишиться: **${month:,.2f}/місяць** "
                f"(extrapolated з останніх {window_min:.1f} хв)"
            )


# =====================================================================
# TAB 3 — Evals
# =====================================================================
with tab_evals:
    judged = [t for t in st.session_state.traces if t.quality is not None]
    if not judged:
        st.info("Запусти «Inject off-topic + eval» або «Run eval on last 5» у sidebar.")
    else:
        avg_quality = sum(t.quality for t in judged) / len(judged)
        avg_hall = sum(t.hallucination_risk for t in judged) / len(judged)
        c1, c2, c3 = st.columns(3)
        c1.metric("Judged traces", len(judged))
        c2.metric("Avg quality", f"{avg_quality:.0f}/100",
                  delta_color="normal" if avg_quality > 70 else "inverse",
                  delta=None if avg_quality > 70 else "below threshold")
        c3.metric("Avg hallucination risk", f"{avg_hall:.0f}/100",
                  delta_color="inverse",
                  delta=None if avg_hall < 30 else "above threshold")

        st.markdown("##### Quality vs hallucination risk")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[t.ts for t in judged],
            y=[t.quality for t in judged],
            mode="markers+lines", name="quality",
            marker=dict(color="#9be37c", size=10),
            line=dict(color="#9be37c", width=2),
        ))
        fig.add_trace(go.Scatter(
            x=[t.ts for t in judged],
            y=[t.hallucination_risk for t in judged],
            mode="markers+lines", name="hallucination risk",
            marker=dict(color="#ff7676", size=10),
            line=dict(color="#ff7676", width=2),
            yaxis="y",
        ))
        fig.add_hline(y=70, line_dash="dash", line_color="#9aa3ad",
                      annotation_text="quality threshold")
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=10, b=10),
            plot_bgcolor="#15181d", paper_bgcolor="#15181d",
            font_color="#e6e8ec",
            xaxis=dict(gridcolor="#2a2f37"),
            yaxis=dict(gridcolor="#2a2f37", range=[0, 100], title="score 0–100"),
            legend=dict(orientation="h", y=-0.15),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("##### Latest judged traces")
        for rec in reversed(judged[-6:]):
            q = rec.quality or 0
            color = "🟢" if q >= 70 else ("🟡" if q >= 40 else "🔴")
            with st.expander(
                f"{color} `{rec.trace_id}` · quality {q:.0f}/100 · halluc {rec.hallucination_risk}/100"
            ):
                st.markdown(f"**Q:** {rec.user_query}")
                st.markdown(f"**A:** {rec.response[:400]}")


# =====================================================================
# TAB 4 — Gateway
# =====================================================================
with tab_gw:
    gw = st.session_state.gateway
    st.markdown("##### Fallback chain")
    cols = st.columns(3)
    for col, model, label in zip(
        cols,
        [gw.primary, gw.fallback_1, gw.fallback_2],
        ["primary", "fallback 1", "fallback 2"],
    ):
        provider = model.split("/", 1)[0]
        dead = provider in gw.dead_providers
        status = "💀 DOWN" if dead else "🟢 LIVE"
        color = "#ff7676" if dead else "#9be37c"
        col.markdown(
            f"<div style='border:2px solid {color};border-radius:10px;"
            f"padding:14px;background:#15181d'>"
            f"<div style='font-size:11px;color:#9aa3ad;text-transform:uppercase'>{label}</div>"
            f"<div style='font-size:14px;font-weight:700;color:#fff;margin-top:4px'>{model}</div>"
            f"<div style='font-size:12px;color:{color};margin-top:4px'>{status}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("##### Gateway log")
    log = st.session_state.gateway_log
    if not log:
        st.caption("// натисни «Run normal traffic» щоб побачити routing")
    else:
        st.code(
            "\n".join(
                f"[{e['ts'].strftime('%H:%M:%S')}] "
                f"{'✓' if e['level']=='ok' else '✗' if e['level']=='err' else '→'} "
                f"{e['msg']}"
                for e in log
            ),
            language="text",
        )

    # Per-provider usage breakdown
    traces = st.session_state.traces
    if traces:
        st.markdown("##### Traffic per provider")
        by_provider: dict[str, int] = {}
        for t in traces:
            if t.error:
                continue
            by_provider[t.provider or "unknown"] = by_provider.get(t.provider or "unknown", 0) + 1
        bar = go.Figure(go.Bar(
            x=list(by_provider.keys()),
            y=list(by_provider.values()),
            marker_color=["#7cd1ff", "#ffd166", "#9be37c", "#c79bff", "#ff7eb6"][:len(by_provider)],
        ))
        bar.update_layout(
            height=240, margin=dict(l=10, r=10, t=10, b=10),
            plot_bgcolor="#15181d", paper_bgcolor="#15181d",
            font_color="#e6e8ec",
            xaxis=dict(gridcolor="#2a2f37"),
            yaxis=dict(gridcolor="#2a2f37"),
        )
        st.plotly_chart(bar, use_container_width=True)
