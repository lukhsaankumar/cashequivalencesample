"""Persistent authenticated browser sessions for SSO-gated sources (Playwright, optional).

Why this exists: `cli diagnose` debug bundles proved that home.investorsgroup.com (GIC Rates,
HISA) and, less conclusively, digital.lipperweb.com (Money Market) are not plain-HTTP-reachable
scraper bugs — the GIC product page redirects an unauthenticated request straight to a real
Microsoft/Entra ID SSO login page (captured markers: "sCompanyDisplayName":"IGMFinancial",
Shibboleth.sso/SAML2/POST), and the Lipper page returns real content but with the actual yield
number absent from the raw server HTML (consistent with a client-side-rendered value). No amount
of regex/header tuning fixes either case — see docs/debugging.md.

What this module does NOT do, ever (see SECURITY.md):
  - It never stores, guesses, brute-forces, or replays a password or MFA code. The user types
    their own credentials into the real login page, in a real visible browser window they can see
    and control (`interactive_login`), exactly as they would in Chrome or Edge.
  - It never automates the login step itself. `interactive_login` opens the window and waits;
    it does not fill in fields or click through prompts.
  - It only ever reuses the *session* (cookies) that results from a login the user already
    performed — functionally identical to a browser's "stay signed in", not a bypass of it.

Session persistence uses Playwright's documented `storage_state()` pattern
(https://playwright.dev/python/docs/auth#reuse-authentication-state) — an explicit JSON snapshot
of cookies + local storage, refreshed after every successful use — rather than
`launch_persistent_context`'s on-disk Chromium profile. That distinction matters: a corporate SSO
session cookie is typically a "session cookie" (no explicit Expires/Max-Age, by design, so it
ends when the browser truly closes), and Chromium's persistent-profile store does not reliably
carry those across separate process launches the way `storage_state()` does — an earlier version
of this module used `launch_persistent_context` throughout and the saved session was gone almost
immediately after a real interactive login, which is what motivated this rewrite.

Fully optional and backward compatible: if playwright isn't installed, or a named profile has
never been created (`cli browser-login` never run for it), every function here degrades to a
silent no-op (`has_profile` false / functions return None) so every responsibility's existing
plain-HTTP tiers are completely unaffected.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from cash_equivalents_mvp.config import browser_profile_dir

# Captured verbatim from a real corporate-network debug bundle — the exact markers present in the
# Microsoft/Entra ID + Shibboleth SAML login interstitial home.investorsgroup.com redirected to
# for an unauthenticated request. Not a guess at what an SSO page "probably" looks like.
LOGIN_HOST_MARKERS = ("login.microsoftonline.com", "login.windows.net", "Shibboleth.sso", "/adfs/")
LOGIN_CONTENT_MARKERS = ("urlMsaSignUp", "sCompanyDisplayName", "Shibboleth.sso/SAML2")

_CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_STATE_FILENAME = "state.json"


class BrowserSessionExpiredError(Exception):
    """A saved profile exists but the site redirected to a login page — the session needs
    refreshing via `cli browser-login`, not a code fix."""


class BrowserDownloadNotTriggeredError(Exception):
    """The saved session is valid (no login page reached) but navigating to the URL didn't
    trigger a browser download either — e.g. a SharePoint share link in Excel Online's "viewer"
    format renders an embedded spreadsheet UI instead of downloading a file. Distinct from an
    expired session: retrying this one via `cli browser-login` won't change the outcome, since
    the session isn't the problem — the link itself isn't a raw downloadable file."""


def profile_path(profile_name: str) -> Path:
    return browser_profile_dir() / profile_name


def _state_path(profile_name: str) -> Path:
    return profile_path(profile_name) / _STATE_FILENAME


def has_profile(profile_name: str) -> bool:
    """True only once `interactive_login` has actually completed and saved a storage-state
    snapshot for this name — an empty/never-created directory means the feature simply isn't set
    up yet, not an error."""
    return _state_path(profile_name).exists()


def is_login_page(final_url: str, text: str) -> bool:
    """Pure and independently testable — detects the exact SSO login markers captured from a real
    debug bundle, not a heuristic guess. Used both to know when to stop waiting during interactive
    login, and to distinguish an expired saved session from a real content/layout problem."""
    if any(marker in final_url for marker in LOGIN_HOST_MARKERS):
        return True
    return any(marker in text for marker in LOGIN_CONTENT_MARKERS)


def interactive_login(profile_name: str, start_url: str, timeout_seconds: int = 300) -> bool:
    """Opens a VISIBLE Chromium window at `start_url` for the user to sign in exactly as they
    normally would (including any MFA prompt). Blocks until the browser has navigated away from
    the login host, or `timeout_seconds` elapses. On success, snapshots cookies + local storage to
    disk via `context.storage_state()` — captured explicitly, not left to Chromium's own profile
    persistence, since that does not reliably survive session-only SSO cookies across separate
    process launches (see module docstring). Returns True if a sign-in was detected."""
    from playwright.sync_api import sync_playwright  # deferred: optional dependency

    dest = profile_path(profile_name)
    dest.mkdir(parents=True, exist_ok=True)
    existing_state = _state_path(profile_name)
    print(f"Opening a browser window for {start_url}")
    print("Sign in exactly as you normally would (including MFA if prompted).")
    print(f"This window closes automatically once you're signed in (or after {timeout_seconds}s).")

    signed_in = False
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        # If this profile already has a saved session (e.g. from signing into a different source
        # that shares this profile name), load it into the new context first so this login ADDS
        # to it instead of replacing it — context.storage_state() below saves the union of both.
        # Without this, a second `browser-login` for a different source silently wipes out every
        # other source's already-saved session, since they'd otherwise start from an empty context.
        context = (browser.new_context(storage_state=str(existing_state)) if existing_state.exists()
                   else browser.new_context())
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                # Read content() first, then url — page.url is a live property while content()
                # takes a moment to resolve, so reading url second keeps both readings closer to
                # the same navigation state instead of interleaving a stale url with fresh content
                # (or vice versa) if a navigation completes in between the two reads.
                html = page.content()
                current_url = page.url
            except Exception:
                # An SSO sign-in involves several navigation hops (home.investorsgroup.com ->
                # login.microsoftonline.com -> back); polling page.content() can transiently race
                # a navigation in progress ("page is navigating and changing the content") right
                # as the user finishes signing in. Not a real failure — just means the poll landed
                # mid-hop; try again next tick instead of crashing the whole login flow.
                time.sleep(2)
                continue
            if not is_login_page(current_url, html):
                signed_in = True
                break
            time.sleep(2)
        if signed_in:
            context.storage_state(path=str(_state_path(profile_name)))
        browser.close()

    if signed_in:
        print(f"Signed in — session saved to {_state_path(profile_name)}")
    else:
        print("Timed out waiting for sign-in; nothing was saved. Run this again if "
              "the source still reports SOURCE_BROWSER_SESSION_EXPIRED.")
    return signed_in


def logout(profile_name: str) -> bool:
    """Deletes the saved profile — equivalent to signing out / clearing a browser's saved
    session. Returns False if there was nothing to delete."""
    dest = profile_path(profile_name)
    if dest.exists():
        shutil.rmtree(dest)
        return True
    return False


def _refresh_state(profile_name: str, context) -> None:
    """Re-saves storage_state after a successful use so token rotation/refresh the site performed
    during this visit extends the saved session's real lifetime, the same way an actual browser
    tab left open would keep sliding its session forward."""
    context.storage_state(path=str(_state_path(profile_name)))


def authenticated_client(profile_name: str, timeout_seconds: float = 20):
    """Returns an httpx.Client pre-loaded with this profile's saved cookies, or None if no
    profile has been created yet — callers should treat None exactly like "browser auth isn't
    configured for this source" and fall through to their existing plain-HTTP tier.

    Cheap: only launches a headless browser briefly to load the saved storage state and read
    cookies, then closes it — the actual HTTP requests are plain httpx using those cookies, so
    existing response-handling code (content-type checks, parsers, error classification) is
    reused unchanged."""
    if not has_profile(profile_name):
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    import httpx

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(_state_path(profile_name)))
        cookies = context.cookies()
        _refresh_state(profile_name, context)
        browser.close()

    jar = httpx.Cookies()
    for c in cookies:
        jar.set(c["name"], c["value"], domain=c.get("domain", ""), path=c.get("path", "/"))
    return httpx.Client(cookies=jar, timeout=timeout_seconds, follow_redirects=True,
                         headers={"User-Agent": _CHROME_UA})


def render_authenticated_page(profile_name: str, url: str, timeout_seconds: float = 20) -> str | None:
    """Full headless render (JS executed) using the saved session — for sources whose real value
    is populated client-side after page load rather than present in the raw server HTML (this is
    the Lipper money-market yield finding — see docs/debugging.md). Returns the final
    page.content(), or None if no profile has been created yet.

    Raises BrowserSessionExpiredError if the saved session no longer works (the page redirected
    to a login page) — distinct from a real layout/content change so the caller can point the
    user at `cli browser-login` instead of a generic "layout may have changed" message."""
    if not has_profile(profile_name):
        return None
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(_state_path(profile_name)))
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_seconds * 1000)
        html = page.content()
        final_url = page.url
        expired = is_login_page(final_url, html)
        if not expired:
            _refresh_state(profile_name, context)
        browser.close()

    if expired:
        raise BrowserSessionExpiredError(
            f"{url} redirected to a login page — the saved session for profile {profile_name!r} "
            f"has expired. Run: python -m cash_equivalents_mvp.cli browser-login --source <id>"
        )
    return html


def download_via_browser(profile_name: str, url: str, timeout_seconds: float = 30) -> bytes | None:
    """Downloads a file by real browser navigation (JS executed) using the saved session, rather
    than a static cookie-jar HTTP request. Necessary for sources that complete their session hand-
    off via client-side JavaScript rather than a plain HTTP redirect — a real debug bundle showed
    a SharePoint fetch land on a Microsoft Defender for Cloud Apps (MCAS) reverse-proxy page: an
    auto-submitting HTML form (`document.forms[0].submit()`) that POSTs a token to
    `*.access.mcas.ms` to finish establishing the session. A real browser executes that JS and
    continues on automatically; a plain `httpx` GET with extracted cookies just receives that raw
    HTML and stops there — the session was fine, the *mechanism* couldn't finish the hop.

    Returns the downloaded bytes, or None if no profile has been created yet (feature not set up).

    Raises BrowserSessionExpiredError if navigation lands on a real login page (the session
    genuinely doesn't work), or BrowserDownloadNotTriggeredError if navigation completes to a real,
    non-login page but no file download ever fires — e.g. a SharePoint share link in Excel
    Online's "viewer" format (`:x:/t/...` / `:x:/r/...`) renders an embedded spreadsheet UI instead
    of downloading a file. That distinction matters: the second case isn't fixed by signing in
    again, since the session isn't what's wrong."""
    if not has_profile(profile_name):
        return None
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(_state_path(profile_name)), accept_downloads=True)
        page = context.new_page()
        try:
            with page.expect_download(timeout=timeout_seconds * 1000) as download_info:
                try:
                    page.goto(url, timeout=timeout_seconds * 1000)
                except PlaywrightTimeoutError:
                    # goto() can itself time out when the navigation is aborted in favor of a
                    # download partway through — expect_download() below is the real signal.
                    pass
            download = download_info.value
        except PlaywrightTimeoutError:
            # No download event fired within the timeout — real page content instead. Distinguish
            # "genuinely not signed in" from "signed in fine, this link just isn't a raw file".
            html = page.content()
            final_url = page.url
            expired = is_login_page(final_url, html)
            if not expired:
                _refresh_state(profile_name, context)
            browser.close()
            if expired:
                raise BrowserSessionExpiredError(
                    f"{url} redirected to a login page — the saved session for profile "
                    f"{profile_name!r} has expired. Run: python -m cash_equivalents_mvp.cli "
                    f"browser-login --source <id>"
                ) from None
            raise BrowserDownloadNotTriggeredError(
                f"{url} did not trigger a file download (landed on {final_url} instead) — it may "
                f"be a viewer/preview link rather than a raw downloadable file."
            ) from None

        path = download.path()
        content = Path(path).read_bytes() if path else None
        _refresh_state(profile_name, context)
        browser.close()
        return content
