from decimal import Decimal

import pytest

from cash_equivalents_mvp.normalization.percentages import (
    en_percent_string, french_percent_text, french_percent_text_trim_zero,
    normalize_to_canonical, parse_and_normalize_rate, parse_french_percent_text, parse_raw_rate,
    validate_rate_range,
)


def test_parse_raw_rate_number():
    assert parse_raw_rate(3.3) == Decimal("3.3")


def test_parse_raw_rate_string_with_percent():
    assert parse_raw_rate("3.30%") == Decimal("0.033")


def test_parse_raw_rate_rejects_na():
    with pytest.raises(ValueError, match="PARSER_NO_ROWS"):
        parse_raw_rate("#N/A")


def test_parse_raw_rate_rejects_none():
    with pytest.raises(ValueError):
        parse_raw_rate(None)


def test_normalize_percent_form_above_one():
    # GIC Rates.xlsx style: bare number, e.g. 3.30 meaning 3.30%
    assert normalize_to_canonical(Decimal("3.30")) == Decimal("0.033")


def test_normalize_percent_form_always_percent_form_low_value():
    # Regression: 0.50 must become 0.50% (0.005), not be misread as an already-canonical 50%.
    assert normalize_to_canonical(Decimal("0.50"), source_convention="always_percent_form") == Decimal("0.005")


def test_normalize_auto_heuristic_low_value_assumed_canonical():
    assert normalize_to_canonical(Decimal("0.0175")) == Decimal("0.0175")


def test_normalize_already_canonical_convention():
    assert normalize_to_canonical(Decimal("0.0175"), source_convention="already_canonical") == Decimal("0.0175")


def test_validate_rate_range_rejects_out_of_bounds():
    with pytest.raises(ValueError):
        validate_rate_range(Decimal("3.30"))  # 330%, clearly a scaling bug if it reaches here


def test_validate_rate_range_accepts_typical_rate():
    validate_rate_range(Decimal("0.0445"))  # should not raise


def test_parse_and_normalize_rate_full_pipeline():
    assert parse_and_normalize_rate("1.75") == Decimal("0.0175")
    # default "auto" convention: bare 4.45 (>1) is treated as percent-form -> 0.0445 (4.45%)
    assert parse_and_normalize_rate(4.45) == Decimal("0.0445")
    # already-canonical values (<=1) pass through unchanged
    assert parse_and_normalize_rate(0.0175) == Decimal("0.0175")


def test_en_percent_string():
    assert en_percent_string(Decimal("0.0445")) == "4.45%"


def test_french_percent_text():
    assert french_percent_text(Decimal("0.0445")) == "4,45%"
    assert french_percent_text(Decimal("0.0175")) == "1,75%"


def test_french_percent_text_trim_zero_whole_percent():
    assert french_percent_text_trim_zero(Decimal("0.02")) == "2%"


def test_french_percent_text_trim_zero_non_whole():
    assert french_percent_text_trim_zero(Decimal("0.0282")) == "2,82%"


def test_parse_french_percent_text_roundtrip():
    assert parse_french_percent_text("4,45%") == Decimal("0.0445")
    assert parse_french_percent_text("1,80%") == Decimal("0.018")
