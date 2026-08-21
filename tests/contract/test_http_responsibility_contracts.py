"""Common contract suite (master prompt §16.2) for the three HTTP-sourced responsibilities:
canada_prime, us_fed_funds, money_market. All network calls are mocked — this suite never
touches the real internet, so it belongs in the default offline test run.
"""
from __future__ import annotations

import httpx
import pytest

from cash_equivalents_mvp.models import ManualInput, ResponsibilityStatus
from cash_equivalents_mvp.responsibilities.canada_prime import CanadaPrimeResponsibility
from cash_equivalents_mvp.responsibilities.fed_funds import FedFundsResponsibility
from cash_equivalents_mvp.responsibilities.money_market import MoneyMarketResponsibility
from tests.conftest import make_context

BOC_BODY = {"observations": [{"d": "2026-05-08", "V80691311": {"v": "4.45"}}]}
FRED_UPPER_CSV = "observation_date,DFEDTARU\n2026-05-08,3.75\n"
FRED_LOWER_CSV = "observation_date,DFEDTARL\n2026-05-08,3.50\n"
LIPPER_HTML = "<html><body>Current Yield 2.00%</body></html>"


class _FakeResponse:
    def __init__(self, *, json_body=None, text_body=None, status_code=200):
        self._json = json_body
        self.text = text_body or ""
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        return self._json


SCENARIOS = [
    pytest.param(
        CanadaPrimeResponsibility, "canada_prime",
        {"https://www.bankofcanada.ca/valet/observations/V80691311/json?recent=5":
         _FakeResponse(json_body=BOC_BODY)},
        id="canada_prime",
    ),
    pytest.param(
        FedFundsResponsibility, "us_fed_funds",
        {"upper": _FakeResponse(text_body=FRED_UPPER_CSV), "lower": _FakeResponse(text_body=FRED_LOWER_CSV)},
        id="us_fed_funds",
    ),
    pytest.param(
        MoneyMarketResponsibility, "money_market",
        {"cad": _FakeResponse(text_body=LIPPER_HTML), "us": _FakeResponse(text_body=LIPPER_HTML)},
        id="money_market",
    ),
]


def _patch_success(monkeypatch, responsibility_id, fake_responses):
    if responsibility_id == "canada_prime":
        monkeypatch.setattr(httpx, "get", lambda url, **kw: fake_responses[url])
    elif responsibility_id == "us_fed_funds":
        def fake_get(url, **kw):
            return fake_responses["upper"] if "DFEDTARU" in url else fake_responses["lower"]
        monkeypatch.setattr(httpx, "get", fake_get)
    elif responsibility_id == "money_market":
        monkeypatch.setattr(httpx, "get", lambda url, **kw: fake_responses["cad"])


@pytest.mark.parametrize("resp_cls,responsibility_id,fake_responses", SCENARIOS)
def test_automatic_success(monkeypatch, tmp_path, resp_cls, responsibility_id, fake_responses):
    _patch_success(monkeypatch, responsibility_id, fake_responses)
    resp = resp_cls()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)
    assert status == ResponsibilityStatus.COMPLETE
    records = ctx.db.get_rate_records(ctx.run_id, responsibility_id)
    assert len(records) >= 1
    # provenance present
    assert all(r.source_artifact_id or r.extraction_method for r in records)


@pytest.mark.parametrize("resp_cls,responsibility_id,fake_responses", SCENARIOS)
def test_automatic_transient_failure_falls_back_to_manual_required(monkeypatch, tmp_path, resp_cls,
                                                                     responsibility_id, fake_responses):
    def raise_timeout(url, **kw):
        raise httpx.TimeoutException("simulated timeout")
    monkeypatch.setattr(httpx, "get", raise_timeout)
    resp = resp_cls()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)
    assert status == ResponsibilityStatus.MANUAL_REQUIRED
    errors = ctx.db.get_errors(ctx.run_id, responsibility_id)
    assert len(errors) >= 1
    assert errors[-1].error_code == "SOURCE_HTTP_TIMEOUT"
    assert errors[-1].retryable is True


@pytest.mark.parametrize("resp_cls,responsibility_id,fake_responses", SCENARIOS)
def test_automatic_permanent_failure_403_falls_back_to_manual_required(monkeypatch, tmp_path, resp_cls,
                                                                         responsibility_id, fake_responses):
    def raise_403(url, **kw):
        return _FakeResponse(status_code=403)
    monkeypatch.setattr(httpx, "get", raise_403)
    resp = resp_cls()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)
    assert status == ResponsibilityStatus.MANUAL_REQUIRED
    errors = ctx.db.get_errors(ctx.run_id, responsibility_id)
    assert errors[-1].error_code == "SOURCE_HTTP_403"
    assert errors[-1].retryable is False


@pytest.mark.parametrize("resp_cls,responsibility_id,fake_responses", SCENARIOS)
def test_automatic_permanent_failure_401_falls_back_to_manual_required(monkeypatch, tmp_path, resp_cls,
                                                                         responsibility_id, fake_responses):
    # Regression test: a 401 (e.g. an unauthenticated SharePoint/SSO request) was previously
    # misclassified as SOURCE_HTTP_TIMEOUT/retryable=True — found via a real corporate-network
    # debug bundle, not a synthetic test. See collectors/http.py: classify_http_exception.
    def raise_401(url, **kw):
        return _FakeResponse(status_code=401)
    monkeypatch.setattr(httpx, "get", raise_401)
    resp = resp_cls()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)
    assert status == ResponsibilityStatus.MANUAL_REQUIRED
    errors = ctx.db.get_errors(ctx.run_id, responsibility_id)
    assert errors[-1].error_code == "SOURCE_HTTP_401"
    assert errors[-1].retryable is False


def test_money_market_yield_not_found_saves_debug_html_and_requires_manual(tmp_path, monkeypatch):
    """The page loads fine (200 OK, no exception) but doesn't contain the expected 'current
    yield' text — most likely a login redirect, distinct from a network/TLS failure. Must save
    the actual HTML for diagnosis rather than fail silently or misreport as a connection issue."""
    def fake_get(url, **kw):
        return _FakeResponse(text_body="<html><body>Please sign in to continue</body></html>")
    monkeypatch.setattr(httpx, "get", fake_get)

    resp = MoneyMarketResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    assert status == ResponsibilityStatus.MANUAL_REQUIRED
    errors = ctx.db.get_errors(ctx.run_id, "money_market")
    assert errors[-1].error_code == "SOURCE_LAYOUT_CHANGED"
    assert "saved to" in errors[-1].message

    import re
    saved_path_match = re.search(r"saved to (\S+)\.", errors[-1].message)
    assert saved_path_match, errors[-1].message
    from pathlib import Path
    saved_path = Path(saved_path_match.group(1))
    assert saved_path.exists()
    assert "sign in" in saved_path.read_text(encoding="utf-8")
    saved_path.unlink()  # cleanup — this writes outside tmp_path, into raw_sources_dir()


def test_canada_prime_manual_fallback_accepted(tmp_path):
    resp = CanadaPrimeResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    mi = ManualInput(responsibility_id="canada_prime", kind="numeric",
                      numeric_fields={"rate": "4.45"}, override_reason="test override")
    status = resp.run_manual(ctx, mi)
    assert status == ResponsibilityStatus.COMPLETE
    records = ctx.db.get_rate_records(ctx.run_id, "canada_prime")
    assert records[0].manually_overridden is True
    assert records[0].override_reason == "test override"


def test_canada_prime_manual_fallback_rejected_without_reason(tmp_path):
    resp = CanadaPrimeResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    mi = ManualInput(responsibility_id="canada_prime", kind="numeric",
                      numeric_fields={"rate": "4.45"}, override_reason="")
    status = resp.run_manual(ctx, mi)
    assert status == ResponsibilityStatus.VALIDATION_FAILED
    errors = ctx.db.get_errors(ctx.run_id, "canada_prime")
    assert any("MANUAL_OVERRIDE_REASON_MISSING" in e.message or e.error_code for e in errors)


def test_us_fed_funds_idempotent_rerun_produces_same_record_count(monkeypatch, tmp_path):
    _patch_success(monkeypatch, "us_fed_funds", SCENARIOS[1].values[2])
    resp = FedFundsResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    resp.run_automatic(ctx)
    first_count = len(ctx.db.get_rate_records(ctx.run_id, "us_fed_funds"))
    resp.run_automatic(ctx)
    second_count = len(ctx.db.get_rate_records(ctx.run_id, "us_fed_funds"))
    assert first_count == second_count == 1


def _db(tmp_path):
    from cash_equivalents_mvp.database import Database
    return Database(tmp_path / "contract_test.db")
