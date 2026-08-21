"""Tests for the new GIC Rates dynamic web-pull chain (SharePoint direct link ->
gic-tca.shtml link-scrape -> file/fixture fallback). All network calls mocked — see
tests/contract/test_file_responsibility_contracts.py's _block_real_network fixture note on why
this suite must never depend on real network access.
"""
from __future__ import annotations

import httpx
import pytest

from cash_equivalents_mvp.config import source_material_dir
from cash_equivalents_mvp.database import Database
from cash_equivalents_mvp.models import ResponsibilityStatus
from cash_equivalents_mvp.responsibilities.gic_rates import GicRatesResponsibility
from tests.conftest import make_context, requires_source_material


def _db(tmp_path):
    return Database(tmp_path / "gic_web_test.db")


class _FakeResponse:
    # Plain __init__-based class (not a class nested in a function with `attr = attr` in its
    # body) — a class body does NOT close over its enclosing function's locals the way a nested
    # function does, so `content = content` inside a function-local class raises NameError.
    def __init__(self, *, content: bytes, content_type: str, text: str | None = None):
        self.status_code = 200
        self.headers = {"content-type": content_type}
        self.content = content
        self.text = text if text is not None else content.decode(errors="replace")

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


def test_web_pull_succeeds_via_sharepoint_direct_link(monkeypatch, tmp_path):
    """When the SharePoint link genuinely returns a real xlsx, it should be parsed directly —
    verified against the real GIC Rates.xlsx bytes so the full download->parse path is exercised."""
    import cash_equivalents_mvp.responsibilities.gic_rates as gic_mod

    real_gic_file = source_material_dir() / "GIC Rates.xlsx"
    if not real_gic_file.exists():
        pytest.skip("source_material/GIC Rates.xlsx not present")
    real_bytes = real_gic_file.read_bytes()

    def fake_get(url, **kw):
        assert "sharepoint.com" in url
        return _fake_xlsx_response(content=real_bytes)
    monkeypatch.setattr(httpx, "get", fake_get)

    resp = GicRatesResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    assert status == ResponsibilityStatus.COMPLETE
    records = ctx.db.get_rate_records(ctx.run_id, "gic_rates")
    assert len(records) >= 1
    artifacts = ctx.db.get_artifacts(ctx.run_id)
    web_artifact = next(a for a in artifacts if a.responsibility_id == "gic_rates")
    assert web_artifact.collection_method == "sharepoint_direct"


def test_web_pull_scrapes_product_page_when_sharepoint_fails(monkeypatch, tmp_path):
    """SharePoint fails outright; the product page is scraped for a rates-file link and that
    link is followed instead — exercises the BeautifulSoup link-discovery path."""
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
            raise httpx.ConnectError("simulated SharePoint auth failure")
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
    artifacts = ctx.db.get_artifacts(ctx.run_id)
    web_artifact = next(a for a in artifacts if a.responsibility_id == "gic_rates")
    assert web_artifact.collection_method == "web_scraped"
    assert web_artifact.source_url.endswith("current-gic-rates.xlsx")


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
    assert any(e.error_code == "SOURCE_LAYOUT_CHANGED" for e in errors)
