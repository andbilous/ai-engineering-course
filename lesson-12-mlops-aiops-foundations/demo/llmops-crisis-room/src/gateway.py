"""LLM Gateway with fallback chain — мініатюрний LiteLLM."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable

from .llm import CallResult, call


@dataclass
class GatewayConfig:
    primary: str
    fallback_1: str
    fallback_2: str
    dead_providers: set[str] = field(default_factory=set)

    def chain(self) -> list[str]:
        return [self.primary, self.fallback_1, self.fallback_2]


def default_gateway() -> GatewayConfig:
    return GatewayConfig(
        primary=os.getenv("MODEL_PRIMARY", "openai/gpt-4o-mini"),
        fallback_1=os.getenv("MODEL_FALLBACK_1", "anthropic/claude-haiku-4.5"),
        fallback_2=os.getenv("MODEL_FALLBACK_2", "google/gemini-2.0-flash-001"),
    )


def route_with_fallback(
    gw: GatewayConfig,
    *,
    system: str,
    user: str,
    trace_name: str,
    metadata: dict | None = None,
    on_attempt: Callable[[str, str], None] | None = None,
) -> tuple[CallResult, list[str]]:
    """Try primary → fallback_1 → fallback_2. Returns (result, chain_attempted)."""
    attempted: list[str] = []
    last_err: CallResult | None = None
    for model in gw.chain():
        provider = model.split("/", 1)[0]
        if provider in gw.dead_providers:
            attempted.append(f"{model} (skipped: provider down)")
            if on_attempt:
                on_attempt(model, "skipped")
            continue
        attempted.append(model)
        if on_attempt:
            on_attempt(model, "trying")

        # Simulate provider down by passing an invalid model string
        effective = "invalid/dead-model" if provider in gw.dead_providers else model
        result = call(
            model=effective,
            system=system,
            user=user,
            trace_name=trace_name,
            metadata={**(metadata or {}), "gateway_attempt": model},
        )
        if not result.error:
            if on_attempt:
                on_attempt(model, "ok")
            result.model = model
            result.provider = provider
            return result, attempted
        last_err = result
        if on_attempt:
            on_attempt(model, "failed")
        time.sleep(0.1)  # brief backoff

    # All failed
    if last_err is None:
        last_err = CallResult(
            text="", model=gw.primary, input_tokens=0, output_tokens=0,
            cost_usd=0.0, latency_ms=0, error="no providers attempted"
        )
    return last_err, attempted
