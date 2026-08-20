import pytest

from cash_equivalents_mvp.parsers.gic_csv import parse_gic_rates_csv


def test_parses_canonical_schema(tmp_path):
    p = tmp_path / "gic.csv"
    p.write_text(
        "code,dealer,block,term_years,bucket_days,min,rate\n"
        "BNSGICR,Bank of Nova Scotia,cashables,1,,1000,1.75\n"
        "EQBGICP,Equitable Bank,short_term_deposits,,180,1000,2.70\n",
        encoding="utf-8",
    )
    rows = parse_gic_rates_csv(p)
    assert len(rows) == 2
    cashable = next(r for r in rows if r["block"] == "cashables")
    assert cashable["code"] == "BNSGICR"
    assert cashable["raw_value"] == "1.75"
    std = next(r for r in rows if r["block"] == "short_term_deposits")
    assert std["bucket_days"] == 180


def test_parses_wide_annual_export(tmp_path):
    p = tmp_path / "gic_wide.csv"
    p.write_text(
        "code,dealer,min,1 year,2 year,3 year,4 year,5 year\n"
        "BNSG,Bank of Nova Scotia,1000,2.55,2.75,2.85,2.90,3.05\n",
        encoding="utf-8",
    )
    rows = parse_gic_rates_csv(p)
    assert len(rows) == 5
    assert all(r["block"] == "annual" for r in rows)
    year1 = next(r for r in rows if r["term_years"] == 1)
    assert year1["raw_value"] == "2.55"


def test_rejects_unrecognized_header(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="PARSER_NO_ROWS"):
        parse_gic_rates_csv(p)


def test_rejects_empty_file_after_header(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("code,dealer,block,term_years,bucket_days,min,rate\n", encoding="utf-8")
    with pytest.raises(ValueError, match="PARSER_NO_ROWS"):
        parse_gic_rates_csv(p)


def test_skips_blank_code_rows(tmp_path):
    p = tmp_path / "gic.csv"
    p.write_text(
        "code,dealer,block,term_years,bucket_days,min,rate\n"
        ",Bank of Nova Scotia,cashables,1,,1000,1.75\n"
        "EQBGICR,Equitable Bank,cashables,1,,1000,1.50\n",
        encoding="utf-8",
    )
    rows = parse_gic_rates_csv(p)
    assert len(rows) == 1
    assert rows[0]["code"] == "EQBGICR"
