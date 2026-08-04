# DOMAIN.md — canonical shared domain design

Canonical DDD + DI design for the whole workspace. Package-level `DOMAIN.md` files
describe each package's *realization* of this design and may diverge as versions
evolve; this file is the shared reference they start from.

Source of domain knowledge: `data/附件4：平价上网光伏发电项目经济评价模型（第7.1版）.xlsx`
(solar, v7.1) and `data/附件2：平价及竞价上网风电项目经济评价模型（第3版）.xlsx`
(wind, v3 — structurally identical, used as portability check).

## Bounded contexts

| Context | Sheet(s) | Role |
|---|---|---|
| **ProjectParameters** | 参数表 | Upstream supplier to everything. NOTE: inputs are not pure data — cells may be formulas (`=C9+C11`, `=100%*0.95`), so "input" means *given or derived-from-givens*, not *literal*. |
| **InvestmentPlanning** | 投资计划 | Capex schedule over construction years. |
| **Cost** | 成本 | Operating cost series. |
| **DebtService** | 还贷 | Loan drawdown/repayment schedule. |
| **CashFlow** | 现金流量 | Project/equity cash flows; feeds IRR/NPV. |
| **BalanceSheet** | 资产负债 | Annual balance sheet. |
| **FinancialPlan** | 财务计划 | Financing plan. |
| **PnL** | 损益 | Revenue, taxes, profit series. |
| **Valuation** | 估值结果 + 指标汇总 | Downstream consumer; the verification contract. |

### Context map

```
ProjectParameters ──(supplier)──> InvestmentPlanning, Cost, DebtService, PnL
InvestmentPlanning, Cost, DebtService, PnL ──> CashFlow, BalanceSheet, FinancialPlan
CashFlow, PnL, ... ──(conformist)──> Valuation
```

- ProjectParameters is an **open host / supplier**; everything conforms to its parameter vocabulary.
- Valuation is a **downstream conformist** — it must not redefine terms, only aggregate.
- Cross-context references in the workbook are raw cell refs (`=参数表!$C$38`); in software they become typed value objects passed through ports.

## Anti-corruption layer (ACL)

The **formula parser + evaluator** is the ACL between xlsx-speak and domain-speak:

- xlsx-speak: cell addresses (`损益!G8`), defined names (`增值税率`, `所得税率`, `装机容量`, `总投资`, … — filter junk names like `aa`, `b`, `i`, `j`), functions (`IF`, `SUM`, `IRR`, …), year-column iteration.
- domain-speak: named value objects and year-series (`AnnualRevenue`, `VatRate`, `InstalledCapacity`).

- **solar-v1 lives entirely behind the ACL**: it is a faithful interpreter; node ids stay cell addresses.
- **solar-v2 is the distilled domain model**: ACL output is lifted into domain objects, year-series become polars frames with readable names, and `dag.yaml`'s `code_ref` documents where each original cell landed.

## Year-series (ubiquitous language)

Calc sheets iterate years across columns (e.g. `损益!G8=G5*G7`, `H8=H5*H7`, …; year
headers sourced from `参数表` row 4, 2020→). A column-shifted identical formula is ONE
domain concept over a year axis, not N nodes of logic. Software MUST model these as
polars series keyed by year; per-cell nodes exist only in the extracted dag.yaml as
provenance.

## DI design

Ports & adapters, plain constructor injection — no DI framework (boring > clever).

```
ports (Protocols):  WorkbookLoader, DagStore, FormulaEvaluator, RecalcEngine
adapters:           OpenpyxlLoader, YamlDagStore, PolarsVectorEvaluator,
                    LibreOfficeRecalc | FormulasPkgRecalc | ExcelComRecalc  (path 1.1, empirical pick)
settings:           pydantic-settings Settings — paths, tolerances, engine choice,
                    all env/CLI overridable, nothing hardcoded
composition root:   each app's bootstrap.py wires adapters → ports → use cases
```

Per-package `DOMAIN.md` records: which contexts the package realizes, which ports it
consumes/exposes, and any deviation from this canonical design.

## Cross-package contracts (settled 2026-07-25; subagents MUST conform)

### dag.yaml node schema (xlsx-core is the schema of record)

```yaml
version: 1
source: <workbook path relative to repo root>
nodes:
  - id: "损益!G8"            # canonical "<sheet>!<A1>"
    sheet: "损益"
    col: "G"                 # column letters
    row: 8
    type: formula | literal | error
    expression: "G5*G7"      # formula text WITHOUT leading '='; null for literal
    value: 123.45            # cached value; for type=error the error string ("#REF!")
    year_series: null        # or {key: "<sheet>!row<row>:<concept>", index: <int>} when detected
```

- EVERY non-blank cell becomes a node. `type=error` when the expression contains an
  error literal (`#REF!` etc.) or the cached value is an Excel error — never coerce.
- Node `value` is the workbook cached value (openpyxl `data_only=True`) — G1's oracle.

### NodeValues contract (v1 and the v2 benchmark harness)

`NodeValues` = frozen pydantic model wrapping an immutable mapping `values: dict[node_id, Scalar]`
where `Scalar = int | float | str | bool | None | ErrorValue`. `ErrorValue` carries the
error string (e.g. `#REF!`). solar-v1 exposes `compute(...) -> NodeValues` over all dag
nodes; solar-v2's test-side `v2_benchmark.projection` produces the same mapping from
the engine's typed `ModelResults`.

### v2 engine contract (v2-rebuild, 2026-07-26)

solar-v2 is a standalone domain engine: `solar_v2.engine.compute_model(ModelInputs) ->
ModelResults` — per-domain polars frames + typed scalars, zero I/O, no dag/xlsx-core
imports, no cell identity. Cell identity lives ONLY in the test-side
`v2_benchmark` (layout/projection/compare). G2 = project(ModelResults) vs solar-v1's
NodeValues, set-join on node id + value compare (numbers rel tol 1e-6; errors
error-for-error). See packages/solar-v2/DOMAIN.md for the full architecture.

### RecalcEngine port (path 1.1)

```python
class RecalcEngine(Protocol):
    name: str
    def recalc(self, workbook: Path, out_dir: Path) -> RecalcResult: ...
```

`RecalcResult` = frozen model: recalculated workbook path (or values map), wall time,
per-engine error. Adapters: `LibreOfficeRecalc` (soffice headless),
`FormulasPkgRecalc` (`formulas` package), `ExcelComRecalc` (pywin32 COM). Winner is
chosen empirically (accuracy vs cached values + wall time) and stored in Settings.
