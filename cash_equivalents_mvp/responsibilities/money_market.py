"""Money-Market Fund responsibility — IG Premium (CAD) / IG Mackenzie US current yield.

Automatic source: Lipper fund profile pages linked from Info.docx (digital.lipperweb.com),
which require the IG VPN + an authenticated Lipper session (see docs/source_inventory.md).
Not reachable from this environment; the collector is implemented for when it is.
"""
from __future__ import annotations

import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

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

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        cfg = context.source_config(self.responsibility_id).get("automatic", {})
        timeout = cfg.get("timeout_seconds", 15)
        results = {}
        for currency, url_key in [("CAD", "url_cad"), ("USD", "url_us")]:
            url = cfg.get(url_key)
            try:
                resp = httpx.get(url, timeout=timeout, follow_redirects=True)
                resp.raise_for_status()
                yield_str = _extract_current_yield(resp.text)
                if yield_str is None:
                    raise ValueError("current yield field not found on page")
                results[currency] = yield_str
            except httpx.TimeoutException as exc:
                err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                           stage="collect_automatic", error_code="SOURCE_HTTP_TIMEOUT",
                                           retryable=True, message=f"{currency} fund page timed out: {exc}")
                return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)
            except Exception as exc:
                err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                           stage="collect_automatic", error_code="SOURCE_AUTH_REQUIRED",
                                           message=f"{currency} fund page unreachable (likely requires IG VPN "
                                                   f"+ authenticated Lipper session): {exc}")
                return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        artifact = SourceArtifact(
            run_id=context.run_id, responsibility_id=self.responsibility_id,
            filename="lipper_money_market.html", sha256="", source_url=cfg.get("url_cad"),
            collection_method="authenticated_http", mime_type="text/html", local_path="",
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
