"""FastAPI app for solar-server — serves solar-v1 and solar-v2 compute + verify.

Caching strategy: ``functools.lru_cache`` on frozen positional args.
NodeValues is immutable (frozen pydantic model), so cached snapshots are safe
to hand out.  Settings-fingerprint = ``(version, workbook_path, dag_path)``.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import NamedTuple, cast

from fastapi import FastAPI, HTTPException, Request
from xlsx_core.model import Scalar
from xlsx_core.settings import Settings

from solar_server.schemas import (
    ComputeRequest,
    ComputeResponse,
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
# Cached compute
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=8)
def _cached_compute(
    version: str,
    workbook_path: str,
    dag_path: str,
) -> dict[str, object]:
    """Run compute for the given version+paths, return {node_id: Scalar}.

    ``lru_cache`` keyed on individual positional args. NodeValues is immutable
    so sharing cached results across requests is safe.
    """
    settings = Settings(workbook_path=workbook_path, dag_path=dag_path)  # type: ignore[call-arg]

    if version == "v1":
        from solar_v1.api import compute as v1_compute

        result = v1_compute(settings)
    elif version == "v2":
        from solar_v2.api import compute as v2_compute

        result = v2_compute(settings)
    else:
        raise ValueError(f"Unknown version: {version}")

    return dict(result.values)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: xlsx-core Settings. Uses defaults if None.

    Returns:
        Configured FastAPI app.
    """
    app = FastAPI(title="solar-server", version="0.1.0")

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

        s = settings or Settings()
        cached = _cached_compute(version, str(s.workbook_path), str(s.dag_path))

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

    @app.post("/verify", response_model=VerifyResponse)
    def verify_route(
        body: VerifyRequest | None = None,
    ) -> VerifyResponse:
        s = settings or Settings()
        engine: str | None = None
        skip_engine: bool = False
        skip_v2: bool = False
        if body is not None:
            engine = body.engine
            skip_engine = body.skip_engine
            skip_v2 = body.skip_v2

        # 503 if engine requested but unavailable
        effective_engine: str = engine or s.recalc_engine
        if not skip_engine and not _check_engine_available(effective_engine, s):
            raise HTTPException(
                status_code=503,
                detail=f"Recalc engine {effective_engine!r} is not available.",
            )

        return _verify(s, engine=engine, skip_engine=skip_engine, skip_v2=skip_v2)

    @app.middleware("http")
    async def _store_settings(
        request: Request, call_next: Callable[[Request], Awaitable[object]],
    ) -> object:
        # Extension point: per-request settings override (not used yet).
        response = await call_next(request)
        return response

    return app


# Module-level app for ``uvicorn solar_server.main:app``
app: FastAPI = create_app()
