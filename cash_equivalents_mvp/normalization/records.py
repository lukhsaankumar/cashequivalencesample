"""Week-over-week comparison of RateRecord lists."""
from __future__ import annotations

from decimal import Decimal

from cash_equivalents_mvp.models import RateRecord


def record_key(r: RateRecord) -> tuple:
    return (r.category, r.provider, r.product_code, r.currency, r.term_days, r.term_years)


def compare_records(previous: list[RateRecord], current: list[RateRecord]) -> list[dict]:
    """Returns rows: category, provider, product, currency, term, previous value, current value,
    change, status. Matches the shape needed by the Review UI page / comparison.csv."""
    prev_by_key = {record_key(r): r for r in previous}
    rows: list[dict] = []
    seen = set()
    for r in current:
        key = record_key(r)
        seen.add(key)
        prev = prev_by_key.get(key)
        prev_rate = prev.rate if prev else None
        change = (r.rate - prev_rate) if prev_rate is not None else None
        rows.append({
            "category": r.category,
            "provider": r.provider,
            "product": r.product_name or r.product_code,
            "currency": r.currency,
            "term": r.term_years or r.term_days,
            "previous_value": str(prev_rate) if prev_rate is not None else "",
            "current_value": str(r.rate),
            "change": str(change) if change is not None else "new",
            "status": "unchanged" if change == Decimal(0) else ("new" if prev_rate is None else "changed"),
        })
    for key, prev in prev_by_key.items():
        if key not in seen:
            rows.append({
                "category": prev.category,
                "provider": prev.provider,
                "product": prev.product_name or prev.product_code,
                "currency": prev.currency,
                "term": prev.term_years or prev.term_days,
                "previous_value": str(prev.rate),
                "current_value": "",
                "change": "removed",
                "status": "removed",
            })
    return rows
