"""Core data models for xlsx-core — frozen pydantic, immutable snapshot."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Scalar types
# ---------------------------------------------------------------------------


class ErrorValue(BaseModel):
    """An Excel error literal — true semantic value, not an exception."""

    model_config = ConfigDict(frozen=True)

    error: (
        str  # e.g. "#REF!", "#DIV/0!", "#VALUE!", "#N/A", "#NAME?", "#NULL!", "#NUM!"
    )

    def __str__(self) -> str:
        return self.error

    def __repr__(self) -> str:
        return f"ErrorValue({self.error!r})"


# The union of all possible cell values
Scalar = int | float | str | bool | None | ErrorValue


# ---------------------------------------------------------------------------
# NodeValues — immutable mapping of node_id → Scalar for compute results
# ---------------------------------------------------------------------------


class NodeValues(BaseModel):
    """Immutable key-value bag mapping node ids to their computed scalar values."""

    model_config = ConfigDict(frozen=True)

    values: dict[str, Scalar] = Field(default_factory=dict)

    def get(self, node_id: str) -> Scalar:
        return self.values.get(node_id)

    def __getitem__(self, node_id: str) -> Scalar:
        return self.values[node_id]

    def __len__(self) -> int:
        return len(self.values)

    def __iter__(self):  # noqa: ANN204
        return iter(self.values)


# ---------------------------------------------------------------------------
# DagNode
# ---------------------------------------------------------------------------


class YearSeriesMarker(BaseModel):
    """Marks a node as belonging to a year series (column-shifted identical formula)."""

    model_config = ConfigDict(frozen=True)

    key: str  # e.g. "损益!row8:G5*G7"
    index: int  # zero-based column index within the series


class DagNode(BaseModel):
    """One cell from the workbook, frozen."""

    model_config = ConfigDict(frozen=True)

    id: str  # canonical "sheet!A1"
    sheet: str  # sheet name
    col: str  # column letters, e.g. "A", "AB"
    row: int  # 1-based row number
    type: Literal["formula", "literal", "error"]
    expression: str | None = None  # formula text WITHOUT leading '='; None for literal
    value: Scalar = None  # cached value from data_only=True pass
    year_series: YearSeriesMarker | None = None


# ---------------------------------------------------------------------------
# WorkbookDag — collection of all nodes + metadata
# ---------------------------------------------------------------------------


class WorkbookDag(BaseModel):
    """Complete immutable snapshot of a workbook as a DAG of cells."""

    model_config = ConfigDict(frozen=True)

    version: int = 1
    source: str = ""  # workbook path relative to repo root
    nodes: list[DagNode] = Field(default_factory=list)
    defined_names: dict[str, str] = Field(
        default_factory=dict
    )  # name → sheet!A1 target

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    def node_by_id(self, node_id: str) -> DagNode | None:
        """Look up a node by its canonical id. O(n) — use only for small lookups."""
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None
