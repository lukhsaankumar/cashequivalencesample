"""US Federal Funds responsibility — FRED (official St. Louis Fed source) for target range
lower/upper bounds, with a configurable rule for which figure becomes the report value.
See config/business_rules.yaml: fed_funds.rule (default UPPER_BOUND, UNCONFIRMED_BUSINESS_RULE).
"""
from __future__ import annotations

import csv
import io
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


def _latest_fred_value(csv_text: str) -> tuple[str, str] | None:
    """FRED graph CSV: 'observation_date,<SERIES>' header, rows may have '.' for missing."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = [r for r in reader if len(r) == 2 and r[1] not in (".", "")]
    if len(rows) <= 1:
        return None
    date_, value = rows[-1]
    return date_, value


class FedFundsResponsibility(Responsibility):
    responsibility_id = "us_fed_funds"
    display_name = "US Federal Funds Rate"
    dependencies = ()

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        cfg = context.source_config(self.responsibility_id).get("automatic", {})
        timeout = cfg.get("timeout_seconds", 20)
        try:
            upper_resp = httpx.get(cfg["url_upper"], timeout=timeout, follow_redirects=True)
            lower_resp = httpx.get(cfg["url_lower"], timeout=timeout, follow_redirects=True)
            upper_resp.raise_for_status()
            lower_resp.raise_for_status()
        except httpx.TimeoutException as exc:
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code="SOURCE_HTTP_TIMEOUT",
                                       retryable=True, message=str(exc))
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)
        except httpx.HTTPStatusError as exc:
            code = "SOURCE_HTTP_403" if exc.response.status_code == 403 else "SOURCE_HTTP_TIMEOUT"
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code=code,
                                       retryable=(code != "SOURCE_HTTP_403"), message=str(exc))
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)
        except Exception as exc:
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code="SOURCE_HTTP_TIMEOUT",
                                       retryable=True, message=f"FRED request failed: {exc}")
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        upper = _latest_fred_value(upper_resp.text)
        lower = _latest_fred_value(lower_resp.text)
        if not upper or not lower:
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code="SOURCE_LAYOUT_CHANGED",
                                       message="FRED CSV had no usable observations")
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        source_date, upper_val = upper
        _, lower_val = lower
        artifact = SourceArtifact(
            run_id=context.run_id, responsibility_id=self.responsibility_id,
            filename=f"fred_dfedtar_{source_date}.csv", sha256="", source_url=cfg["url_upper"],
            collection_method="official_http", mime_type="text/csv",
            local_path="", parser_version="fred_csv-1.0",
            effective_at=datetime.fromisoformat(source_date),
        )
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS,
                                 raw_rows=[{"lower": lower_val, "upper": upper_val, "source_date": source_date}],
                                 artifact=artifact)

    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult:
        lower = manual_input.numeric_fields.get("lower")
        upper = manual_input.numeric_fields.get("upper")
        selected = manual_input.numeric_fields.get("selected_value")
        if not lower or not upper:
            raise ValueError("US Fed Funds manual override requires numeric_fields['lower'] and ['upper']")
        if not manual_input.override_reason:
            raise ValueError("MANUAL_OVERRIDE_REASON_MISSING")
        source_date = (manual_input.effective_date.isoformat() if manual_input.effective_date
                       else context.report_date.isoformat())
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS,
                                 raw_rows=[{"lower": lower, "upper": upper, "source_date": source_date,
                                            "selected_value": selected, "override_reason": manual_input.override_reason}])

    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]:
        row = collection.raw_rows[0]
        lower = parse_and_normalize_rate(row["lower"])
        upper = parse_and_normalize_rate(row["upper"])

        rule = context.business_rules()["fed_funds"]["rule"]
        if row.get("selected_value"):
            selected = parse_and_normalize_rate(row["selected_value"])
        elif rule == "UPPER_BOUND":
            selected = upper
        elif rule == "LOWER_BOUND":
            selected = lower
        elif rule == "MIDPOINT":
            selected = (upper + lower) / 2
        else:
            selected = upper  # EFFECTIVE_RATE/MANUAL without an explicit value falls back to upper

        return [RateRecord(
            run_id=context.run_id, responsibility_id=self.responsibility_id,
            category="fed_funds", provider="Federal Reserve", currency="USD",
            rate=selected, gross_or_net="gross",
            selection_rule_id=rule, selection_reason=f"fed_funds_rule={rule}",
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
            findings.append(finding(context.run_id, rid, "PARSER_NO_ROWS", "blocking", "No Fed Funds record produced"))
            return ValidationResult(ok=False, findings=findings)
        r = records[0]
        findings += check_rate_range(context.run_id, rid, r.rate, "Cash!H31")
        if context.business_rules()["fed_funds"]["rule_status"] == "UNCONFIRMED_BUSINESS_RULE":
            findings.append(finding(context.run_id, rid, "FED_RULE_UNCONFIRMED", "warning",
                                     "fed_funds.rule (UPPER_BOUND) is inferred from the historical example, "
                                     "not confirmed in writing — verify before approving."))
        return ValidationResult(ok=not any(f.severity == "blocking" for f in findings), findings=findings)
