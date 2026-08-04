"""solar-cli — typer CLI for the consume-xlsx-as-software toolchain.

Commands:
  extract   — workbook → dag/solar.dag.yaml (xlsx-core)
  compute   — run solar-v1 or solar-v2, dump node values
  verify    — three-way golden check: v1 vs recalc engine, v2 vs v1

Global option:
  --config PATH  — TOML config file overriding Settings defaults.
                   Precedence: CLI option > TOML > XLSX_ env > default.
"""

from __future__ import annotations

import csv
import json
import tempfile
import time
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

if TYPE_CHECKING:
    from solar_v2.inputs import ModelInputs


import openpyxl
import typer
from xlsx_core.extract import extract_dag, write_dag_yaml
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

# TOML config: valid Settings keys (mapping TOML key → Settings field).
# Keys NOT in this set are rejected with a clear error listing valid ones.
_VALID_TOML_KEYS: frozenset[str] = frozenset({
    "workbook_path",
    "dag_path",
    "dag_v2_path",
    "rel_tol",
    "abs_tol",
    "recalc_engine",
    "libreoffice_path",
    "inputs_toml",
})

# TOML keys whose string values are resolved as Paths relative to the
# config file's parent directory.
_PATH_KEYS: frozenset[str] = frozenset({
    "workbook_path",
    "dag_path",
    "dag_v2_path",
    "libreoffice_path",
    "inputs_toml",
})

# Context object key for the base Settings (post-TOML, pre-CLI-overrides).
_CTX_SETTINGS_KEY = "settings"


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


def _load_toml_config(config_path: Path) -> dict[str, object]:
    """Load and validate a TOML config file.

    Returns a dict of Settings field overrides with Path keys resolved
    relative to the config file's parent directory.
    """
    if not config_path.exists():
        typer.echo(f"Config file not found: {config_path}", err=True)
        raise typer.Exit(code=2)

    try:
        with open(config_path, "rb") as f:
            data: dict[str, object] = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        typer.echo(f"Invalid TOML in {config_path}: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    # Allow "inputs" as a non-Settings key (handled by ModelInputs.from_toml)
    settings_keys = set(data.keys()) - {"inputs"}
    unknown = settings_keys - _VALID_TOML_KEYS
    if unknown:
        typer.echo(
            f"Unknown config key(s): {', '.join(sorted(unknown))}. "
            f"Valid keys: {', '.join(sorted(_VALID_TOML_KEYS))}",
            err=True,
        )
        raise typer.Exit(code=2)

    config_dir = config_path.parent.resolve()
    result: dict[str, object] = {}
    for key, value in data.items():
        if key == "inputs":
            continue  # handled by _load_model_inputs_from_toml
        if key in _PATH_KEYS and isinstance(value, str):
            result[key] = (config_dir / value).resolve()
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# callback — global --config
# ---------------------------------------------------------------------------


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="Path to TOML config file",
            exists=False,  # we handle existence in _load_toml_config
        ),
    ] = None,
) -> None:
    """solar-cli — consume-xlsx-as-software toolchain CLI.

    Precedence: CLI option > TOML config > XLSX_ env var > default.
    """
    ctx.ensure_object(dict)

    if config is not None:
        toml_overrides = _load_toml_config(config)
        # Base: env > default, then TOML overrides on top.
        base_kwargs = Settings().model_dump()
        base_kwargs.update(toml_overrides)
        ctx.obj[_CTX_SETTINGS_KEY] = Settings(**base_kwargs)
        ctx.obj["_config_path"] = config
    else:
        ctx.obj[_CTX_SETTINGS_KEY] = Settings()


def _build_settings(
    base: Settings | None = None,
    workbook: Path | None = None,
    dag: Path | None = None,
    rel_tol: float | None = None,
    abs_tol: float | None = None,
    engine: str | None = None,
    libreoffice_path: Path | None = None,
) -> Settings:
    """Build final Settings: CLI overrides on top of base (or defaults).

    When `base` is supplied (from ctx.obj), it already includes TOML >
    env > default.  CLI overrides are layered on top.
    """
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

    if overrides:
        if base is not None:
            kwargs = base.model_dump()
            kwargs.update(overrides)
            return Settings(**kwargs)
        return Settings(**overrides)  # ty: ignore[invalid-argument-type]
    if base is not None:
        return base
    return Settings()


def _resolve_engine(
    name: str, libreoffice_path: Path,
) -> tuple[RecalcEngine | None, str | None]:
    """Resolve an engine name to an adapter instance.

    Returns (adapter, None) on success or (None, error_message) on failure.
    """
    if name == "excel-com":
        try:
            return ExcelComRecalc(), None
        except Exception as exc:
            return None, str(exc)
    if name == "libreoffice":
        if not libreoffice_path.exists():
            return None, (
                f"LibreOffice not found at {libreoffice_path}. "
                "Set XLSX_LIBREOFFICE_PATH or libreoffice_path in config."
            )
        return LibreOfficeRecalc(libreoffice_path), None
    if name == "formulas-pkg":
        return FormulasPkgRecalc(), None
    return (
        None,
        f"Unknown engine {name!r}. Valid: excel-com, libreoffice, formulas-pkg",
    )


def _print_mismatches(
    mismatches: list[tuple[str, Scalar, Scalar]],
    label: str,
    max_show: int = 20,
) -> None:
    """Print mismatch summary."""
    typer.echo(f"\n{label}: {len(mismatches)} MISMATCH(ES)")
    for nid, expected, got in mismatches[:max_show]:
        typer.echo(f"  {nid}: expected={expected!r}, got={got!r}")
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
    ctx: typer.Context,
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
    base: Settings = ctx.obj[_CTX_SETTINGS_KEY]
    settings = _build_settings(base, workbook=workbook, dag=dag)
    t0 = time.perf_counter()
    dag_obj = extract_dag(settings)
    write_dag_yaml(dag_obj, settings.dag_path)
    elapsed = time.perf_counter() - t0
    typer.echo(
        f"Extracted {len(dag_obj.nodes)} nodes to {settings.dag_path}"
    )
    typer.echo(f"Elapsed: {elapsed:.2f}s")


@app.command()
def compute(
    ctx: typer.Context,
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
    flat: Annotated[
        bool,
        typer.Option(
            "--flat",
            help="Output flat {node_id: value} via v2_benchmark projection (v2 only)",
        ),
    ] = False,
) -> None:
    """Compute node values via solar-v1 or solar-v2.

    v1: interpret the DAG (flat node_id→value map).
    v2: run the domain engine (domain-structured JSON by default; --flat for
    node_id→value via v2_benchmark.projection).
    """
    if version not in ("v1", "v2"):
        typer.echo(f"Invalid --version: {version!r}. Use v1 or v2.", err=True)
        raise typer.Exit(code=1)

    base: Settings = ctx.obj[_CTX_SETTINGS_KEY]
    settings = _build_settings(base, workbook=workbook, dag=dag)
    t0 = time.perf_counter()

    if version == "v1":
        from solar_v1.api import compute as compute_v1

        node_values = compute_v1(settings)
        elapsed = time.perf_counter() - t0
        count = len(node_values.values)

        if out is not None:
            _write_node_values(node_values, out)
            typer.echo(
                f"Wrote {count} node values to {out} ({elapsed:.2f}s)"
            )
        else:
            typer.echo(
                f"Computed {count} node values via solar-v1 ({elapsed:.2f}s)"
            )
    else:
        # --- v2: domain engine ---
        try:
            from solar_v2.engine import compute_model
            from solar_v2.inputs import ModelInputs
        except ImportError as exc:
            typer.echo(
                f"solar-v2 not available ({exc}) — mid-rewrite. Use v1.",
                err=True,
            )
            raise typer.Exit(code=1) from exc

        # Load ModelInputs from TOML config if --config was given
        config_path: Path | None = ctx.obj.get("_config_path")
        if config_path is not None:
            inputs = _load_model_inputs_from_toml(config_path)
        else:
            inputs = ModelInputs()

        results = compute_model(inputs)
        elapsed = time.perf_counter() - t0

        if flat:
            from v2_benchmark.projection import project as project_v2

            dag_path = str(settings.dag_path)
            flat_values = project_v2(results, dag_path=dag_path)
            if out is not None:
                _write_flat_values(flat_values, out)
                typer.echo(
                    f"Wrote {len(flat_values)} node values to {out} ({elapsed:.2f}s)"
                )
            else:
                typer.echo(json.dumps(flat_values, ensure_ascii=False, indent=2))
                typer.echo(
                    f"\nComputed {len(flat_values)} node values via solar-v2 "
                    f"engine ({elapsed:.2f}s)"
                )
        else:
            domain_json = _model_results_to_json(results)
            if out is not None:
                out.parent.mkdir(parents=True, exist_ok=True)
                with open(str(out), "w", encoding="utf-8") as f:
                    json.dump(domain_json, f, ensure_ascii=False, indent=2)
                typer.echo(
                    f"Wrote domain results to {out} ({elapsed:.2f}s)"
                )
            else:
                typer.echo(json.dumps(domain_json, ensure_ascii=False, indent=2))
                typer.echo(
                    f"\nComputed 9-domain model via solar-v2 engine ({elapsed:.2f}s)"
                )


@app.command()
def verify(
    ctx: typer.Context,
    engine: Annotated[
        str | None,
        typer.Option(
            "--engine",
            help="Recalc engine for path 1.1: excel-com | libreoffice | formulas-pkg",
        ),
    ] = None,
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
    base: Settings = ctx.obj[_CTX_SETTINGS_KEY]
    settings = _build_settings(
        base,
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
        engine_name = settings.recalc_engine
        adapter, err_msg = _resolve_engine(
            engine_name, settings.libreoffice_path
        )
        if err_msg is not None:
            typer.echo(
                f"ERROR: Engine {engine_name!r} unavailable: {err_msg}",
                err=True,
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

    # --- Path 1.2: v2 engine vs v1 ---
    if not skip_v2:
        try:
            from solar_v2.engine import compute_model
            from solar_v2.inputs import ModelInputs
            from v2_benchmark.compare import diff as diff_v2
            from v2_benchmark.compare import format_report
            from v2_benchmark.projection import project as project_v2
        except ImportError as exc:
            typer.echo(
                f"\nPath 1.2 SKIPPED: solar-v2 not available ({exc})"
                " — solar-v2 may be mid-rewrite.",
            )
        else:
            typer.echo("\n--- Path 1.2: v2 engine vs v1 ---")
            t0 = time.perf_counter()

            # Load ModelInputs from TOML config if --config was given
            config_path: Path | None = ctx.obj.get("_config_path")
            if config_path is not None:
                inputs = _load_model_inputs_from_toml(config_path)
            else:
                inputs = ModelInputs()

            results = compute_model(inputs)
            dag_path = str(settings.dag_path)
            projected = project_v2(results, dag_path=dag_path)
            typer.echo(
                f"solar-v2 engine: {len(projected)} projected nodes"
                f" ({time.perf_counter() - t0:.2f}s)"
            )

            # Compare vs v1: use compare.diff
            v1_dict = dict(v1_values.values)
            diffs = diff_v2(projected, v1_dict, rel_tol=rel)

            typer.echo(
                f"Path 1.2: {len(projected)} projected nodes, "
                f"{len(diffs)} differences"
            )

            if diffs:
                typer.echo(format_report(diffs))
                exit_code = 1
            else:
                typer.echo(
                    "Path 1.2 CLEAN: all projected nodes match v1"
                )

    if not skip_engine and not skip_v2:
        if exit_code == 0:
            typer.echo("\nG4 gate: PASS (both paths clean)")
        else:
            typer.echo("\nG4 gate: FAIL")
    elif exit_code == 0:
        typer.echo("\nAll enabled paths: PASS")

    raise typer.Exit(code=exit_code)


# ---------------------------------------------------------------------------
# v2 engine helpers
# ---------------------------------------------------------------------------


def _load_model_inputs_from_toml(config_path: Path) -> ModelInputs:
    """Extract ModelInputs from a TOML config that may mix Settings keys.

    Uses ``ModelInputs.from_toml``, but handles the case where the TOML
    file has both top-level Settings keys and an ``[inputs]`` table by
    extracting only the ``[inputs]`` section.
    """
    from solar_v2.inputs import ModelInputs

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))

    # If file has both [inputs] and other top-level keys, extract [inputs]
    if "inputs" in raw:
        inputs_raw = raw["inputs"]
    else:
        # Filter to only ModelInputs field names (ignore Settings keys)
        valid = set(ModelInputs.model_fields.keys())
        inputs_raw = {k: v for k, v in raw.items() if k in valid}

    if not inputs_raw:
        return ModelInputs()

    # Coerce types matching ModelInputs.from_toml
    return _coerce_and_build_inputs(inputs_raw, ModelInputs)


def _coerce_and_build_inputs(
    inputs_raw: dict[str, object],
    cls: type[ModelInputs],
) -> ModelInputs:
    """Coerce TOML values to ModelInputs field types and construct."""
    from solar_v2.inputs import ModelInputs
    coerced: dict[str, float | int | bool | tuple[float, ...] | str] = {}
    for key, val in inputs_raw.items():
        if key == "western_dev_preferential" and isinstance(val, str):
            # "是" → True, "否" → False
            s = val.strip()
            if s == "是":
                coerced[key] = True
            elif s == "否":
                coerced[key] = False
            else:
                raise ValueError(
                    f"western_dev_preferential must be '是' or '否', got {val!r}"
                )
        elif key in ModelInputs._FLOAT_FIELDS and isinstance(val, int):
            coerced[key] = float(val)
        elif key in (
            "degradation_factor",
            "load_rate",
            "repair_rate_series",
        ) and isinstance(val, list):
            coerced[key] = tuple(float(v) for v in cast(list[float | int], val))
        else:
            coerced[key] = cast(float | int | bool | str, val)

    return cls.model_validate(coerced)


def _model_results_to_json(results: object) -> dict[str, object]:
    """Serialize ModelResults to domain-structured JSON dict.

    Returns a dict with ``version``, one key per domain (params, invest,
    debt, cost, pnl, cashflow, finplan, balance, valuation), and
    ``headline`` scalars.  Each domain has ``key``, ``sheet``, ``label``,
    ``years``, and ``items`` (each with ``key``, ``label``, ``unit``,
    ``formula``, ``kind``, and ``value`` or ``values``).
    """
    from solar_v2.schema import all_domains

    schemas = all_domains()
    domains: dict[str, object] = {}

    for ds in schemas:
        domain_result = getattr(results, ds.key)
        years = _get_domain_years(domain_result)
        items: list[dict[str, object]] = []

        for item_schema in ds.items:
            entry: dict[str, object] = {
                "key": item_schema.key,
                "label": item_schema.label,
                "unit": item_schema.unit,
                "formula": item_schema.formula,
                "kind": item_schema.kind,
            }
            if item_schema.kind == "scalar":
                scalars = getattr(domain_result, "scalars", None)
                value = _read_scalar_value(scalars, domain_result, item_schema.key)
                entry["value"] = value
            else:
                frame = getattr(domain_result, "frame", None)
                if frame is not None and item_schema.key in frame.columns:
                    series = frame[item_schema.key]
                    vals: list[object] = []
                    for v in series.to_list():
                        if isinstance(v, float) and (
                            v != v or v == float("inf") or v == float("-inf")
                        ):
                            vals.append(None)
                        else:
                            vals.append(v)
                    entry["values"] = vals
                else:
                    entry["values"] = None
            items.append(entry)

        domains[ds.key] = {
            "key": ds.key,
            "sheet": ds.sheet,
            "label": ds.label,
            "years": years,
            "items": items,
        }

    return {
        "version": "v2",
        **domains,
        "headline": {
            "equity_irr": getattr(results, "equity_irr", None),
            "project_irr_after_tax": getattr(results, "project_irr_after_tax", None),
            "equity_npv": getattr(results, "equity_npv", None),
            "project_npv_after_tax": getattr(results, "project_npv_after_tax", None),
            "equity_sale_price": getattr(results, "equity_sale_price", None),
        },
    }

def _read_scalar_value(
    scalars: object | None,
    domain_result: object,
    key: str,
) -> object:
    """Read a scalar value with suffix fallback for key mismatches."""
    if scalars is not None:
        if hasattr(scalars, key):
            return getattr(scalars, key)
        for suffix in ("_after_tax", "_pre_tax", "_total", "_pct"):
            alt = key + suffix
            if hasattr(scalars, alt):
                return getattr(scalars, alt)
    if hasattr(domain_result, key):
        return getattr(domain_result, key)
    return None


def _get_domain_years(domain_result: object) -> list[int]:
    """Extract calendar years from a domain result."""
    years = getattr(domain_result, "years", None)
    if years is not None:
        return list(years)
    periods = getattr(domain_result, "periods", None)
    if periods is not None:
        return list(periods)
    for attr in ("income", "frame"):
        frame = getattr(domain_result, attr, None)
        if frame is not None and "year" in frame.columns:
            return [int(y) for y in frame["year"].to_list()]
    return []


def _write_node_values(node_values: object, out: Path) -> None:
    """Write NodeValues to a JSON or CSV file."""
    from xlsx_core.model import ErrorValue

    plain: dict[str, object] = {}
    vals: object = getattr(node_values, "values", None)
    if vals is None or not isinstance(vals, dict):
        raise TypeError("Expected NodeValues with .values dict")
    vals_dict: dict[str, object] = cast(dict[str, object], vals)
    for k, v in vals_dict.items():
        if isinstance(v, ErrorValue):
            plain[k] = v.error
        else:
            plain[k] = v
    out_str = str(out)
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


def _write_flat_values(values: dict[str, float | str], out: Path) -> None:
    """Write flat {node_id: value} dict to a JSON or CSV file."""
    out_str = str(out)
    if out_str.endswith(".csv"):
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out_str, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["node_id", "value"])
            for k, v in values.items():
                writer.writerow([k, v])
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out_str, "w", encoding="utf-8") as f:
            json.dump(values, f, ensure_ascii=False, indent=2)


