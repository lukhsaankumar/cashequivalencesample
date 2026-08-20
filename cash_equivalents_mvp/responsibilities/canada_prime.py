"""Canadian Prime Rate responsibility — Bank of Canada Valet API, series V80691311.

Public, unauthenticated source — should work without VPN. Target cell Cash!D31 (EN) /
Espèces!E32 (FR, French-text-formatted) per config/workbook_map_*.yaml.
"""
from __future__ import annotations

from datetime import datetime

import httpx

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

SERIES = "V80691311"


class CanadaPrimeResponsibility(Responsibility):
    responsibility_id = "canada_prime"
    display_name = "Canadian Prime Rate"
    dependencies = ()
    retryable_error_codes = ("SOURCE_HTTP_TIMEOUT",)

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        cfg = context.source_config(self.responsibility_id).get("automatic", {})
        url = cfg.get("url")
        timeout = cfg.get("timeout_seconds", 20)
        try:
            resp = httpx.get(url, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as exc:
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code="SOURCE_HTTP_TIMEOUT",
                                       retryable=True, message=str(exc))
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)
        except httpx.HTTPStatusError as exc:
            code = "SOURCE_HTTP_403" if exc.response.status_code == 403 else "SOURCE_HTTP_TIMEOUT"
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code=code, message=str(exc))
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)
        except Exception as exc:
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code="SOURCE_HTTP_TIMEOUT",
                                       retryable=True, message=f"Bank of Canada request failed: {exc}")
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        observations = data.get("observations", [])
        if not observations:
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code="SOURCE_LAYOUT_CHANGED",
                                       message="Bank of Canada response had no observations")
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        latest = observations[-1]
        value = latest.get(SERIES, {}).get("v")
        source_date = latest.get("d")
        if value is None:
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code="SOURCE_LAYOUT_CHANGED",
                                       message=f"Series {SERIES} not present in latest observation")
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        artifact = SourceArtifact(
            run_id=context.run_id, responsibility_id=self.responsibility_id,
            filename=f"boc_prime_{source_date}.json", sha256="", source_url=url,
            collection_method="official_http", mime_type="application/json",
            local_path="", parser_version="boc_valet-1.0",
            effective_at=datetime.fromisoformat(source_date),
        )
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS,
                                 raw_rows=[{"value": value, "source_date": source_date}], artifact=artifact)

    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult:
        value = manual_input.numeric_fields.get("rate")
        if not value:
            raise ValueError("Canadian Prime manual override requires numeric_fields['rate']")
        if not manual_input.override_reason:
            raise ValueError("MANUAL_OVERRIDE_REASON_MISSING")
        source_date = (manual_input.effective_date.isoformat() if manual_input.effective_date
                       else context.report_date.isoformat())
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS,
                                 raw_rows=[{"value": value, "source_date": source_date,
                                            "override_reason": manual_input.override_reason}])

    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]:
        row = collection.raw_rows[0]
        rate = parse_and_normalize_rate(row["value"])
        return [RateRecord(
            run_id=context.run_id, responsibility_id=self.responsibility_id,
            category="prime", provider="Bank of Canada", currency="CAD",
            rate=rate, gross_or_net="gross",
            source_artifact_id=collection.artifact.artifact_id if collection.artifact else None,
            source_effective_at=datetime.fromisoformat(row["source_date"]),
            extraction_method="official_http" if collection.artifact else "manual_entry",
            manually_overridden=bool(row.get("override_reason")),
            override_reason=row.get("override_reason"),
        )]

    def validate(self, context: RunContext, records: list[RateRecord]) -> ValidationResult:
        findings = []
        rid = self.responsibility_id
        if not records:
            findings.append(finding(context.run_id, rid, "PARSER_NO_ROWS", "blocking", "No Prime rate record produced"))
            return ValidationResult(ok=False, findings=findings)
        r = records[0]
        findings += check_rate_range(context.run_id, rid, r.rate, "Cash!D31")
        return ValidationResult(ok=not any(f.severity == "blocking" for f in findings), findings=findings)
