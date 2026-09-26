# Strip v1/dag from the serving binary — server becomes pure v2

Status: claimed
Type: task

## Context

Profiling (2026-09-26) proved the v2 serving path never reads the dag
(0 dag/yaml functions in all profiles; ~50ms live). The only seconds-scale
path in the server is the v1 branch parsing the 1.2MB dag yaml (3.35s on the
VPS). The frontend calls exactly: `GET /api/schema`,
`POST /api/domains/compute` (v2), `GET /api/download/domains.xlsx?version=v2`,
plus `/health`. The golden check (v1 vs xlsx, v2 vs v1) is a dev-loop tool and
lives in `packages/solar-v1` + CLI + tests — the VPS is not responsible for it.

## Change

apps/server only; `packages/solar-v1` untouched.

- main.py: delete `/compute/{version}` route entirely (v1 = dag interpreter;
  v2 flat = test-side v2_benchmark dag projection; non-flat v2 duplicates
  /api/domains/compute). Delete `/verify`. Delete `_cached_compute_v1`,
  `_cached_engine_results`, dag/workbook settings usage. v2-only branches in
  `/api/domains/compute` and `/api/download/domains.xlsx` (drop version param
  handling → always v2).
- domains.py: delete dag machinery (`_NodeInfo`, `_load_dag_nodes`,
  `_ensure_dag_index`, `_build_item_cells`, `_build_domains_compute`,
  `_gather_col_letters`, `_search_year_labels`, `_build_xlsx`, col-letter
  helpers). Keep schema loading for `/api/schema`.
- verify.py: delete file.
- schemas.py: `HealthResponse.versions` → `("v2",)`; delete Compute/Verify
  request/response models now unreferenced.
- tests: update test_server.py / test_domains.py — remove v1/verify/compute
  tests; add contract test: removed routes 404, health reports ["v2"].
- deploy/env.template + deploy.md: drop XLSX_DAG_PATH and v1/verify docs.
- apps/server/DOMAIN.md: evolve to v2-only serving.
- JOURNAL.md entry.

## Acceptance

- Gates green: `uv run ty check`, `uv run ruff check`, `uv run pytest`.
- Local smoke: `/health` → versions ["v2"]; v2 domains compute 200;
  `/compute/v1` and `/verify` → 404.
- Deployed to SWAS VPS (git pull + restart), live verification same checks.
- Ticket resolved with evidence.

## Answer

(pending)
