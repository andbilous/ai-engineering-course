from __future__ import annotations

from src.tools.transaction_tools import (
    aggregate_by_category,
    aggregate_by_merchant,
    compare_periods,
    detect_fraud,
    detect_patterns,
    get_monthly_summary,
    get_subscription_report,
    query_transactions,
)

TOOL_REGISTRY = {
    "query_transactions": query_transactions,
    "aggregate_by_category": aggregate_by_category,
    "aggregate_by_merchant": aggregate_by_merchant,
    "get_monthly_summary": get_monthly_summary,
    "compare_periods": compare_periods,
    "get_subscription_report": get_subscription_report,
    "detect_patterns": detect_patterns,
    "detect_fraud": detect_fraud,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_transactions",
            "description": "Filter transactions by category, merchant, dates, and account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "merchant": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "account": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_by_category",
            "description": "Aggregate expense totals by category for an optional date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_by_merchant",
            "description": "Aggregate expense totals by merchant, optionally within one category and date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_monthly_summary",
            "description": "Return income, expenses, net, and top categories for a month.",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer"},
                    "month": {"type": "integer"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_periods",
            "description": "Compare two explicit date ranges with totals and deltas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start1": {"type": "string"},
                    "end1": {"type": "string"},
                    "start2": {"type": "string"},
                    "end2": {"type": "string"},
                },
                "required": ["start1", "end1", "start2", "end2"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_subscription_report",
            "description": "Audit recurring subscriptions, estimate monthly spend, and flag forgotten ones.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_patterns",
            "description": "Detect behavioral patterns like late-night delivery, weekend spikes, coffee rituals, and credit behavior.",
            "parameters": {
                "type": "object",
                "properties": {"pattern_type": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_fraud",
            "description": "Return suspicious foreign credit card transactions and recent card activity.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]

__all__ = ["TOOL_REGISTRY", "TOOL_SCHEMAS"]
