"""Tests for the GIC Rates dynamic web-pull chain (gic-tca.shtml link-scrape, tried first ->
SharePoint direct link, fallback only -> file/fixture fallback). All network calls mocked — see
tests/contract/test_file_responsibility_contracts.py's _block_real_network fixture note on why
this suite must never depend on real network access.
"""
from __future__ import annotations

import httpx
import pytest

from cash_equivalents_mvp.collectors import browser_session
from cash_equivalents_mvp.config import source_material_dir
from cash_equivalents_mvp.database import Database
from cash_equivalents_mvp.models import ResponsibilityStatus
from cash_equivalents_mvp.responsibilities.gic_rates import GicRatesResponsibility, _force_sharepoint_download
from tests.conftest import make_context, requires_source_material


def test_force_sharepoint_download_appends_param_to_sharepoint_urls():
    # Real evidence: a scraped ":x:/t/..." SharePoint link opened Excel Online's viewer instead of
    # downloading a file (BrowserDownloadNotTriggeredError) — download=1 is SharePoint/OneDrive's
    # own documented parameter for requesting the raw file instead.
    url = "https://446346262425.sharepoint.com/:x:/t/IGInvestmentProduct/abc123?xsdata=foo"
    result = _force_sharepoint_download(url)
    assert "download=1" in result
    assert "xsdata=foo" in result  # existing query params preserved, not clobbered


def test_force_sharepoint_download_is_a_no_op_for_non_sharepoint_urls():
    url = "https://home.investorsgroup.com/Content/en/products/pr/current-gic-rates.xlsx"
    assert _force_sharepoint_download(url) == url


def _db(tmp_path):
    return Database(tmp_path / "gic_web_test.db")


class _FakeResponse:
    # Plain __init__-based class (not a class nested in a function with `attr = attr` in its
    # body) — a class body does NOT close over its enclosing function's locals the way a nested
    # function does, so `content = content` inside a function-local class raises NameError.
    def __init__(self, *, content: bytes, content_type: str, text: str | None = None, url: str = ""):
        self.status_code = 200
        self.headers = {"content-type": content_type}
        self.content = content
        self.text = text if text is not None else content.decode(errors="replace")
        self.url = url  # real httpx.Response always has this; browser-session detection reads it

    def raise_for_status(self):
        pass


def _fake_xlsx_response(content: bytes = b"PK\x03\x04fakezipcontent"):
    return _FakeResponse(
        content=content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _fake_html_login_response(html: str = "<html><body>Please sign in</body></html>"):
    return _FakeResponse(content=html.encode(), content_type="text/html; charset=utf-8", text=html)


@requires_source_material
def test_sharepoint_returning_html_login_page_falls_through_to_source_material(monkeypatch, tmp_path):
    """A SharePoint link without an authenticated session typically 200s with an HTML login
    page, not an error — must be detected by content-type/magic-bytes, not mis-parsed as xlsx."""
    def fake_get(url, **kw):
        return _fake_html_login_response()
    monkeypatch.setattr(httpx, "get", fake_get)

    resp = GicRatesResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    assert status == ResponsibilityStatus.COMPLETE  # fell through to source_material fixture
    records = ctx.db.get_rate_records(ctx.run_id, "gic_rates")
    assert len(records) >= 1

    # The failed web tiers must be logged as non-fatal warnings, not silently dropped.
    errors = ctx.db.get_errors(ctx.run_id, "gic_rates")
    assert any(e.error_code == "SOURCE_AUTH_REQUIRED" and e.severity == "warning" for e in errors)


def test_web_pull_succeeds_via_product_page_scrape_tried_first(monkeypatch, tmp_path):
    """The product page is tried FIRST (not as a fallback) — it's re-discovered fresh every run
    from whatever gic-tca.shtml actually links to right now, unlike the static SharePoint URL,
    which can go stale (see its embedded share-link token in config/sources.yaml). Verified
    against the real GIC Rates.xlsx bytes so the full scrape->download->parse path is exercised,
    and that SharePoint is never even called when the scrape succeeds on the first try."""
    real_gic_file = source_material_dir() / "GIC Rates.xlsx"
    if not real_gic_file.exists():
        pytest.skip("source_material/GIC Rates.xlsx not present")
    real_bytes = real_gic_file.read_bytes()

    product_page_html = """
    <html><body>
      <p>Some marketing copy.</p>
      <a href="/Content/en/products/pr/current-gic-rates.xlsx">Current GIC Rates</a>
    </body></html>
    """

    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if "sharepoint.com" in url:
            raise AssertionError("SharePoint fallback should not be called when the scrape succeeds")
        if url.endswith("gic-tca.shtml"):
            return _fake_html_login_response(product_page_html)
        if url.endswith("current-gic-rates.xlsx"):
            return _fake_xlsx_response(content=real_bytes)
        raise AssertionError(f"unexpected URL requested: {url}")

    monkeypatch.setattr(httpx, "get", fake_get)

    resp = GicRatesResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    assert status == ResponsibilityStatus.COMPLETE
    assert any(c.endswith("current-gic-rates.xlsx") for c in calls)
    records = ctx.db.get_rate_records(ctx.run_id, "gic_rates")
    assert len(records) >= 1
    artifacts = ctx.db.get_artifacts(ctx.run_id)
    web_artifact = next(a for a in artifacts if a.responsibility_id == "gic_rates")
    assert web_artifact.collection_method == "web_scraped"
    assert web_artifact.source_url.endswith("current-gic-rates.xlsx")


def test_web_pull_falls_back_to_sharepoint_when_scrape_fails(monkeypatch, tmp_path):
    """When the product page can't be scraped (unreachable, or no matching link found), the
    static SharePoint link is tried as a fallback — this is the "share-link token still happens
    to work" fast path, only ever reached after the self-updating tier has failed."""
    real_gic_file = source_material_dir() / "GIC Rates.xlsx"
    if not real_gic_file.exists():
        pytest.skip("source_material/GIC Rates.xlsx not present")
    real_bytes = real_gic_file.read_bytes()

    def fake_get(url, **kw):
        if "sharepoint.com" in url:
            return _fake_xlsx_response(content=real_bytes)
        raise httpx.ConnectError("simulated product page unreachable")
    monkeypatch.setattr(httpx, "get", fake_get)

    resp = GicRatesResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    assert status == ResponsibilityStatus.COMPLETE
    records = ctx.db.get_rate_records(ctx.run_id, "gic_rates")
    assert len(records) >= 1
    artifacts = ctx.db.get_artifacts(ctx.run_id)
    web_artifact = next(a for a in artifacts if a.responsibility_id == "gic_rates")
    assert web_artifact.collection_method == "sharepoint_direct_fallback"

    # The failed scrape tier must still be logged, not silently skipped.
    errors = ctx.db.get_errors(ctx.run_id, "gic_rates")
    assert any(e.error_code == "SOURCE_HTTP_TIMEOUT" and e.severity == "warning" for e in errors)


def test_product_page_with_no_matching_link_logs_layout_changed_warning(monkeypatch, tmp_path):
    def fake_get(url, **kw):
        if "sharepoint.com" in url:
            raise httpx.ConnectError("simulated")
        return _fake_html_login_response("<html><body>Nothing useful here.</body></html>")
    monkeypatch.setattr(httpx, "get", fake_get)

    resp = GicRatesResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    resp.run_automatic(ctx)

    errors = ctx.db.get_errors(ctx.run_id, "gic_rates")
    layout_error = next((e for e in errors if e.error_code == "SOURCE_LAYOUT_CHANGED"), None)
    assert layout_error is not None

    # The actual HTML must be saved for diagnosis, not just described in the message — this is
    # what turns a repeat "no link found" failure into something we can actually look at.
    import re
    from pathlib import Path
    saved_path_match = re.search(r"saved to (\S+) for inspection", layout_error.message)
    assert saved_path_match, layout_error.message
    saved_path = Path(saved_path_match.group(1))
    assert saved_path.exists()
    assert "Nothing useful here" in saved_path.read_text(encoding="utf-8")
    saved_path.unlink()  # cleanup — this writes outside tmp_path, into raw_sources_dir()


class _FakeAuthenticatedClient:
    """Stand-in for the httpx.Client returned by browser_session.authenticated_client — same
    .get(url, timeout=, follow_redirects=)/.close() shape, keyed responses by exact URL."""
    def __init__(self, responses: dict):
        self._responses = responses
        self.calls: list[str] = []
        self.closed = False

    def get(self, url, **kw):
        self.calls.append(url)
        return self._responses[url]

    def close(self):
        self.closed = True


def test_browser_session_tried_first_when_profile_configured(monkeypatch, tmp_path):
    """config/sources.yaml sets gic_rates.automatic.browser_profile — when a saved session exists
    (cli browser-login was run): the product-page scrape uses the saved cookies (a plain httpx GET
    can't get past gic-tca.shtml's SSO wall at all), and the file download uses real browser
    navigation (a plain cookie-jar GET can't complete a SharePoint MCAS session hand-off, which
    requires executing client-side JS — see browser_session.download_via_browser's docstring for
    the real debug-bundle evidence)."""
    real_gic_file = source_material_dir() / "GIC Rates.xlsx"
    if not real_gic_file.exists():
        pytest.skip("source_material/GIC Rates.xlsx not present")
    real_bytes = real_gic_file.read_bytes()

    product_url = "https://home.investorsgroup.com/Content/en/products/pr/gic-tca.shtml"
    xlsx_url = "https://home.investorsgroup.com/Content/en/products/pr/current-gic-rates.xlsx"
    product_page_html = f'<html><body><a href="{xlsx_url}">Current GIC Rates</a></body></html>'

    fake_client = _FakeAuthenticatedClient({product_url: _fake_html_login_response(product_page_html)})
    download_calls = []

    def fake_download_via_browser(profile, url, timeout, headless=True):
        download_calls.append(url)
        assert url == xlsx_url
        # Deliberately headless=False — MCAS's device-trust check needs a real, visible browser
        # window to negotiate a client certificate; headless has no way to do that at all.
        assert headless is False
        return real_bytes

    def fail_plain_http(url, **kw):
        raise AssertionError(f"plain httpx.get must not be called when a browser session is available: {url}")
    monkeypatch.setattr(httpx, "get", fail_plain_http)
    monkeypatch.setattr(browser_session, "has_profile", lambda name: True)
    monkeypatch.setattr(browser_session, "authenticated_client", lambda profile, timeout: fake_client)
    monkeypatch.setattr(browser_session, "download_via_browser", fake_download_via_browser)

    resp = GicRatesResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    assert status == ResponsibilityStatus.COMPLETE
    assert fake_client.calls == [product_url]  # scrape only — download went through the browser instead
    assert download_calls == [xlsx_url]
    assert fake_client.closed is True
    artifacts = ctx.db.get_artifacts(ctx.run_id)
    web_artifact = next(a for a in artifacts if a.responsibility_id == "gic_rates")
    assert web_artifact.collection_method == "web_scraped_authenticated"


def test_browser_session_expired_falls_through_to_sharepoint_via_plain_http(monkeypatch, tmp_path):
    """A saved session that no longer works (e.g. it expired since the last browser-login) must
    be reported as SOURCE_BROWSER_SESSION_EXPIRED, not a generic auth/layout error, and every
    remaining tier must fall back to plain httpx rather than retrying the same dead session."""
    real_gic_file = source_material_dir() / "GIC Rates.xlsx"
    if not real_gic_file.exists():
        pytest.skip("source_material/GIC Rates.xlsx not present")
    real_bytes = real_gic_file.read_bytes()

    product_url = "https://home.investorsgroup.com/Content/en/products/pr/gic-tca.shtml"
    sharepoint_url = ("https://446346262425.sharepoint.com/:x:/r/teams/IG-Portfolio-Strategist/"
                       "Shared%20Documents/Cash%20and%20equivalents/Mike%27s%20Folder/GIC%20Rates.xlsx"
                       "?d=w3963642ba08c4bae8190dad1a4ae884a&csf=1&web=1&e=pcDvdc")

    login_resp = _fake_html_login_response(
        '<script>var $Config={"sCompanyDisplayName":"IGMFinancial"};</script>'
    )
    login_resp.url = "https://login.microsoftonline.com/tenant/oauth2/authorize"
    fake_client = _FakeAuthenticatedClient({product_url: login_resp})

    def fake_plain_get(url, **kw):
        if url == sharepoint_url:
            return _fake_xlsx_response(content=real_bytes)
        raise AssertionError(f"unexpected plain httpx.get call: {url}")
    monkeypatch.setattr(httpx, "get", fake_plain_get)
    monkeypatch.setattr(browser_session, "has_profile", lambda name: True)
    monkeypatch.setattr(browser_session, "authenticated_client", lambda profile, timeout: fake_client)

    resp = GicRatesResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    assert status == ResponsibilityStatus.COMPLETE
    errors = ctx.db.get_errors(ctx.run_id, "gic_rates")
    expired_error = next((e for e in errors if e.error_code == "SOURCE_BROWSER_SESSION_EXPIRED"), None)
    assert expired_error is not None and expired_error.severity == "warning"
    assert fake_client.calls == [product_url]  # never retried against sharepoint with the dead session
    artifacts = ctx.db.get_artifacts(ctx.run_id)
    web_artifact = next(a for a in artifacts if a.responsibility_id == "gic_rates")
    assert web_artifact.collection_method == "sharepoint_direct_fallback"  # not the _authenticated variant

    # save_debug_html writes outside tmp_path, into the real raw_sources_dir() — clean up.
    import re
    from pathlib import Path
    saved_path_match = re.search(r"saved to (\S+)\.", expired_error.message)
    assert saved_path_match, expired_error.message
    Path(saved_path_match.group(1)).unlink(missing_ok=True)


def test_sharepoint_fallback_download_gets_download_param_appended(monkeypatch, tmp_path):
    """The browser-navigation download of a SharePoint link must go through
    _force_sharepoint_download first — a real debug bundle showed the un-transformed link landing
    on Excel Online's viewer (BrowserDownloadNotTriggeredError) instead of downloading a file."""
    real_gic_file = source_material_dir() / "GIC Rates.xlsx"
    if not real_gic_file.exists():
        pytest.skip("source_material/GIC Rates.xlsx not present")
    real_bytes = real_gic_file.read_bytes()

    sharepoint_url = ("https://446346262425.sharepoint.com/:x:/r/teams/IG-Portfolio-Strategist/"
                       "Shared%20Documents/Cash%20and%20equivalents/Mike%27s%20Folder/GIC%20Rates.xlsx"
                       "?d=w3963642ba08c4bae8190dad1a4ae884a&csf=1&web=1&e=pcDvdc")

    def fail_product_page_scrape(url, **kw):
        raise httpx.ConnectError("simulated: force straight to the sharepoint fallback tier")
    monkeypatch.setattr(httpx, "get", fail_product_page_scrape)
    monkeypatch.setattr(browser_session, "has_profile", lambda name: True)
    monkeypatch.setattr(browser_session, "authenticated_client", lambda profile, timeout: None)

    download_calls = []

    def fake_download_via_browser(profile, url, timeout, headless=True):
        download_calls.append(url)
        return real_bytes
    monkeypatch.setattr(browser_session, "download_via_browser", fake_download_via_browser)

    resp = GicRatesResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    assert status == ResponsibilityStatus.COMPLETE
    assert len(download_calls) == 1
    assert "download=1" in download_calls[0]
    assert download_calls[0].startswith(sharepoint_url.split("?")[0])
