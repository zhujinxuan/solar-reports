"""Frozen pydantic schemas for solar-server request/response bodies.

All I/O types live here — no business logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from xlsx_core.model import ErrorValue, Scalar

# ---------------------------------------------------------------------------
# ScalarJSON — JSON-safe representation of Scalar
# ---------------------------------------------------------------------------


class ErrorMarker(BaseModel):
    """JSON marker for ErrorValue — {"error": "#REF!"}."""

    model_config = ConfigDict(frozen=True)

    error: str


# Union of all JSON-serializable scalar forms
ScalarJSON = (
    float | int | str | bool | None | ErrorMarker
)


def scalar_to_json(value: Scalar) -> ScalarJSON:
    """Convert a Scalar to its JSON-safe representation."""
    if value is None:
        return None
    if isinstance(value, ErrorValue):
        return ErrorMarker(error=value.error)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """GET /health response."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    versions: tuple[Literal["v1", "v2"], Literal["v1", "v2"]] = ("v1", "v2")  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------


class ComputeRequest(BaseModel):
    """POST /compute/{version} optional body — filter by node_ids."""

    model_config = ConfigDict(frozen=True)

    node_ids: tuple[str, ...] | None = Field(
        default=None,
        description="If provided, return only these node ids.",
    )


class ComputeResponse(BaseModel):
    """POST /compute/{version} response."""

    model_config = ConfigDict(frozen=True)

    version: str
    node_count: int
    values: dict[str, ScalarJSON]


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


class VerifyRequest(BaseModel):
    """POST /verify optional body."""

    model_config = ConfigDict(frozen=True)

    engine: str | None = Field(
        default=None,
        description="Recalc engine name (e.g. 'excel-com'). Default from Settings.",
    )
    skip_engine: bool = Field(
        default=False,
        description="Skip path 1.1 (recalc + compare).",
    )
    skip_v2: bool = Field(
        default=False,
        description="Skip path 1.2 (v1 vs v2 comparison).",
    )


class MismatchJSON(BaseModel):
    """A single mismatch, JSON-safe."""

    model_config = ConfigDict(frozen=True)

    node_id: str
    expected: ScalarJSON
    got: ScalarJSON


class Path11Result(BaseModel):
    """Path 1.1 result: recalc engine vs v1."""

    model_config = ConfigDict(frozen=True)

    engine: str
    ok: bool
    mismatch_count: int
    total: int
    sample_mismatches: tuple[MismatchJSON, ...] = Field(default_factory=tuple)


class Path11Skipped(BaseModel):
    """Path 1.1 skipped marker."""

    model_config = ConfigDict(frozen=True)

    skipped: Literal[True] = True


class Path12Result(BaseModel):
    """Path 1.2 result: v1 vs v2."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    mismatch_count: int
    total: int
    sample_mismatches: tuple[MismatchJSON, ...] = Field(default_factory=tuple)


class VerifyResponse(BaseModel):
    """POST /verify response."""

    model_config = ConfigDict(frozen=True)

    path_1_1: Path11Result | Path11Skipped
    path_1_2: Path12Result | None = None
    ok: bool
