"""Tests for Excel COM recalculation adapter (WINNER).

Execution tests skipped when MS Office is not installed.
"""

from __future__ import annotations

import contextlib

import pytest


def test_excel_com_import() -> None:
    """Construction smoke test — import and instantiate."""
    from xlsx_core.recalc.excel_com import ExcelComRecalc

    assert ExcelComRecalc.name == "excel-com"


def test_excel_com_recalc_requires_office() -> None:
    """Recalc execution test — skipped if Excel COM not available."""
    from pathlib import Path

    try:
        import pythoncom
        import win32com.client
    except ImportError:
        pytest.skip("pywin32 not installed")

    # Check that Excel.Application can be dispatched
    pythoncom.CoInitialize()
    try:
        excel = win32com.client.Dispatch("Excel.Application")
        _version = excel.Version
        excel.Quit()
    except Exception:
        pythoncom.CoUninitialize()
        pytest.skip("Excel.Application not available via COM")
    finally:
        with contextlib.suppress(Exception):
            pythoncom.CoUninitialize()

    # Now do the actual recalc test
    import tempfile

    from xlsx_core.recalc.excel_com import ExcelComRecalc

    adapter = ExcelComRecalc()
    workbook = Path("data/附件4：平价上网光伏发电项目经济评价模型（第7.1版）.xlsx")
    if not workbook.exists():
        pytest.skip("Workbook not found")

    with tempfile.TemporaryDirectory() as tmp:
        result = adapter.recalc(workbook, Path(tmp))
        assert result.engine == "excel-com"
        assert result.ok
        assert result.wall_seconds > 0
        assert result.recalced_path is not None
        assert result.recalced_path.suffix == ".xlsx"
        assert result.recalced_path.exists()
