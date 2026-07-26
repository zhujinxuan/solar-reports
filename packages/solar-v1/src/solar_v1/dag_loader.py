"""YAML DAG loader — reads dag.yaml (nodes + defined names)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from xlsx_core.model import (
    DagNode,
    ErrorValue,
    Scalar,
    WorkbookDag,
    YearSeriesMarker,
)
from xlsx_core.yamlutil import load_dag_doc

NodeType = Literal["formula", "literal", "error"]

# Error strings that openpyxl may cache for error cells
_ERROR_SET: frozenset[str] = frozenset({
    "#REF!", "#DIV/0!", "#VALUE!", "#N/A", "#NAME?", "#NULL!", "#NUM!",
})


def _parse_node_value(raw_value: object, node_type: str) -> Scalar:
    """Convert YAML-serialized value to Scalar, detecting error strings."""
    if node_type == "error" and isinstance(raw_value, str) and raw_value in _ERROR_SET:
        return ErrorValue(error=raw_value)
    # YAML values are always int, float, str, bool, or None
    return cast(Scalar, raw_value)


def load_dag(dag_path: Path, workbook_path: Path | None = None) -> WorkbookDag:
    """Load WorkbookDag from a YAML file (nodes + defined names)."""
    _ = workbook_path  # compat: defined names now live in the dag itself
    raw = load_dag_doc(dag_path)

    nodes: list[DagNode] = []
    for n_dict in raw.get("nodes", []):
        yr_raw = n_dict.get("year_series")
        yr: YearSeriesMarker | None = None
        if yr_raw is not None:
            yr = YearSeriesMarker(
                key=str(yr_raw["key"]),  # type: ignore[arg-type]
                index=int(str(yr_raw["index"])),
            )

        nodes.append(
            DagNode(
                id=n_dict["id"],
                sheet=n_dict["sheet"],
                col=n_dict["col"],
                row=n_dict["row"],
                type=cast(NodeType, n_dict["type"]),
                expression=n_dict.get("expression"),
                value=_parse_node_value(n_dict.get("value"), n_dict["type"]),
                year_series=yr,
            )
        )

    return WorkbookDag(
        version=raw.get("version", 1),
        source=raw.get("source", ""),
        nodes=nodes,
        defined_names=raw.get("defined_names", {}),
    )
