"""Percentage parsing/scaling/formatting. Canonical storage is always Decimal, e.g. 2.05% -> Decimal('0.0205').

See docs/current_process_findings.md "GIC percentage scale is a real, recurring failure mode".
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

PERCENT_FORM_THRESHOLD = Decimal(1)
MIN_VALID_RATE = Decimal(0)
MAX_VALID_RATE = Decimal("0.20")  # 20%, per master prompt validation rule


class PercentageScaleAmbiguous(ValueError):
    pass


def parse_raw_rate(value) -> Decimal:
    """Parse a raw cell/CSV value into a Decimal, without scaling.

    Accepts numbers, numeric strings, and strings with a trailing '%'.
    Raises ValueError for non-numeric / N/A markers — callers must handle those explicitly
    (never silently treat #N/A as 0).
    """
    if value is None:
        raise ValueError("PERCENTAGE_SCALE_AMBIGUOUS: value is None")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text or text.upper() in {"#N/A", "N/A", "NA", "-"}:
        raise ValueError(f"PARSER_NO_ROWS: non-numeric rate value {value!r}")
    had_percent_sign = text.endswith("%")
    text = text.rstrip("%").strip()
    text = text.replace(",", ".") if text.count(",") == 1 and text.count(".") == 0 else text.replace(",", "")
    try:
        dec = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"PARSER_NO_ROWS: cannot parse rate {value!r}") from exc
    if had_percent_sign:
        dec = dec / Decimal(100)
    return dec


def normalize_to_canonical(raw: Decimal, *, already_percent_sign: bool = False,
                            source_convention: str = "auto") -> Decimal:
    """Scale a bare-number rate (e.g. 3.30 meaning 3.30%) to canonical decimal (0.0330).

    source_convention:
      "auto"                — ambiguous manual-entry heuristic: values > 1 are assumed
                               percent-form and divided by 100; values <= 1 are assumed already
                               canonical. Only safe when the source could plausibly be either
                               (e.g. free-form manual override fields).
      "always_percent_form" — the source is *known* to always store bare percent numbers
                               regardless of magnitude (e.g. GIC Rates.xlsx, where 0.50 means
                               0.50% just as much as 3.30 means 3.30% — "auto" would
                               misinterpret 0.50 as an already-canonical 50%). Always divides
                               by 100.
      "already_canonical"   — the source is known to already store canonical decimals.

    already_percent_sign=True means the caller (parse_raw_rate) already divided by 100 because
    the source text carried an explicit '%' — so `raw` is returned unchanged here.
    """
    if already_percent_sign:
        return raw
    if source_convention == "always_percent_form":
        return raw / Decimal(100)
    if source_convention == "already_canonical":
        return raw
    if raw > PERCENT_FORM_THRESHOLD:
        return raw / Decimal(100)
    return raw


def validate_rate_range(rate: Decimal, *, min_rate: Decimal = MIN_VALID_RATE, max_rate: Decimal = MAX_VALID_RATE) -> None:
    if rate < min_rate or rate > max_rate:
        raise ValueError(
            f"Rate {rate} outside plausible range [{min_rate}, {max_rate}] — "
            "possible percentage scale error"
        )


def parse_and_normalize_rate(value) -> Decimal:
    """Full pipeline: raw value -> canonical Decimal, with a final sanity-range check."""
    text = str(value).strip() if not isinstance(value, Decimal) else None
    had_percent = text.endswith("%") if text else False
    raw = parse_raw_rate(value)
    canonical = normalize_to_canonical(raw, already_percent_sign=had_percent)
    validate_rate_range(canonical)
    return canonical


def en_percent_string(rate: Decimal, decimals: int = 2) -> str:
    """English display string, e.g. Decimal('0.0445') -> '4.45%'. Used only for text-template cells."""
    pct = (rate * 100).quantize(Decimal(1).scaleb(-decimals))
    return f"{pct}%"


def french_percent_text(rate: Decimal, decimals: int = 2) -> str:
    """French display string with comma decimal, e.g. Decimal('0.0445') -> '4,45%'."""
    pct = (rate * 100).quantize(Decimal(1).scaleb(-decimals))
    s = f"{pct}"
    return f"{s.replace('.', ',')}%"


def french_percent_text_trim_zero(rate: Decimal) -> str:
    """Matches the observed Executive Summary convention: whole percents drop the decimal
    (2.00 -> '2%'), others show 2 decimal places (2.82 -> '2,82%')."""
    pct = (rate * 100).quantize(Decimal("0.01"))
    if pct == pct.to_integral_value():
        return f"{int(pct)}%"
    return french_percent_text(rate)


def parse_french_percent_text(text: str) -> Decimal:
    """Inverse of french_percent_text — used by bilingual-parity validation to re-derive a
    Decimal from a French text cell for comparison against the EN numeric cell."""
    text = text.strip().rstrip("%").strip()
    text = text.replace(",", ".")
    return Decimal(text) / Decimal(100)
