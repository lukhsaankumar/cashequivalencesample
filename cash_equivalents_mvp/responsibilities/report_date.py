"""Report Date responsibility — the date chosen when the run was created is the single input;
this responsibility just validates it and records it as a RateRecord-less artifact of provenance
so the Workbook Rendering responsibility can rely on it having been checked.
"""
from __future__ import annotations

from cash_equivalents_mvp.models import (
    CollectionResult,
    ManualInput,
    RateRecord,
    ResponsibilityStatus,
    ValidationResult,
)
from cash_equivalents_mvp.responsibilities.base import Responsibility, RunContext
from cash_equivalents_mvp.validation.common import finding


class ReportDateResponsibility(Responsibility):
    responsibility_id = "report_date"
    display_name = "Report Date"
    dependencies = ()

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS,
                                 raw_rows=[{"report_date": context.report_date.isoformat()}])

    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult:
        value = manual_input.numeric_fields.get("report_date")
        if not value:
            raise ValueError("Report date manual override requires numeric_fields['report_date']")
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=[{"report_date": value}])

    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]:
        return []  # no RateRecords — the date is consumed directly from context.report_date

    def validate(self, context: RunContext, records: list[RateRecord]) -> ValidationResult:
        findings = []
        if context.report_date.weekday() >= 5:
            findings.append(finding(context.run_id, self.responsibility_id, "REPORT_DATE_WEEKEND", "warning",
                                     f"{context.report_date} falls on a weekend"))
        return ValidationResult(ok=True, findings=findings)
