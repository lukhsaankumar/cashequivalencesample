"""Retry policy for collect_automatic(): retried in-process for transient/retryable error codes
(SOURCE_HTTP_TIMEOUT etc.), not retried for permanent ones (SOURCE_HTTP_403, SOURCE_AUTH_REQUIRED,
FILE_MISSING...) — those go straight to MANUAL_REQUIRED since retrying won't help.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from cash_equivalents_mvp.models import CollectionResult

BACKOFF_SECONDS = (0.5, 2.0)  # delay before retry attempt N (0-indexed)


def collect_with_retries(collect_fn: Callable[[], CollectionResult], max_retries: int,
                          retryable_error_codes: tuple[str, ...]) -> tuple[CollectionResult, int]:
    """Returns (final_result, attempts_made). Retries only when the failure's error is marked
    retryable AND its error_code is in retryable_error_codes; anything else fails fast."""
    attempts = 0
    while True:
        result = collect_fn()
        attempts += 1
        if result.ok:
            return result, attempts
        err = result.error
        can_retry = (
            err is not None and err.retryable and err.error_code in retryable_error_codes
            and attempts <= max_retries
        )
        if not can_retry:
            return result, attempts
        delay = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
        time.sleep(delay)
