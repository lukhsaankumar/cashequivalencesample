"""Unit tests for collectors/browser_session.py. Deliberately never launches a real Playwright
browser (this suite must run in environments without playwright installed at all — the "no
profile created yet" path must short-circuit before ever importing playwright, so most sources
never pay any cost for this feature existing) — see money_market.py / gic_rates.py's use of it.
"""
from __future__ import annotations

import pytest

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
        self.new_context_calls: list[dict] = []
        self.launch_calls: list[dict] = []

    def new_context(self, **kw):
        self.new_context_calls.append(kw)
        return self._context

    def close(self):
        self.closed = True


class _FakeSyncPlaywrightCM:
    """Stands in for `with sync_playwright() as p: ...` — p.chromium.launch(...) records its
    kwargs (e.g. headless=) on the single scripted fake browser and returns it regardless."""
    def __init__(self, browser):
        self._browser = browser

    def __enter__(self):
        def _launch(self_, **kw):
            self._browser.launch_calls.append(kw)
            return self._browser
        chromium = type("_Chromium", (), {"launch": _launch})()
        return type("_Playwright", (), {"chromium": chromium})()

    def __exit__(self, *exc_info):
        return False


class _FakePlaywrightTimeoutError(Exception):
    pass


def _install_fake_playwright(monkeypatch, page):
    import sys
    import types
    context = _FakeContext(page)
    browser = _FakeBrowser(context)

    fake_module = types.ModuleType("playwright.sync_api")
    fake_module.sync_playwright = lambda: _FakeSyncPlaywrightCM(browser)
    fake_module.TimeoutError = _FakePlaywrightTimeoutError
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)
    if "playwright" not in sys.modules:
        monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    return context, browser


class _FakeExpectDownload:
    """Stands in for `with page.expect_download() as download_info: ...` — .value returns the
    scripted download, or raises the scripted (fake) PlaywrightTimeoutError if none was set,
    matching how a real "no download ever fired" case surfaces."""
    def __init__(self, download=None, error=None):
        self._download = download
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    @property
    def value(self):
        if self._error is not None:
            raise self._error
        return self._download


class _FakeDownload:
    def __init__(self, content: bytes, dest_dir):
        self._path = dest_dir / "downloaded.xlsx"
        self._path.write_bytes(content)

    def path(self):
        return str(self._path)


class _FakeDownloadPage:
    """Page double for download_via_browser — goto() is a no-op; expect_download() returns
    whatever outcome the test scripted (a real download, or a timeout meaning none fired), and
    content()/url reflect what the page would show if no download happened. content_raises_before_
    success lets a test simulate the transient "page is navigating" race that content() can hit."""
    def __init__(self, *, download_content: bytes | None = None, dest_dir=None,
                 final_url: str = "", final_html: str = "", content_raises_before_success: int = 0):
        self.url = final_url
        self._html = final_html
        self._content_calls = 0
        self._content_raises_before_success = content_raises_before_success
        if download_content is not None:
            self._expect_download_result = _FakeExpectDownload(
                download=_FakeDownload(download_content, dest_dir))
        else:
            self._expect_download_result = _FakeExpectDownload(error=_FakePlaywrightTimeoutError("no download"))

    def goto(self, url, **kw):
        pass

    def expect_download(self, timeout=None):
        return self._expect_download_result

    def content(self):
        self._content_calls += 1
        if self._content_calls <= self._content_raises_before_success:
            raise RuntimeError("Page.content: Unable to retrieve content because the page is "
                                "navigating and changing the content.")
        return self._html


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


def test_interactive_login_loads_existing_session_before_saving_a_new_one(tmp_path, monkeypatch):
    """Regression test for a real bug: all four sources share one profile name (igm_default).
    interactive_login used to always start from an empty context and unconditionally overwrite
    state.json — so signing into a second source silently destroyed the first source's already-
    saved session instead of adding to it. A real user hit this: `browser-login --source
    money_market` after an earlier successful `browser-login --source gic_rates` wiped the
    gic_rates session back to expired on the very next run."""
    monkeypatch.setattr(browser_session, "has_profile", _REAL_HAS_PROFILE)
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    monkeypatch.setattr(browser_session.time, "sleep", lambda s: None)

    # Simulate an already-saved session from a prior browser-login for a different source.
    profile_dir = tmp_path / "igm_default"
    profile_dir.mkdir()
    existing_state_path = profile_dir / "state.json"
    existing_state_path.write_text('{"cookies": [{"name": "gic_rates_session"}], "origins": []}')

    real_url = "https://digital.lipperweb.com/invgrp/profile?symbol=68317397&lang=en"
    page = _FakePage([(real_url, "<html>signed in to lipper</html>")])
    context, browser = _install_fake_playwright(monkeypatch, page)

    ok = browser_session.interactive_login("igm_default", real_url, timeout_seconds=30)

    assert ok is True
    # The new context must have been seeded with the pre-existing session, not started empty —
    # this is what makes the saved storage_state() at the end a union of both sources' cookies
    # instead of a wholesale replacement.
    assert browser.new_context_calls == [{"storage_state": str(existing_state_path)}]


def _seed_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_session, "has_profile", _REAL_HAS_PROFILE)
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    profile_dir = tmp_path / "igm_default"
    profile_dir.mkdir()
    (profile_dir / "state.json").write_text('{"cookies": [], "origins": []}')


def test_download_via_browser_returns_none_when_no_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_session, "has_profile", _REAL_HAS_PROFILE)
    monkeypatch.setattr(browser_session, "browser_profile_dir", lambda: tmp_path)
    assert browser_session.download_via_browser("igm_default", "https://example.test/file.xlsx") is None


def test_download_via_browser_returns_bytes_on_real_download(tmp_path, monkeypatch):
    _seed_profile(monkeypatch, tmp_path)
    dl_dir = tmp_path / "downloads"
    dl_dir.mkdir()
    page = _FakeDownloadPage(download_content=b"PK\x03\x04fake-xlsx-bytes", dest_dir=dl_dir)
    context, browser = _install_fake_playwright(monkeypatch, page)

    result = browser_session.download_via_browser("igm_default", "https://example.test/file.xlsx")

    assert result == b"PK\x03\x04fake-xlsx-bytes"
    assert context.storage_state_calls  # session refreshed after a successful use
    assert browser.closed is True


def test_download_via_browser_raises_session_expired_when_login_page_reached(tmp_path, monkeypatch):
    """No download fired AND the page we landed on is a real login page — a real code fix
    (browser-login) is what's needed, not a retry."""
    _seed_profile(monkeypatch, tmp_path)
    page = _FakeDownloadPage(
        download_content=None,
        final_url="https://login.microsoftonline.com/tenant/oauth2/authorize",
        final_html="<html>sign in</html>",
    )
    context, browser = _install_fake_playwright(monkeypatch, page)

    with pytest.raises(browser_session.BrowserSessionExpiredError):
        browser_session.download_via_browser("igm_default", "https://example.test/file.xlsx")
    assert browser.closed is True
    assert not context.storage_state_calls  # an expired session must not be re-saved as if valid


def test_download_via_browser_raises_not_triggered_for_real_non_login_content(tmp_path, monkeypatch):
    """No download fired, but we landed on real, non-login content (e.g. a SharePoint Excel
    Online viewer page) — the session is fine, the link just isn't a raw downloadable file, so
    this must be distinguishable from BrowserSessionExpiredError."""
    _seed_profile(monkeypatch, tmp_path)
    page = _FakeDownloadPage(
        download_content=None,
        final_url="https://446346262425.sharepoint.com/:x:/t/IGInvestmentProduct/abc123",
        final_html="<html>Excel Online viewer content, not a login page</html>",
    )
    context, browser = _install_fake_playwright(monkeypatch, page)

    with pytest.raises(browser_session.BrowserDownloadNotTriggeredError):
        browser_session.download_via_browser("igm_default", "https://example.test/file.xlsx")
    assert browser.closed is True
    assert context.storage_state_calls  # session is valid, just refreshed as normal


def test_download_via_browser_defaults_to_headless_true(tmp_path, monkeypatch):
    _seed_profile(monkeypatch, tmp_path)
    dl_dir = tmp_path / "downloads"
    dl_dir.mkdir()
    page = _FakeDownloadPage(download_content=b"bytes", dest_dir=dl_dir)
    context, browser = _install_fake_playwright(monkeypatch, page)

    browser_session.download_via_browser("igm_default", "https://example.test/file.xlsx")

    assert browser.launch_calls == [{"headless": True}]


def test_download_via_browser_threads_through_headless_false(tmp_path, monkeypatch):
    """Regression test: gic_rates.py deliberately passes headless=False for the SharePoint
    download so a real, visible browser window gets a chance at MCAS's device-trust client-
    certificate negotiation, which a headless browser has no way to complete at all."""
    _seed_profile(monkeypatch, tmp_path)
    dl_dir = tmp_path / "downloads"
    dl_dir.mkdir()
    page = _FakeDownloadPage(download_content=b"bytes", dest_dir=dl_dir)
    context, browser = _install_fake_playwright(monkeypatch, page)

    browser_session.download_via_browser("igm_default", "https://example.test/file.xlsx", headless=False)

    assert browser.launch_calls == [{"headless": False}]


def test_read_content_and_url_retries_transient_failures(monkeypatch):
    monkeypatch.setattr(browser_session.time, "sleep", lambda s: None)

    class _FlakyPage:
        url = "https://example.test/final"
        calls = 0

        def content(self):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("Page.content: Unable to retrieve content because the page is "
                                    "navigating and changing the content.")
            return "<html>ok</html>"

    page = _FlakyPage()
    html, url = browser_session._read_content_and_url(page)
    assert html == "<html>ok</html>"
    assert url == "https://example.test/final"
    assert page.calls == 3


def test_read_content_and_url_raises_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr(browser_session.time, "sleep", lambda s: None)

    class _AlwaysFlakyPage:
        url = "https://example.test/final"

        def content(self):
            raise RuntimeError("always fails")

    with pytest.raises(RuntimeError, match="always fails"):
        browser_session._read_content_and_url(_AlwaysFlakyPage(), attempts=3)


def test_download_via_browser_survives_transient_content_race(tmp_path, monkeypatch):
    """Regression test for a real crash: a user hit the exact same "page is navigating" race
    inside download_via_browser (this time on a real GIC Rates SharePoint fetch) that
    interactive_login was already fixed for — download_via_browser had its own unguarded
    page.content() call that let the same transient exception crash the whole download attempt
    instead of retrying."""
    monkeypatch.setattr(browser_session.time, "sleep", lambda s: None)
    _seed_profile(monkeypatch, tmp_path)
    page = _FakeDownloadPage(
        download_content=None,  # no download fires -> falls into the page.content()-reading path
        final_url="https://446346262425.sharepoint.com/:x:/t/IGInvestmentProduct/abc123",
        final_html="<html>Excel Online viewer content, not a login page</html>",
        content_raises_before_success=2,
    )
    context, browser = _install_fake_playwright(monkeypatch, page)

    with pytest.raises(browser_session.BrowserDownloadNotTriggeredError):
        browser_session.download_via_browser("igm_default", "https://example.test/file.xlsx")
    assert browser.closed is True
    assert context.storage_state_calls  # still reached the "valid session" refresh afterward
