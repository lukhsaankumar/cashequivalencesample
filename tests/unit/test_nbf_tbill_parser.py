from datetime import date

import pytest

from cash_equivalents_mvp.config import source_material_dir
from cash_equivalents_mvp.parsers.nbf_tbill import parse_nbf_tbill_pdf, parse_nbf_tbill_text

from tests.conftest import requires_source_material

SAMPLE_TEXT = """Correspondent T Bill Rate
                                        ---------------------------------------
maturity   TBILLS           IBM #
======== =============   =========   =======  =============================
 # days   yield  price             |  yield        CDN     USD
                                    30  Day        na      na
26/06/17  2.23  99.756    A03AS5    60  Day        na      na
  40                                90  Day        na
26/07/15  2.23  99.586    A03AS7       US BILLS
  68                                 26/06/06      3.52
26/08/12  2.24  99.414    A03AT2     26/07/14      3.51
  96                                 26/08/13      3.51
26/10/21  2.35  98.943    A03AW5     26/10/08      3.50
 166                                 27/04/15      3.52
27/04/21  2.59  97.590    A03AW6
 348
"""


def test_parses_five_cad_and_five_us_rows_from_synthetic_text():
    parsed = parse_nbf_tbill_text(SAMPLE_TEXT)
    assert len(parsed["CAD"]) == 5
    assert len(parsed["USD"]) == 5


def test_cad_rows_have_price_and_identifier():
    parsed = parse_nbf_tbill_text(SAMPLE_TEXT)
    first = parsed["CAD"][0]
    assert first["maturity_date"] == date(2026, 6, 17)
    assert first["yield_raw"] == "2.23"
    assert first["price"] == "99.756"
    assert first["identifier"] == "A03AS5"


def test_us_rows_have_no_price_or_identifier():
    parsed = parse_nbf_tbill_text(SAMPLE_TEXT)
    first = parsed["USD"][0]
    assert first["maturity_date"] == date(2026, 6, 6)
    assert first["yield_raw"] == "3.52"
    assert first["price"] is None
    assert first["identifier"] is None


def test_rejects_text_with_no_matches():
    with pytest.raises(ValueError, match="PARSER_NO_ROWS"):
        parse_nbf_tbill_text("nothing here matches the expected format")


@requires_source_material
def test_parses_real_nbf_pdf_fixture():
    parsed = parse_nbf_tbill_pdf(source_material_dir() / "NBF T bill rates.pdf")
    assert len(parsed["CAD"]) == 5
    assert len(parsed["USD"]) == 5
    # Verified against docs/source_inventory.md: all 5 CAD dates/rates match the historical fixture.
    assert parsed["CAD"][0]["maturity_date"] == date(2026, 6, 17)
    assert parsed["CAD"][0]["yield_raw"] == "2.23"
    assert parsed["CAD"][4]["maturity_date"] == date(2027, 4, 21)
    assert parsed["CAD"][4]["yield_raw"] == "2.59"
