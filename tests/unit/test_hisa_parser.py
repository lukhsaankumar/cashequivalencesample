from decimal import Decimal

from cash_equivalents_mvp.config import resolve_sheet_name, settings, source_material_dir, workbook_map
from cash_equivalents_mvp.parsers.hisa import parse_hisa_csv, parse_hisa_from_workbook

from tests.conftest import requires_source_material


@requires_source_material
def test_parses_cdn_and_us_blocks_from_report_workbook():
    en_template = source_material_dir() / settings()["templates"]["en"]
    rows = parse_hisa_from_workbook(en_template, workbook_map("en")["hisa"], resolve_sheet_name("en", "hisa"))
    currencies = {r["currency"] for r in rows}
    assert currencies == {"CAD", "USD"}


@requires_source_material
def test_equitable_bank_individual_cdn_rate_matches_historical_fixture():
    en_template = source_material_dir() / settings()["templates"]["en"]
    rows = parse_hisa_from_workbook(en_template, workbook_map("en")["hisa"], resolve_sheet_name("en", "hisa"))
    eqb = next(r for r in rows if r["fund_code"] == "EQB110 - Individual")
    assert Decimal(str(eqb["raw_rate"])) == Decimal("0.0205")


@requires_source_material
def test_bns_higher_rate_row_is_present_but_not_selected_by_the_parser():
    # The parser must not filter/select — that decision belongs to the responsibility's
    # business-rule validation (config/business_rules.yaml: hisa_summary_selection).
    en_template = source_material_dir() / settings()["templates"]["en"]
    rows = parse_hisa_from_workbook(en_template, workbook_map("en")["hisa"], resolve_sheet_name("en", "hisa"))
    bns_rows = [r for r in rows if "BNS HISA - Personal" in r["provider"] and r["currency"] == "CAD"]
    assert any(Decimal(str(r["raw_rate"])) == Decimal("0.021") for r in bns_rows)


def test_parse_hisa_csv_canonical_schema(tmp_path):
    p = tmp_path / "hisa.csv"
    p.write_text(
        "provider,fund_code,minimum,maximum,corporate_eligible,cdic_eligible,currency,rate,source,effective_date\n"
        "Test Bank HISA,TB100,500,100000,No,Yes,CAD,0.0205,manual,2026-05-11\n",
        encoding="utf-8",
    )
    rows = parse_hisa_csv(p)
    assert len(rows) == 1
    assert rows[0]["provider"] == "Test Bank HISA"
    assert rows[0]["currency"] == "CAD"


def test_parse_hisa_csv_rejects_missing_columns(tmp_path):
    import pytest
    p = tmp_path / "bad.csv"
    p.write_text("provider,rate\nX,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="PARSER_NO_ROWS"):
        parse_hisa_csv(p)
