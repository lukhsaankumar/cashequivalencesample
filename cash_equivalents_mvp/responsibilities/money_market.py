"""Money-Market Fund responsibility — IG Premium (CAD) / IG Mackenzie US current yield.

Automatic source: Lipper fund profile pages linked from Info.docx (digital.lipperweb.com),
which require the IG VPN + an authenticated Lipper session (see docs/source_inventory.md).

Collection order:
  0. If a persistent browser session has been set up (`cli browser-login --source money_market`),
     render the page with JavaScript executed (`browser_session.render_authenticated_page`) and
     parse the yield out of the post-render HTML. A real debug bundle showed the plain-HTTP tier
     below reaches genuine Lipper content (not a login redirect) but the raw server HTML contains
     no percentage-formatted value anywhere — consistent with the number being populated by
     client-side JS after load, which only a real browser render can capture. No profile
     configured/created yet -> this tier is a complete no-op.
  1. Plain httpx GET (kept as-is): works if the page turns out not to need a live session, and
     gives a real, specific failure reason (auth wall vs TLS vs timeout) either way.
  2. Otherwise MANUAL_REQUIRED.
"""
from __future__ import annotations

import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from cash_equivalents_mvp.collectors import browser_session
from cash_equivalents_mvp.collectors.http import classify_http_exception, describe_failure, save_debug_html
from cash_equivalents_mvp.models import (
    CollectionResult,
    ManualInput,
    RateRecord,
    ResponsibilityError,
    ResponsibilityStatus,
    SourceArtifact,
    ValidationResult,
)
from cash_equivalents_mvp.normalization.percentages import parse_and_normalize_rate
from cash_equivalents_mvp.responsibilities.base import Responsibility, RunContext
from cash_equivalents_mvp.validation.common import check_rate_range, finding

_YIELD_PATTERN = re.compile(r"current\s+yield[^0-9%]{0,20}([\d.]+)\s*%", re.IGNORECASE)


def _extract_current_yield(html: str) -> str | None:
    text = BeautifulSoup(html, "lxml").get_text(" ")
    m = _YIELD_PATTERN.search(text)
    return m.group(1) if m else None


class MoneyMarketResponsibility(Responsibility):
    responsibility_id = "money_market"
    display_name = "Money Market Funds (IG Premium / IG Mackenzie US)"
    dependencies = ()

    def _browser_rendered_yield(self, context: RunContext, currency: str, url: str,
                                 profile: str, timeout: float) -> str | None:
        """Tier 0: render with JS executed via a saved browser session. Returns the extracted
        yield string, or None (not a hard failure — caller falls through to the plain-HTTP tier)
        if no profile is configured, the session expired, or the value still isn't found even
        post-render."""
        try:
            html = browser_session.render_authenticated_page(profile, url, timeout)
        except browser_session.BrowserSessionExpiredError as exc:
            self._record_error(context, "collect_automatic", "SOURCE_BROWSER_SESSION_EXPIRED", str(exc),
                                severity="warning")
            return None
        if html is None:  # no profile ever created — feature not set up, silent no-op
            return None

        yield_str = _extract_current_yield(html)
        if yield_str is None:
            debug_path = save_debug_html(context.run_id, f"lipper_{currency.lower()}_rendered", html)
            self._record_error(
                context, "collect_automatic", "SOURCE_LAYOUT_CHANGED",
                f"{currency} fund page ({url}) rendered successfully with a valid browser session "
                f"but 'current yield' text still was not found — the page layout may have changed. "
                f"Rendered response saved to {debug_path}.",
                severity="warning",
            )
        return yield_str

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        cfg = context.source_config(self.responsibility_id).get("automatic", {})
        timeout = cfg.get("timeout_seconds", 15)
        browser_profile = cfg.get("browser_profile")
        results = {}
        used_browser_session = False
        for currency, url_key in [("CAD", "url_cad"), ("USD", "url_us")]:
            url = cfg.get(url_key)

            if browser_profile:
                yield_str = self._browser_rendered_yield(context, currency, url, browser_profile, timeout)
                if yield_str is not None:
                    results[currency] = yield_str
                    used_browser_session = True
                    continue

            try:
                resp = httpx.get(url, timeout=timeout, follow_redirects=True)
                resp.raise_for_status()
            except Exception as exc:
                code, retryable = classify_http_exception(exc)
                err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                           stage="collect_automatic", error_code=code, retryable=retryable,
                                           message=f"{currency} fund page: {describe_failure(url, exc)}")
                return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

            yield_str = _extract_current_yield(resp.text)
            if yield_str is None:
                # The page loaded fine (200, no exception) but didn't contain what we expected —
                # most likely a login redirect (not authenticated to Lipper specifically, distinct
                # from VPN connectivity) or the real page uses different wording than our regex
                # assumes. Save the actual HTML so this is diagnosable instead of a repeat guess.
                debug_path = save_debug_html(context.run_id, f"lipper_{currency.lower()}", resp.text)
                err = ResponsibilityError(
                    run_id=context.run_id, responsibility_id=self.responsibility_id,
                    stage="collect_automatic", error_code="SOURCE_LAYOUT_CHANGED",
                    message=f"{currency} fund page ({url}) loaded but 'current yield' text was not "
                            f"found — likely not authenticated to Lipper, or the value is rendered "
                            f"client-side (set config/sources.yaml money_market.browser_profile and "
                            f"run `cli browser-login --source money_market`), or the page layout "
                            f"differs from what's expected. Actual response saved to {debug_path}.",
                )
                return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)
            results[currency] = yield_str

        artifact = SourceArtifact(
            run_id=context.run_id, responsibility_id=self.responsibility_id,
            filename="lipper_money_market.html", sha256="", source_url=cfg.get("url_cad"),
            collection_method="browser_session_rendered" if used_browser_session else "authenticated_http",
            mime_type="text/html", local_path="",
            parser_version="lipper_yield-1.0", effective_at=datetime.utcnow(),
        )
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS,
                                 raw_rows=[{"currency": c, "yield": v} for c, v in results.items()],
                                 artifact=artifact)

    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult:
        cad = manual_input.numeric_fields.get("cad_yield")
        us = manual_input.numeric_fields.get("us_yield")
        if not cad or not us:
            raise ValueError("Money Market manual override requires numeric_fields['cad_yield'] and ['us_yield']")
        if not manual_input.override_reason:
            raise ValueError("MANUAL_OVERRIDE_REASON_MISSING")
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS,
                                 raw_rows=[{"currency": "CAD", "yield": cad, "override_reason": manual_input.override_reason},
                                           {"currency": "USD", "yield": us, "override_reason": manual_input.override_reason}])

    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]:
        records = []
        for row in collection.raw_rows:
            rate = parse_and_normalize_rate(row["yield"])
            provider = "IG Premium Money Market Fund" if row["currency"] == "CAD" else "IG Mackenzie US Money Market Fund"
            records.append(RateRecord(
                run_id=context.run_id, responsibility_id=self.responsibility_id,
                category="money_market", provider=provider, currency=row["currency"],
                rate=rate, gross_or_net="gross",
                source_artifact_id=collection.artifact.artifact_id if collection.artifact else None,
                extraction_method="authenticated_http" if collection.artifact else "manual_entry",
                manually_overridden=bool(row.get("override_reason")),
                override_reason=row.get("override_reason"),
            ))
        return records

    def validate(self, context: RunContext, records: list[RateRecord]) -> ValidationResult:
        findings = []
        rid = self.responsibility_id
        currencies = {r.currency for r in records}
        if currencies != {"CAD", "USD"}:
            findings.append(finding(context.run_id, rid, "PARSER_NO_ROWS", "blocking",
                                     f"Expected CAD and USD money market yields, got {currencies}"))
        for r in records:
            findings += check_rate_range(context.run_id, rid, r.rate, f"Executive Summary money market/{r.currency}")
        return ValidationResult(ok=not any(f.severity == "blocking" for f in findings), findings=findings)
