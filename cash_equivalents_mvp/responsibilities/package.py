"""Package responsibility — bundles EN/FR xlsx+pdf, an unsent .eml draft, and a ZIP for download.
Never sends email — see reporting/email_draft.py and SECURITY.md.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from cash_equivalents_mvp.config import settings
from cash_equivalents_mvp.models import (
    CollectionResult,
    ManualInput,
    RateRecord,
    ResponsibilityError,
    ResponsibilityStatus,
    ValidationResult,
)
from cash_equivalents_mvp.reporting.email_draft import build_eml_draft
from cash_equivalents_mvp.responsibilities.base import Responsibility, RunContext
from cash_equivalents_mvp.validation.common import finding


class PackageResponsibility(Responsibility):
    responsibility_id = "package"
    display_name = "Output Package"
    dependencies = ("pdf_export",)

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        template_paths = context.run_dir / "template_paths.txt"
        pdf_paths = context.run_dir / "pdf_paths.txt"
        if not template_paths.exists() or not pdf_paths.exists():
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code="FILE_MISSING",
                                       message="Rendered workbooks or PDFs not found.")
            return CollectionResult(ok=False, status=ResponsibilityStatus.BLOCKED, error=err)
        en_xlsx, fr_xlsx = (Path(p) for p in template_paths.read_text(encoding="utf-8").splitlines())
        en_pdf, fr_pdf = (Path(p) for p in pdf_paths.read_text(encoding="utf-8").splitlines())
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS,
                                 raw_rows=[{"en_xlsx": str(en_xlsx), "fr_xlsx": str(fr_xlsx),
                                            "en_pdf": str(en_pdf), "fr_pdf": str(fr_pdf)}])

    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult:
        return self.collect_automatic(context)

    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]:
        row = collection.raw_rows[0]
        en_xlsx, fr_xlsx = Path(row["en_xlsx"]), Path(row["fr_xlsx"])
        en_pdf, fr_pdf = Path(row["en_pdf"]), Path(row["fr_pdf"])

        outputs_dir = context.run_dir / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        date_str = context.report_date.strftime(settings()["naming"]["date_format"])
        prefix = settings()["naming"]["package_prefix"]

        final_en_xlsx = outputs_dir / f"{date_str} {prefix} EN.xlsx"
        final_fr_xlsx = outputs_dir / f"{date_str} {prefix} FR.xlsx"
        import shutil
        shutil.copy2(en_xlsx, final_en_xlsx)
        shutil.copy2(fr_xlsx, final_fr_xlsx)

        eml_path = outputs_dir / f"{date_str} {prefix} Email Draft.eml"
        msg = build_eml_draft(context.report_date.isoformat(), en_pdf, fr_pdf, final_en_xlsx, final_fr_xlsx)
        eml_path.write_bytes(bytes(msg))

        zip_path = outputs_dir / f"{date_str} {prefix} Package.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in (final_en_xlsx, final_fr_xlsx, en_pdf, fr_pdf, eml_path):
                zf.write(f, arcname=f.name)

        (context.run_dir / "package_paths.txt").write_text(
            "\n".join(str(p) for p in (final_en_xlsx, final_fr_xlsx, en_pdf, fr_pdf, eml_path, zip_path)),
            encoding="utf-8",
        )
        return []

    def validate(self, context: RunContext, records: list[RateRecord]) -> ValidationResult:
        findings = []
        rid = self.responsibility_id
        paths_file = context.run_dir / "package_paths.txt"
        if not paths_file.exists():
            findings.append(finding(context.run_id, rid, "FILE_MISSING", "blocking", "Package was not created"))
            return ValidationResult(ok=False, findings=findings)

        paths = [Path(p) for p in paths_file.read_text(encoding="utf-8").splitlines()]
        for p in paths:
            if not p.exists():
                findings.append(finding(context.run_id, rid, "FILE_MISSING", "blocking", f"Missing output: {p.name}"))

        eml_path = next((p for p in paths if p.suffix == ".eml"), None)
        if eml_path and eml_path.exists():
            import email
            with open(eml_path, "rb") as f:
                msg = email.message_from_binary_file(f)
            for header in ("To", "Cc", "Bcc"):
                if msg.get(header, "").strip():
                    findings.append(finding(context.run_id, rid, "MANUAL_OVERRIDE_REASON_MISSING", "blocking",
                                             f"Email draft {header} header is not empty — it must never be pre-addressed"))

        return ValidationResult(ok=not any(f.severity == "blocking" for f in findings), findings=findings)
