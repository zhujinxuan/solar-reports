"""FastAPI app for solar-server — serves solar-v1 and solar-v2 compute + verify.

Caching: LRU on v1 (Settings-dependent); v2 engine results cached on
ModelInputs identity (immutable pydantic).  NodeValues are immutable,
so sharing cached results across requests is safe.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast

if TYPE_CHECKING:
    from solar_v2.inputs import ModelInputs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from xlsx_core.model import Scalar
from xlsx_core.settings import Settings

from solar_server.domains import (
    _build_domains_compute,
    _build_schema_response,
    _build_xlsx,
    _ensure_dag_index,
)
from solar_server.schemas import (
    ComputeRequest,
    ComputeResponse,
    DomainsComputeRequest,
    DomainsComputeResponse,
    DomainsSchemaResponse,
    HealthResponse,
    ScalarJSON,
    VerifyRequest,
    VerifyResponse,
    scalar_to_json,
)
from solar_server.verify import _check_engine_available
from solar_server.verify import verify as _verify

# ---------------------------------------------------------------------------
# Cache key — frozen namedtuple
# ---------------------------------------------------------------------------


class _CacheKey(NamedTuple):
    version: str
    workbook_path: str
    dag_path: str


# ---------------------------------------------------------------------------
# Cached compute (v1 only — dag/cell-based)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=8)
def _cached_compute_v1(
    workbook_path: str,
    dag_path: str,
) -> dict[str, object]:
    """Run solar-v1 compute, return {node_id: Scalar}."""
    settings = Settings(workbook_path=workbook_path, dag_path=dag_path)  # type: ignore[call-arg]
    from solar_v1.api import compute as v1_compute

    result = v1_compute(settings)
    return dict(result.values)


# ---------------------------------------------------------------------------
# Cached v2 engine (by ModelInputs identity)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=4)
def _cached_engine_results(
    inputs_fingerprint: int,
    inputs_json: str,
) -> dict[str, object]:
    """Run solar-v2 engine, return domain-structured JSON dict.

    ``inputs_fingerprint`` and ``inputs_json`` together form the cache key;
    the actual ModelInputs are rebuilt from JSON inside the function.
    """
    import json as _json

    from solar_v2.engine import compute_model
    from solar_v2.inputs import ModelInputs

    inputs = ModelInputs(**_json.loads(inputs_json))
    results = compute_model(inputs)
    return _domain_json_from_results(results)


def _domain_json_from_results(results: object) -> dict[str, object]:
    """Serialize ModelResults to domain-structured JSON (same as CLI format)."""
    from solar_v2.schema import all_domains

    schemas = all_domains()
    domains: dict[str, object] = {}

    for ds in schemas:
        domain_result = getattr(results, ds.key)
        years = _get_domain_years(domain_result)
        items: list[dict[str, object]] = []

        for item_schema in ds.items:
            entry: dict[str, object] = {
                "key": item_schema.key,
                "label": item_schema.label,
                "unit": item_schema.unit,
                "formula": item_schema.formula,
                "kind": item_schema.kind,
            }
            if item_schema.kind == "scalar":
                scalars = getattr(domain_result, "scalars", None)
                if scalars is not None and hasattr(scalars, item_schema.key):
                    entry["value"] = getattr(scalars, item_schema.key)
                elif hasattr(domain_result, item_schema.key):
                    entry["value"] = getattr(domain_result, item_schema.key)
                else:
                    entry["value"] = None
            else:
                frame = getattr(domain_result, "frame", None)
                if frame is not None and item_schema.key in frame.columns:
                    series = frame[item_schema.key]
                    vals: list[object] = []
                    for v in series.to_list():
                        if isinstance(v, float) and (
                            v != v or v == float("inf") or v == float("-inf")
                        ):
                            vals.append(None)
                        else:
                            vals.append(v)
                    entry["values"] = vals
                else:
                    entry["values"] = None
            items.append(entry)

        domains[ds.key] = {
            "key": ds.key,
            "sheet": ds.sheet,
            "label": ds.label,
            "years": years,
            "items": items,
        }

    return {
        "version": "v2",
        **domains,
        "headline": {
            "equity_irr": getattr(results, "equity_irr", None),
            "project_irr_after_tax": getattr(results, "project_irr_after_tax", None),
            "equity_npv": getattr(results, "equity_npv", None),
            "project_npv_after_tax": getattr(results, "project_npv_after_tax", None),
            "equity_sale_price": getattr(results, "equity_sale_price", None),
        },
    }


def _get_domain_years(domain_result: object) -> list[int]:
    """Extract calendar years from a domain result."""
    years = getattr(domain_result, "years", None)
    if years is not None:
        return list(years)
    periods = getattr(domain_result, "periods", None)
    if periods is not None:
        return list(periods)
    for attr in ("income", "frame"):
        frame = getattr(domain_result, attr, None)
        if frame is not None and "year" in frame.columns:
            return [int(y) for y in frame["year"].to_list()]
    return []


# ---------------------------------------------------------------------------
# ModelInputs — TOML load + merge helper
# ---------------------------------------------------------------------------


def _load_inputs_from_toml(toml_path: str) -> dict[str, object]:
    """Load ModelInputs from a TOML file, returning as plain dict.

    Handles mixed files: if the TOML has both Settings keys and an
    [inputs] section, extracts only the [inputs] section.
    """
    import tomllib

    from solar_v2.inputs import ModelInputs

    with open(toml_path, "rb") as f:
        raw = tomllib.load(f)

    if "inputs" in raw:
        inputs_raw = raw["inputs"]
    else:
        valid = set(ModelInputs.model_fields.keys())
        inputs_raw = {k: v for k, v in raw.items() if k in valid}

    return inputs_raw


def _build_model_inputs(
    toml_path: str | None,
    json_overrides: dict[str, object] | None,
) -> ModelInputs:
    """Build ModelInputs from TOML + optional JSON override fields.

    Returns default ModelInputs if neither source is provided.
    """
    from solar_v2.inputs import ModelInputs

    base: dict[str, object] = {}

    if toml_path is not None:
        base = _load_inputs_from_toml(toml_path)

    if json_overrides:
        base.update(json_overrides)

    if not base:
        return ModelInputs()

    # Coerce types
    coerced: dict[str, float | int | bool | tuple[float, ...] | str] = {}
    for key, val in base.items():
        if key == "western_dev_preferential" and isinstance(val, str):
            s = val.strip()
            coerced[key] = s == "是"
        elif key in ModelInputs._FLOAT_FIELDS and isinstance(val, int):
            coerced[key] = float(val)
        elif key in (
            "degradation_factor",
            "load_rate",
            "repair_rate_series",
        ) and isinstance(val, list):
            coerced[key] = tuple(float(v) for v in cast(list[float | int], val))
        else:
            coerced[key] = cast(float | int | bool | str, val)

    return ModelInputs.model_validate(coerced)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: xlsx-core Settings override. Uses defaults if None.

    The returned app has TOML inputs pre-loaded if Settings specifies
    an ``inputs_toml`` path (env ``SOLAR_INPUTS_TOML``).
    """

    app = FastAPI(title="solar-server", version="0.1.0")

    s = settings or Settings()
    inputs_toml: str | None = getattr(s, "inputs_toml", None) or None

    # Pre-load base ModelInputs from TOML at startup
    _base_inputs = _build_model_inputs(inputs_toml, None)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.post("/compute/{version}", response_model=ComputeResponse)
    def compute(
        version: str,
        body: ComputeRequest | None = None,
    ) -> ComputeResponse:
        if version not in ("v1", "v2"):
            raise HTTPException(
                status_code=422,
                detail=f"Unknown version: {version!r}. Use 'v1' or 'v2'.",
            )

        if version == "v1":
            cached = _cached_compute_v1(str(s.workbook_path), str(s.dag_path))

            if body is not None and body.node_ids is not None:
                filtered: dict[str, object] = {}
                for nid in body.node_ids:
                    if nid in cached:
                        filtered[nid] = cached[nid]
            else:
                filtered = cached

            json_values: dict[str, ScalarJSON] = {
                k: scalar_to_json(cast(Scalar, v)) for k, v in filtered.items()
            }

            return ComputeResponse(
                version=version,
                node_count=len(json_values),
                values=json_values,
            )
        else:
            # v2: domain-structured JSON
            import json as _json

            # Check for flat flag or inputs overrides
            flat = False
            inputs_overrides = None
            if body is not None and hasattr(body, "flat"):
                flat = getattr(body, "flat", False)
            if body is not None and hasattr(body, "inputs"):
                inputs_overrides = getattr(body, "inputs", None)

            if inputs_overrides is not None:
                inputs = _build_model_inputs(inputs_toml, inputs_overrides)
            else:
                inputs = _base_inputs

            if flat:
                from solar_v2.engine import compute_model
                from v2_benchmark.projection import project as project_v2

                results = compute_model(inputs)
                dag_path = str(s.dag_path)
                flat_values = project_v2(results, dag_path=dag_path)
                json_values: dict[str, ScalarJSON] = {
                    k: scalar_to_json(cast(Scalar, v))
                    for k, v in flat_values.items()
                }
                return ComputeResponse(
                    version=version,
                    node_count=len(json_values),
                    values=json_values,
                )
            else:
                domain = _cached_engine_results(
                    hash(_json.dumps(inputs.model_dump(), sort_keys=True)),
                    _json.dumps(inputs.model_dump(), sort_keys=True),
                )
                return ComputeResponse(
                    version=version,
                    node_count=len(domain),
                    values=domain,  # type: ignore[arg-type]
                )

    @app.post("/verify", response_model=VerifyResponse)
    def verify_route(
        body: VerifyRequest | None = None,
    ) -> VerifyResponse:
        engine: str | None = None
        skip_engine: bool = False
        skip_v2: bool = False
        if body is not None:
            engine = body.engine
            skip_engine = body.skip_engine
            skip_v2 = body.skip_v2

        effective_engine: str = engine or s.recalc_engine
        if not skip_engine and not _check_engine_available(effective_engine, s):
            raise HTTPException(
                status_code=503,
                detail=f"Recalc engine {effective_engine!r} is not available.",
            )

        return _verify(s, engine=engine, skip_engine=skip_engine, skip_v2=skip_v2)

    # ── Domain schema + compute ──────────────────────────────

    @app.get("/api/schema", response_model=DomainsSchemaResponse)
    def api_schema() -> DomainsSchemaResponse:
        return _build_schema_response()

    @app.post("/api/domains/compute", response_model=DomainsComputeResponse)
    def api_domains_compute(
        request: Request,
        body: DomainsComputeRequest | None = None,
    ) -> DomainsComputeResponse:
        version = body.version if body is not None else "v2"
        if version not in ("v1", "v2"):
            raise HTTPException(
                status_code=422,
                detail=f"Unknown version: {version!r}. Use 'v1' or 'v2'.",
            )
        if version == "v1":
            dag_nodes = _ensure_dag_index(request, s)
            cached = _cached_compute_v1(str(s.workbook_path), str(s.dag_path))
            return _build_domains_compute(version, dag_nodes, cached)
        else:
            # v2: build from ModelResults + schemas
            from solar_v2.engine import compute_model

            from solar_server._engine_serialize import model_results_to_compute_response

            # Merge TOML base + optional JSON overrides from request body
            overrides = body.inputs if body is not None else None
            if overrides is not None:
                inputs = _build_model_inputs(inputs_toml, overrides)
            else:
                inputs = _build_model_inputs(inputs_toml, None)

            results = compute_model(inputs)
            return model_results_to_compute_response(results)

    @app.get("/api/download/domains.xlsx")
    def api_download_xlsx(
        request: Request,
        version: str = "v2",
    ) -> StreamingResponse:
        if version not in ("v1", "v2"):
            raise HTTPException(
                status_code=422,
                detail=f"Unknown version: {version!r}. Use 'v1' or 'v2'.",
            )
        if version == "v1":
            dag_nodes = _ensure_dag_index(request, s)
            cached = _cached_compute_v1(str(s.workbook_path), str(s.dag_path))
            buf = _build_xlsx(dag_nodes, cached)
        else:
            from solar_v2.engine import compute_model

            from solar_server._engine_serialize import model_results_to_xlsx

            inputs = _build_model_inputs(inputs_toml, None)
            results = compute_model(inputs)
            buf = model_results_to_xlsx(results)

        from urllib.parse import quote

        filename = "domains.xlsx"
        content_disposition = (
            f"attachment; filename*=utf-8''{quote(filename)}"
        )
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": content_disposition},
        )

    # ── Static frontend mount ──────────────────────────────

    _static_dir = Path(__file__).parent.parent.parent / "static"
    if _static_dir.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(_static_dir), html=True),
            name="static",
        )

    @app.middleware("http")
    async def _store_settings(
        request: Request, call_next: Callable[[Request], Awaitable[object]],
    ) -> object:
        response = await call_next(request)
        return response

    return app


# Module-level app for ``uvicorn solar_server.main:app``
app: FastAPI = create_app()
