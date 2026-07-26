"""Excel COM recalculation adapter (Windows-only, pywin32).

Uses win32com to drive Excel.Application for recalculation.
Requires Microsoft Office to be installed.
"""

from __future__ import annotations

import contextlib
import shutil
import time
from pathlib import Path

from xlsx_core.recalc.base import RecalcResult


class ExcelComRecalc:
    """Recalculate a workbook via Excel COM automation (win32com).

    Requires pywin32 and Microsoft Office installed (not just Store stub).
    """

    name: str = "excel-com"

    def recalc(self, workbook: Path, out_dir: Path) -> RecalcResult:
        t0 = time.perf_counter()
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            wall = time.perf_counter() - t0
            return RecalcResult(
                engine=self.name,
                ok=False,
                wall_seconds=wall,
                errors=(f"ImportError: {exc}",),
            )

        pythoncom.CoInitialize()
        excel = None
        wb = None
        try:
            excel = win32com.client.Dispatch("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            with contextlib.suppress(Exception):
                excel.Calculation = -4105  # xlCalculationAutomatic

            output_path = out_dir / workbook.name
            shutil.copy2(workbook, output_path)

            wb = excel.Workbooks.Open(str(output_path.resolve()))
            excel.CalculateFull()
            wb.Save()
            wb.Close()
            wb = None

            wall = time.perf_counter() - t0
            return RecalcResult(
                engine=self.name,
                ok=True,
                wall_seconds=wall,
                recalced_path=output_path,
            )
        except Exception as exc:
            wall = time.perf_counter() - t0
            return RecalcResult(
                engine=self.name,
                ok=False,
                wall_seconds=wall,
                errors=(f"Excel COM dispatch failed: {exc}",),
            )
        finally:
            if wb is not None:
                with contextlib.suppress(Exception):
                    wb.Close(False)
            if excel is not None:
                with contextlib.suppress(Exception):
                    excel.Quit()
            with contextlib.suppress(Exception):
                pythoncom.CoUninitialize()
