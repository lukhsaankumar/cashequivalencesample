"""Unit tests for collectors/browser_session.py. Deliberately never launches a real Playwright
browser (this suite must run in environments without playwright installed at all — the "no
profile created yet" path must short-circuit before ever importing playwright, so most sources
never pay any cost for this feature existing) — see money_market.py / gic_rates.py's use of it.
"""
from __future__ import annotations

from cash_equivalents_mvp.collectors import browser_session

# tests/conftest.py's autouse `_no_real_browser_profile` fixture stubs has_profile() to always
# return False for the rest of the suite (so a real local profile never leaks into other tests)
# — this file exists specifically to test has_profile() itself, so it restores the real
# implementation, captured here before any monkeypatching happens.
_REAL_HAS_PROFILE = browser_session.has_profile


def test_is_login_page_detects_real_captured_microsoft_sso_markers():
    # Captured verbatim (labels only, not full contents) from a real corporate debug bundle —
    # this is the exact evidence that proved gic-tca.shtml is behind interactive SSO, not a
    # scraper bug. Regression-pinned so the detector never regresses on the concrete case that
    # motivated this whole module.
    html = (
        '<script>var $Config={"urlMsaSignUp":"...", "sCompanyDisplayName":"IGMFinancial", '
        '"urlCancel":"https://home.investorsgroup.com/Shibboleth.sso/SAML2/POST?error=access_denied"};'
        "</script>"
    )
    assert browser_session.is_login_page("https://login.microsoftonline.com/some/path", html) is True


def test_is_login_page_detects_by_host_alone():
    assert browser_session.is_login_page("https://login.microsoftonline.com/tenant/oauth2", "") is True


def test_is_login_page_false_for_real_content():
    assert browser_session.is_login_page(
        "https://home.investorsgroup.com/Content/en/products/pr/gic-tca.shtml",
        "<html><body>Current GIC rates: <a href='rates.xlsx'>download</a></body></html>",
    ) is False


def test_has_profile_false_when_never_created(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_session, "has_profile", _REAL_HAS_PROFILE)
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    assert browser_session.has_profile("igm_default") is False


def test_has_profile_false_when_directory_exists_but_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_session, "has_profile", _REAL_HAS_PROFILE)
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    (tmp_path / "igm_default").mkdir()
    assert browser_session.has_profile("igm_default") is False


def test_has_profile_true_once_populated(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_session, "has_profile", _REAL_HAS_PROFILE)
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    profile_dir = tmp_path / "igm_default"
    profile_dir.mkdir()
    (profile_dir / "Default").mkdir()
    assert browser_session.has_profile("igm_default") is True


def test_authenticated_client_returns_none_without_importing_playwright_when_no_profile(tmp_path, monkeypatch):
    """The whole point of the has_profile() short-circuit: a source with no browser_profile ever
    set up must behave identically whether or not playwright/browser binaries are installed."""
    import sys
    monkeypatch.setattr(browser_session, "has_profile", _REAL_HAS_PROFILE)
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    monkeypatch.setitem(sys.modules, "playwright", None)  # would raise ImportError if ever touched
    assert browser_session.authenticated_client("igm_default") is None


def test_render_authenticated_page_returns_none_without_importing_playwright_when_no_profile(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(browser_session, "has_profile", _REAL_HAS_PROFILE)
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    monkeypatch.setitem(sys.modules, "playwright", None)
    assert browser_session.render_authenticated_page("igm_default", "https://example.test") is None


def test_logout_returns_false_when_nothing_to_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    assert browser_session.logout("igm_default") is False


def test_logout_deletes_existing_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    profile_dir = tmp_path / "igm_default"
    profile_dir.mkdir()
    (profile_dir / "Default").mkdir()
    assert browser_session.logout("igm_default") is True
    assert not profile_dir.exists()
