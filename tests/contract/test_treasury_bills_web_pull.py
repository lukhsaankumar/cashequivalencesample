"""Tests for the Treasury Bills browser-session-based web-pull chain (NBIN landing-page scrape ->
PDF download via real browser navigation -> file/fixture fallback). All network/browser calls
mocked — see test_file_responsibility_contracts.py's _block_real_network fixture note on why this
suite must never depend on real network access. NBIN's real authenticated page structure has never
been captured, so these tests exercise the mechanics (tiering, fallback, debug-html saving) against
synthetic HTML rather than claiming to match NBIN's actual layout.
"""
from __future__ import annotations

import httpx
import pytest

from cash_equivalents_mvp.collectors import browser_session
from cash_equivalents_mvp.config import source_material_dir
from cash_equivalents_mvp.database import Database
from cash_equivalents_mvp.models import ResponsibilityStatus
from cash_equivalents_mvp.responsibilities.treasury_bills import TreasuryBillsResponsibility
from tests.conftest import make_context


def _db(tmp_path):
    return Database(tmp_path / "tbills_web_test.db")


class _FakeResponse:
    def __init__(self, *, content: bytes, content_type: str, text: str | None = None, url: str = ""):
        self.status_code = 200
        self.headers = {"content-type": content_type}
        self.content = content
        self.text = text if text is not None else content.decode(errors="replace")
        self.url = url

    def raise_for_status(self):
        pass


def _fake_pdf_response(content: bytes):
    return _FakeResponse(content=content, content_type="application/pdf")


def _fake_html_response(html: str, url: str = ""):
    return _FakeResponse(content=html.encode(), content_type="text/html; charset=utf-8", text=html, url=url)


class _FakeAuthenticatedClient:
    def __init__(self, responses: dict):
        self._responses = responses
        self.calls: list[str] = []
        self.closed = False

    def get(self, url, **kw):
        self.calls.append(url)
        return self._responses[url]

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch):
    def _fail_fast(url, **kw):
        raise httpx.ConnectError("blocked in test: no real network calls in the offline suite")
    monkeypatch.setattr(httpx, "get", _fail_fast)


def _real_pdf_bytes():
    path = source_material_dir() / "NBF T bill rates.pdf"
    if not path.exists():
        pytest.skip("source_material/NBF T bill rates.pdf not present")
    return path.read_bytes()


def test_no_browser_profile_configured_falls_through_to_source_material(monkeypatch, tmp_path):
    """No profile ever created (has_profile False, the default via conftest's autouse fixture) ->
    the web tier is a complete no-op and this behaves exactly like the pre-browser-session version:
    falls straight through to the source_material/ historical fixture."""
    resp = TreasuryBillsResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    if source_material_dir().exists() and any(source_material_dir().glob("NBF*.pdf")):
        assert status == ResponsibilityStatus.COMPLETE
        artifacts = ctx.db.get_artifacts(ctx.run_id)
        artifact = next(a for a in artifacts if a.responsibility_id == "treasury_bills")
        assert artifact.collection_method == "file_watch_detected"
    else:
        assert status == ResponsibilityStatus.MANUAL_REQUIRED


def test_browser_session_scrape_and_download_succeed(monkeypatch, tmp_path):
    real_bytes = _real_pdf_bytes()
    nav_url = "https://www.nbin.ca/cmst/site/index.jhtml?navid=814"
    pdf_url = "https://www.nbin.ca/cmst/rates/current-tbill-rates.pdf"
    landing_html = f'<html><body><a href="{pdf_url}">T-Bill Rate Sheet</a></body></html>'

    fake_client = _FakeAuthenticatedClient({nav_url: _fake_html_response(landing_html, url=nav_url)})
    download_calls = []

    def fake_download_via_browser(profile, url, timeout, headless=True):
        download_calls.append(url)
        assert headless is False  # same device-trust reasoning as gic_rates.py
        return real_bytes

    def fail_plain_http(url, **kw):
        raise AssertionError(f"plain httpx.get must not be called when a browser session succeeds: {url}")
    monkeypatch.setattr(httpx, "get", fail_plain_http)
    monkeypatch.setattr(browser_session, "has_profile", lambda name: True)
    monkeypatch.setattr(browser_session, "authenticated_client", lambda profile, timeout: fake_client)
    monkeypatch.setattr(browser_session, "download_via_browser", fake_download_via_browser)

    resp = TreasuryBillsResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    assert status == ResponsibilityStatus.COMPLETE
    assert fake_client.calls == [nav_url]
    assert download_calls == [pdf_url]
    assert fake_client.closed is True
    records = ctx.db.get_rate_records(ctx.run_id, "treasury_bills")
    assert len(records) >= 1
    artifacts = ctx.db.get_artifacts(ctx.run_id)
    artifact = next(a for a in artifacts if a.responsibility_id == "treasury_bills")
    assert artifact.collection_method == "web_scraped_authenticated"


def test_session_expired_on_landing_page_falls_through_to_file_fixture(monkeypatch, tmp_path):
    nav_url = "https://www.nbin.ca/cmst/site/index.jhtml?navid=814"
    login_resp = _fake_html_response(
        '<script>var $Config={"sCompanyDisplayName":"IGMFinancial"};</script>',
        url="https://login.microsoftonline.com/tenant/oauth2/authorize",
    )
    fake_client = _FakeAuthenticatedClient({nav_url: login_resp})
    monkeypatch.setattr(browser_session, "has_profile", lambda name: True)
    monkeypatch.setattr(browser_session, "authenticated_client", lambda profile, timeout: fake_client)

    resp = TreasuryBillsResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    errors = ctx.db.get_errors(ctx.run_id, "treasury_bills")
    expired_error = next((e for e in errors if e.error_code == "SOURCE_BROWSER_SESSION_EXPIRED"), None)
    assert expired_error is not None and expired_error.severity == "warning"

    # save_debug_html writes outside tmp_path, into the real raw_sources_dir() — clean up.
    import re
    from pathlib import Path
    saved_path_match = re.search(r"saved to (\S+)\.", expired_error.message)
    assert saved_path_match, expired_error.message
    Path(saved_path_match.group(1)).unlink(missing_ok=True)

    if source_material_dir().exists() and any(source_material_dir().glob("NBF*.pdf")):
        assert status == ResponsibilityStatus.COMPLETE
    else:
        assert status == ResponsibilityStatus.MANUAL_REQUIRED


def test_no_matching_pdf_link_saves_debug_html(monkeypatch, tmp_path):
    nav_url = "https://www.nbin.ca/cmst/site/index.jhtml?navid=814"
    fake_client = _FakeAuthenticatedClient({
        nav_url: _fake_html_response("<html><body>Nothing useful here.</body></html>", url=nav_url)
    })
    monkeypatch.setattr(browser_session, "has_profile", lambda name: True)
    monkeypatch.setattr(browser_session, "authenticated_client", lambda profile, timeout: fake_client)

    resp = TreasuryBillsResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    resp.run_automatic(ctx)

    errors = ctx.db.get_errors(ctx.run_id, "treasury_bills")
    layout_error = next((e for e in errors if e.error_code == "SOURCE_LAYOUT_CHANGED"), None)
    assert layout_error is not None

    import re
    from pathlib import Path
    saved_path_match = re.search(r"saved to (\S+) for inspection", layout_error.message)
    assert saved_path_match, layout_error.message
    saved_path = Path(saved_path_match.group(1))
    assert saved_path.exists()
    assert "Nothing useful here" in saved_path.read_text(encoding="utf-8")
    saved_path.unlink()
