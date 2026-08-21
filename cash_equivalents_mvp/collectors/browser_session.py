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


class BrowserSessionExpiredError(Exception):
    """A saved profile exists but the site redirected to a login page — the session needs
    refreshing via `cli browser-login`, not a code fix."""


def profile_path(profile_name: str) -> Path:
    return browser_profile_dir() / profile_name


def has_profile(profile_name: str) -> bool:
    """True only once `interactive_login` has actually completed for this name — an empty/never-
    created directory means the feature simply isn't set up yet, not an error."""
    p = profile_path(profile_name)
    return p.exists() and any(p.iterdir())


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
    the login host, or `timeout_seconds` elapses. Playwright's persistent context writes cookies/
    local storage for the profile to disk as the user browses, so no explicit "save" step is
    needed — closing the context is enough. Returns True if a sign-in was detected."""
    from playwright.sync_api import sync_playwright  # deferred: optional dependency

    dest = profile_path(profile_name)
    dest.mkdir(parents=True, exist_ok=True)
    print(f"Opening a browser window for {start_url}")
    print("Sign in exactly as you normally would (including MFA if prompted).")
    print(f"This window closes automatically once you're signed in (or after {timeout_seconds}s).")

    signed_in = False
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(dest), headless=False)
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not is_login_page(page.url, page.content()):
                signed_in = True
                break
            time.sleep(2)
        context.close()

    if signed_in:
        print(f"Signed in — session saved to {dest}")
    else:
        print("Timed out waiting for sign-in; nothing was saved as confirmed. Run this again if "
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


def authenticated_client(profile_name: str, timeout_seconds: float = 20):
    """Returns an httpx.Client pre-loaded with this profile's saved cookies, or None if no
    profile has been created yet — callers should treat None exactly like "browser auth isn't
    configured for this source" and fall through to their existing plain-HTTP tier.

    Cheap: only launches a headless browser briefly to read cookies off disk, then closes it —
    the actual HTTP requests are plain httpx using those cookies, so existing response-handling
    code (content-type checks, parsers, error classification) is reused unchanged."""
    if not has_profile(profile_name):
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    import httpx

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(profile_path(profile_name)), headless=True)
        cookies = context.cookies()
        context.close()

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
        context = p.chromium.launch_persistent_context(str(profile_path(profile_name)), headless=True)
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_seconds * 1000)
        html = page.content()
        final_url = page.url
        context.close()

    if is_login_page(final_url, html):
        raise BrowserSessionExpiredError(
            f"{url} redirected to a login page — the saved session for profile {profile_name!r} "
            f"has expired. Run: python -m cash_equivalents_mvp.cli browser-login --source <id>"
        )
    return html
