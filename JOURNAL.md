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
