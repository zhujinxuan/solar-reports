# DOMAIN.md — solar-v1

Realizes **all bounded contexts at cell resolution** by interpreting
`dag/solar.dag.yaml` — the ACL-bound faithful translation. Node ids stay
`sheet!cell`; no domain renaming happens here.

## Owns
- `interpret(dag, settings) -> NodeValues`: topological evaluation of every node via
  xlsx-core's parser/evaluator. Literal nodes → cached value; error-typed nodes →
  their ErrorValue (no re-evaluation — their formula may contain deleted refs that
  diverge from blank-cell semantics); formula nodes → parsed + evaluated.
  Blank referenced cells → 0.0. Internal `_SheetAwareResolver` wraps the evaluator's
  `CellResolver` protocol with current-sheet context for same-sheet references.
- `golden_check(values, dag, settings) -> GoldenReport`: compare interpreted values
  against workbook cached values on ALL formula + error nodes (G1).
- `load_dag(dag_path, workbook_path) -> WorkbookDag`: YAML loader that augments
  the dag with defined names from the workbook (xlsx-core's `_write_dag_yaml` omits
  them).
- `compute(settings) -> NodeValues`, `verify(settings) -> GoldenReport`: thin
  stable façade for apps.

## DI
- Consumes `xlsx_core.model` (DagNode, WorkbookDag, NodeValues, ErrorValue, Scalar).
- Consumes `xlsx_core.parser` (parse, ParseError).
- Consumes `xlsx_core.evaluator` (Evaluator, CellResolver Protocol).
- Consumes `xlsx_core.loader` (load_workbook — for defined names only).
- Consumes `xlsx_core.settings` (Settings).
- Consumes `xlsx_core.ast` (CellRef, RangeRef, DefinedName, BinaryOp, UnaryOp,
  FuncCall, _col_to_letters).
- Exposes `NodeValues` and `GoldenReport` to apps/cli + apps/server, and to G2
  comparison in solar-v2 verification.

## xlsx-core gaps filled
- `solar_v1.dag_loader.load_dag()` — reads dag.yaml and enriches with workbook
  defined names. xlsx-core's extract.py writes dag to YAML but `_write_dag_yaml`
  omits `defined_names`; there is no public `load_dag` function upstream.
  This loader exists as `packages/solar-v1/src/solar_v1/dag_loader.py`.
