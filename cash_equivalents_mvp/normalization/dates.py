"""Date parsing and term-day calculation."""
from __future__ import annotations

from datetime import date, datetime

from dateutil import parser as dateutil_parser


def parse_date(value) -> date:
    if value is None:
        raise ValueError("PARSER_NO_ROWS: date value is None")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError("PARSER_NO_ROWS: empty date value")
    return dateutil_parser.parse(text, dayfirst=False, yearfirst=True).date()


def parse_yy_mm_dd(text: str, *, century_pivot: int = 70) -> date:
    """Parse the NBF PDF's 'YY/MM/DD' format, e.g. '26/06/17' -> 2026-06-17.

    century_pivot: two-digit years >= pivot are 19xx, below are 20xx (matches dateutil default).
    """
    text = text.strip()
    parts = text.split("/")
    if len(parts) != 3:
        raise ValueError(f"PARSER_NO_ROWS: unrecognized date format {text!r}")
    yy, mm, dd = (int(p) for p in parts)
    year = 2000 + yy if yy < century_pivot else 1900 + yy
    return date(year, mm, dd)


def term_days(maturity_date: date, report_date: date) -> int:
    """Days from report_date to maturity_date. Never trust a source-provided day count —
    see docs/current_process_findings.md."""
    delta = (maturity_date - report_date).days
    if delta < 0:
        raise ValueError(
            f"TBILL_TERM_DAY_MISMATCH: maturity {maturity_date} is before report date {report_date}"
        )
    return delta
