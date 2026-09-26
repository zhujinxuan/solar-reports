# JOURNAL.md — experiment timeline

Append-only. Every non-trivial attempt (success or failure) gets an entry BEFORE moving on.
Format per AGENTS.md. Learnings that generalize get promoted to AGENTS.md / DOMAIN.md.

## 2026-07-25 · project-setup
- Hypothesis: the solar workbook can be turned into software via extract → interpret → distill.
- Action: inspected both workbooks (sheet structure, formulas, defined names); settled workspace layout, DDD contexts, DI design, three-way golden check; wrote AGENTS.md + docs/DOMAIN.md.
- Outcome: 10 sheets each, same names; year-column formula iteration confirmed (损益!G8=G5*G7…); defined names 增值税率/所得税率/… plus junk names; `#REF!` present in 损益!D4. Deps installed via uv. `/goal` not found in OMP docs or user config.
- Learning: "input sheet = pure data" is FALSE — 参数表 mixes literals and formulas; interpreter must evaluate inputs too. Year-series (column-shifted identical formulas) is the core simplification axis.
- Learning: goal-writing format for this user — (1) explicit shall-NOT list, (2) result to achieve, (3) verification gates. Wind workbook dropped from the goal (portability check deferred to a later goal).

## 2026-07-25 · workspace-scaffold
- Hypothesis: a uv workspace with 5 members (xlsx-core, solar-v1, solar-v2, cli, server) can host the whole goal with clean gates.
- Action: moved workbooks to `data/`; created packages/apps skeletons (hatchling src layout, workspace sources); seeded per-package DOMAIN.md; appended cross-package contracts (dag.yaml schema, NodeValues, code_ref, RecalcEngine port) to docs/DOMAIN.md; root ruff/ty/pytest config.
- Outcome: `uv sync` OK; all 5 import packages load; `uv run ruff check` + `uv run ty check` green on empty skeleton. Workbook inventory: 5119 formula cells, 0 uncached, 4 error cells (损益!D4/E4, 财务计划!U36/AD36); function vocabulary = SUM/IF/INT/MIN/AND/MAX/SUMIF/IRR/NPV/AVERAGE/PMT; no external refs; iterate=None (no circular calc); 20 defined names (7 junk); fullCalcOnLoad=True. LibreOffice found at C:/Program Files/LibreOffice/program/soffice.exe; MS Office dir is a Store stub (COM likely dead — benchmark will confirm).
- Learning: fullCalcOnLoad=True means a LibreOffice headless convert SHOULD recalculate — but "should" needs a perturbation test to prove.

## 2026-07-25 · recalc-benchmark-wave1
- Hypothesis: LibreOffice headless would be the most accurate recalc engine for the SOLAR workbook.
- Action: built three RecalcEngine adapters in xlsx_core/recalc/ (LibreOfficeRecalc, FormulasPkgRecalc, ExcelComRecalc); benchmarked all against the original cached values on 5059 formula cells (scripts/benchmark_recalc.py → dag/recalc_benchmark.json).
- Outcome: **excel-com 0/5059 mismatches in 9.6s**; libreoffice 2/5059 in 77.1s; formulas-pkg 5059/5059 (parses the workbook but `.calculate()` leaves every formula cell unresolved — cannot handle cross-sheet refs/defined names/financial functions here). Excel COM works: real Office 16.0 is installed despite the Store-stub-looking directory. Perturbation proof: 参数表!C3 1145→1155 moved downstream values through the LO xlsx→ods→xlsx two-step (LO's direct xlsx export writes empty <v/> for recalculated cells; OOXMLRecalcMode=0 profile + ODS intermediate required).
- Learning: benchmark winner = **excel-com**, set as `Settings.recalc_engine` default. LibreOffice stays as fallback adapter. The `formulas` package is a dead end for this workbook class — don't retry it for wind either. Never trust `--convert-to` to recalc without a perturbation test; LO needs the two-step or profile setting. **→ promoted to AGENTS.md (recalc engines) + xlsx-core/DOMAIN.md**

## 2026-07-25 · xlsx-core-kernel-wave1
- Hypothesis: a hand-written Pratt parser + evaluator can reproduce every formula cell of the SOLAR workbook exactly (0 mismatches vs cached values).
- Action: built xlsx-core kernel — regex tokenizer (0.18s/5059 formulas), Pratt parser (CJK/quoted sheet names, ranges, % postfix, error literals), evaluator (all 11 functions: SUM/IF/INT/MIN/AND/MAX/SUMIF/IRR/NPV/AVERAGE/PMT), R1C1 canonicalizer, year-series detector, dag extractor; topological full-workbook eval vs cached.
- Outcome: **0 mismatches across 5054 formulas + 5 error nodes reproduced error-for-error** (0.5s eval). dag/solar.dag.yaml: 6560 nodes (1501 literal, 5054 formula, 5 error: 损益!D4/E4 #REF!, 财务计划!E36/U36/AD36 #REF!+#DIV/0!), 208 year-series covering 4705 nodes. Gates: ruff/ty clean, 75 tests green.
- Learning: 1) `#REF!` literals appear inline in formula text (openpyxl's deleted-ref replacement) — the parser must accept them as error tokens. 2) Blank referenced cell = 0.0 in numeric context, not None. 3) R1C1 canonicalization IS year-series detection: column-shifted identical formulas share one R1C1 string. 4) IRR needs overflow guards in NPV denominators. 5) Defined names must be expanded in the dependency graph for correct topo order.

## 2026-07-26 · solar-v1-interpreter
- Hypothesis: solar-v1 can interpret dag/solar.dag.yaml with 0 mismatches vs cached values via dep-graph + topo sort + xlsx-core evaluator.
- Action: built packages/solar-v1 (dag_loader, interpreter, golden, api). Kahn topo sort over AST refs incl. cross-sheet + defined-name expansion; _SheetAwareResolver for bare refs; error-typed nodes reproduce their cached ErrorValue instead of re-evaluating.
- Outcome: **G1 GREEN — 0/5059 mismatches** (5054 formula + 5 error), rel tol 1e-6. 18 tests pass; ruff/ty clean.
- Learning: 1) xlsx-core's dag.yaml omits defined_names — a YAML dag loader must bridge them from the workbook snapshot (solar_v1.dag_loader.load_dag). 2) Error-typed nodes MUST reproduce the cached error, not re-evaluate: their expressions reference deleted cells, and blank-cell-to-0 semantics would wrongly resolve them (财务计划!E36: IF(D28+E28=0,0,…) with blank D28/E28 → 0 ≠ #REF!). **→ promoted to AGENTS.md (error type follows cached value)**

## 2026-07-26 · solar-v2-clone-attempt-REJECTED
- Hypothesis (subagent's): solar-v2 could "distill" by reusing the evaluator.
- Action: first SolarV2 delivery made api.py compute() a clone of the v1 interpreter (xlsx_core.parser/Evaluator in the compute path), with domain naming only in the annotated dag.
- Outcome: REJECTED before acceptance — violates the goal ("Do NOT translate cell-by-cell in solar-v2", "DDD-distilled polars implementation") and makes G2 vacuous (same engine diffing itself). Sent back for a real polars domain rewrite.
- Learning: a golden diff of 0 proves nothing when both sides share the engine — G2's value depends on v2 being an INDEPENDENT computation path. When delegating distillation, "no parser/evaluator imports in the compute path" must be verified by grep, not by the agent's summary. **→ promoted to AGENTS.md (distillation verification)**

## 2026-07-26 · apps-cli-wave3
- Hypothesis: a typer CLI (solar-cli extract/compute/verify) can be built against the settled contract surfaces.
- Action: solar_cli/main.py with extract (→ extract_dag), compute (v1|v2, json/csv), verify (path 1.1 engine-recalc vs v1; path 1.2 v2 vs v1 inner join); 9 CliRunner tests; importlib-based graceful skip while v2 is rebuilt.
- Outcome: **G4 path 1.1 GREEN**: `uv run solar-cli verify --engine excel-com` exits 0 — 5059 nodes match after Excel COM recalc vs v1. 9/9 tests pass; ruff/ty clean.
- Learning: 1) Excel COM sequential create/destroy corrupts COM state (RPC_E_CALL_REJECTED) — test guards must be import-only, never Dispatch-probe. 2) importlib.import_module in try/except keeps both ty and runtime happy for temporarily-missing packages.

## 2026-07-26 · apps-server-wave3
- Hypothesis: FastAPI backend can serve compute (v1/v2) and two-path verify behind frozen pydantic schemas.
- Action: solar_server/{schemas,verify,main}.py; lru_cache on (version, workbook, dag) frozen key; def endpoints for threadpool; ScalarJSON union (ErrorMarker, ISO datetimes); 422/503 handling; 15 tests.
- Outcome: 15 tests green; uvicorn boots, /health answers; engine-backed path 1.1 = 0/5059.
- Learning: openpyxl iter_rows hits MergedCell lacking column_letter — guard with hasattr. v2 compute dominated test time (~57s) when it re-extracted the dag — the new pipeline architecture removes that.

## 2026-07-26 · solar-v2-restructure
- Hypothesis: per-sheet slices against a fixed unit-schedule architecture succeed where whole-workbook distillation failed twice (interpreter clone, then cached-value lookup).
- Action: REJECTED the second clone (it read cached values and relabeled them — worse than the first). Wiped solar-v2, built the skeleton inline: static unit schedule (305 steps from unit-level topo sort; only 8 SCCs, all intra-sheet), pipeline + ValueView, typed Params (参数表 distilled by hand), param_steps + invest.py exemplar (both oracle-verified 0-diff), oracle test harness. Fan out 7 per-sheet slices with grep-enforced "no parser/evaluator/cached reads in compute path".
- Outcome: exemplar green: 参数表 + 投资计划 reproduce every cached node through real domain code (2/2 tests). 7 slices dispatched. Fixed en route: Excel column letters are not contiguous ASCII (C..AB needs AA/AB after Z); 参数表!C15 static investment includes land-rent PAYMENT C68 (313.82), not annual rent C59 (156.91); junk defined names aa/ab/ac/b/cc/i/j point to 投资计划 aux literals and ARE used by formulas; 存款利率/公益金/流动资金贷款比例 are #REF!-broken names.
- Learning: 1) whole-sheet dependency cycles dissolve at row granularity — a static unit schedule beats iterative pipeline ordering debates. 2) The delegation failure mode was scope: one agent facing 5059 cells retreats to the oracle; one agent facing ~700 cells with a per-sheet diff harness has nowhere to hide. 3) "error type" follows the cached VALUE, not the AST (财务计划!E36). 4) Verify delegated distillation by grep for forbidden imports, never by summary prose.

## 2026-07-26 · solar-v2-slices-wave1
- Hypothesis: per-sheet slices against the unit-schedule skeleton each reach 0-diff vs the workbook oracle.
- Action: 7 parallel slices （还贷/成本/损益/现金流量/财务计划/资产负债/估值结果+指标汇总）, each one module + one oracle test.
- Outcome: 6/7 clean on first delivery （资产负债 487✓, 估值结果+指标汇总 552✓, 还贷 510✓, 损益 810✓, 财务计划 726✓, 现金流量 1077✓). CostSlice found 4 REAL mismatches — traced to a schedule-generator bug: only range ENDPOINTS were captured as dependencies (SUM(T14:T17) missed rows 15/16, hiding 成本!13→成本!16→还贷!21).
- Learning (slice-reported): 1) cross-sheet column offsets differ per sheet pair (损益+2, 投资计划+2, 参数表-1) — verify against the dag, never assume. 2) Year-series can have column-specific formula variations (损益 row 7 freezes at H7 from I onward). 3) AF aggregate columns are not always SUM (损益!AF16 = MIN). 4) SCC carry chains are simple sequential recurrences once you see them (balance[i] = balance[i-1] - repayment[i-1]).

## 2026-07-26 · schedule-fine-steps
- Hypothesis: fixing range expansion keeps the schedule row-granular.
- Action: expanded ranges to every cell in the rectangle in gen_schedule.py — which exposed a 31-row CROSS-SHEET cycle （损益 tax block ↔ 财务计划 ↔ 还贷 ↔ 成本 ↔ 现金流量): year-shifted mutual refs, row-cyclic but cell-acyclic. Split those rows into per-column fine steps (sheet,row,col); extended pipeline (fine_registry, FineStepFn) and oracle; slices converted the affected rows to per-cell fns.
- Outcome: 1087 steps (802 fine); all 7 slices re-verified 0-diff; full oracle-free integration GREEN at first attempt: **G2 = 0/6560 nodes diverge from cached values; `solar-cli verify --engine excel-com` exits 0 with BOTH paths clean** (path 1.1: v1 vs recalc 5059/5059; path 1.2: v2 vs v1 6560/6560).
- Learning: 1) dependency extraction must expand ranges — endpoints-only is silently wrong. 2) Row-cyclic/cell-acyclic patterns (this year ↔ prior year across sheets) need column-split scheduling, not iteration. 3) Per-slice oracle verification + a static schedule made the 5059-node integration pass on the FIRST run — composition of locally-verified units works. **→ promoted to AGENTS.md (range expansion, fine scheduling)**

## 2026-07-26 · v2-integration-cleanup
- Hypothesis: integration is done once the diff is empty.
- Action: wired api.py registry across 9 modules; G2 integration test (no oracle); annotated dag regenerated (6560 nodes, description + code_ref per node); filtered pipeline output to dag node ids after finding 69 phantom emissions （成本 row 17 cells the workbook leaves blank); deleted SolarV2's scratch-file litter (11 root + 4 dag/ files); repo-wide ruff/ty green.
- Outcome: `solar-cli verify --skip-engine` exit 0 (6560/6560). Phantom emissions now dropped at the pipeline boundary.
- Learning: NodeValues' domain is the dag node set — enforce at the pipeline boundary, not per slice.

## 2026-07-26 · domain-calculation-schemas
- Hypothesis: every context module can declare a frozen DomainSchema mapping each sheet's formula/error rows to named items (Chinese label, human-readable formula, explicit input refs), mechanically coverage-checked.
- Action: pnl.py SCHEMA written as exemplar (35 items); SchemaSlice added the other 8 modules + tests/test_schema.py (count/order, coverage, input resolution, formula non-empty, valuation dual-sheet).
- Outcome: 9 domains, **329 items, 312/312 formula rows covered, zero gaps**. ruff/ty/pytest green. E501 per-file-ignores scoped to the 8 schema modules (long Chinese formula strings are data).
- Learning: params:X input refs may mean a Params dataclass field OR a param_steps item key (same domain key) — the test checks both. fmt: off suppresses the formatter, not the linter.

## 2026-07-26 · server-domains-excel
- Hypothesis: schema + per-domain values + Excel export can layer onto the existing FastAPI app without touching the compute core.
- Action: solar_server/domains.py — GET /api/schema, POST /api/domains/compute (schema items + dag cells + computed values), GET /api/download/domains.xlsx (openpyxl, one sheet per domain, 项目|公式|单位 header + 年份 row); StaticFiles mount at / with graceful skip; 10 new tests.
- Outcome: 24/25 tests (1 pre-existing flake); curl-verified: compute 0.34s cached (329 items), xlsx 9 sheets with real values and #REF! as text.
- Learning: [INFERENCE flagged by Main — fixed post-delivery] the slice's defensive `_load_all_domains() -> list[object]` failed ty; loaders must return the real DomainSchema type. `isinstance` narrowing beats getattr + ignore.

## 2026-07-26 · cli-toml-config
- Hypothesis: a global `--config PATH` TOML option can drive all Settings fields with clean precedence.
- Action: typer callback builds effective Settings (TOML over env/defaults) into ctx.obj; commands layer CLI options on top; unknown keys rejected with the valid list; config.example.toml with Chinese comments; 5 tests.
- Outcome: 12/12 fast tests; precedence proven (CLI --dag beats TOML dag_path); `solar-cli --config config.example.toml compute --version v1` works.
- Learning: Windows backslash paths break tomllib string values — use Path.as_posix(). pydantic-settings model_dump + kwargs.update chains precedence correctly.

## 2026-07-26 · frontend-two-tab (designer agent)
- Hypothesis: a no-build vanilla JS + inline SVG app can present both the input→output flow and the domain workflow diagram accessibly, all in Chinese.
- Action (designer): engineering-report aesthetic (warm paper, single teal accent 5.7:1); Tab 1 计算 with honest read-only param display + KPI cards + 9 domain tables; Tab 2 流程与公式 with 9-node/7-layer SVG dependency graph, keyboard-selectable nodes (role=button, aria-pressed), hover/focus neighbor highlighting, schema detail table (项目|公式|单位|逐列值), zoom buttons, Excel download; mock-harness verified.
- Outcome: Main's real-browser verification: both tabs work, diagram ARIA correct, download valid. ONE BUG: KPI regex matched benchmark_rate (0.085) for both IRR and 估值结果 cards — headline IRRs actually live in the cashflow domain (equity_irr 现金流量!H61 = 9.56%), and valuation kpi_* items are dual-purpose year-series where first-cell extraction is meaningless. Sent back for explicit per-card item binding.
- Learning: KPI extraction by regex over labels is fragile against dual-purpose workbook rows — bind headline cards to explicit (domain, item, transform) triples. Read-only honesty (marking params as 只读参考) beats fake interactivity.

## 2026-07-26 · v3-verification-and-commit
- Hypothesis: real-browser verification of the frontend + full gates close the v3 milestone.
- Action: uvicorn + headless Chromium drive: Tab 1 compute flow (6 KPI cards, 9 domain tables), Tab 2 diagram (9 nodes/38 edges, click + keyboard Enter selection with aria-pressed, neighbor highlight, zoom buttons, schema detail panel with formulas + per-column values), Excel download (curl + openpyxl read-back); repo-wide ruff/ty; full pytest per-package.
- Outcome: frontend verified end-to-end after ONE fix — KPI regex had matched benchmark_rate (0.085) for the IRR card; now explicit bindings (资本金IRR = cashflow:equity_irr 9.56%, 股权估值(收益法) = valuation:val_sale_price_inc 12,795万元). Excel: 9 sheets, 项目|公式|单位|年份 rows, #REF! as text. **149/149 tests green** (cli 14, server 25, packages 110). ty/ruff clean.
- Learning: full-suite pytest hung 40min with 23 dots — Excel COM contention with the RUNNING uvicorn server (COM serializes per machine; tests Dispatch while the server held an instance). Stop the server (or any COM client) before running engine tests.

## 2026-07-26 · v2-rebuild-design
- Hypothesis: the distilled logic trapped in the dag-scheduled pipeline can be lifted into a standalone typed domain engine (no dag, no xlsx-core, no cell plumbing) while preserving the 0-diff benchmark.
- Action: 4 parallel scouts mapped the mutual block (31 fine rows = per-year feed-forward recurrence, 3 carry values: 财务计划 short_term_borrowing, 损益 cum_profit, 财务计划 cumulative_surplus), the input inventory (~59 givens + 3 given series + 3 aux ratios), the integration surface, and all 8 module maps. Settled architecture: ModelInputs (frozen pydantic, TOML) -> domains/{params,invest,debt,cost,pnl,cashflow,finplan,balance,valuation} (year-keyed polars frames, typed frozen results) + mutual.py (step_year loop) -> engine.compute_model -> ModelResults; v2_benchmark (separate import root) owns ALL cell identity (layout tables, projection, compare). Structural convention: one named compute_<key> fn per non-coupled item; coupled items computed by mutual.step_year; schema items gain kind/coupled metadata; depends_on verified against type annotations.
- Outcome: contract going into packages/solar-v2/DOMAIN.md; build fanned out to parallel per-domain slices.
- Learning: the workbook's row-level cycle is a sequential year recurrence, not a fixed point -- per-year stepping with 3 carries is the honest domain shape. Echo-chains must be re-expressed through ORIGIN domains (财务计划 reads 现金流量 rows 53/55/56 which merely echo cost/pnl -- read cost/pnl directly) to avoid fake domain cycles. Genuine cross-stage back-edges: 损益 row 43 reads 资产负债 (compute post-balance); 投资计划 G6/H6 read 成本/指标汇总 (resolve via a cost-statics stage).

## 2026-07-26 · v2-rebuild-integration-G2-GREEN
- Hypothesis: 11 parallel domain slices + typed engine glue can reach an empty golden diff against solar-v1.
- Action: fanned out 11 builders (inputs+params, 8 domain modules, mutual solver, benchmark harness) against the DOMAIN.md contract; integrated engine.py/results.py; iteratively drove the projection diff (v2_benchmark vs solar-v1) to zero. ~30 integration fixes.
- Outcome: **G2 = 0/5059 formula+error nodes vs solar-v1 (rel tol 1e-6, errors error-for-error)**. compute_model cold ~2.7s. Bug catalog (each localized by the diff): pnl VAT-credit carry never updated in loop; params static_investment_total used annual rent instead of first land-rent PAYMENT; projection year_idx ignored 26-row frames (added per-sheet frame_offset + per-row span offsets); finplan land-rent payment off-by-one and lt_loan_repay read balance instead of principal; cashflow cost/pnl slices assumed 26-row frames; IRR bracket expanded past the rate=-1 singularity; DSCR average window off-by-one ([2:17]→[2:16]); 期初累计利润 plug (-0.001) is a GIVEN (new ModelInputs.initial_cum_profit); balance current assets/liabilities must be blank at construction; intangibles read the shifted land-rent section one year ahead; valuation read retained-earnings where the workbook reads accumulated reserves; dual-purpose KPI rows need per-cell scalar overrides in layout; equity adjustment uses sale-tax rate not mgmt ratio; salvage recovery gated on operating_years.
- Learning: 1) The golden diff is the integration debugger — every mismatch localized to a (sheet,row) cluster, and clusters cascade from single roots (one dropped carry = ~2000 cells). 2) Parallel slice verification against the old pipeline is necessary but NOT sufficient: cross-slice interface drift (attribute names, frame row counts, scalar field names) only surfaces at integration — budget an explicit reconciliation pass. 3) Workbook plugs in pre-operating columns (损益 F16=-0.001) are INPUTS, not artifacts — carry them in ModelInputs. 4) Excel AVERAGE/SUM over partially-blank ranges = windowed aggregates; map them to engine scalars, not frame reductions.

## 2026-07-26 · v2-rebuild-final-gates + complexity-metrics
- Hypothesis: the rebuilt engine + harness clear every gate, and the "understanding via compression" claim can be measured anti-gameably.
- Action: G7(b) reconciled (depends_on now matches code-extracted type+schema-input deps for all 9 domains; params declares stage-12 back-edge deps cost/pnl; cost orchestrators retyped off object). Typing cleanup drove ty to 0. Added complexity_analysis.py + docs/complexity_report.md + tests/test_complexity.py gate.
- Outcome — ALL GATES GREEN:
  - G1 solar-v1+xlsx-core 93 tests pass; G2 golden 0/5059 (test_accuracy + CLI path 1.2);
  - G3 ty check 0, ruff repo-wide 0, pytest 162 passed 0 skipped;
  - G4 `solar-cli verify --engine excel-com` exit 0 both paths (5059/5059 recalc, 0 diff engine-vs-v1);
  - G5 no xlsx_core/solar_v1/yaml/dag imports + no cell-address patterns (AST-checked), pure-code ModelInputs matches headline truth;
  - G6 cold compute ~2.6s (<5s);
  - G7 structural test green: 1 computer per item, depends_on==code deps, no single-cell series fns, 362 items;
  - G8 properties + perturbation green; G9 real-browser: both Chinese tabs render real engine values (KPI cards + 9 domain tables + 194 values), Excel download = 9 sheets.
- Complexity metrics (the anti-cheating signature set the user asked for):
  - MDL ratio engine-compute-AST / dag-expression-tokens = 0.670 (engine logic is TERSER than the raw cell formulas; re-chunking can't move it). One named function per 14.4 cells.
  - Reuse: 362 items, 423 edges, mean fan-out 1.97 over producers (cell-translation ≈1.0), 54 hubs fan-out≥3, max 8 — hubs are the distilled concepts (total_profit, output_vat, interest_expense, sales_revenue).
  - Cyclomatic: median 1.0, max 14 (only 4 branchy orchestrators: step_year, invest intermediates, cost/finplan assemblers).
  - Halstead vocab 1508, volume 87k; DAG depth 31.
  - Gate bounds in test_complexity.py: mdl<1.0, fan-out≥1.5, hubs≥30, cc_max≤20, cc_median≤2, items≤380.
- Learning: pure node/line counting is gameable in one direction; the robust "understanding = compression" signatures are (1) total description length (MDL — invariant to re-chunking), (2) reuse structure (fan-out hubs — translation has fan-out≈1), (3) bounded per-unit cyclomatic complexity (catches stuffed nodes), used TOGETHER. A typed engine can be shorter in logic-AST than the flat cell formulas it replaces while being human-readable — that ratio (0.67 here) is the honest compression number, not item count alone.

## 2026-07-26 · kpi-total-investment-fix
- Hypothesis: the 总投资 KPI card showing 0 万元 is a frontend binding bug, not an engine error.
- Action: traced it — invest:total_investment is a per-period series [build1=0, build2=0, oper1=56837, oper2=450] (the workbook allocates 100% of static investment to the oper1 period via completion ratios aa=0/ab=0/ac=1). The KPI rule "按列序取首个数值单元" read build1 = 0. The real total is the 合计 column C5 = 57287 = sum of the period series = scalars.total_investment_total. Added a sumNumericCells() transform to app.js and bound 总投资 with agg:"sum" (note 各期合计).
- Outcome: 总投资 card now renders 57,287 万元; all 6 KPI cards correct (engine values unchanged — engine was always right). Verified in headless browser with cache disabled.
- Learning: "first cell" extraction is wrong for period series whose leading period is a zero-allocation construction slot; headline totals over a period/year schedule must use the aggregate (sum), with the period item kept for the per-period breakdown. Generalizes: any KPI that is a Σ over a schedule needs an explicit agg transform, never positional first-cell.

## 2026-08-04 · vps-deployment-kit
- Hypothesis: solar-server can deploy to a yum-based Linux VPS with uv + systemd
  and no containers, since every dependency ships manylinux wheels.
- Action: audited deploy constraints — Python 3.13 absent from yum repos (uv must
  manage the interpreter); Settings defaults are Windows-shaped (excel-com engine,
  C:/ LibreOffice path). Added deploy/ (systemd unit, env.template, update.sh) +
  .gitattributes LF pin. Then a scout verified the frontend-only footprint.
- Outcome: gates green (ty/ruff, 162 tests). Scout evidence: the static UI calls
  only GET /api/schema, POST /api/domains/compute {version:"v2"}, GET
  /api/download/domains.xlsx?version=v2 (app.js:15-17,48,136,146-149,577,672) —
  all zero-file-I/O (engine.py:8-9); ModelInputs() boots from defaults
  (main.py:225-226, inputs.py:29-217), so a frontend-only VPS needs NO xlsx, NO
  dag, NO recalc engine, empty env is valid. dag/workbook keys only matter for
  direct v1/verify calls; v1 itself never opens the workbook anymore
  (dag_loader.py:35-36). Fixed main.py docstring mislabeling the inputs TOML env
  var as SOLAR_INPUTS_TOML (real key: XLSX_INPUTS_TOML per env_prefix).
- Learning: deployment readiness = auditing Settings defaults against the target
  OS plus tracing the frontend's actual endpoint set to file I/O — env keys
  belong to endpoints, not to "the app". Latent hazard found: v2_benchmark is
  undeclared in every pyproject; editable uv installs mask it, any wheel-based
  install would ImportError on /compute/v2?flat=true and /verify path 1.2.
  Also XLSX_DAG_V2_PATH is dead config (no reader; file moved to
  packages/solar-v2/dag/).

## 2026-08-04 · url-prefix-and-port-config
- Hypothesis: serving under ip:13005/solar-server is best done by mounting the
  app under a configurable prefix in-code (proxy forwards paths unchanged),
  with the frontend switched to relative URLs.
- Action: create_app(url_prefix=...) wraps the app in a root FastAPI mount when
  a prefix is set (arg or SOLAR_URL_PREFIX env; default = serve at root so all
  existing tests/paths stay untouched); app.js/index.html absolute /api/... refs
  became relative; systemd unit gained SOLAR_HOST/SOLAR_PORT (default
  127.0.0.1:14905) consumed via EnvironmentFile; update.sh smoke test reads
  port+prefix from env; wrote deploy.md with the Aliyun scenario (Caddy 13005 →
  uvicorn 14905, security-group + firewalld, IP-only HTTPS options).
- Outcome: gates green; 2 new TestClient tests cover prefix mount (env + arg).
- Learning: a path prefix must be owned by exactly one layer — app-side mount +
  relative frontend URLs means no proxy rewriting anywhere; the alternative
  (proxy strips prefix, app unaware) breaks the moment the frontend uses
  absolute paths or the app is reached without the proxy. Relative URLs are
  only safe because StaticFiles redirects prefix-without-slash to
  prefix-with-slash.

## 2026-08-04 · vps-ops-model
- Hypothesis: the deployment kit should match the VPS's real ops model — an
  unprivileged app account plus an admin-owned edge — instead of a scripted
  root install.
- Action: user corrected the design (checkout at /home/appuser/solar-price-servec,
  uv preinstalled, Caddy managed by admin, explicit "no sudo scripts in this
  project"). Deleted deploy/update.sh + deploy/solar-server.service (both
  root-oriented); added deploy/run.sh — sources ./env, execs
  `uv run uvicorn solar_server.main:app --host/--port` as the current user
  (foreground or nohup). Rewrote deploy.md as a role table (appuser = code +
  service via uv run; admin = Caddy/security-group/firewall, documented not
  scripted) with an optional systemd USER unit appendix (one-time admin
  lingering command labeled as such). AGENTS.md gained the hard rule: no
  privilege escalation in repo tooling.
- Outcome: repo ships zero sudo; app-side lifecycle is clone → uv sync →
  run.sh → pkill; edge config stays admin prose. Gates unaffected (script/doc
  changes only).
- Learning: ask WHO runs what before writing deploy scripts — a "deployment
  script" that silently assumes root violates the target's account model; the
  unprivileged default (uv run launcher + user-level persistence) is also the
  more portable one. **→ promoted to AGENTS.md (no privilege escalation)**

## 2026-08-04 · pywin32-linux-sync-failure
- Hypothesis: the first real VPS deploy (`uv sync` on Aliyun Linux) fails
  because pywin32 was declared unconditionally and the universal lock carries
  it to every platform.
- Action: added the environment marker — `"pywin32>=312; sys_platform ==
  'win32'"` in packages/xlsx-core/pyproject.toml; re-locked with `uv lock
  --offline` (pypi.org TLS handshake-eof from this laptop; metadata already
  cached). Lock diff: 2 lines.
- Outcome: gates green (ty/ruff, 164 tests). Marker propagates into the
  universal lock, so Linux sync skips pywin32 entirely; runtime was already
  safe — excel_com lazy-imports win32com and converts ImportError into
  RecalcResult(ok=False) (excel_com.py:29-39).
- Learning: platform-specific deps MUST carry markers at declaration — a
  universal lockfile records what you declared, it doesn't filter it per
  platform. One marker line fixes every OS; no per-platform lockfiles needed.

## 2026-08-04 · dag-test-purity
- Hypothesis: the test-suite churn in dag/solar.dag.yaml has two roots — a
  write side effect inside extract_dag() and a per-process salted hash in the
  year-series keys.
- Action: split extraction from writing — extract_dag() is now pure;
  write_dag_yaml() is public and called only by the CLI extract command
  (solar_cli/main.py). Replaced abs(hash(r1c1)) with zlib.crc32 in
  _make_concept_hint (year_series.py) so keys are deterministic across
  processes. Added regression test: extract_dag(Settings(dag_path=tmp)) must
  create nothing. Regenerated the tracked dag once with the new hash.
- Outcome: gates green (ty/ruff, 165 tests); dag diff = 308 key-suffix lines
  only, no node/value changes; post-pytest git status shows zero test-induced
  writes.
- Learning: any function that both computes AND writes a tracked artifact
  will be abused by tests — purity at the library edge, writing at the command
  edge. And never put Python's salted hash() into persisted identifiers.

## 2026-09-26 · editable-param-form
- Hypothesis: the read-only parameter form was a frontend-only limitation —
  the v2 engine already accepts per-request ModelInputs overrides
  (DomainsComputeRequest.inputs → _build_model_inputs → compute_model).
- Action: dropped readonly from the 7 param inputs (index.html), mapped
  标杆上网电价 to ModelInputs field base_tariff (feed_in_tariff is DERIVED =
  base_tariff + subsidy_per_kwh, not an input), collectParamInputs() gathers
  finite numbers into the POST body, form "input" events invalidate the
  memoized computePromise/computed cache. Removed the now-dead
  input[readonly] CSS rule.
- Outcome: gates green (ty/ruff, 165 passed 3:12). Live endpoint check:
  capacity 15→30 + hours 1145→2000 scaled pnl:power_generation 15908.34 →
  55575.0, matching the physical ratio (30·2000)/(15·1145) = 3.4930 to 4 dp;
  sales_revenue and equity_irr move consistently. Deployed to SWAS
  :19111/solar-report/ via git pull (static-only, no restart needed).
- Learning: when a UI claims "server computes", verify the override path with
  a physical-ratio check (output scales by the input ratio), not just a
  value-differs check — a differs-check alone can't distinguish real
  parameter flow from RNG/noise.
