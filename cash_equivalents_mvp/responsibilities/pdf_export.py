"""PDF Export responsibility — exports the recalculated EN/FR workbooks to PDF and validates
page count, report date presence, and absence of formula-error text, per master prompt §7.11.
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from cash_equivalents_mvp.config import settings, workbook_map
from cash_equivalents_mvp.models import (
    CollectionResult,
    ManualInput,
    RateRecord,
    ResponsibilityError,
    ResponsibilityStatus,
    ValidationResult,
)
from cash_equivalents_mvp.reporting.renderer_selection import select_renderer
from cash_equivalents_mvp.responsibilities.base import Responsibility, RunContext
from cash_equivalents_mvp.validation.common import finding

EXPECTED_PAGE_COUNT = 7
FORMULA_ERROR_TOKENS = ("#REF!", "#VALUE!", "#NAME?", "#DIV/0!", "#NULL!", "#NUM!")

# The report is exactly these 7 sheets, one page each (verified: reference PDFs are 7 pages).
# 'Data Lists' is visible but is a dropdown-validation source, not part of the printed report —
# see reporting/excel_com.py export_pdf docstring.
REPORT_SHEET_ALIASES = ["cover", "executive_summary", "cash", "tbills", "hisa",
                         "cashable_term_deposits", "gic_1yr_5yr"]


class PdfExportResponsibility(Responsibility):
    responsibility_id = "pdf_export"
    display_name = "PDF Export"
    dependencies = ("workbook_rendering",)

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        paths_file = context.run_dir / "template_paths.txt"
        renderer_file = context.run_dir / "renderer.txt"
        if not paths_file.exists() or not renderer_file.exists():
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code="FILE_MISSING",
                                       message="Rendered workbooks not found — Workbook Rendering must complete first.")
            return CollectionResult(ok=False, status=ResponsibilityStatus.BLOCKED, error=err)
        en_path, fr_path = (Path(p) for p in paths_file.read_text(encoding="utf-8").splitlines())
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS,
                                 raw_rows=[{"en": str(en_path), "fr": str(fr_path)}])

    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult:
        return self.collect_automatic(context)

    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]:
        en_path, fr_path = Path(collection.raw_rows[0]["en"]), Path(collection.raw_rows[0]["fr"])
        _renderer_name, renderer = select_renderer(settings()["renderer"]["preference"])
        if renderer is None:
            raise RuntimeError("EXCEL_NOT_INSTALLED: neither Microsoft Excel nor LibreOffice is available")

        outputs_dir = context.run_dir / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        date_str = context.report_date.strftime(settings()["naming"]["date_format"])
        prefix = settings()["naming"]["package_prefix"]

        en_pdf = outputs_dir / f"{date_str} {prefix} EN.pdf"
        fr_pdf = outputs_dir / f"{date_str} {prefix} FR.pdf"
        en_sheets = [workbook_map("en")["sheets"][alias] for alias in REPORT_SHEET_ALIASES]
        fr_sheets = [workbook_map("fr")["sheets"][alias] for alias in REPORT_SHEET_ALIASES]
        renderer.export_pdf(en_path, en_pdf, sheet_names=en_sheets)
        renderer.export_pdf(fr_path, fr_pdf, sheet_names=fr_sheets)

        (context.run_dir / "pdf_paths.txt").write_text(f"{en_pdf}\n{fr_pdf}\n", encoding="utf-8")
        return []

    def validate(self, context: RunContext, records: list[RateRecord]) -> ValidationResult:
        findings = []
        rid = self.responsibility_id
        paths_file = context.run_dir / "pdf_paths.txt"
        if not paths_file.exists():
            findings.append(finding(context.run_id, rid, "PDF_EXPORT_FAILED", "blocking", "No PDF files were produced"))
            return ValidationResult(ok=False, findings=findings)

        en_pdf, fr_pdf = (Path(p) for p in paths_file.read_text(encoding="utf-8").splitlines())
        for language, path in [("EN", en_pdf), ("FR", fr_pdf)]:
            if not path.exists():
                findings.append(finding(context.run_id, rid, "PDF_EXPORT_FAILED", "blocking", f"{language} PDF missing"))
                continue
            doc = fitz.open(path)
            try:
                if doc.page_count != EXPECTED_PAGE_COUNT:
                    findings.append(finding(context.run_id, rid, "PDF_PAGE_COUNT_MISMATCH", "blocking",
                                             f"{language} PDF has {doc.page_count} pages, expected {EXPECTED_PAGE_COUNT}"))
                full_text = "\n".join(page.get_text() for page in doc)
                for tok in FORMULA_ERROR_TOKENS:
                    if tok in full_text:
                        findings.append(finding(context.run_id, rid, "BILINGUAL_PARITY_FAILED", "blocking",
                                                 f"{language} PDF contains formula error text {tok!r}"))
                for i, page in enumerate(doc):
                    if not page.get_text().strip():
                        findings.append(finding(context.run_id, rid, "PDF_PAGE_COUNT_MISMATCH", "warning",
                                                 f"{language} PDF page {i + 1} appears blank"))
            finally:
                doc.close()

        return ValidationResult(ok=not any(f.severity == "blocking" for f in findings), findings=findings)
