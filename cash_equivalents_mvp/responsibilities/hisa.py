"""HISA responsibility — detailed CDN/US High-Interest Savings Account roster.

Automatic collection order:
  1. home.investorsgroup.com product page (Info.docx hyperlink) — requires IG VPN + auth; attempted,
     expected to fail outside the VPN.
  2. Detect a structured HISA CSV/XLSX in the configured upload folder.
  3. Historical-demo convenience: read the roster straight out of the current EN report workbook's
     HISA sheet in source_material/ (see parsers/hisa.py docstring).
  4. Otherwise MANUAL_REQUIRED.

Never computes summary_rate = max(all_visible_rates) — see docs/current_process_findings.md and
config/business_rules.yaml: hisa_summary_selection. The "approved" CDN/US product is configured by
identity; if a numerically higher rate exists outside it, a warning is raised, never a silent switch.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from cash_equivalents_mvp.audit import sha256_file
from cash_equivalents_mvp.collectors import browser_session
from cash_equivalents_mvp.collectors.http import classify_http_exception, describe_failure
from cash_equivalents_mvp.config import resolve_sheet_name, settings, source_material_dir, workbook_map
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
from cash_equivalents_mvp.parsers.hisa import PARSER_VERSION, parse_hisa_csv, parse_hisa_from_workbook
from cash_equivalents_mvp.responsibilities.base import Responsibility, RunContext
from cash_equivalents_mvp.validation.common import check_rate_range, finding

_TRUTHY = {"yes", "y", "true", "1"}


def _to_bool(value) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in _TRUTHY:
        return True
    if text in {"no", "n", "false", "0"}:
        return False
    return None  # e.g. "Yes, but not TDB8157" — ambiguous, left unset rather than guessed


class HisaResponsibility(Responsibility):
    responsibility_id = "hisa"
    display_name = "High-Interest Savings Accounts"
    dependencies = ()

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        cfg = context.source_config(self.responsibility_id).get("automatic", {})
        url = cfg.get("url")
        timeout = cfg.get("timeout_seconds", 15)
        browser_profile = cfg.get("browser_profile")

        get_fn = httpx.get
        client = None
        if browser_profile:
            client = browser_session.authenticated_client(browser_profile, timeout)
            if client is not None:
                get_fn = client.get

        try:
            resp = get_fn(url, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
            # The product page is a single-product marketing page, not a machine-readable roster —
            # reaching it at all only proves VPN/network (or, with a browser session, SSO)
            # connectivity, not that we could scrape the full ~30-provider table from it. Fall
            # through to the structured-file paths below either way.
        except Exception as exc:
            # Logged as a non-fatal warning (not returned as a failure) — HISA still has real
            # file-based fallback tiers below, unlike money_market. This is what makes the real
            # reason visible in the debug bundle / `cli diagnose` instead of being silently lost.
            code, retryable = classify_http_exception(exc)
            self._record_error(context, "collect_automatic", code, describe_failure(url, exc),
                                severity="warning", retryable=retryable, exc=exc)
        finally:
            if client is not None:
                client.close()

        folder = Path(context.settings()["upload_dir"]) / "hisa"
        csv_candidates = sorted(folder.glob("*.csv")) if folder.exists() else []
        if csv_candidates:
            path = csv_candidates[0]
            try:
                rows = parse_hisa_csv(path)
            except Exception as exc:
                err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                           stage="collect_automatic", error_code="PARSER_NO_ROWS", message=str(exc))
                return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)
            artifact = SourceArtifact(
                run_id=context.run_id, responsibility_id=self.responsibility_id, filename=path.name,
                sha256=sha256_file(path), collection_method="file_watch_detected", mime_type="text/csv",
                local_path=str(path), parser_version=PARSER_VERSION,
            )
            return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows, artifact=artifact)

        # Historical-demo convenience fixture.
        smd = source_material_dir()
        en_template = smd / settings()["templates"]["en"]
        if en_template.exists():
            try:
                rows = parse_hisa_from_workbook(en_template, workbook_map("en")["hisa"],
                                                 resolve_sheet_name("en", "hisa"))
            except Exception as exc:
                err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                           stage="collect_automatic", error_code="PARSER_NO_ROWS", message=str(exc))
                return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)
            artifact = SourceArtifact(
                run_id=context.run_id, responsibility_id=self.responsibility_id, filename=en_template.name,
                sha256=sha256_file(en_template), collection_method="source_material_fixture",
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                local_path=str(en_template), parser_version=PARSER_VERSION,
            )
            return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows, artifact=artifact)

        err = ResponsibilityError(
            run_id=context.run_id, responsibility_id=self.responsibility_id, stage="collect_automatic",
            error_code="SOURCE_AUTH_REQUIRED",
            message="HISA product page requires the IG VPN + authenticated session, and no structured "
                    "roster file was found.",
            suggested_action="Upload a HISA CSV/XLSX or enter records in the structured grid on the "
                              "Manual Uploads page.",
        )
        return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult:
        if manual_input.structured_rows:
            rows = manual_input.structured_rows
            artifact = None
        elif manual_input.file_path:
            path = Path(manual_input.file_path)
            rows = (parse_hisa_from_workbook(path, workbook_map("en")["hisa"], resolve_sheet_name("en", "hisa"))
                    if path.suffix.lower() == ".xlsx" else parse_hisa_csv(path))
            artifact = SourceArtifact(
                run_id=context.run_id, responsibility_id=self.responsibility_id,
                filename=manual_input.original_filename or path.name, sha256=sha256_file(path),
                collection_method="manual_upload",
                mime_type="text/csv" if path.suffix.lower() == ".csv" else
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                local_path=str(path), parser_version=PARSER_VERSION,
            )
        else:
            raise ValueError("HISA manual input requires either structured_rows or an uploaded file")
        if not manual_input.override_reason:
            raise ValueError("MANUAL_OVERRIDE_REASON_MISSING")
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows, artifact=artifact,
                                 override_reason=manual_input.override_reason,
                                 override_user=manual_input.submitted_by)

    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]:
        records = []
        for row in collection.raw_rows:
            raw_rate = row.get("raw_rate") or row.get("rate")
            if raw_rate is None or str(raw_rate).strip().upper() in {"#N/A", "N/A", ""}:
                continue
            try:
                rate = parse_and_normalize_rate(raw_rate)
            except ValueError:
                continue
            min_val = row.get("minimum")
            max_val = row.get("maximum")
            records.append(RateRecord(
                run_id=context.run_id, responsibility_id=self.responsibility_id,
                category="hisa", provider=row["provider"], product_code=row.get("fund_code"),
                currency=row.get("currency", "CAD"), rate=rate, gross_or_net="gross",
                minimum_purchase=_safe_decimal(min_val), maximum_purchase=_safe_decimal(max_val),
                corporate_eligible=_to_bool(row.get("corporate_eligible")),
                insurance_eligible=_to_bool(row.get("cdic_eligible")),
                source_artifact_id=collection.artifact.artifact_id if collection.artifact else None,
                source_cell_or_location=f"HISA!row{row['row']}" if row.get("row") else None,
                extraction_method="deterministic_cell_scan" if collection.artifact else "manual_entry",
                manually_overridden=bool(collection.override_reason),
                override_reason=collection.override_reason,
                override_user=collection.override_user,
            ))
        return records

    def validate(self, context: RunContext, records: list[RateRecord]) -> ValidationResult:
        findings = []
        rid = self.responsibility_id
        if not records:
            findings.append(finding(context.run_id, rid, "PARSER_NO_ROWS", "blocking", "No HISA records produced"))
            return ValidationResult(ok=False, findings=findings)

        for r in records:
            findings += check_rate_range(context.run_id, rid, r.rate, f"HISA/{r.currency}/{r.provider}")

        rules = context.business_rules()["hisa_summary_selection"]
        for currency, key in [("CAD", "cdn"), ("USD", "us")]:
            selection = rules[key]
            currency_records = [r for r in records if r.currency == currency]
            if not currency_records:
                continue
            selected = next((r for r in currency_records
                              if r.provider == selection["provider"] or r.product_code == selection["fund_code"]),
                             None)
            if selected is None:
                findings.append(finding(context.run_id, rid, "HISA_SUMMARY_RULE_UNCONFIRMED", "warning",
                                         f"Configured {currency} summary product "
                                         f"{selection['provider']!r} was not found in this week's roster — "
                                         "manual review required before the Executive Summary figure can be trusted."))
                continue
            higher = [r for r in currency_records if r.rate > selected.rate]
            if higher:
                best = max(higher, key=lambda r: r.rate)
                findings.append(finding(context.run_id, rid, "HISA_HIGHER_RATE_EXCLUDED", "warning",
                                         f"{currency} product {best.provider!r} offers {best.rate} > the "
                                         f"configured summary product {selected.provider!r} at {selected.rate}. "
                                         "This may be intentional (e.g. a CDIC-tier exclusion) — review before approving."))

        return ValidationResult(ok=not any(f.severity == "blocking" for f in findings), findings=findings)


def _safe_decimal(value):
    from decimal import Decimal, InvalidOperation
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
