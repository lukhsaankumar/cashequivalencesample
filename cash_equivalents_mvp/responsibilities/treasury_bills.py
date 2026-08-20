"""Treasury-Bill responsibility — Canadian and US T-bill rates from an NBF/NBCN rate sheet PDF.

Automatic collection: NBIN (nbin.ca) is login-gated (see docs/source_inventory.md), so real
automatic retrieval isn't attempted; this responsibility watches a download folder (and, for the
historical demo, source_material/) for an NBF PDF, matching master prompt step 2 ("monitor a
configured download folder").
"""
from __future__ import annotations

from pathlib import Path

from cash_equivalents_mvp.audit import sha256_file
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
