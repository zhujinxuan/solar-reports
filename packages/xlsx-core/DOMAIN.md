# DOMAIN.md — xlsx-core

Seed: see `docs/DOMAIN.md` (canonical). Realizes the **shared kernel** — no domain.

## Owns
- DAG model (frozen pydantic `DagNode`/`WorkbookDag`), the `dag.yaml` schema of record.
- `WorkbookLoader` port + `OpenpyxlLoader` adapter (formulas AND cached values).
- Formula tokenizer/parser → AST; `FormulaEvaluator` (function library: SUM, IF, INT,
  MIN, AND, MAX, SUMIF, IRR, NPV, AVERAGE, PMT; operators; ranges; cross-sheet refs;
  defined names; `#REF!`/error literals as first-class error values).
- Year-series detector (column-shifted identical formulas).
- `Settings` (pydantic-settings): workbook path, dag paths, tolerances, engine choice.
- `RecalcEngine` port + adapters (LibreOffice headless / formulas pkg / Excel COM).
  Benchmark outcome (dag/recalc_benchmark.json, JOURNAL 2026-07-25): **excel-com
  is the winner** (0/5059 mismatches, 9.6s) and the `Settings.recalc_engine`
  default; LibreOffice works but needs the xlsx→ods→xlsx two-step for recalculated
  values (2/5059, 77s); formulas-pkg cannot evaluate this workbook class.

## DI
Exposes ports + adapters; consumed by solar-v1, solar-v2, apps. No upward imports.
