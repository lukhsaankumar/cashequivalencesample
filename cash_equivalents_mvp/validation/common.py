"""Shared validation helpers used by every responsibility's validate()."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from cash_equivalents_mvp.models import ValidationFinding


def finding(run_id: str, responsibility_id: str, rule_id: str, severity: str, message: str,
            location: str | None = None) -> ValidationFinding:
    return ValidationFinding(
        run_id=run_id,
        responsibility_id=responsibility_id,
        rule_id=rule_id,
        severity=severity,
        message=message,
        location=location,
    )


def check_rate_range(run_id: str, responsibility_id: str, rate: Decimal, location: str,
                      min_rate: Decimal = Decimal(0), max_rate: Decimal = Decimal("0.20")) -> list[ValidationFinding]:
    if rate < min_rate or rate > max_rate:
        return [finding(run_id, responsibility_id, "RATE_OUT_OF_RANGE", "blocking",
                         f"Rate {rate} at {location} is outside plausible range [{min_rate}, {max_rate}]",
                         location)]
    return []


def check_freshness(run_id: str, responsibility_id: str, effective_at: datetime | date | None,
                     report_date: date, max_age_days: int) -> list[ValidationFinding]:
    if effective_at is None:
        return [finding(run_id, responsibility_id, "SOURCE_STALE", "warning",
                         "No effective/source date captured; freshness cannot be verified")]
    eff_date = effective_at.date() if isinstance(effective_at, datetime) else effective_at
    age = (report_date - eff_date).days
    if age > max_age_days:
        return [finding(run_id, responsibility_id, "SOURCE_STALE", "warning",
                         f"Source is {age} days old (max allowed {max_age_days})")]
    return []
