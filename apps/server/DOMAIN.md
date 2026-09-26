# DOMAIN.md — solar-server

Seed: see `docs/DOMAIN.md` (canonical). FastAPI backend serving **solar-v2
only**. The golden check (v1 vs workbook, v2 vs v1) is a dev-loop tool and
lives in `packages/solar-v1` tests, `packages/solar-v2` tests, and the CLI
(`solar-cli verify`) — never in this binary.

## Owns
- HTTP adapters around the v2 compute use case. No business logic; requests
  map to `ModelInputs -> compute_model -> ModelResults`, responses are frozen
  pydantic schemas. No dag, no workbook, no formula parser on any path.
- `src/solar_server/schemas.py` — all frozen pydantic request/response types:
  HealthResponse, ScalarJSON union (numbers, strings, bools, null, ErrorMarker
  for errors, ISO datetimes), DomainsSchemaResponse, DomainsComputeRequest/
  Response, DomainSchemaResponse, ItemSchemaResponse, CellValue, ItemCell,
  DomainComputeResponse.
- `src/solar_server/main.py` — FastAPI app factory `create_app(settings?)` +
  module-level `app` for uvicorn; ModelInputs TOML load + JSON override merge.
- `src/solar_server/domains.py` — GET /api/schema: loads the nine domain
  SCHEMA objects from solar-v2.
- `src/solar_server/_engine_serialize.py` — ModelResults → DomainsComputeResponse
  (app.js shape: domains[].items[].cells[] with col/row/value, synthetic
  year_labels item per domain) and ModelResults → openpyxl workbook (one sheet
  per domain, sheet = domain 中文 name, header row 项目|公式|单位|year cols,
  frozen top row).

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | `{status:"ok", versions:["v2"]}` |
| GET | /api/schema | domain calculation schemas from solar-v2 |
| POST | /api/domains/compute | body `{version?, inputs?}`; per-domain items with cells; `inputs` = ModelInputs field overrides |
| GET | /api/download/domains.xlsx | `?version=v2`; Excel export per domain |
| — | / | static frontend (mount if `static/` dir present) |

- 422 on a version other than `v2`.
- `/compute/{v1,v2}` and `/verify` were removed (2026-09-26, serving-v2-only):
  v1 = dag interpreter, v2 flat = test-side dag projection, verify = golden
  check — all dev-loop surfaces, not serving.

## DI wiring

```
settings: xlsx_core.settings.Settings (pydantic-settings, env XLSX_ prefix)
         ── injected into create_app() as an optional override; only
            inputs_toml (XLSX_INPUTS_TOML) is read.

compute:  solar_v2.engine.compute_model(ModelInputs) -> ModelResults
          ── called per request, uncached; ModelInputs built from the
             optional TOML base + per-request JSON overrides.
```

## Threading

Compute endpoints use `def` (not `async def`) — FastAPI runs them in a
threadpool automatically. v2 compute is CPU-bound ~50ms warm (measured live
2026-09-26) and blocks the worker thread; acceptable for the current scale.
