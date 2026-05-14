"""Langfuse client wrapper + local in-memory trace store as fallback."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Optional


def langfuse_enabled() -> bool:
    return bool(os.getenv("LANGFUSE_SECRET_KEY") and os.getenv("LANGFUSE_PUBLIC_KEY"))


@lru_cache(maxsize=1)
def get_langfuse():
    if not langfuse_enabled():
        return None
    from langfuse import Langfuse
    return Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
    )


@dataclass
class TraceRecord:
    ts: datetime
    trace_id: str
    name: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    quality: Optional[float] = None
    hallucination_risk: Optional[float] = None
    prompt_version: str = "v1"
    provider: str = ""
    fallback_chain: list[str] = field(default_factory=list)
    error: Optional[str] = None
    user_query: str = ""
    response: str = ""
    # --- security & reliability annotations ---
    injection_suspected: bool = False
    injection_pattern: Optional[str] = None
    pii_in_input: dict = field(default_factory=dict)   # {"email": 1, "phone": 1}
    pii_redacted: bool = False
    retries: int = 0
    retry_history: list[str] = field(default_factory=list)
    timed_out: bool = False
    circuit_broke: bool = False
    langfuse_trace_id: Optional[str] = None  # real Langfuse trace id (for scores)
