from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from src import ROOT_DIR

DEFAULT_MODEL = os.getenv("MODEL", "google/gemini-2.0-flash-001")

_PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    "google/gemini-2.0-flash-001": (0.10, 0.40),
    "google/gemini-2.0-flash-lite-001": (0.075, 0.30),
}


def get_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("openrouter_API_KEY")
    if not api_key:
        raise ValueError(f"OPENROUTER_API_KEY is not set in {ROOT_DIR / '.env'}")

    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/andbilous/ai-engineering-course",
            "X-Title": "Personal Finance Coach Homework",
        },
    )


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = _PRICING_PER_MILLION.get(
        model,
        _PRICING_PER_MILLION[DEFAULT_MODEL],
    )
    return round(
        (input_tokens / 1_000_000) * input_price
        + (output_tokens / 1_000_000) * output_price,
        8,
    )


@dataclass
class LLMUsage:
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0
    by_agent: dict[str, dict[str, int | float]] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def add(
        self,
        agent: str,
        input_t: int,
        output_t: int,
        cost: float,
        ms: int,
    ) -> None:
        self.total_input_tokens += input_t
        self.total_output_tokens += output_t
        self.total_cost_usd = round(self.total_cost_usd + cost, 8)
        self.total_latency_ms += ms

        bucket = self.by_agent.setdefault(
            agent,
            {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "latency_ms": 0,
            },
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += input_t
        bucket["output_tokens"] += output_t
        bucket["total_tokens"] += input_t + output_t
        bucket["cost_usd"] = round(float(bucket["cost_usd"]) + cost, 8)
        bucket["latency_ms"] += ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 8),
            "total_latency_ms": self.total_latency_ms,
            "by_agent": self.by_agent,
        }


def call_llm(
    messages: list[dict[str, Any]],
    agent_name: str,
    usage: LLMUsage,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    temperature: float = 0.2,
):
    chosen_model = model or DEFAULT_MODEL
    client = get_client()

    start = time.perf_counter()
    response = client.chat.completions.create(
        model=chosen_model,
        messages=messages,
        tools=tools,
        temperature=temperature,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    prompt_tokens = int(getattr(response.usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(response.usage, "completion_tokens", 0) or 0)
    cost = estimate_cost(chosen_model, prompt_tokens, completion_tokens)
    usage.add(agent_name, prompt_tokens, completion_tokens, cost, elapsed_ms)
    return response
