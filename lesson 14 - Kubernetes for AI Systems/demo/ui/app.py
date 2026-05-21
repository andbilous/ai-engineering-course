"""
Streamlit chat UI for K8s AI demo (lesson 14).

Deployed as a separate pod inside the same K8s cluster as Ollama.
Talks to Ollama via cluster-internal DNS: http://ollama.ai.svc.cluster.local:11434
(or whatever OLLAMA_URL env var points to).
"""

import os
import time
import requests
import streamlit as st

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama.ai.svc.cluster.local:11434")
DEFAULT_MODEL = os.getenv("MODEL_NAME", "phi3:mini")
APP_TITLE = os.getenv("APP_TITLE", "K8s AI Demo — Chat")

st.set_page_config(page_title=APP_TITLE, page_icon="🤖", layout="wide")

st.markdown(
    """
    <style>
      .stApp { background: #0b0d10; color: #e6e8ec; }
      .stChatMessage { background: #15181d !important; border: 1px solid #2a2f37; }
      .meta { color: #9aa3ad; font-size: 11px; font-family: ui-monospace, Menlo, monospace; }
      .badge { display:inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px;
               background: #1d2127; border: 1px solid #2a2f37; color: #7cd1ff;
               font-family: ui-monospace, Menlo, monospace; margin-right: 6px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🤖 " + APP_TITLE)
st.markdown(
    f"<div class='meta'>"
    f"<span class='badge'>pod: {os.getenv('POD_NAME', 'local')}</span>"
    f"<span class='badge'>backend: {OLLAMA_URL}</span>"
    f"<span class='badge'>model: {DEFAULT_MODEL}</span>"
    f"</div>",
    unsafe_allow_html=True,
)
st.caption("Streamlit pod → Service `ollama` → Ollama pod. Усе всередині K8s.")

with st.sidebar:
    st.subheader("Налаштування")
    model = st.text_input("Модель", value=DEFAULT_MODEL)
    temperature = st.slider("Temperature", 0.0, 1.5, 0.7, 0.1)
    num_predict = st.slider("Max tokens", 16, 512, 128, 16)

    if st.button("🩺 Health check Ollama"):
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
            if r.ok:
                tags = [m["name"] for m in r.json().get("models", [])]
                st.success(f"OK · models: {', '.join(tags) or '—'}")
            else:
                st.error(f"HTTP {r.status_code}")
        except Exception as e:
            st.error(f"Не доступний: {e}")

    if st.button("🗑 Очистити чат"):
        st.session_state.messages = []
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "meta" in msg:
            st.markdown(f"<div class='meta'>{msg['meta']}</div>", unsafe_allow_html=True)

prompt = st.chat_input("Напишіть запит до моделі...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        full = ""
        t0 = time.time()
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {"temperature": temperature, "num_predict": num_predict},
                },
                stream=True,
                timeout=600,
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                import json as _json
                chunk = _json.loads(line.decode("utf-8"))
                if chunk.get("response"):
                    full += chunk["response"]
                    placeholder.markdown(full + "▌")
                if chunk.get("done"):
                    break
            placeholder.markdown(full)
            elapsed = time.time() - t0
            tokens = len(full.split())
            tps = tokens / elapsed if elapsed > 0 else 0
            meta = f"⏱ {elapsed:.1f}s · ~{tokens} tokens · {tps:.1f} tok/s"
            st.markdown(f"<div class='meta'>{meta}</div>", unsafe_allow_html=True)
            st.session_state.messages.append(
                {"role": "assistant", "content": full, "meta": meta}
            )
        except Exception as e:
            err = f"❌ Помилка: {e}"
            placeholder.error(err)
            st.session_state.messages.append({"role": "assistant", "content": err})
