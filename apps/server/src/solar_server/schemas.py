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
    versions: tuple[Literal["v2"]] = ("v2",)


# ---------------------------------------------------------------------------
# Domain schemas — /api/schema, /api/domains/compute
# ---------------------------------------------------------------------------


class ItemSchemaResponse(BaseModel):
    """A single domain item in the schema response."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    unit: str
    formula: str
    inputs: tuple[str, ...]
    rows: tuple[int, ...]


class DomainSchemaResponse(BaseModel):
    """One domain in the schema response."""

    model_config = ConfigDict(frozen=True)

    key: str
    sheet: str
    label: str
    depends_on: tuple[str, ...]
    items: tuple[ItemSchemaResponse, ...]


class DomainsSchemaResponse(BaseModel):
    """GET /api/schema response."""

    model_config = ConfigDict(frozen=True)

    domains: tuple[DomainSchemaResponse, ...]


class CellValue(BaseModel):
    """One cell value from a domain item."""

    model_config = ConfigDict(frozen=True)

    node: str = ""
    col: str
    row: int
    value: ScalarJSON


class ItemCell(BaseModel):
    """A domain item with its cell values."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    unit: str
    formula: str
    inputs: tuple[str, ...]
    cells: tuple[CellValue, ...]


class DomainComputeResponse(BaseModel):
    """One domain in the /api/domains/compute response."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    sheet: str
    depends_on: tuple[str, ...]
    items: tuple[ItemCell, ...]


class DomainsComputeRequest(BaseModel):
    """POST /api/domains/compute body."""

    model_config = ConfigDict(frozen=True)

    version: str = "v2"
    inputs: dict[str, object] | None = Field(
        default=None,
        description="ModelInputs field overrides (JSON object).",
    )


class DomainsComputeResponse(BaseModel):
    """POST /api/domains/compute response."""

    model_config = ConfigDict(frozen=True)

    version: str
    domains: tuple[DomainComputeResponse, ...]
