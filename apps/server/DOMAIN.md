# DOMAIN.md — solar-server

Seed: see `docs/DOMAIN.md` (canonical). FastAPI backend serving both versions.

## Owns
- HTTP adapters around the same use cases the CLI exposes: compute v1, compute v2,
  verify. No business logic; requests map to use-case calls, responses are frozen
  pydantic schemas.
- `src/solar_server/schemas.py` — all frozen pydantic request/response types:
  HealthResponse, ComputeRequest/Response, VerifyRequest/Response, MismatchJSON,
  Path11Result/Path11Skipped, Path12Result, ScalarJSON union (numbers, strings,
  bools, null, ErrorMarker for errors, ISO datetimes). Also: DomainsSchemaResponse,
  DomainsComputeRequest/Response, DomainSchemaResponse, ItemSchemaResponse,
  CellValue, ItemCell, DomainComputeResponse.
- `src/solar_server/verify.py` — verification use case: path 1.1 (recalc + compare
  v1 against recalced workbook) and path 1.2 (v1 vs v2 node-by-node). No imports
  from solar_cli; self-contained against xlsx-core + solar-v1/v2 contracts.
- `src/solar_server/main.py` — FastAPI app factory `create_app(settings?)` +
  module-level `app` for uvicorn.
- `src/solar_server/domains.py` — domain schema/compute/download endpoints:
  GET /api/schema, POST /api/domains/compute, GET /api/download/domains.xlsx.
  DAG node index cached on app.state; resolves domain item rows against DAG
  formula/error nodes for cell-level values. Excel export uses openpyxl with
  one sheet per domain (sheet = domain 中文 name), header row 项目|公式|单位|cols,
  and a 年份 row when the domain has a year_labels item.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | `{status:"ok", versions:["v1","v2"]}` |
| POST | /compute/v1 | v1 compute; optional body `{node_ids?: [...]}` filter |
| POST | /compute/v2 | v2 compute; same filter |
| POST | /verify | body `{engine?, skip_engine?, skip_v2?}`; two-path verification |
| GET | /api/schema | domain calculation schemas from solar-v2 |
| POST | /api/domains/compute | body `{version?}`; per-domain items with cells |
| GET | /api/download/domains.xlsx | `?version=v2`; Excel export per domain |
| — | / | static frontend (mount if `static/` dir present) |

- 422 on bad version path param or query param.
- 503 if a requested engine is unavailable on this host.



## DI wiring

```
settings: xlsx_core.settings.Settings (pydantic-settings, env XLSX_ prefix)
         ── injected into create_app() as an optional override; defaults used otherwise.

compute:  solar_v1.api.compute / solar_v2.api.compute → NodeValues
          ── called via functools.lru_cache(maxsize=8) keyed on (version, workbook_path, dag_path).
          Cache is safe because NodeValues is an immutable frozen model.

verify:   solar_server.verify.verify() orchestrates:
          1.1: xlsx_core.recalc adapter (ExcelComRecalc / LibreOfficeRecalc)
               + solar_v1.api.compute + openpyxl for reading recalced workbook
               → compare via xlsx_core.recalc.base.compare_values
          1.2: solar_v1.api.compute vs solar_v2.api.compute
               → compare via same compare_values
```

## Threading

Compute endpoints use `def` (not `async def`) — FastAPI runs them in a threadpool
automatically. Compute is CPU-bound ~1-70s and blocks the worker thread; this is
acceptable for the current scale.

Verify engine-backed path runs Excel COM (CoInitialize/CoUninitialize) in the
same threadpool thread. Engine availability is checked at request time (503 if
unavailable).
