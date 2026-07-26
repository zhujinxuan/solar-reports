"""RecalcEngine port and support types for xlsx-core."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from typing import TypeIs


# ---------------------------------------------------------------------------
# RecalcEngine port
# ---------------------------------------------------------------------------


class RecalcEngine(Protocol):
    """Protocol for recalculation engines — any adapter that recalculates a workbook."""

    name: str

    def recalc(self, workbook: Path, out_dir: Path) -> RecalcResult: ...


# ---------------------------------------------------------------------------
# RecalcResult
# ---------------------------------------------------------------------------


class RecalcResult(BaseModel):
    """Result of a recalculation engine run against a workbook.

    `ok` is True when the engine ran without errors AND produced a recalculated
    workbook at `recalced_path`.  Individual cell mismatches (checked separately
    by the benchmark against cached values) do NOT affect `ok`.
    """

    engine: str
    ok: bool
    wall_seconds: float
    mismatch_count: int = 0
    total_compared: int = 0
    errors: tuple[str, ...] = Field(default_factory=tuple)
    recalced_path: Path | None = None


# ---------------------------------------------------------------------------
# Comparison helpers (local — do NOT import from xlsx_core.model until settled)
# ---------------------------------------------------------------------------


def _is_numeric(v: object) -> TypeIs[int | float]:
    """Return True for int or float (NOT bool — bools compare exactly)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_error_string(v: object) -> bool:
    """Return True for Excel error strings like '#REF!', '#VALUE!', etc."""
    return (
        isinstance(v, str)
        and v.startswith("#")
        and v.endswith(("!", "?"))
        and len(v) <= 16
    )


def compare_values(
    a: object,
    b: object,
    *,
    rel_tol: float = 1e-6,
    abs_tol: float = 1e-9,
) -> bool:
    """Compare two cell values using the golden-check rule.

    - Numbers: abs(a-b) <= max(rel_tol * abs(b), abs_tol)
    - Strings, bools, datetimes: exact equality
    - Excel error strings (#REF!, #VALUE!, etc.): must be the same error string
    - None vs None: equal
    - Mixed types: not equal
    """
    # None equality
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False

    # Numeric comparison (excluding bool)
    if _is_numeric(a) and _is_numeric(b):
        diff = abs(a - b)
        if not isfinite(diff):
            # both inf or both -inf or both nan — compare directly
            return a == b
        threshold = max(rel_tol * abs(b), abs_tol)
        return diff <= threshold

    # Excel error strings
    if _is_error_string(a) and _is_error_string(b):
        return a == b

    # datetimes
    if isinstance(a, datetime) and isinstance(b, datetime):
        return a == b

    # All other types — exact equality (strings, bools, etc.)
    return a == b
