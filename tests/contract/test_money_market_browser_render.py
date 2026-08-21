"""Tests for money_market.py's browser-session render tier. A real debug bundle showed the plain
HTTP tier reaches genuine Lipper content (not a login redirect) but the raw server HTML has no
percentage value anywhere — consistent with the yield being populated by JavaScript after page
load. `render_authenticated_page` (full headless render, JS executed) is the fix; these tests
never launch a real browser — browser_session's functions are mocked at the module boundary.
"""
from __future__ import annotations

import httpx
import pytest

from cash_equivalents_mvp.collectors import browser_session
from cash_equivalents_mvp.database import Database
from cash_equivalents_mvp.models import ResponsibilityStatus
from cash_equivalents_mvp.responsibilities.money_market import MoneyMarketResponsibility
from tests.conftest import make_context


def _db(tmp_path):
    return Database(tmp_path / "mm_browser_test.db")


def test_rendered_page_used_first_when_profile_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_session, "has_profile", lambda name: True)

    rendered = {
        "https://digital.lipperweb.com/invgrp/profile?symbol=68317397&lang=en":
            "<html><body>Current Yield 2.00%</body></html>",
        "https://digital.lipperweb.com/invgrp/profile?symbol=68002367&lang=en":
            "<html><body>Current Yield 2.82%</body></html>",
    }

    def fake_render(profile, url, timeout_seconds=20):
        return rendered[url]
    monkeypatch.setattr(browser_session, "render_authenticated_page", fake_render)

    def fail_plain_http(url, **kw):
        raise AssertionError(f"plain httpx.get must not be called when the render tier succeeds: {url}")
    monkeypatch.setattr(httpx, "get", fail_plain_http)

    resp = MoneyMarketResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    assert status == ResponsibilityStatus.COMPLETE
    records = ctx.db.get_rate_records(ctx.run_id, "money_market")
    # RateRecord.rate is stored canonical (fractional, e.g. 2.00% -> 0.02), not the raw percent text.
    assert {str(r.rate) for r in records} == {"0.02", "0.0282"}
    artifacts = ctx.db.get_artifacts(ctx.run_id)
    artifact = next(a for a in artifacts if a.responsibility_id == "money_market")
    assert artifact.collection_method == "browser_session_rendered"


def test_session_expired_falls_through_to_plain_http(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_session, "has_profile", lambda name: True)

    def fake_render(profile, url, timeout_seconds=20):
        raise browser_session.BrowserSessionExpiredError(url)
    monkeypatch.setattr(browser_session, "render_authenticated_page", fake_render)

    def fake_plain_get(url, **kw):
        return _Resp("<html><body>Current Yield 2.00%</body></html>")
    monkeypatch.setattr(httpx, "get", fake_plain_get)

    resp = MoneyMarketResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    assert status == ResponsibilityStatus.COMPLETE
    errors = ctx.db.get_errors(ctx.run_id, "money_market")
    assert any(e.error_code == "SOURCE_BROWSER_SESSION_EXPIRED" and e.severity == "warning" for e in errors)
    artifacts = ctx.db.get_artifacts(ctx.run_id)
    artifact = next(a for a in artifacts if a.responsibility_id == "money_market")
    assert artifact.collection_method == "authenticated_http"  # plain tier, not the rendered one


def test_rendered_page_missing_yield_saves_debug_html_and_still_tries_plain_http(monkeypatch, tmp_path):
    """Post-render content that STILL doesn't contain a yield is a genuine layout problem (the
    render succeeded, so it can't be blamed on JS not having run) — must be diagnosable, and must
    not block the existing plain-HTTP tier from still getting a chance."""
    monkeypatch.setattr(browser_session, "has_profile", lambda name: True)

    def fake_render(profile, url, timeout_seconds=20):
        return "<html><body>No yield info here.</body></html>"
    monkeypatch.setattr(browser_session, "render_authenticated_page", fake_render)

    def fake_plain_get(url, **kw):
        return _Resp("<html><body>Current Yield 2.00%</body></html>")
    monkeypatch.setattr(httpx, "get", fake_plain_get)

    resp = MoneyMarketResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)

    assert status == ResponsibilityStatus.COMPLETE
    errors = ctx.db.get_errors(ctx.run_id, "money_market")
    layout_errors = [e for e in errors if e.error_code == "SOURCE_LAYOUT_CHANGED"]
    assert layout_errors, errors
    assert "saved to" in layout_errors[0].message

    # save_debug_html writes outside tmp_path, into the real raw_sources_dir() — clean up.
    import re
    from pathlib import Path
    for e in layout_errors:
        m = re.search(r"saved to (\S+)\.", e.message)
        if m:
            Path(m.group(1)).unlink(missing_ok=True)


class _Resp:
    def __init__(self, text):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        pass
