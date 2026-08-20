"""LibreOffice headless fallback renderer, used when Microsoft Excel is not installed.

LibreOffice's `soffice --headless --convert-to` recalculates formulas as part of loading (subject
to its own formula-compatibility limitations) and can export PDF directly. It cannot force a
"full rebuild" recalculation the way Excel COM can, so this path is a genuine fallback, not a
perfect substitute — see docs/architecture.md.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class LibreOfficeRenderer:
    def is_available(self) -> bool:
        return shutil.which("soffice") is not None or shutil.which("soffice.exe") is not None

    def _soffice(self) -> str:
        path = shutil.which("soffice") or shutil.which("soffice.exe")
        if path is None:
            raise RuntimeError("LIBREOFFICE_NOT_INSTALLED: soffice not found on PATH")
        return path

    def recalculate_and_save(self, path: Path) -> None:
        # LibreOffice recalculates on load/convert; round-tripping through xlsx forces that.
        out_dir = path.parent
        result = subprocess.run(
            [self._soffice(), "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(out_dir), str(path)],
            capture_output=True, text=True, timeout=120, check=False,  # returncode handled explicitly below
        )
        if result.returncode != 0:
            raise RuntimeError(f"LIBREOFFICE_NOT_INSTALLED: {result.stderr}")

    def export_pdf(self, xlsx_path: Path, pdf_path: Path, sheet_names: list[str] | None = None) -> None:
        # LibreOffice's headless CLI conversion has no per-sheet selection option, unlike Excel
        # COM's Worksheets(...).Select(); this fallback always exports every visible sheet.
        result = subprocess.run(
            [self._soffice(), "--headless", "--calc", "--convert-to", "pdf", "--outdir",
             str(pdf_path.parent), str(xlsx_path)],
            capture_output=True, text=True, timeout=120, check=False,  # returncode handled explicitly below
        )
        if result.returncode != 0:
            raise RuntimeError(f"PDF_EXPORT_FAILED: {result.stderr}")
        produced = xlsx_path.with_suffix(".pdf")
        if produced != pdf_path and produced.exists():
            produced.replace(pdf_path)
