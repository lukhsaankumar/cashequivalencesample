"""Shared HTTP collection helpers. Classifies network/TLS failures into the same error-code
taxonomy every responsibility uses, so a corporate proxy's self-signed certificate, a timeout,
and a 403 are all labeled consistently no matter which responsibility hit them — see
SECURITY.md and ASSUMPTIONS.md for the corporate-TLS-inspection case this was built for.
"""
from __future__ import annotations

import re

import httpx

from cash_equivalents_mvp.config import raw_sources_dir

TLS_TRUST_MARKERS = (
    "CERTIFICATE_VERIFY_FAILED", "certificate verify failed", "self-signed certificate",
    "unable to get local issuer certificate",
)


def classify_http_exception(exc: BaseException) -> tuple[str, bool]:
    """Returns (error_code, retryable). Retrying a TLS trust failure, a 401, or a 403 never
    helps — all three need a human (VPN, corporate CA, an interactive login, or a manual
    upload), not a second automatic attempt. A 5xx is a different story: that's the server's
    problem, not an auth wall, and is genuinely worth retrying.
    """
    if isinstance(exc, httpx.TimeoutException):
        return "SOURCE_HTTP_TIMEOUT", True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 403:
            return "SOURCE_HTTP_403", False
        if status == 401:
            return "SOURCE_HTTP_401", False
        if status >= 500:
            return "SOURCE_HTTP_TIMEOUT", True
        return "SOURCE_AUTH_REQUIRED", False
    text = str(exc)
    if any(marker in text for marker in TLS_TRUST_MARKERS):
        return "SOURCE_TLS_TRUST_FAILURE", False
    if isinstance(exc, httpx.ConnectError):
        return "SOURCE_HTTP_TIMEOUT", True
    return "SOURCE_AUTH_REQUIRED", False


def describe_failure(url: str, exc: BaseException) -> str:
    code, _ = classify_http_exception(exc)
    if code == "SOURCE_TLS_TRUST_FAILURE":
        return (f"{url} — TLS certificate not trusted (likely a corporate proxy doing SSL "
                f"inspection with its own root CA): {exc}. See SECURITY.md for the "
                f"pip-system-certs / truststore workaround.")
    return f"{url} unreachable (likely requires the IG VPN + an authenticated session): {exc}"


_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]")


def save_debug_html(run_id: str, label: str, html: str) -> str:
    """Saves the raw HTML of a page whose content didn't match what a scraper expected — a page
    that loaded (no exception, no non-2xx status) but had no matching link/pattern is otherwise
    a dead end for diagnosis: was it a real page with differently-labeled content, a login
    redirect, or something JS-rendered with nothing useful in the raw HTML? Saving the actual
    bytes turns the next occurrence into something a human can open and look at, or attach to a
    debug bundle, instead of another round of blind guessing at the page structure.

    Returns the saved path as a string (for embedding directly in the error message).
    """
    safe_label = _UNSAFE_NAME_CHARS.sub("_", label)[:80]
    dest_dir = raw_sources_dir() / run_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{safe_label}_debug.html"
    dest.write_text(html, encoding="utf-8", errors="replace")
    return str(dest)
