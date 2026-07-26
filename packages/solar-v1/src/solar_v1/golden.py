"""Golden check — compare interpreted values against workbook cached values.

The contract matching rule (from xlsx_core.evaluator._numbers_equal):
- Numbers: abs(a-b) <= max(rel_tol * abs(b), abs_tol)
- Strings, bools: exact equality
- ErrorValue: same error string
- None vs None: equal
- Mixed types: not equal
"""

from __future__ import annotations

from math import isfinite

from pydantic import BaseModel, ConfigDict
from xlsx_core.model import ErrorValue, NodeValues, Scalar, WorkbookDag
from xlsx_core.settings import Settings


class Mismatch(BaseModel):
    """A single golden-check mismatch."""

    node_id: str
    expected: Scalar
    got: Scalar


class GoldenReport(BaseModel):
    """Result of golden-checking interpreted values against cached values."""

    model_config = ConfigDict(frozen=True)

    total_formula_nodes: int
    mismatch_count: int
    mismatches: tuple[Mismatch, ...]


def _numbers_equal(
    a: float,
    b: float,
    rel_tol: float = 1e-6,
    abs_tol: float = 1e-9,
) -> bool:
    """Check if two floats match within tolerances."""
    diff = abs(a - b)
    if not isfinite(diff):
        return a == b
    return diff <= max(rel_tol * abs(b), abs_tol)


def _scalars_match(a: Scalar, b: Scalar, rel_tol: float, abs_tol: float) -> bool:
    """Check if two scalars match per the contract rule."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False

    if isinstance(a, ErrorValue) and isinstance(b, ErrorValue):
        return a.error == b.error
    if isinstance(a, ErrorValue) or isinstance(b, ErrorValue):
        return False

    if isinstance(a, bool) and isinstance(b, bool):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return False

    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _numbers_equal(float(a), float(b), rel_tol, abs_tol)

    if isinstance(a, str) and isinstance(b, str):
        return a == b

    return a == b


def golden_check(
    values: NodeValues,
    dag: WorkbookDag,
    settings: Settings,
) -> GoldenReport:
    """Compare interpreted values against workbook cached values.

    Checks every formula and error node in the DAG. Literal nodes
    are excluded (they're identity-mapped during interpretation).

    Args:
        values: Computed NodeValues from interpret().
        dag: The workbook DAG with cached values as oracle.
        settings: Tolerances for numeric comparison.

    Returns:
        GoldenReport with mismatch details.
    """
    mismatches: list[Mismatch] = []
    formula_count = 0

    for node in dag.nodes:
        if node.type not in ("formula", "error"):
            continue
        formula_count += 1

        computed = values.values.get(node.id)
        expected = node.value

        if not _scalars_match(computed, expected, settings.rel_tol, settings.abs_tol):
            mismatches.append(
                Mismatch(
                    node_id=node.id,
                    expected=expected,
                    got=computed,
                )
            )

    return GoldenReport(
        total_formula_nodes=formula_count,
        mismatch_count=len(mismatches),
        mismatches=tuple(mismatches),
    )
