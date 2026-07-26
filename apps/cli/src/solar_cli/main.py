"""solar-cli — typer CLI for the consume-xlsx-as-software toolchain.

Commands:
  extract   — workbook → dag/solar.dag.yaml (xlsx-core)
  compute   — run solar-v1 or solar-v2, dump node values
  verify    — three-way golden check: v1 vs recalc engine, v2 vs v1
"""

from __future__ import annotations

import csv
import json
import tempfile
import time
from pathlib import Path
from typing import Annotated

import openpyxl
import typer
from xlsx_core.extract import extract_dag
from xlsx_core.model import ErrorValue, Scalar
from xlsx_core.recalc.base import (
    RecalcEngine,
    RecalcResult,
    compare_values,
)
from xlsx_core.recalc.excel_com import ExcelComRecalc
from xlsx_core.recalc.formulas_pkg import FormulasPkgRecalc
from xlsx_core.recalc.libreoffice import LibreOfficeRecalc
from xlsx_core.settings import Settings

app = typer.Typer(
    name="solar-cli",
    help="CLI for the consume-xlsx-as-software toolchain",
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_ERROR_STRINGS: frozenset[str] = frozenset(
    {"#REF!", "#DIV/0!", "#VALUE!", "#N/A", "#NAME?", "#NULL!", "#NUM!"}
)


def _parse_cached_value(raw: object) -> Scalar:
    """Convert openpyxl cached value to Scalar, detecting error strings."""
    if isinstance(raw, str) and raw.strip() in _ERROR_STRINGS:
        return ErrorValue(error=raw.strip())
    if isinstance(raw, (int, float, str, bool)):
        return raw
    if raw is None:
        return None
    return str(raw)


def _node_id_to_cell(node_id: str) -> tuple[str, str, int]:
    """Parse 'sheet!A1' → (sheet, col_letter, row)."""
    import re

    m = re.match(r"^(.+)!([A-Z]+)(\d+)$", node_id)
    if m is None:
        msg = f"Invalid node id: {node_id}"
        raise ValueError(msg)
    return m.group(1), m.group(2), int(m.group(3))


def _load_recalced_values(
    recalced_path: Path, node_ids: set[str]
) -> dict[str, Scalar]:
    """Load cached values from a recalced workbook for given node ids."""
    wb = openpyxl.load_workbook(str(recalced_path), data_only=True)
    result: dict[str, Scalar] = {}
    try:
        for nid in node_ids:
            sheet_name, col, row = _node_id_to_cell(nid)
            if sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            raw = ws[f"{col}{row}"].value
            result[nid] = _parse_cached_value(raw)
    finally:
        wb.close()
    return result




def _build_settings(
    workbook: Path | None = None,
    dag: Path | None = None,
    rel_tol: float | None = None,
    abs_tol: float | None = None,
    engine: str | None = None,
    libreoffice_path: Path | None = None,
) -> Settings:
    """Build Settings from CLI overrides, falling back to defaults."""
    overrides: dict[str, object] = {}
    if workbook is not None:
        overrides["workbook_path"] = workbook
    if dag is not None:
        overrides["dag_path"] = dag
    if rel_tol is not None:
        overrides["rel_tol"] = rel_tol
    if abs_tol is not None:
        overrides["abs_tol"] = abs_tol
    if engine is not None:
        overrides["recalc_engine"] = engine
    if libreoffice_path is not None:
        overrides["libreoffice_path"] = libreoffice_path
    return Settings(**overrides) if overrides else Settings()  # ty: ignore[invalid-argument-type]


def _resolve_engine(
    name: str, libreoffice_path: Path,
) -> tuple[RecalcEngine | None, str | None]:
    """Resolve an engine name to an adapter instance.

    Returns (adapter, error_message) — exactly one is non-None.
    Availability checks are lightweight (import-only); actual dispatch
    failures surface during recalc.
    """
    name = name.strip()
    if name == "excel-com":
        try:
            __import__("pythoncom")
            __import__("win32com.client")
        except ImportError:
            return None, "pywin32 not installed — install with: uv add pywin32"
        return ExcelComRecalc(), None
    if name == "libreoffice":
        soffice = libreoffice_path
        if not soffice.exists():
            return None, f"LibreOffice not found at {soffice}"
        return LibreOfficeRecalc(soffice), None
    if name == "formulas-pkg":
        try:
            __import__("formulas")
        except ImportError:
            return None, "formulas package not installed"
        return FormulasPkgRecalc(), None
    return (
        None,
        f"Unknown engine: {name!r}"
        " — choose excel-com | libreoffice | formulas-pkg",
    )


def _print_mismatches(
    mismatches: list[tuple[str, Scalar, Scalar]],
    label: str,
    max_show: int = 20,
) -> None:
    """Print mismatch summary."""
    typer.echo(f"\n{label}: {len(mismatches)} mismatch(es)")
    for nid, expected, got in mismatches[:max_show]:
        typer.echo(f"  {nid}: expected={expected!r} got={got!r}")
    if len(mismatches) > max_show:
        typer.echo(f"  ... and {len(mismatches) - max_show} more")


def _scalars_match(
    a: Scalar, b: Scalar, rel_tol: float, abs_tol: float,
) -> bool:
    """Check if two scalars match per the contract matching rule."""
    return compare_values(a, b, rel_tol=rel_tol, abs_tol=abs_tol)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


@app.command()
def extract(
    workbook: Annotated[
        Path | None,
        typer.Option(
            "--workbook",
            help="Path to the source workbook",
            show_default="Settings.workbook_path",
        ),
    ] = None,
    dag: Annotated[
        Path | None,
        typer.Option(
            "--dag",
            help="Output DAG YAML path",
            show_default="Settings.dag_path",
        ),
    ] = None,
) -> None:
    """Extract the SOLAR workbook into a DAG YAML file (dag/solar.dag.yaml).

    Reads every non-blank cell from the workbook, classifies each as formula /
    literal / error, detects year-series column patterns, and writes the full
    node set to disk.
    """
    settings = _build_settings(workbook=workbook, dag=dag)
    t0 = time.perf_counter()
    dag_obj = extract_dag(settings)
    elapsed = time.perf_counter() - t0
    typer.echo(
        f"Extracted {len(dag_obj.nodes)} nodes to {settings.dag_path}"
    )
    typer.echo(f"Elapsed: {elapsed:.2f}s")


@app.command()
def compute(
    version: Annotated[
        str,
        typer.Option(
            "--version",
            help="Version to compute: v1 (interpreter) or v2 (domain)",
        ),
    ],
    workbook: Annotated[
        Path | None,
        typer.Option(
            "--workbook",
            help="Path to the source workbook",
        ),
    ] = None,
    dag: Annotated[
        Path | None,
        typer.Option(
            "--dag",
            help="Path to dag.yaml",
        ),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help="Output file path (.json or .csv); stdout summary if omitted",
        ),
    ] = None,
) -> None:
    """Compute node values via solar-v1 or solar-v2.

    Writes results as JSON ({node_id: value}) or CSV (node_id,value) if --out
    is given.  Prints a count + elapsed summary otherwise.
    """
    if version not in ("v1", "v2"):
        typer.echo(f"Invalid --version: {version!r}. Use v1 or v2.", err=True)
        raise typer.Exit(code=1)

    settings = _build_settings(workbook=workbook, dag=dag)
    t0 = time.perf_counter()

    if version == "v1":
        from solar_v1.api import compute as compute_v1

        node_values = compute_v1(settings)
    else:
        try:
            import importlib

            compute_v2 = importlib.import_module(
                "solar_v2.api"
            ).compute
        except (ImportError, ModuleNotFoundError) as exc:
            typer.echo(
                f"solar-v2 not available ({exc})"
                " — solar-v2 may be mid-rewrite. Use --version v1.",
                err=True,
            )
            raise typer.Exit(code=1) from exc

        node_values = compute_v2(settings)

    elapsed = time.perf_counter() - t0
    count = len(node_values.values)

    if out is not None:
        out_str = str(out)
        plain: dict[str, object] = {}
        for k, v in node_values.values.items():
            if isinstance(v, ErrorValue):
                plain[k] = v.error
            else:
                plain[k] = v

        if out_str.endswith(".csv"):
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out_str, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["node_id", "value"])
                for k, v in plain.items():
                    writer.writerow([k, v])
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out_str, "w", encoding="utf-8") as f:
                json.dump(plain, f, ensure_ascii=False, indent=2)

        typer.echo(
            f"Wrote {count} node values to {out} ({elapsed:.2f}s)"
        )
    else:
        typer.echo(
            f"Computed {count} node values via solar-{version} ({elapsed:.2f}s)"
        )


@app.command()
def verify(
    engine: Annotated[
        str,
        typer.Option(
            "--engine",
            help="Recalc engine for path 1.1: excel-com | libreoffice | formulas-pkg",
        ),
    ] = "excel-com",
    workbook: Annotated[
        Path | None,
        typer.Option(
            "--workbook",
            help="Path to the source workbook",
        ),
    ] = None,
    dag: Annotated[
        Path | None,
        typer.Option(
            "--dag",
            help="Path to dag.yaml",
        ),
    ] = None,
    rel_tol: Annotated[
        float | None,
        typer.Option(
            "--rel-tol",
            help="Relative tolerance for numeric comparison",
        ),
    ] = None,
    abs_tol: Annotated[
        float | None,
        typer.Option(
            "--abs-tol",
            help="Absolute tolerance for numeric comparison",
        ),
    ] = None,
    skip_engine: Annotated[
        bool,
        typer.Option(
            "--skip-engine",
            help="Skip path 1.1 (engine recalc + v1 comparison)",
        ),
    ] = False,
    skip_v2: Annotated[
        bool,
        typer.Option(
            "--skip-v2",
            help="Skip path 1.2 (v2-to-v1 inner-join comparison)",
        ),
    ] = False,
) -> None:
    """Three-way golden check — G4 gate.

    Path 1.1: recalc the workbook with the chosen engine, then compare
    solar-v1's interpreted values against the recalced workbook on every
    formula+error node.

    Path 1.2: compare solar-v2 compute() vs solar-v1 compute()
    node-by-node (inner join on v2's claimed node ids).

    Exit 0 iff all enabled paths clean.
    Exit 1 on diffs (first ~20 mismatches printed).
    Exit 2 if a required engine is unavailable.
    """
    settings = _build_settings(
        workbook=workbook,
        dag=dag,
        rel_tol=rel_tol,
        abs_tol=abs_tol,
        engine=engine,
    )

    rel = settings.rel_tol
    abs_t = settings.abs_tol

    # --- Run solar-v1 compute once (needed by both paths) ---
    from solar_v1.api import compute as compute_v1
    from solar_v1.dag_loader import load_dag

    typer.echo("Computing solar-v1 values ... ", nl=False)
    t0 = time.perf_counter()
    v1_values = compute_v1(settings)
    typer.echo(
        f"{len(v1_values.values)} nodes ({time.perf_counter() - t0:.2f}s)"
    )

    dag_obj = load_dag(settings.dag_path, settings.workbook_path)
    formula_error_ids: set[str] = {
        n.id for n in dag_obj.nodes if n.type in ("formula", "error")
    }

    exit_code = 0

    # --- Path 1.1: recalc engine ---
    if not skip_engine:
        adapter, err_msg = _resolve_engine(engine, settings.libreoffice_path)
        if err_msg is not None:
            typer.echo(
                f"ERROR: Engine {engine!r} unavailable: {err_msg}", err=True
            )
            raise typer.Exit(code=2)
        assert adapter is not None  # guaranteed by _resolve_engine contract
        with tempfile.TemporaryDirectory(
            prefix="solar_cli_recalc_"
        ) as tmpdir:
            tmp = Path(tmpdir)
            result: RecalcResult = adapter.recalc(
                settings.workbook_path, tmp
            )
            if not result.ok:
                typer.echo(
                    f"ERROR: Recalc failed: {result.errors}", err=True
                )
                raise typer.Exit(code=2)

            typer.echo(
                f"Recalc complete: {result.wall_seconds:.1f}s"
                f" → {result.recalced_path}"
            )

            t0 = time.perf_counter()
            recalced_values = _load_recalced_values(
                result.recalced_path,  # ty: ignore[invalid-argument-type]
                formula_error_ids,
            )
            typer.echo(
                f"Loaded {len(recalced_values)} recalced values"
                f" ({time.perf_counter() - t0:.2f}s)"
            )

            mismatches: list[tuple[str, Scalar, Scalar]] = []
            for nid in sorted(formula_error_ids):
                v1_val = v1_values.values.get(nid)
                eng_val = recalced_values.get(nid)
                if not _scalars_match(v1_val, eng_val, rel, abs_t):
                    mismatches.append((nid, v1_val, eng_val))

            if mismatches:
                _print_mismatches(
                    mismatches, "Path 1.1: v1 vs recalc engine",
                )
                exit_code = 1
            else:
                typer.echo(
                    f"Path 1.1 CLEAN: {len(formula_error_ids)} formula+error"
                    " nodes match after recalc"
                )

    # --- Path 1.2: v2 vs v1 ---
    if not skip_v2:
        try:
            import importlib

            compute_v2 = importlib.import_module(
                "solar_v2.api"
            ).compute
        except (ImportError, ModuleNotFoundError) as exc:
            typer.echo(
                f"\nPath 1.2 SKIPPED: solar-v2 not available ({exc})"
                " — solar-v2 may be mid-rewrite.",
            )
        else:
            typer.echo("\n--- Path 1.2: v2 vs v1 ---")
            t0 = time.perf_counter()
            v2_values = compute_v2(settings)
            typer.echo(
                f"solar-v2: {len(v2_values.values)} values"
                f" ({time.perf_counter() - t0:.2f}s)"
            )

            v2_mismatches: list[tuple[str, Scalar, Scalar]] = []
            compared = 0
            for nid in sorted(v2_values.values.keys()):
                v1_val = v1_values.values.get(nid)
                v2_val = v2_values.values.get(nid)
                if v1_val is None:
                    continue
                compared += 1
                if not _scalars_match(v1_val, v2_val, rel, abs_t):
                    v2_mismatches.append((nid, v1_val, v2_val))

            missing_from_v2 = formula_error_ids - set(
                v2_values.values.keys()
            )
            if missing_from_v2:
                typer.echo(
                    f"WARNING: v2 missing {len(missing_from_v2)}"
                    f" formula/error nodes: {sorted(missing_from_v2)[:10]}..."
                )

            typer.echo(
                f"Path 1.2: compared {compared} inner-join nodes"
            )

            if v2_mismatches:
                _print_mismatches(
                    v2_mismatches, "Path 1.2: v2 vs v1",
                )
                exit_code = 1
            else:
                typer.echo(
                    "Path 1.2 CLEAN: all inner-join nodes match"
                )

    if not skip_engine and not skip_v2:
        if exit_code == 0:
            typer.echo("\nG4 gate: PASS (both paths clean)")
        else:
            typer.echo("\nG4 gate: FAIL")
    elif exit_code == 0:
        typer.echo("\nAll enabled paths: PASS")

    raise typer.Exit(code=exit_code)
