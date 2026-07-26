"""YAML DAG loader — reads dag.yaml and augments with defined names from workbook.

xlsx-core's _write_dag_yaml omits defined_names from the serialized YAML
(see extract.py), so we load them from the workbook snapshot. This is the
bridge: fast YAML read for nodes, workbook read for name bindings.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml
from xlsx_core.loader import load_workbook
from xlsx_core.model import (
    DagNode,
    ErrorValue,
    Scalar,
    WorkbookDag,
    YearSeriesMarker,
)

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


def load_dag(dag_path: Path, workbook_path: Path) -> WorkbookDag:
    """Load WorkbookDag from a YAML file, enriching with workbook defined names.

    Args:
        dag_path: Path to the dag.yaml file.
        workbook_path: Path to the source workbook (for defined names).

    Returns:
        A fully-populated WorkbookDag.
    """
    with open(str(dag_path), encoding="utf-8") as f:
        raw: dict = yaml.safe_load(f)

    nodes: list[DagNode] = []
    for n_dict in raw.get("nodes", []):
        yr_raw = n_dict.get("year_series")
        yr: YearSeriesMarker | None = None
        if yr_raw is not None:
            yr = YearSeriesMarker(key=yr_raw["key"], index=yr_raw["index"])

        nodes.append(
            DagNode(
                id=n_dict["id"],
                sheet=n_dict["sheet"],
                col=n_dict["col"],
                row=n_dict["row"],
                type=n_dict["type"],
                expression=n_dict.get("expression"),
                value=_parse_node_value(n_dict.get("value"), n_dict["type"]),
                year_series=yr,
            )
        )

    # Load defined names from the workbook (not in YAML)
    snapshot = load_workbook(workbook_path)

    return WorkbookDag(
        version=raw.get("version", 1),
        source=raw.get("source", str(workbook_path)),
        nodes=nodes,
        defined_names=snapshot.defined_names,
    )
