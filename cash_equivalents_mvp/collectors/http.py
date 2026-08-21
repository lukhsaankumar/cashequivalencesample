"""Shared HTTP collection helpers. Classifies network/TLS failures into the same error-code
taxonomy every responsibility uses, so a corporate proxy's self-signed certificate, a timeout,
and a 403 are all labeled consistently no matter which responsibility hit them — see
SECURITY.md and ASSUMPTIONS.md for the corporate-TLS-inspection case this was built for.
"""
from __future__ import annotations

import httpx

TLS_TRUST_MARKERS = (
    "CERTIFICATE_VERIFY_FAILED", "certificate verify failed", "self-signed certificate",
    "unable to get local issuer certificate",
)


def classify_http_exception(exc: BaseException) -> tuple[str, bool]:
    """Returns (error_code, retryable). Retrying a TLS trust failure or a 403 never helps —
    both need a human (VPN, corporate CA, or a manual upload), not a second attempt.
    """
    if isinstance(exc, httpx.TimeoutException):
        return "SOURCE_HTTP_TIMEOUT", True
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 403:
            return "SOURCE_HTTP_403", False
        return "SOURCE_HTTP_TIMEOUT", True
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
