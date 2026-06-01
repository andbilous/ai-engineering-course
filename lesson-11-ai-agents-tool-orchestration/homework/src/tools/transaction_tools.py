from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.tseries.offsets import MonthEnd

DATA_PATH = (
    Path(__file__).resolve().parents[2] / "starter" / "data" / "transactions.csv"
)
TRANSACTIONS = pd.read_csv(DATA_PATH, parse_dates=["date"]).sort_values("date")
TRANSACTIONS["category_norm"] = TRANSACTIONS["category"].str.strip().str.lower()
TRANSACTIONS["merchant_norm"] = TRANSACTIONS["merchant"].str.strip().str.lower()
TRANSACTIONS["account_norm"] = TRANSACTIONS["account"].str.strip().str.lower()

DATA_START = TRANSACTIONS["date"].min()
DATA_END = TRANSACTIONS["date"].max()
SUSPICIOUS_MERCHANTS = {"booking.com", "aliexpress"}
CATEGORY_ALIASES = {
    "coffee": {"coffee", "кава", "каву", "кави", "кав'ярня", "кафе"},
    "delivery": {"delivery", "доставка", "доставку", "доставки"},
    "subscriptions": {"subscriptions", "підписка", "підписки", "subscription"},
    "credit_payment": {
        "credit_payment",
        "кредитка",
        "кредитну картку",
        "кредитної картки",
        "платіж по кредитці",
        "погашення кредитки",
    },
    "groceries": {"groceries", "продукти", "супермаркет"},
    "salary": {"salary", "зарплата", "дохід", "заробіток"},
    "travel": {"travel", "подорожі", "подорож", "traveling"},
    "shopping": {"shopping", "покупки", "шопінг"},
    "utilities": {"utilities", "комуналка", "комунальні"},
    "health": {"health", "здоров'я", "медицина"},
    "restaurants": {"restaurants", "ресторани", "ресторан"},
    "entertainment": {"entertainment", "розваги"},
}
ACCOUNT_ALIASES = {
    "main_debit": {"main_debit", "debit", "дебетова", "основна карта"},
    "credit_card": {"credit_card", "credit", "кредитка", "кредитна карта"},
    "savings": {"savings", "заощадження", "ощадний"},
}


def _round(value: float) -> float:
    return round(float(value), 2)


def _iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).isoformat()


def _serialize_frame(frame: pd.DataFrame, limit: int = 50) -> tuple[list[dict[str, Any]], int]:
    ordered = frame.sort_values("date", ascending=False)
    visible = ordered.head(limit)
    records = [
        {
            "date": _iso(row.date),
            "merchant": row.merchant,
            "amount": _round(row.amount),
            "currency": row.currency,
            "category": row.category,
            "account": row.account,
            "recurring": bool(row.recurring),
        }
        for row in visible.itertuples(index=False)
    ]
    omitted_count = max(len(ordered) - len(visible), 0)
    return records, omitted_count


def _to_period_bounds(label: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    normalized = label.strip().lower()
    aliases = {
        "last week": "last_week",
        "минулого тижня": "last_week",
        "минулий тиждень": "last_week",
        "this month": "this_month",
        "current month": "this_month",
        "цього місяця": "this_month",
        "поточний місяць": "this_month",
        "last month": "last_month",
        "минулого місяця": "last_month",
        "this year": "this_year",
        "current year": "this_year",
        "цього року": "this_year",
        "поточний рік": "this_year",
        "last year": "last_year",
        "минулого року": "last_year",
    }
    kind = aliases.get(normalized)
    if not kind:
        return None

    if kind == "last_week":
        end = DATA_END.normalize()
        start = end - pd.Timedelta(days=6)
        return start, end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    if kind == "this_month":
        start = DATA_END.to_period("M").start_time
        end = DATA_END.to_period("M").end_time
        return start, end
    if kind == "last_month":
        month = DATA_END.to_period("M") - 1
        return month.start_time, month.end_time
    if kind == "this_year":
        year = DATA_END.to_period("Y")
        return year.start_time, year.end_time
    if kind == "last_year":
        year = DATA_END.to_period("Y") - 1
        return year.start_time, year.end_time
    return None


def _parse_date(value: str, is_end: bool = False) -> pd.Timestamp:
    relative = _to_period_bounds(value)
    if relative:
        return relative[1] if is_end else relative[0]

    quarter_match = re.fullmatch(r"(\d{4})-?Q([1-4])", value.strip(), flags=re.IGNORECASE)
    if quarter_match:
        year, quarter = quarter_match.groups()
        period = pd.Period(f"{year}Q{quarter}", freq="Q")
        return period.end_time if is_end else period.start_time

    month_match = re.fullmatch(r"\d{4}-\d{2}", value.strip())
    if month_match:
        ts = pd.Timestamp(f"{value}-01")
        return ts + MonthEnd(1) if is_end else ts

    ts = pd.Timestamp(value)
    if is_end and ts.hour == 0 and ts.minute == 0 and ts.second == 0 and ts.microsecond == 0:
        return ts + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    return ts


def _apply_filters(
    frame: pd.DataFrame,
    category: str | None = None,
    merchant: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    account: str | None = None,
) -> pd.DataFrame:
    filtered = frame.copy()

    if category:
        normalized_category = _normalize_alias(category, CATEGORY_ALIASES)
        filtered = filtered[filtered["category_norm"] == normalized_category]
    if merchant:
        merchant_norm = merchant.strip().lower()
        filtered = filtered[filtered["merchant_norm"].str.contains(merchant_norm, regex=False)]
    if account:
        normalized_account = _normalize_alias(account, ACCOUNT_ALIASES)
        filtered = filtered[filtered["account_norm"] == normalized_account]

    if start_date and not end_date:
        relative = _to_period_bounds(start_date)
        if relative:
            start_ts, end_ts = relative
            filtered = filtered[(filtered["date"] >= start_ts) & (filtered["date"] <= end_ts)]
            return filtered

    if start_date:
        filtered = filtered[filtered["date"] >= _parse_date(start_date, is_end=False)]
    if end_date:
        filtered = filtered[filtered["date"] <= _parse_date(end_date, is_end=True)]
    return filtered


def _normalize_alias(value: str, aliases: dict[str, set[str]]) -> str:
    normalized = value.strip().lower()
    for canonical, options in aliases.items():
        if normalized == canonical or normalized in options:
            return canonical
    if "кав" in normalized:
        return "coffee"
    if "достав" in normalized:
        return "delivery"
    if "підпис" in normalized:
        return "subscriptions"
    if "кредит" in normalized:
        return "credit_payment"
    if "зарп" in normalized or "дох" in normalized:
        return "salary"
    return normalized


def _summarize_period(frame: pd.DataFrame) -> dict[str, Any]:
    expenses = frame[frame["amount"] < 0]
    income = frame[frame["amount"] > 0]
    top_categories = (
        expenses.assign(abs_amount=expenses["amount"].abs())
        .groupby("category", as_index=False)
        .agg(total=("abs_amount", "sum"))
        .sort_values("total", ascending=False)
        .head(5)
    )
    return {
        "income": _round(income["amount"].sum()),
        "expenses": _round(expenses["amount"].abs().sum()),
        "net": _round(frame["amount"].sum()),
        "transaction_count": int(len(frame)),
        "top_categories": [
            {"category": row.category, "total": _round(row.total)}
            for row in top_categories.itertuples(index=False)
        ],
    }


def query_transactions(
    category: str | None = None,
    merchant: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    resolved_category = _normalize_alias(category, CATEGORY_ALIASES) if category else None
    resolved_account = _normalize_alias(account, ACCOUNT_ALIASES) if account else None
    filtered = _apply_filters(
        TRANSACTIONS,
        category=category,
        merchant=merchant,
        start_date=start_date,
        end_date=end_date,
        account=account,
    )
    records, omitted_count = _serialize_frame(filtered)

    expenses = filtered[filtered["amount"] < 0]["amount"].abs().sum()
    income = filtered[filtered["amount"] > 0]["amount"].sum()
    return {
        "filters": {
            "category": category,
            "merchant": merchant,
            "start_date": start_date,
            "end_date": end_date,
            "account": account,
        },
        "resolved_filters": {
            "category": resolved_category,
            "merchant": merchant.lower() if merchant else None,
            "account": resolved_account,
        },
        "dataset_range": {
            "start": _iso(DATA_START),
            "end": _iso(DATA_END),
        },
        "count": int(len(filtered)),
        "total_amount": _round(filtered["amount"].sum()),
        "total_expenses": _round(expenses),
        "total_income": _round(income),
        "transactions": records,
        "omitted_count": omitted_count,
        "summary": (
            f"Matched {len(filtered)} transactions with total expenses ${_round(expenses)} "
            f"and total income ${_round(income)}."
        ),
    }


def aggregate_by_category(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    filtered = _apply_filters(TRANSACTIONS, start_date=start_date, end_date=end_date)
    expenses = filtered[filtered["amount"] < 0].copy()
    expenses["abs_amount"] = expenses["amount"].abs()
    grouped = (
        expenses.groupby("category", as_index=False)
        .agg(total=("abs_amount", "sum"), count=("amount", "size"))
        .sort_values("total", ascending=False)
    )
    grand_total = grouped["total"].sum()
    categories = [
        {
            "category": row.category,
            "total": _round(row.total),
            "count": int(row.count),
            "share_pct": _round((row.total / grand_total) * 100) if grand_total else 0.0,
        }
        for row in grouped.itertuples(index=False)
    ]
    return {
        "start_date": start_date,
        "end_date": end_date,
        "grand_total": _round(grand_total),
        "categories": categories,
    }


def aggregate_by_merchant(
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    resolved_category = _normalize_alias(category, CATEGORY_ALIASES) if category else None
    filtered = _apply_filters(
        TRANSACTIONS,
        category=category,
        start_date=start_date,
        end_date=end_date,
    )
    expenses = filtered[filtered["amount"] < 0].copy()
    expenses["abs_amount"] = expenses["amount"].abs()
    grouped = (
        expenses.groupby("merchant", as_index=False)
        .agg(total=("abs_amount", "sum"), count=("amount", "size"))
        .sort_values("total", ascending=False)
    )
    merchants = [
        {"merchant": row.merchant, "total": _round(row.total), "count": int(row.count)}
        for row in grouped.itertuples(index=False)
    ]
    grand_total = _round(sum(item["total"] for item in merchants))
    return {
        "category": resolved_category,
        "original_category": category,
        "start_date": start_date,
        "end_date": end_date,
        "grand_total": grand_total,
        "merchants": merchants,
        "summary": (
            f"Total spend for category {resolved_category or 'all'} is ${grand_total} "
            f"across {len(merchants)} merchants."
        ),
    }


def get_monthly_summary(
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    if year is None or month is None:
        target = DATA_END.to_period("M")
    else:
        target = pd.Period(f"{year}-{month:02d}", freq="M")

    filtered = TRANSACTIONS[TRANSACTIONS["date"].dt.to_period("M") == target]
    summary = _summarize_period(filtered)
    summary["period"] = {
        "year": int(target.year),
        "month": int(target.month),
        "label": f"{target.year}-{target.month:02d}",
    }
    return summary


def compare_periods(start1: str, end1: str, start2: str, end2: str) -> dict[str, Any]:
    period1_frame = _apply_filters(TRANSACTIONS, start_date=start1, end_date=end1)
    period2_frame = _apply_filters(TRANSACTIONS, start_date=start2, end_date=end2)
    period1 = _summarize_period(period1_frame)
    period2 = _summarize_period(period2_frame)

    def _pct_change(new: float, old: float) -> float | None:
        if old == 0:
            return None
        return _round(((new - old) / old) * 100)

    return {
        "period1": {"range": {"start": start1, "end": end1}, **period1},
        "period2": {"range": {"start": start2, "end": end2}, **period2},
        "changes": {
            "expense_change_abs": _round(period2["expenses"] - period1["expenses"]),
            "expense_change_pct": _pct_change(period2["expenses"], period1["expenses"]),
            "income_change_abs": _round(period2["income"] - period1["income"]),
            "income_change_pct": _pct_change(period2["income"], period1["income"]),
            "net_change_abs": _round(period2["net"] - period1["net"]),
            "net_change_pct": _pct_change(period2["net"], period1["net"]),
        },
    }


def get_subscription_report() -> dict[str, Any]:
    subs = TRANSACTIONS[
        (TRANSACTIONS["category_norm"] == "subscriptions") | (TRANSACTIONS["recurring"] == True)
    ].copy()
    subs["abs_amount"] = subs["amount"].abs()
    subs["billing_month"] = subs["date"].dt.to_period("M")
    grouped = (
        subs.groupby("merchant", as_index=False)
        .agg(
            total_spent=("abs_amount", "sum"),
            charges=("amount", "size"),
            months_active=("billing_month", "nunique"),
            last_charge=("date", "max"),
            first_charge=("date", "min"),
            recurring=("recurring", "max"),
        )
        .sort_values("total_spent", ascending=False)
    )

    subscriptions: list[dict[str, Any]] = []
    forgotten: list[dict[str, Any]] = []
    total_monthly = 0.0

    for row in grouped.itertuples(index=False):
        monthly_estimate = row.total_spent / max(int(row.months_active), 1)
        months_since_last = (DATA_END.to_period("M") - row.last_charge.to_period("M")).n
        item = {
            "merchant": row.merchant,
            "monthly_estimate": _round(monthly_estimate),
            "total_spent": _round(row.total_spent),
            "charges": int(row.charges),
            "months_active": int(row.months_active),
            "first_charge": _iso(row.first_charge),
            "last_charge": _iso(row.last_charge),
            "months_since_last_charge": int(months_since_last),
            "is_forgotten": bool(months_since_last >= 3),
            "recurring": bool(row.recurring),
        }
        subscriptions.append(item)
        total_monthly += monthly_estimate
        if item["is_forgotten"]:
            forgotten.append(item)

    return {
        "subscriptions": subscriptions,
        "total_monthly": _round(total_monthly),
        "forgotten": forgotten,
    }


def detect_patterns(pattern_type: str | None = None) -> dict[str, Any]:
    delivery = TRANSACTIONS[TRANSACTIONS["category_norm"] == "delivery"].copy()
    delivery["after_21"] = delivery["date"].dt.hour >= 21
    weekend = TRANSACTIONS[TRANSACTIONS["amount"] < 0].copy()
    weekend["is_weekend"] = weekend["date"].dt.weekday >= 5
    weekend["abs_amount"] = weekend["amount"].abs()
    coffee = TRANSACTIONS[TRANSACTIONS["category_norm"] == "coffee"].copy()
    coffee["billing_month"] = coffee["date"].dt.to_period("M")
    credit = TRANSACTIONS[TRANSACTIONS["category_norm"] == "credit_payment"].copy()
    credit["billing_month"] = credit["date"].dt.to_period("M")
    credit["payment_type"] = credit["amount"].abs().apply(
        lambda amount: "minimum_payment" if amount <= 60 else "full_payment"
    )

    patterns = {
        "late_night_delivery": {
            "type": "late_night_delivery",
            "title": "Пізні замовлення доставки",
            "share_pct": _round(delivery["after_21"].mean() * 100) if len(delivery) else 0.0,
            "total_spend": _round(delivery["amount"].abs().sum()),
            "late_night_spend": _round(delivery[delivery["after_21"]]["amount"].abs().sum()),
            "delivery_count": int(len(delivery)),
        },
        "weekend_spike": {
            "type": "weekend_spike",
            "title": "Середній чек у вихідні вищий",
            "weekend_avg": _round(weekend[weekend["is_weekend"]]["abs_amount"].mean()),
            "weekday_avg": _round(weekend[~weekend["is_weekend"]]["abs_amount"].mean()),
            "difference_pct": _round(
                (
                    weekend[weekend["is_weekend"]]["abs_amount"].mean()
                    / weekend[~weekend["is_weekend"]]["abs_amount"].mean()
                    - 1
                )
                * 100
            ),
        },
        "coffee_ritual": {
            "type": "coffee_ritual",
            "title": "Стабільний ранковий coffee ritual",
            "avg_monthly_spend": _round(
                coffee.groupby("billing_month")["amount"].sum().abs().mean()
            ),
            "monthly_totals": {
                str(period): _round(amount)
                for period, amount in coffee.groupby("billing_month")["amount"].sum().abs().items()
            },
            "weekday_morning_pct": _round(
                (
                    (
                        (coffee["date"].dt.weekday < 5)
                        & (coffee["date"].dt.hour.between(7, 11))
                    ).mean()
                )
                * 100
            ),
        },
        "credit_card_behavior": {
            "type": "credit_card_behavior",
            "title": "Поведінка погашення кредитки",
            "minimum_payment_months": int((credit["payment_type"] == "minimum_payment").sum()),
            "full_payment_months": int((credit["payment_type"] == "full_payment").sum()),
            "payments": [
                {
                    "month": str(row.billing_month),
                    "amount": _round(abs(row.amount)),
                    "payment_type": row.payment_type,
                }
                for row in credit.sort_values("date").itertuples(index=False)
            ],
        },
    }

    if pattern_type:
        requested = pattern_type.strip().lower().replace(" ", "_")
        for key, value in patterns.items():
            if requested in {key, value["type"]}:
                return {"requested_pattern": key, "patterns": [value]}
        raise ValueError(
            f"Unknown pattern_type '{pattern_type}'. Supported values: {json.dumps(sorted(patterns))}"
        )

    return {"requested_pattern": "all", "patterns": list(patterns.values())}


def detect_fraud() -> dict[str, Any]:
    suspicious = TRANSACTIONS[
        TRANSACTIONS["merchant_norm"].isin(SUSPICIOUS_MERCHANTS)
        & (TRANSACTIONS["account_norm"] == "credit_card")
    ].copy()
    transactions, omitted_count = _serialize_frame(suspicious, limit=20)
    recent_card = TRANSACTIONS[TRANSACTIONS["account_norm"] == "credit_card"].copy()
    recent_transactions, _ = _serialize_frame(recent_card, limit=5)
    return {
        "count": int(len(suspicious)),
        "total_amount": _round(suspicious["amount"].abs().sum()),
        "suspicious_transactions": transactions,
        "omitted_count": omitted_count,
        "recent_credit_card_transactions": recent_transactions,
        "recommendation": (
            "Це схоже на потенційний fraud. Агент не блокує картку самостійно: "
            "потрібно звернутися в підтримку банку та disputed transactions."
        ),
    }
