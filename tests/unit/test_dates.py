from datetime import date

import pytest

from cash_equivalents_mvp.normalization.dates import parse_date, parse_yy_mm_dd, term_days


def test_parse_yy_mm_dd():
    assert parse_yy_mm_dd("26/06/17") == date(2026, 6, 17)
    assert parse_yy_mm_dd("27/04/21") == date(2027, 4, 21)


def test_parse_date_from_datetime_and_string():
    assert parse_date(date(2026, 5, 11)) == date(2026, 5, 11)
    assert parse_date("2026-05-11") == date(2026, 5, 11)


def test_parse_date_rejects_empty():
    with pytest.raises(ValueError):
        parse_date("")


def test_term_days_matches_workbook_formula():
    # TBills!A17 = DAYS(A15,$G$1) & " days" — verified 2026-06-17 vs report date 2026-05-11 = 37 days.
    assert term_days(date(2026, 6, 17), date(2026, 5, 11)) == 37
    assert term_days(date(2027, 4, 21), date(2026, 5, 11)) == 345


def test_term_days_rejects_maturity_before_report_date():
    with pytest.raises(ValueError, match="TBILL_TERM_DAY_MISMATCH"):
        term_days(date(2026, 1, 1), date(2026, 5, 11))


def test_term_days_zero_is_allowed():
    assert term_days(date(2026, 5, 11), date(2026, 5, 11)) == 0
