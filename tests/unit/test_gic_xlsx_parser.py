from decimal import Decimal

from cash_equivalents_mvp.config import source_material_dir, workbook_map
from cash_equivalents_mvp.normalization.percentages import normalize_to_canonical, parse_raw_rate
from cash_equivalents_mvp.parsers.gic_xlsx import parse_gic_rates_xlsx

from tests.conftest import requires_source_material


@requires_source_material
def test_parses_all_five_blocks():
    source_map = workbook_map("en")["gic_rates_source"]
    rows = parse_gic_rates_xlsx(source_material_dir() / "GIC Rates.xlsx", source_map)
    blocks = {r["block"] for r in rows}
    assert blocks == {"annual", "monthly", "compound", "short_term_deposits", "cashables"}


@requires_source_material
def test_bns_cashable_rate_matches_master_prompt_assertion():
    # master prompt §16.3: "Bank of Nova Scotia cashable rate parses as 1.75%"
    source_map = workbook_map("en")["gic_rates_source"]
    rows = parse_gic_rates_xlsx(source_material_dir() / "GIC Rates.xlsx", source_map)
    bns = next(r for r in rows if r["block"] == "cashables" and r["code"].strip() == "BNSGICR")
    canonical = normalize_to_canonical(parse_raw_rate(bns["raw_value"]), source_convention="always_percent_form")
    assert canonical == Decimal("0.0175")


@requires_source_material
def test_equitable_bank_180_day_deposit_matches_master_prompt_assertion():
    # master prompt §16.3: "Equitable Bank 180-day deposit parses as 2.70%"
    source_map = workbook_map("en")["gic_rates_source"]
    rows = parse_gic_rates_xlsx(source_material_dir() / "GIC Rates.xlsx", source_map)
    eqb_180 = next(r for r in rows if r["block"] == "short_term_deposits"
                   and r["code"].strip() == "EQBGICP" and r["bucket_days"] == 180)
    canonical = normalize_to_canonical(parse_raw_rate(eqb_180["raw_value"]), source_convention="always_percent_form")
    assert canonical == Decimal("0.027")


@requires_source_material
def test_b2b_one_year_annual_rate_near_330_per_master_prompt():
    # master prompt §16.3: "B2B one-year annual rate parses around 3.30%" — this is a live GIC
    # Rates.xlsx snapshot (see docs/source_inventory.md), so we assert "close to" not exact.
    source_map = workbook_map("en")["gic_rates_source"]
    rows = parse_gic_rates_xlsx(source_material_dir() / "GIC Rates.xlsx", source_map)
    b2b = next(r for r in rows if r["block"] == "annual" and r["code"].strip() == "B2BGICP" and r["term_years"] == 1)
    canonical = normalize_to_canonical(parse_raw_rate(b2b["raw_value"]), source_convention="always_percent_form")
    assert Decimal("0.02") < canonical < Decimal("0.05")


@requires_source_material
def test_source_3_30_becomes_canonical_0_0330():
    canonical = normalize_to_canonical(parse_raw_rate(3.30), source_convention="always_percent_form")
    assert canonical == Decimal("0.0330")


@requires_source_material
def test_na_values_are_present_in_raw_rows_not_silently_dropped_by_parser():
    # The parser itself must surface #N/A as-is; it's the responsibility layer's job to skip it
    # rather than overwrite a report cell — see responsibilities/gic_rates.py normalize().
    source_map = workbook_map("en")["gic_rates_source"]
    rows = parse_gic_rates_xlsx(source_material_dir() / "GIC Rates.xlsx", source_map)
    home_bank_cashable = next(r for r in rows if r["block"] == "cashables" and r["code"].strip() == "HOBKGICR")
    assert home_bank_cashable["raw_value"] == "#N/A"


@requires_source_material
def test_missing_sheet_raises_workbook_sheet_missing():
    import pytest
    source_map = dict(workbook_map("en")["gic_rates_source"])
    source_map["sheet"] = "NoSuchSheet"
    with pytest.raises(ValueError, match="WORKBOOK_SHEET_MISSING"):
        parse_gic_rates_xlsx(source_material_dir() / "GIC Rates.xlsx", source_map)
