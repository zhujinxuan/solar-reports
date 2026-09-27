"""FastAPI app for solar-server — serves solar-v2 compute only.

The server is a thin shell over the solar-v2 domain engine
(``ModelInputs -> compute_model -> ModelResults``): no dag, no workbook,
no formula parser in its compute path. The golden check (v1 vs workbook,
v2 vs v1) is a dev-loop tool — it lives in ``packages/solar-v1``, the CLI
(``solar-cli verify``), and the package test suites, not in this binary.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from solar_v2.inputs import ModelInputs

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope
from xlsx_core.settings import Settings

from solar_server.domains import _build_schema_response
from solar_server.schemas import (
    DomainsComputeRequest,
    DomainsComputeResponse,
    DomainsSchemaResponse,
    HealthResponse,
)


class _RevalidatedStaticFiles(StaticFiles):
    """StaticFiles that force revalidation on every load.

    ``Cache-Control: no-cache`` makes the browser revalidate via ETag
    (cheap 304 when unchanged) instead of heuristic caching — without it a
    deploy can leave a stale app.js in the browser while the new index.html
    references behavior the old script does not have (hit 2026-09-27).
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response

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


def _resolve_url_prefix(url_prefix: str | None) -> str:
    """Normalize the URL prefix; '' serves the app at root.

    Explicit argument wins; otherwise the ``SOLAR_URL_PREFIX`` env var.
    """
    raw = (
        os.environ.get("SOLAR_URL_PREFIX", "")
        if url_prefix is None
        else url_prefix
    )
    prefix = raw.strip().rstrip("/")
    if prefix and not prefix.startswith("/"):
        prefix = "/" + prefix
    return prefix


def create_app(
    settings: Settings | None = None,
    url_prefix: str | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: xlsx-core Settings override. Uses defaults if None. Only
            ``inputs_toml`` is read (env ``XLSX_INPUTS_TOML``).
        url_prefix: path prefix to mount the app under (e.g. ``/solar-report``).
            ``None`` reads env ``SOLAR_URL_PREFIX``; default serves at root.
    """
    app = FastAPI(title="solar-server", version="0.2.0")

    s = settings or Settings()
    inputs_toml: str | None = getattr(s, "inputs_toml", None) or None

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/api/schema", response_model=DomainsSchemaResponse)
    def api_schema() -> DomainsSchemaResponse:
        return _build_schema_response()

    @app.post("/api/domains/compute", response_model=DomainsComputeResponse)
    def api_domains_compute(
        body: DomainsComputeRequest | None = None,
    ) -> DomainsComputeResponse:
        version = body.version if body is not None else "v2"
        if version != "v2":
            raise HTTPException(
                status_code=422,
                detail=f"Unknown version: {version!r}. Only 'v2' is served.",
            )
        from solar_v2.engine import compute_model

        from solar_server._engine_serialize import model_results_to_compute_response

        # Merge TOML base + optional JSON overrides from request body
        overrides = body.inputs if body is not None else None
        inputs = _build_model_inputs(inputs_toml, overrides)
        results = compute_model(inputs)
        return model_results_to_compute_response(results)

    @app.get("/api/download/domains.xlsx")
    def api_download_xlsx(
        version: str = "v2",
    ) -> StreamingResponse:
        if version != "v2":
            raise HTTPException(
                status_code=422,
                detail=f"Unknown version: {version!r}. Only 'v2' is served.",
            )
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
            _RevalidatedStaticFiles(directory=str(_static_dir), html=True),
            name="static",
        )

    prefix = _resolve_url_prefix(url_prefix)
    if not prefix:
        return app
    root = FastAPI(title="solar-server (root)")
    root.mount(prefix, app)
    return root


# Module-level app for ``uvicorn solar_server.main:app``
app: FastAPI = create_app()
