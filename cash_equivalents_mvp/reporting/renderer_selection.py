"""Auto-detects which WorkbookRenderer to use, per master prompt §7.10 renderer preference order."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from cash_equivalents_mvp.reporting.excel_com import ExcelComRenderer
from cash_equivalents_mvp.reporting.libreoffice import LibreOfficeRenderer


class WorkbookRenderer(Protocol):
    def is_available(self) -> bool: ...
    def recalculate_and_save(self, path: Path) -> None: ...
    def export_pdf(self, xlsx_path: Path, pdf_path: Path, sheet_names: list[str] | None = None) -> None: ...


_RENDERERS: dict[str, type[WorkbookRenderer]] = {
    "excel_com": ExcelComRenderer, "libreoffice": LibreOfficeRenderer,
}


def select_renderer(preference: list[str]) -> tuple[str, WorkbookRenderer] | tuple[None, None]:
    for name in preference:
        cls = _RENDERERS.get(name)
        if cls is None:
            continue
        instance = cls()
        if instance.is_available():
            return name, instance
    return None, None
