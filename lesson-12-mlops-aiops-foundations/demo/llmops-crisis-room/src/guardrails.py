"""Naïve guardrails — мініатюрні аналоги Lakera / NeMo Guardrails / Presidio.

У продакшні ти б брав готові інструменти, але для пари важливо показати
що "під капотом" це звичайний rule-based + regex шар перед / після LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from data.scenarios import INJECTION_PATTERNS


# ---------- prompt injection ----------
@dataclass
class InjectionVerdict:
    suspected: bool
    matched_pattern: str | None = None


def detect_injection(text: str) -> InjectionVerdict:
    """Naïve substring match. У проді — Lakera або prompt-injection classifier."""
    low = text.lower()
    for p in INJECTION_PATTERNS:
        if p in low:
            return InjectionVerdict(True, p)
    return InjectionVerdict(False)


# ---------- PII redaction ----------
# Спрощені regex. У проді — Microsoft Presidio (NER) або Lakera PII.
PII_PATTERNS: dict[str, re.Pattern] = {
    "email":  re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone":  re.compile(r"\+?\d[\d\s\-().]{7,}\d"),
    "card":   re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    # український паспорт (10 цифр) або серія+номер (2 літери + 6 цифр)
    "passport": re.compile(r"\b[А-ЯA-Z]{2}\s?\d{6}\b|\b\d{10}\b"),
}


def find_pii(text: str) -> dict[str, list[str]]:
    """Returns {pii_type: [matches]}. Empty dict = clean."""
    found: dict[str, list[str]] = {}
    for kind, rx in PII_PATTERNS.items():
        matches = rx.findall(text)
        if matches:
            found[kind] = matches
    return found


def redact_pii(text: str) -> tuple[str, dict[str, int]]:
    """Replace PII with [REDACTED_X] tokens. Returns (clean_text, counts)."""
    counts: dict[str, int] = {}
    clean = text
    for kind, rx in PII_PATTERNS.items():
        clean, n = rx.subn(f"[{kind.upper()}_REDACTED]", clean)
        if n:
            counts[kind] = n
    return clean, counts
