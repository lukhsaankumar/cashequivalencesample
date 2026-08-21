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


def test_has_profile_false_when_directory_has_unrelated_files_but_no_state_json(tmp_path, monkeypatch):
    """A stray file must not be mistaken for a real saved session — only state.json (written by
    interactive_login's context.storage_state()) counts."""
    monkeypatch.setattr(browser_session, "has_profile", _REAL_HAS_PROFILE)
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    profile_dir = tmp_path / "igm_default"
    profile_dir.mkdir()
    (profile_dir / "some_other_file.txt").write_text("not a session")
    assert browser_session.has_profile("igm_default") is False


def test_has_profile_true_once_state_json_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_session, "has_profile", _REAL_HAS_PROFILE)
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    profile_dir = tmp_path / "igm_default"
    profile_dir.mkdir()
    (profile_dir / "state.json").write_text('{"cookies": [], "origins": []}')
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
    (profile_dir / "state.json").write_text('{"cookies": [], "origins": []}')
    assert browser_session.logout("igm_default") is True
    assert not profile_dir.exists()


class _FakePage:
    """Scripted (url, content-or-exception) sequence — one entry consumed per content() call."""
    def __init__(self, script):
        self._script = list(script)
        self._idx = 0
        self.url = script[0][0]

    def goto(self, url, **kw):
        self.url = url

    def content(self):
        url, outcome = self._script[min(self._idx, len(self._script) - 1)]
        self._idx += 1
        self.url = url
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.storage_state_calls: list[str] = []

    def new_page(self):
        return self._page

    def storage_state(self, path):
        self.storage_state_calls.append(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"cookies": [], "origins": []}')


class _FakeBrowser:
    def __init__(self, context):
        self._context = context
        self.closed = False

    def new_context(self):
        return self._context

    def close(self):
        self.closed = True


class _FakeSyncPlaywrightCM:
    """Stands in for `with sync_playwright() as p: ...` — p.chromium.launch(...) returns the
    single scripted fake browser regardless of headless=True/False."""
    def __init__(self, browser):
        self._browser = browser

    def __enter__(self):
        chromium = type("_Chromium", (), {"launch": lambda self_, **kw: self._browser})()
        return type("_Playwright", (), {"chromium": chromium})()

    def __exit__(self, *exc_info):
        return False


def _install_fake_playwright(monkeypatch, page):
    import sys
    import types
    context = _FakeContext(page)
    browser = _FakeBrowser(context)

    fake_module = types.ModuleType("playwright.sync_api")
    fake_module.sync_playwright = lambda: _FakeSyncPlaywrightCM(browser)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)
    if "playwright" not in sys.modules:
        monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    return context, browser


def test_interactive_login_survives_transient_content_race_during_sso_redirect(tmp_path, monkeypatch):
    """Regression test for a real crash: a user hit `Page.content: Unable to retrieve content
    because the page is navigating and changing the content` mid-SSO-redirect — interactive_login
    used to let that exception propagate and crash the whole login flow instead of just retrying
    on the next poll tick."""
    monkeypatch.setattr(browser_session, "has_profile", _REAL_HAS_PROFILE)
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    monkeypatch.setattr(browser_session.time, "sleep", lambda s: None)

    login_url = "https://login.microsoftonline.com/tenant/oauth2/authorize"
    real_url = "https://home.investorsgroup.com/Content/en/products/pr/gic-tca.shtml"
    script = [
        (login_url, "<html>sign in</html>"),
        (login_url, RuntimeError("Page.content: Unable to retrieve content because the page is "
                                  "navigating and changing the content.")),
        (real_url, "<html>real content, signed in</html>"),
    ]
    page = _FakePage(script)
    context, browser = _install_fake_playwright(monkeypatch, page)

    ok = browser_session.interactive_login("igm_default", real_url, timeout_seconds=30)

    assert ok is True
    assert browser.closed is True
    assert context.storage_state_calls  # session was saved
    assert browser_session.has_profile("igm_default") is True
