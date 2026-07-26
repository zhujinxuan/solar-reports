# DOMAIN.md — solar-cli

Seed: see `docs/DOMAIN.md` (canonical). Composition root for command-line use.

## Commands

### `extract` — workbook → DAG YAML
Options: `--workbook`, `--dag` (defaults from `xlsx_core.settings.Settings`).
Calls `xlsx_core.extract.extract_dag`, writes `dag/solar.dag.yaml`.

### `compute` — evaluate node values
Options: `--version v1|v2` (required), `--workbook`, `--dag`, `--out` (json/csv by extension; stdout summary if omitted).
Calls `solar_v1.api.compute` or `solar_v2.api.compute`, writes/prints NodeValues.

### `verify` — G4 golden gate
Options:
- `--engine excel-com|libreoffice|formulas-pkg` (default: `Settings.recalc_engine`)
- `--workbook`, `--dag`, `--rel-tol`, `--abs-tol`
- `--skip-engine` — skip path 1.1
- `--skip-v2` — skip path 1.2

Path 1.1: recalc workbook via engine adapter → compare solar-v1 NodeValues
against recalced workbook values on every formula+error node.

Path 1.2: compare solar-v2 `compute()` vs solar-v1 `compute()`
inner-join on v2's claimed node ids.

Exit codes: 0 = all enabled paths clean; 1 = diffs found (first ~20 printed);
2 = required engine unavailable.

## DI wiring
All paths, tolerances, and engine choice come from `xlsx_core.settings.Settings`,
overridable via CLI options and env vars (`XLSX_` prefix). No logic lives here — wiring only.

## Testing
`typer.testing.CliRunner` integration tests in `tests/test_main.py`.
Excel COM tests (`test_verify_path1_excel_com`) use import-only guards
(no COM Dispatch probe — sequential Dispatch/Quit cycles corrupt COM state).
