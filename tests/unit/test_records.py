from decimal import Decimal

from cash_equivalents_mvp.models import RateRecord
from cash_equivalents_mvp.normalization.records import compare_records


def _rec(rate, provider="Bank of Nova Scotia", currency="CAD", term_years=1, run_id="r1"):
    return RateRecord(run_id=run_id, responsibility_id="gic_rates", category="gic",
                       provider=provider, product_code="BNSG", currency=currency,
                       term_years=term_years, rate=Decimal(rate))


def test_compare_records_detects_change():
    previous = [_rec("0.0255", run_id="prev")]
    current = [_rec("0.0275", run_id="cur")]
    rows = compare_records(previous, current)
    assert len(rows) == 1
    assert rows[0]["status"] == "changed"
    assert rows[0]["previous_value"] == "0.0255"
    assert rows[0]["current_value"] == "0.0275"


def test_compare_records_detects_unchanged():
    previous = [_rec("0.0255", run_id="prev")]
    current = [_rec("0.0255", run_id="cur")]
    rows = compare_records(previous, current)
    assert rows[0]["status"] == "unchanged"


def test_compare_records_detects_new():
    current = [_rec("0.0255", run_id="cur")]
    rows = compare_records([], current)
    assert rows[0]["status"] == "new"
    assert rows[0]["previous_value"] == ""


def test_compare_records_detects_removed():
    previous = [_rec("0.0255", run_id="prev")]
    rows = compare_records(previous, [])
    assert rows[0]["status"] == "removed"
    assert rows[0]["current_value"] == ""
