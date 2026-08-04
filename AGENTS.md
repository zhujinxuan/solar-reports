# AGENTS.md — consume-xlsx-as-software

Turn Excel economic-evaluation workbooks into real software: extract → interpret → distill into DDD code.

## Hard rules

- **uv only**: `uv run`, `uv add`. Never naked `python`/`pip`.
- **polars**, never pandas.
- **Gates before yield**: `uv run ty check` and `uv run ruff check` clean; `uv run pytest` green.
- **Typing discipline**: no `Any`, no naked `dict` / `dict[str, Any]`. Every helper's I/O is a **frozen** pydantic model or `@dataclass(frozen=True)`.
- **No hardcoding**: paths, tolerances, workbook names, engine choice → `pydantic-settings` Settings, env/CLI overridable.
- **No privilege escalation in repo tooling**: deploy scripts run as the app
  user (`uv run`), never sudo; system-level config (Caddy, firewall, security
  group) is documented in deploy.md, not scripted. (2026-08-04 · vps-ops-model)
- **Year-series, not cell-by-cell**: columns that iterate years (detected via column-shifted identical formulas) MUST be aggregated as polars year-series with readable domain names. Results must still match the xlsx numerically.
- **solar-v1 carries the extracted `dag/solar.dag.yaml`** (position/expression/type);
  solar-v2 is a standalone domain engine — no dag, no cell identity in the compute
  path; cell identity lives only in its test-side `v2_benchmark` harness.
- **Every package carries its own `DOMAIN.md`** — bounded contexts it owns/realizes and its DI wiring. Read it before coding in that package; evolve it when the package changes. The shared canonical design lives in `docs/DOMAIN.md`.
- **JOURNAL.md is append-only and mandatory** — every non-trivial attempt (success OR failure: engine benchmarks, evaluator designs, simplification tries) gets an entry BEFORE moving on. Format:

  ```
  ## YYYY-MM-DD · <step-name>
  - Hypothesis: what we expected
  - Action: approach, commands, config
  - Outcome: evidence — numbers, diff counts, gate results (not vibes)
  - Learning: reusable rule, or "none — dead end because X"
  ```

  Distillation path: a Learning that generalizes MUST be promoted into AGENTS.md or
  the relevant DOMAIN.md, with the journal entry edited to link the promotion.
  The journal is the raw material; the docs are the distillate.

## Workspace layout

```
packages/xlsx-core    shared kernel: DAG model, formula AST/parser, evaluator,
                      workbook loader (openpyxl), year-series detector. No domain.
packages/solar-v1     v1 software = dag.yaml interpreter (ACL-bound translation)
packages/solar-v2     v2 software = standalone distilled domain engine
                      (ModelInputs -> compute_model -> ModelResults; polars
                      year-series; v2_benchmark = test-side cell projection)
apps/cli              typer CLI, works against any version package
apps/server           FastAPI backend (frontend deferred)
dag/                  extracted + annotated dag.yaml artifacts
data/                 source workbooks (solar first, wind as portability check)
docs/DOMAIN.md        canonical shared domain design (contexts, context map, ACL, DI)
```

## Golden check (definition of done)

Three-way, per-node — not just final totals:

1. **v1 vs xlsx**: the dag interpreter must reproduce the workbook's cached values on
   every formula cell of every calc sheet (参数表 derived cells included), relative
   tolerance 1e-6. This makes v1 the executable specification at cell resolution.
2. **v2 vs v1**: the distilled DDD code must match v1's dag-versioned values node by
   node (via `code_ref` in its annotated dag.yaml), so any divergence localizes to an
   exact `sheet!cell`.
3. **Simplification safety**: every simplification (year-series collapse, dead-branch
   elimination, constant folding) is accepted only while the golden diff stays empty.

Known hazards: the workbook contains `#REF!` errors (e.g. 损益!D4) — policy: record
them as error-typed nodes, never silently coerce.

Promoted learnings (from JOURNAL.md — each links its source entry):

- **Error type follows the cached VALUE, not the AST**: an error literal in a dead
  IF branch （财务计划!E36) does not make the node error-typed; lazy evaluation
  computes the live value. Error-typed nodes reproduce the cached error, never
  re-evaluate. (2026-07-26 · solar-v1-interpreter, schedule-fine-steps)
- **Dependency extraction MUST expand ranges**: capturing only range endpoints
  (SUM(T14:T17) → rows 14,17) silently drops interior-row deps and corrupts any
  topo order built on it. (2026-07-26 · schedule-fine-steps)
- **Row-cyclic/cell-acyclic sheets** (year-shifted mutual refs across sheets)
  need per-column fine scheduling, not iteration. (2026-07-26 · schedule-fine-steps)
- **Recalc engines**: excel-com won the benchmark (0/5059, 9.6s); LibreOffice
  needs the xlsx→ods→xlsx two-step or OOXMLRecalcMode=0 to actually recalc, and
  `--convert-to` claims must be proven by a perturbation test; the `formulas`
  package cannot evaluate this workbook class — do not retry it. (2026-07-25 ·
  recalc-benchmark-wave1)
- **Distillation verification**: a shared engine makes a golden diff vacuous —
  verify "no parser/evaluator/cached reads in the compute path" by grep, never
  by summary prose. (2026-07-26 · solar-v2-clone-attempt-REJECTED, solar-v2-restructure)
