"""Treasury-Bill responsibility — Canadian and US T-bill rates from an NBF/NBCN rate sheet PDF.

Automatic collection: NBIN (nbin.ca) is login-gated (see docs/source_inventory.md), so a live GET
is still attempted every run — not to scrape rate data from it (a raw unauthenticated request
against a login-gated page has nothing parseable to offer, and its real post-login page structure
has never been seen by this codebase), but so the *real* reason it can't be used automatically
(timeout, TLS trust failure, login redirect, etc.) is captured and visible in the debug bundle /
`cli diagnose`, instead of the responsibility silently skipping straight to the file-watch tier.
Falls through to watching a download folder (and, for the historical demo, source_material/) for
an NBF PDF, matching master prompt step 2 ("monitor a configured download folder").
"""
from __future__ import annotations

from pathlib import Path

import httpx

from cash_equivalents_mvp.audit import sha256_file
from cash_equivalents_mvp.collectors import browser_session
from cash_equivalents_mvp.collectors.http import classify_http_exception, describe_failure
from cash_equivalents_mvp.config import source_material_dir
from cash_equivalents_mvp.models import (
    CollectionResult,
    ManualInput,
    RateRecord,
    ResponsibilityError,
    ResponsibilityStatus,
    SourceArtifact,
    ValidationResult,
)
from cash_equivalents_mvp.normalization.dates import term_days
from cash_equivalents_mvp.normalization.percentages import parse_and_normalize_rate
from cash_equivalents_mvp.parsers.nbf_tbill import PARSER_VERSION, parse_nbf_tbill_pdf
from cash_equivalents_mvp.responsibilities.base import Responsibility, RunContext
from cash_equivalents_mvp.validation.common import check_rate_range, finding


class TreasuryBillsResponsibility(Responsibility):
    responsibility_id = "treasury_bills"
    display_name = "Treasury Bills"
    dependencies = ()

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        cfg = context.source_config(self.responsibility_id).get("automatic", {})
        url = cfg.get("url")
        timeout = cfg.get("timeout_seconds", 15)
        browser_profile = cfg.get("browser_profile")
        if url:
            get_fn = httpx.get
            client = None
            if browser_profile:
                client = browser_session.authenticated_client(browser_profile, timeout)
                if client is not None:
                    get_fn = client.get
            try:
                resp = get_fn(url, timeout=timeout, follow_redirects=True)
                resp.raise_for_status()
            except Exception as exc:
                code, retryable = classify_http_exception(exc)
                self._record_error(context, "collect_automatic", code, describe_failure(url, exc),
                                    severity="warning", retryable=retryable, exc=exc)
            finally:
                if client is not None:
                    client.close()

        folder = Path(cfg.get("folder", "local_data/uploads/tbills"))
        candidates = sorted(folder.glob("*.pdf")) if folder.exists() else []
        smd = source_material_dir()
        candidates += sorted(smd.glob("NBF T bill rates*.pdf")) + sorted(smd.glob("NBF*.pdf"))

        if not candidates:
            err = ResponsibilityError(
                run_id=context.run_id, responsibility_id=self.responsibility_id, stage="collect_automatic",
                error_code="FILE_MISSING", message="No NBF/NBCN T-bill rate PDF found.",
                suggested_action="Upload the NBF/NBCN PDF or text rate sheet on the Manual Uploads page.",
            )
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        path = candidates[0]
        try:
            parsed = parse_nbf_tbill_pdf(path)
        except Exception as exc:
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code="PARSER_NO_ROWS", message=str(exc))
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        artifact = SourceArtifact(
            run_id=context.run_id, responsibility_id=self.responsibility_id, filename=path.name,
            sha256=sha256_file(path), collection_method="file_watch_detected",
            mime_type="application/pdf", local_path=str(path), parser_version=PARSER_VERSION,
        )
        rows = [{"currency": cur, **row} for cur, items in parsed.items() for row in items]
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows, artifact=artifact)

    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult:
        if not manual_input.file_path:
            raise ValueError("Treasury Bills manual input requires an uploaded file")
        if not manual_input.override_reason:
            raise ValueError("MANUAL_OVERRIDE_REASON_MISSING")
        path = Path(manual_input.file_path)
        parsed = parse_nbf_tbill_pdf(path)
        artifact = SourceArtifact(
            run_id=context.run_id, responsibility_id=self.responsibility_id,
            filename=manual_input.original_filename or path.name, sha256=sha256_file(path),
            collection_method="manual_upload", mime_type="application/pdf",
            local_path=str(path), parser_version=PARSER_VERSION,
        )
        rows = [{"currency": cur, **row} for cur, items in parsed.items() for row in items]
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows, artifact=artifact,
                                 override_reason=manual_input.override_reason,
                                 override_user=manual_input.submitted_by)

    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]:
        records = []
        for row in collection.raw_rows:
            rate = parse_and_normalize_rate(row["yield_raw"])
            days = term_days(row["maturity_date"], context.report_date)
            records.append(RateRecord(
                run_id=context.run_id, responsibility_id=self.responsibility_id,
                category="tbill", provider="Government of Canada" if row["currency"] == "CAD" else "US Treasury",
                product_code=row.get("identifier"), currency=row["currency"],
                maturity_date=row["maturity_date"], term_days=days, rate=rate, gross_or_net="gross",
                source_artifact_id=collection.artifact.artifact_id if collection.artifact else None,
                extraction_method="deterministic_regex" if collection.artifact and collection.artifact.mime_type == "application/pdf" else "manual_entry",
                manually_overridden=bool(collection.override_reason),
                override_reason=collection.override_reason,
                override_user=collection.override_user,
            ))
        return records

    def validate(self, context: RunContext, records: list[RateRecord]) -> ValidationResult:
        findings = []
        rid = self.responsibility_id
        if not records:
            findings.append(finding(context.run_id, rid, "PARSER_NO_ROWS", "blocking", "No T-bill records produced"))
            return ValidationResult(ok=False, findings=findings)

        for r in records:
            findings += check_rate_range(context.run_id, rid, r.rate, f"TBills/{r.currency}/{r.maturity_date}")
            if r.term_days is not None and r.term_days < 0:
                findings.append(finding(context.run_id, rid, "TBILL_TERM_DAY_MISMATCH", "blocking",
                                         f"{r.currency} bill maturing {r.maturity_date} is before report date {context.report_date}"))

        cad = [r for r in records if r.currency == "CAD"]
        usd = [r for r in records if r.currency == "USD"]
        if len(cad) != 5:
            findings.append(finding(context.run_id, rid, "TBILL_TERM_DAY_MISMATCH", "warning",
                                     f"Expected 5 Canadian T-bill maturities, found {len(cad)}"))
        if len(usd) != 5:
            findings.append(finding(context.run_id, rid, "TBILL_TERM_DAY_MISMATCH", "warning",
                                     f"Expected 5 US T-bill maturities, found {len(usd)}"))

        return ValidationResult(ok=not any(f.severity == "blocking" for f in findings), findings=findings)
