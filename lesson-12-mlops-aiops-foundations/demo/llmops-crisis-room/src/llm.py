"""OpenRouter client with Langfuse tracing."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

from .observability import get_langfuse, langfuse_enabled

PRICING_USD_PER_M = {
    "openai/gpt-4o-mini":              (0.15, 0.60),
    "openai/gpt-4o":                   (2.50, 10.0),
    "anthropic/claude-haiku-4.5":      (1.0,  5.0),
    "anthropic/claude-sonnet-4.5":     (3.0,  15.0),
    "anthropic/claude-sonnet-4.6":     (3.0,  15.0),
    "google/gemini-2.0-flash-001":     (0.10, 0.40),
    "google/gemini-2.5-flash":         (0.30, 2.50),
}


@dataclass
class CallResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    error: Optional[str] = None
    provider: str = ""
    trace_id: Optional[str] = None   # Langfuse trace id (for attaching scores)


def _client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or api_key.startswith("sk-or-v1-..."):
        raise RuntimeError(
            "OPENROUTER_API_KEY not set. Скопіюй .env.example у .env і додай ключ "
            "(https://openrouter.ai/keys)."
        )
    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/andbilous/ai-engineering-course",
            "X-Title": "LLMOps Crisis Room",
        },
    )


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rate_in, rate_out = PRICING_USD_PER_M.get(model, (1.0, 5.0))
    return (input_tokens / 1_000_000) * rate_in + (output_tokens / 1_000_000) * rate_out


def call(
    *,
    model: str,
    system: str,
    user: str,
    trace_name: str = "llm_call",
    metadata: dict | None = None,
    max_tokens: int = 400,
) -> CallResult:
    """One LLM call with Langfuse generation logged."""
    client = _client()
    started = time.time()

    langfuse = get_langfuse() if langfuse_enabled() else None
    trace = None
    generation = None
    if langfuse is not None:
        trace = langfuse.trace(name=trace_name, metadata=metadata or {})
        generation = trace.generation(
            name=trace_name,
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            metadata=metadata or {},
        )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        latency_ms = int((time.time() - started) * 1000)
        text = (resp.choices[0].message.content or "").strip()
        usage = getattr(resp, "usage", None)
        in_tok = usage.prompt_tokens if usage else 0
        out_tok = usage.completion_tokens if usage else 0
        cost = _cost_usd(model, in_tok, out_tok)

        if generation is not None:
            generation.end(
                output=text,
                usage={"input": in_tok, "output": out_tok, "unit": "TOKENS"},
                metadata={"latency_ms": latency_ms, "cost_usd": cost},
            )
        if trace is not None:
            trace.update(output=text)
        if langfuse is not None:
            langfuse.flush()  # ensure UI sees the trace immediately

        return CallResult(
            text=text,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            latency_ms=latency_ms,
            provider=model.split("/", 1)[0],
            trace_id=getattr(trace, "id", None) if trace is not None else None,
        )
    except Exception as exc:
        latency_ms = int((time.time() - started) * 1000)
        if generation is not None:
            generation.end(level="ERROR", status_message=str(exc))
        if trace is not None:
            trace.update(output=f"ERROR: {exc}")
        if langfuse is not None:
            langfuse.flush()  # make sure ERROR observation reaches the server
        return CallResult(
            text="",
            model=model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=latency_ms,
            error=str(exc),
            provider=model.split("/", 1)[0],
            trace_id=getattr(trace, "id", None) if trace is not None else None,
        )
