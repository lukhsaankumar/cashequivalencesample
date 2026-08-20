"""Excel COM automation (Windows only). Runs in-process but always inside its own
CoInitialize/CoUninitialize pair so it's safe to call from a worker thread.

Never used to edit the workbook's business content — cell writes happen earlier via openpyxl
(reporting/mappings.py) while the file is closed. This module only opens the already-populated
file, forces a full recalculation, saves, and exports a PDF — the same three steps a human would
do by hand in Excel.
"""
from __future__ import annotations

from pathlib import Path


class ExcelNotAvailable(Exception):
    pass


class ExcelComRenderer:
    """WorkbookRenderer implementation using Microsoft Excel via pywin32."""

    def is_available(self) -> bool:
        try:
            import pythoncom
            import win32com.client
        except ImportError:
            return False
        try:
            pythoncom.CoInitialize()
            try:
                import win32com.client
                app = win32com.client.DispatchEx("Excel.Application")
                app.Quit()
                return True
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            return False

    def recalculate_and_save(self, path: Path) -> None:
        """Opens path in Excel, forces a full recalculation, saves in place, closes Excel."""
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        app = None
        try:
            app = win32com.client.DispatchEx("Excel.Application")
            app.Visible = False
            app.DisplayAlerts = False
            wb = app.Workbooks.Open(str(path.resolve()), UpdateLinks=0, ReadOnly=False)
            try:
                app.CalculateFullRebuild()
                wb.Save()
            finally:
                wb.Close(SaveChanges=True)
        except Exception as exc:
            raise RuntimeError(f"EXCEL_COM_FAILURE: {exc}") from exc
        finally:
            if app is not None:
                app.Quit()
            pythoncom.CoUninitialize()

    def export_pdf(self, xlsx_path: Path, pdf_path: Path, sheet_names: list[str] | None = None) -> None:
        """sheet_names, if given, selects exactly those sheets (in order) before export — needed
        because ExportAsFixedFormat on the whole Workbook includes every *visible* sheet, and this
        workbook has a visible 'Data Lists' (dropdown source) sheet that is not part of the
        printed 7-page report. Selecting the report sheets first reproduces what a human does by
        Ctrl-clicking the report tabs before File > Export in Excel."""
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        app = None
        try:
            app = win32com.client.DispatchEx("Excel.Application")
            app.Visible = False
            app.DisplayAlerts = False
            wb = app.Workbooks.Open(str(xlsx_path.resolve()), UpdateLinks=0, ReadOnly=True)
            try:
                if sheet_names:
                    # Workbook.ExportAsFixedFormat always exports every sheet regardless of tab
                    # selection — grouping tabs and exporting from ActiveSheet is what actually
                    # limits the export to the selected/grouped sheets (standard Excel behavior
                    # when multiple tabs are selected as a group).
                    wb.Worksheets(list(sheet_names)).Select()
                    target = wb.ActiveSheet
                else:
                    target = wb
                # xlTypePDF = 0
                target.ExportAsFixedFormat(0, str(pdf_path.resolve()))
            finally:
                wb.Close(SaveChanges=False)
        except Exception as exc:
            raise RuntimeError(f"PDF_EXPORT_FAILED: {exc}") from exc
        finally:
            if app is not None:
                app.Quit()
            pythoncom.CoUninitialize()
