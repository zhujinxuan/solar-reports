"""Verification use case for solar-server.

Two paths:
  1.1: Recalc the workbook with chosen engine → compare solar-v1 NodeValues
       against the RECALCULATED workbook's values on every formula+error node.
  1.2: Compare solar-v2 compute() vs solar-v1 compute() node-by-node.
"""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from typing import cast

import openpyxl
from xlsx_core.model import ErrorValue, Scalar
from xlsx_core.recalc.base import RecalcEngine, compare_values
from xlsx_core.settings import Settings

from solar_server.schemas import (
    MismatchJSON,
    Path11Result,
    Path11Skipped,
    Path12Result,
    VerifyResponse,
    scalar_to_json,
)

_SAMPLE_CAP: int = 20

_ENGINE_MAP: dict[str, RecalcEngine | None] = {}


def _get_engine(name: str, settings: Settings) -> RecalcEngine | None:
    """Lazy-load a recalc engine adapter by name."""
    if name not in _ENGINE_MAP:
        if name == "excel-com":
            from xlsx_core.recalc.excel_com import ExcelComRecalc

            _ENGINE_MAP[name] = ExcelComRecalc()
        elif name == "libreoffice":
            from xlsx_core.recalc.libreoffice import LibreOfficeRecalc

            _ENGINE_MAP[name] = LibreOfficeRecalc(settings.libreoffice_path)
        else:
            _ENGINE_MAP[name] = None
    return _ENGINE_MAP[name]

def _check_engine_available(name: str, settings: Settings) -> bool:
    if name == "excel-com":
        try:
            import pythoncom
            import win32com.client
        except ImportError:
            return False
        try:
            pythoncom.CoInitialize()  # type: ignore[possibly-unbound]
            excel = win32com.client.Dispatch("Excel.Application")  # type: ignore[possibly-unbound]
            excel.Quit()
            return True
        except Exception:
            return False
        finally:
            with contextlib.suppress(Exception):
                pythoncom.CoUninitialize()  # type: ignore[possibly-unbound]
    if name == "libreoffice":
        return settings.libreoffice_path.exists()
    return False


def _read_recalced_values(workbook_path: Path) -> dict[str, Scalar]:
    """Read all cell values from a recalced workbook using openpyxl.

    Returns {sheet!col_lettersrow: value} for every non-empty cell.
    """
    wb = openpyxl.load_workbook(str(workbook_path), data_only=True, read_only=True)
    try:
        values: dict[str, Scalar] = {}
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            for row in ws.iter_rows():
                for cell in row:
                    if not hasattr(cell, 'column_letter'):
                        continue
                    col_letter = cell.column_letter  # type: ignore[attr-defined]
                    node_id = f"{sheet_name}!{col_letter}{cell.row}"
                    raw: object = cell.value
                    if raw is None:
                        continue
                    if isinstance(raw, str) and raw.startswith("#"):
                        values[node_id] = ErrorValue(error=raw)
                    elif isinstance(raw, (int, float, str, bool)):
                        values[node_id] = raw  # type: ignore[assignment]
                    else:
                        values[node_id] = str(raw)  # type: ignore[assignment]
        return values
    finally:
        wb.close()



def _run_path_1_1(
    settings: Settings,
    engine_name: str,
) -> Path11Result | Path11Skipped:
    """Path 1.1: recalc + compare v1 vs recalced workbook."""
    adapter = _get_engine(engine_name, settings)
    if adapter is None:
        return Path11Result(
            engine=engine_name,
            ok=False,
            mismatch_count=-1,
            total=0,
            sample_mismatches=(),
        )

    with tempfile.TemporaryDirectory(prefix="solar_recalc_") as tmp_dir:
        out_dir = Path(tmp_dir)
        result = adapter.recalc(settings.workbook_path, out_dir)

        if not result.ok or result.recalced_path is None:
            return Path11Result(
                engine=engine_name,
                ok=False,
                mismatch_count=-1,
                total=0,
                sample_mismatches=(),
            )

        # Get v1 computed values
        from solar_v1.api import compute as v1_compute

        v1_values = v1_compute(settings)
        recalced_values = _read_recalced_values(result.recalced_path)

        # Compare on formula+error nodes only
        from solar_v1.dag_loader import load_dag

        dag = load_dag(settings.dag_path, settings.workbook_path)
        mismatches: list[MismatchJSON] = []
        total: int = 0

        for node in dag.nodes:
            if node.type not in ("formula", "error"):
                continue
            total += 1
            expected = recalced_values.get(node.id)
            got = v1_values.values.get(node.id)
            if not compare_values(
                got, expected,
                rel_tol=settings.rel_tol, abs_tol=settings.abs_tol,
            ):
                mismatches.append(
                    MismatchJSON(
                        node_id=node.id,
                        expected=scalar_to_json(expected),
                        got=scalar_to_json(got),
                    )
                )
                if len(mismatches) >= _SAMPLE_CAP:
                    break

        return Path11Result(
            engine=engine_name,
            ok=len(mismatches) == 0 and total > 0,
            mismatch_count=len(mismatches),
            total=total,
            sample_mismatches=tuple(mismatches),
        )


def _run_path_1_2(settings: Settings) -> Path12Result:
    """Path 1.2: compare solar-v2 engine vs solar-v1 compute().

    Runs compute_model() → v2_benchmark.projection.project() →
    compare vs solar_v1 values.
    """
    from solar_v1.api import compute as v1_compute
    from solar_v2.engine import compute_model
    from v2_benchmark.compare import diff as diff_v2
    from v2_benchmark.projection import project as project_v2

    v1_values = v1_compute(settings)
    v1_dict = dict(v1_values.values)

    results = compute_model()
    dag_path = str(settings.dag_path)
    projected = project_v2(results, dag_path=dag_path)

    # Use compare.diff
    diffs = diff_v2(projected, v1_dict, rel_tol=settings.rel_tol)

    mismatches: list[MismatchJSON] = []
    for d in diffs[: _SAMPLE_CAP]:
        mismatches.append(
            MismatchJSON(
                node_id=d.node_id,
                expected=scalar_to_json(cast(Scalar, d.benchmark)),
                got=scalar_to_json(cast(Scalar, d.projected)),
            )
        )

    return Path12Result(
        ok=len(diffs) == 0 and len(projected) > 0,
        mismatch_count=len(diffs),
        total=len(projected),
        sample_mismatches=tuple(mismatches),
    )


def verify(
    settings: Settings,
    *,
    engine: str | None = None,
    skip_engine: bool = False,
    skip_v2: bool = False,
) -> VerifyResponse:
    """Run the two-path verification.

    Args:
        settings: xlsx-core Settings.
        engine: Override for recalc engine (default from settings).
        skip_engine: Skip path 1.1.
        skip_v2: Skip path 1.2.

    Returns:
        VerifyResponse with both path results.
    """
    engine_name: str = engine or settings.recalc_engine

    if skip_engine:
        path_1_1: Path11Result | Path11Skipped = Path11Skipped()
    else:
        path_1_1 = _run_path_1_1(settings, engine_name)

    path_1_2: Path12Result | None = None
    if not skip_v2:
        path_1_2 = _run_path_1_2(settings)

    if isinstance(path_1_1, Path11Skipped):
        p1_ok: bool = True
    else:
        p1_ok = path_1_1.ok

    p2_ok: bool = path_1_2.ok if path_1_2 is not None else True

    return VerifyResponse(
        path_1_1=path_1_1,
        path_1_2=path_1_2,
        ok=p1_ok and p2_ok,
    )
