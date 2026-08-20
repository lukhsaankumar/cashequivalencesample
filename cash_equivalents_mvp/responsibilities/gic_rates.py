"""GIC Rates responsibility — cashable GICs, term deposits, GIC 1yr-5yr (annual/compound/monthly).

Automatic collection order (per master prompt §7.3):
  1. Approved direct file/API retrieval — not configured (no such endpoint documented); skipped.
  2. Authenticated retrieval through a user-authorized session — the SharePoint copy of
     GIC Rates.xlsx (see docs/source_inventory.md) requires the IG VPN + auth; not attempted here.
  3. Detect a newly downloaded GIC Rates.xlsx in the configured folder
     (local_data/uploads/gic_rates), falling back to source_material/ for the historical demo.
  4. Detect GIC Rates(Eng).csv in the same folder.
  5. Otherwise MANUAL_REQUIRED.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cash_equivalents_mvp.audit import sha256_file
from cash_equivalents_mvp.config import source_material_dir, workbook_map
from cash_equivalents_mvp.models import (
    CollectionResult,
    ManualInput,
    RateRecord,
    ResponsibilityError,
    ResponsibilityStatus,
    SourceArtifact,
    ValidationResult,
)
from cash_equivalents_mvp.normalization.percentages import (
    normalize_to_canonical,
    parse_raw_rate,
    validate_rate_range,
)
from cash_equivalents_mvp.normalization.providers import provider_name_for_code, provider_prefix_for_code
from cash_equivalents_mvp.parsers.gic_csv import parse_gic_rates_csv
from cash_equivalents_mvp.parsers.gic_xlsx import PARSER_VERSION as XLSX_PARSER_VERSION
from cash_equivalents_mvp.parsers.gic_xlsx import parse_gic_rates_xlsx
from cash_equivalents_mvp.responsibilities.base import Responsibility, RunContext
from cash_equivalents_mvp.validation.common import check_rate_range, finding

EXPECTED_PROVIDER_PREFIXES_12 = {"B2B", "BMO", "BMT", "BOM", "BNS", "EQB", "EQT", "HOBK", "HTC", "LBC", "MBC", "NBC"}
EXPECTED_PROVIDER_PREFIXES_8 = {"BMO", "BMT", "BOM", "BNS", "EQB", "EQT", "HOBK", "HTC"}


class GicRatesResponsibility(Responsibility):
    responsibility_id = "gic_rates"
    display_name = "GIC Rates"
    dependencies = ()

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        cfg = context.source_config(self.responsibility_id)
        folder = Path(cfg.get("automatic", {}).get("folder", "local_data/uploads/gic_rates"))
        candidates = []
        if folder.exists():
            candidates += sorted(folder.glob("GIC Rates*.xlsx")) + sorted(folder.glob("GIC Rates*.csv"))
        # Historical-demo convenience: source_material/ holds the weekly GIC Rates.xlsx snapshot.
        smd = source_material_dir()
        candidates += sorted(smd.glob("GIC Rates*.xlsx"))

        if not candidates:
            err = ResponsibilityError(
                run_id=context.run_id, responsibility_id=self.responsibility_id, stage="collect_automatic",
                error_code="FILE_MISSING", retryable=False,
                message="No GIC Rates.xlsx or GIC Rates(Eng).csv found in the watched folder or source_material/.",
                suggested_action="Upload GIC Rates.xlsx or a CSV on the Manual Uploads page.",
            )
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        path = candidates[0]
        method = "file_watch_detected" if path.parent != smd else "source_material_fixture"
        try:
            source_map = workbook_map("en")["gic_rates_source"]
            rows = (parse_gic_rates_xlsx(path, source_map) if path.suffix.lower() == ".xlsx"
                    else parse_gic_rates_csv(path))
        except Exception as exc:
            err = ResponsibilityError(
                run_id=context.run_id, responsibility_id=self.responsibility_id, stage="collect_automatic",
                error_code="PARSER_NO_ROWS", message=str(exc),
            )
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        artifact = SourceArtifact(
            run_id=context.run_id, responsibility_id=self.responsibility_id, filename=path.name,
            sha256=sha256_file(path), collection_method=method,
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if path.suffix.lower() == ".xlsx" else "text/csv",
            local_path=str(path), parser_version=XLSX_PARSER_VERSION,
            freshness_status="unknown",
        )
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows, artifact=artifact)

    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult:
        if not manual_input.file_path:
            raise ValueError("GIC rates manual input requires an uploaded file")
        if not manual_input.override_reason:
            raise ValueError("MANUAL_OVERRIDE_REASON_MISSING")
        path = Path(manual_input.file_path)
        source_map = workbook_map("en")["gic_rates_source"]
        rows = (parse_gic_rates_xlsx(path, source_map) if path.suffix.lower() == ".xlsx"
                else parse_gic_rates_csv(path))
        artifact = SourceArtifact(
            run_id=context.run_id, responsibility_id=self.responsibility_id,
            filename=manual_input.original_filename or path.name, sha256=sha256_file(path),
            collection_method="manual_upload",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if path.suffix.lower() == ".xlsx" else "text/csv",
            local_path=str(path), parser_version=XLSX_PARSER_VERSION,
        )
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows, artifact=artifact,
                                 override_reason=manual_input.override_reason,
                                 override_user=manual_input.submitted_by)

    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]:
        records: list[RateRecord] = []
        for row in collection.raw_rows:
            raw_value = row["raw_value"]
            if raw_value is None or str(raw_value).strip().upper() in {"#N/A", "N/A", ""}:
                continue  # never let #N/A overwrite a report cell
            try:
                raw = parse_raw_rate(raw_value)
                # GIC Rates.xlsx always stores bare percent numbers (0.50 means 0.50%, not
                # already-canonical 50%) — see normalization/percentages.py source_convention docs.
                canonical = normalize_to_canonical(raw, source_convention="always_percent_form")
                validate_rate_range(canonical)
            except ValueError:
                continue  # surfaced as a validation warning below via re-check, not silently lost

            provider = provider_name_for_code(row["code"]) or row.get("dealer") or row["code"]
            records.append(RateRecord(
                run_id=context.run_id, responsibility_id=self.responsibility_id,
                category="gic", provider=provider, product_code=row["code"],
                currency="CAD", account_type=row["block"],
                term_years=row.get("term_years"), term_days=row.get("bucket_days"),
                rate=canonical, gross_or_net="gross",
                minimum_purchase=Decimal(str(row["min"])) if row.get("min") not in (None, "") else None,
                source_artifact_id=collection.artifact.artifact_id if collection.artifact else None,
                source_cell_or_location=f"Eng!row{row.get('row')}" if row.get("row") else None,
                extraction_method="deterministic_cell_scan",
                validation_status="unvalidated",
                manually_overridden=bool(collection.override_reason),
                override_reason=collection.override_reason,
                override_user=collection.override_user,
            ))
        return records

    def validate(self, context: RunContext, records: list[RateRecord]) -> ValidationResult:
        findings = []
        rid = self.responsibility_id

        for r in records:
            findings += check_rate_range(context.run_id, rid, r.rate,
                                          f"{r.account_type}/{r.product_code}/{r.term_years or r.term_days}")

        by_block: dict[str, set[str]] = {}
        for r in records:
            prefix = provider_prefix_for_code(r.product_code or "")
            if prefix and r.account_type:
                by_block.setdefault(r.account_type, set()).add(prefix)

        for block in ("annual", "monthly", "compound", "short_term_deposits"):
            missing = EXPECTED_PROVIDER_PREFIXES_12 - by_block.get(block, set())
            if missing:
                findings.append(finding(context.run_id, rid, "PARSER_PROVIDER_MISSING", "warning",
                                         f"Block {block!r} is missing expected providers: {sorted(missing)}"))
        missing_cashable = EXPECTED_PROVIDER_PREFIXES_8 - by_block.get("cashables", set())
        if missing_cashable:
            findings.append(finding(context.run_id, rid, "PARSER_PROVIDER_MISSING", "warning",
                                     f"Cashables block is missing expected providers: {sorted(missing_cashable)}"))

        annual = {(provider_prefix_for_code(r.product_code or ""), r.term_years): r.rate
                  for r in records if r.account_type == "annual"}
        compound = {(provider_prefix_for_code(r.product_code or ""), r.term_years): r.rate
                    for r in records if r.account_type == "compound"}
        for key, a_rate in annual.items():
            c_rate = compound.get(key)
            if c_rate is not None and c_rate != a_rate:
                findings.append(finding(context.run_id, rid, "GIC_ANNUAL_COMPOUND_PARITY_MISMATCH", "warning",
                                         f"Annual {a_rate} vs Compound {c_rate} diverge for {key}"))

        if not records:
            findings.append(finding(context.run_id, rid, "PARSER_NO_ROWS", "blocking",
                                     "No valid GIC rate records were extracted"))

        return ValidationResult(ok=not any(f.severity == "blocking" for f in findings), findings=findings)
