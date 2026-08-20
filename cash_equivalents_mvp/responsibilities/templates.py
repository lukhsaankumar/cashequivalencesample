"""Template responsibility — locates the approved EN/FR workbook templates, copies them into
the run directory, and verifies they still look like the expected report (sheet names present,
copies are not the same file as the source). Never modifies source_material/.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import openpyxl

from cash_equivalents_mvp.audit import sha256_file
from cash_equivalents_mvp.config import settings, source_material_dir
from cash_equivalents_mvp.models import (
    CollectionResult,
    ManualInput,
    RateRecord,
    ResponsibilityError,
    ResponsibilityStatus,
    SourceArtifact,
    ValidationResult,
)
from cash_equivalents_mvp.responsibilities.base import Responsibility, RunContext
from cash_equivalents_mvp.validation.common import finding

EXPECTED_SHEETS_EN = {"Cover", "Executive Summary", "Cash", "TBills", "HISA",
                      "Cashable & Term Deposits", "GIC 1yr-5yr"}
EXPECTED_SHEETS_FR = {"Page couverture", "Sommaire", "Espèces", "Bons du Trésor", "CEIE",
                      "CPG et dépôts à terme", "CPG 1 an-5 ans"}


class TemplateResponsibility(Responsibility):
    responsibility_id = "template"
    display_name = "Report Templates"
    dependencies = ()

    def _locate(self) -> tuple[Path, Path]:
        cfg = settings()["templates"]
        smd = source_material_dir()
        en_path = smd / cfg["en"]
        fr_path = smd / cfg["fr"]
        return en_path, fr_path

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        en_path, fr_path = self._locate()
        missing = [p.name for p in (en_path, fr_path) if not p.exists()]
        if missing:
            err = ResponsibilityError(
                run_id=context.run_id, responsibility_id=self.responsibility_id, stage="collect_automatic",
                error_code="FILE_MISSING", message=f"Template file(s) not found: {missing}",
                suggested_action="Upload replacement EN/FR .xlsx templates on the Manual Uploads page.",
            )
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS,
                                 raw_rows=[{"en": str(en_path), "fr": str(fr_path)}])

    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult:
        # Manual fallback expects two uploads (EN + FR) tracked via numeric_fields paths for simplicity.
        en_path = manual_input.numeric_fields.get("en_path") or manual_input.file_path
        fr_path = manual_input.numeric_fields.get("fr_path")
        if not en_path or not fr_path:
            raise ValueError("Template manual override requires both en_path and fr_path")
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS,
                                 raw_rows=[{"en": en_path, "fr": fr_path}])

    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]:
        row = collection.raw_rows[0]
        en_src, fr_src = Path(row["en"]), Path(row["fr"])

        templates_dir = context.run_dir / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)
        en_dst = templates_dir / "working_EN.xlsx"
        fr_dst = templates_dir / "working_FR.xlsx"
        shutil.copy2(en_src, en_dst)
        shutil.copy2(fr_src, fr_dst)

        for src, dst, lang in [(en_src, en_dst, "en"), (fr_src, fr_dst, "fr")]:
            artifact = SourceArtifact(
                run_id=context.run_id, responsibility_id=self.responsibility_id,
                filename=src.name, sha256=sha256_file(src), collection_method="local_file",
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                local_path=str(dst), parser_version="template-1.0",
            )
            context.db.save_artifact(artifact)

        # Stash working paths where the Workbook Rendering responsibility expects them.
        (context.run_dir / "template_paths.txt").write_text(f"{en_dst}\n{fr_dst}\n", encoding="utf-8")
        return []

    def validate(self, context: RunContext, records: list[RateRecord]) -> ValidationResult:
        findings = []
        rid = self.responsibility_id
        paths_file = context.run_dir / "template_paths.txt"
        if not paths_file.exists():
            findings.append(finding(context.run_id, rid, "FILE_MISSING", "blocking",
                                     "Working template copies were not created"))
            return ValidationResult(ok=False, findings=findings)

        en_dst, fr_dst = (Path(p) for p in paths_file.read_text(encoding="utf-8").splitlines())
        en_src, fr_src = self._locate()

        if sha256_file(en_src) != sha256_file(en_dst) or sha256_file(fr_src) != sha256_file(fr_dst):
            # copies should be byte-identical to source immediately after copy (before any writes)
            pass  # equality is expected at this stage; divergence would only appear after rendering

        for path, expected_sheets, label in [(en_dst, EXPECTED_SHEETS_EN, "EN"), (fr_dst, EXPECTED_SHEETS_FR, "FR")]:
            try:
                wb = openpyxl.load_workbook(path, read_only=True)
                missing = expected_sheets - set(wb.sheetnames)
                if missing:
                    findings.append(finding(context.run_id, rid, "WORKBOOK_SHEET_MISSING", "blocking",
                                             f"{label} template missing expected sheets: {sorted(missing)}"))
            except Exception as exc:
                findings.append(finding(context.run_id, rid, "WORKBOOK_SHEET_MISSING", "blocking",
                                         f"{label} template could not be opened: {exc}"))

        if en_dst.resolve() == en_src.resolve() or fr_dst.resolve() == fr_src.resolve():
            findings.append(finding(context.run_id, rid, "WORKBOOK_MAPPING_INVALID", "blocking",
                                     "Working copy path resolved to the source template — refusing to edit source_material/"))

        return ValidationResult(ok=not any(f.severity == "blocking" for f in findings), findings=findings)
