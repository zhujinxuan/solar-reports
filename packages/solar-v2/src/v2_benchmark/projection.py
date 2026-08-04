"""Project computed ModelResults into dag node-id → value mapping.

Walks the cell layout (layout.py) and reads values from the typed
ModelResults produced by the solar-v2 engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from v2_benchmark.layout import CellSource, resolve_node

if TYPE_CHECKING:
    from solar_v2.results import ModelResults


def project(
    results: ModelResults, dag_path: str = "dag/solar.dag.yaml"
) -> dict[str, float | str]:
    """Project all formula/error dag nodes to their computed values.

    Reads values from the typed ModelResults dataclass:
    - results.<domain>.frame for year-series items
    - results.<domain>.scalars for scalar items
    - results.valuation.income_frame / market_frame for valuation axes
    - results.finplan.error_checks for error-check items

    Returns {node_id: value} where value is float | str (for errors).
    """


    import yaml

    output: dict[str, float | str] = {}

    # Load dag node set
    with open(dag_path, encoding="utf-8") as f:
        dag = yaml.safe_load(f)

    fe_nodes = [n["id"] for n in dag["nodes"] if n.get("type") in ("formula", "error")]

    for node_id in fe_nodes:
        try:
            cs = resolve_node(node_id)
        except (KeyError, ValueError):
            continue  # Skip unresolvable nodes (layout gap)

        if cs.error is not None:
            output[node_id] = cs.error
            continue

        value = _read_source(cs, results)
        output[node_id] = value

    return output


def _read_source(cs: CellSource, results: ModelResults) -> float | str:
    """Read a single value from ModelResults using a CellSource."""
    domain_result = getattr(results, cs.domain, None)
    if domain_result is None:
        raise KeyError(f"Domain result not found: {cs.domain}")

    # Scalar
    if cs.scalar_field is not None:
        scalars = getattr(domain_result, "scalars", None)
        if scalars is None:
            raise AttributeError(
                f"Domain {cs.domain} has no scalars attribute"
            )
        v = getattr(scalars, cs.scalar_field)
        return v if isinstance(v, str) else float(v)

    # Year-series
    if cs.year_idx is not None:
        # Special: finplan error_checks comes from error_checks attribute
        if cs.domain == "finplan" and cs.item_key == "error_checks":
            error_checks = getattr(domain_result, "error_checks", None)
            if error_checks is not None:
                if cs.year_idx < 0:
                    if len(error_checks) > 0:
                        ec = error_checks[0]
                        return ec.error if ec.error else float(ec.value)
                    return "#REF!"
                if cs.year_idx >= len(error_checks):
                    return "#REF!"
                ec = error_checks[cs.year_idx]
                return ec.error if ec.error else float(ec.value)
            return "#REF!"

        frame = _frame_of(domain_result, cs.item_key)
        col = frame[cs.item_key]
        if cs.year_idx < 0:
            # Construction-year column: 26-row frames hold it at index 0
            if len(col) > 0:
                return float(col[0])
            return 0.0
        if cs.year_idx >= len(col):
            return 0.0
        return float(col[cs.year_idx])
    # Aggregate
    if cs.agg is not None:
        if cs.agg == "sumof":
            total = 0.0
            for key in cs.item_key.split("+"):
                total += float(_frame_of(domain_result, key)[key].sum())
            return total
        if cs.agg == "neg":
            return float(-_frame_of(domain_result, cs.item_key)[cs.item_key].sum())
        if cs.agg == "const":
            return float(cs.item_key)
        if cs.agg == "axis":
            if cs.item_key == "construction_year":
                return float(results.params.axis.construction_year)
            raise ValueError(f"Unknown axis attribute: {cs.item_key}")
        frame = _frame_of(domain_result, cs.item_key)
        col = frame[cs.item_key]
        return _compute_agg(col, cs.agg)

    raise ValueError(f"Unresolvable CellSource: {cs}")


def _frame_of(domain_result: object, key: str) -> pl.DataFrame:
    """The domain frame holding column `key` (frame/income/market)."""
    _frame: object
    for attr in ("frame", "income", "market"):
        _frame = getattr(domain_result, attr, None)
        if _frame is not None and key in _frame.columns:
            return _frame  # type: ignore[return-value]
    raise AttributeError(
        f"No frame with column {key!r} on {type(domain_result).__name__}"
    )


def _compute_agg(values: list[float] | pl.Series, kind: str) -> float:
    """Compute an aggregate over a Polars Series."""

    arr: list[float] = (
        [float(v) for v in values.to_list()]
        if isinstance(values, pl.Series)
        else [float(v) for v in values]
    )

    if not arr:
        return 0.0

    if kind == "sum":
        return float(sum(arr))
    elif kind == "sumop":
        return float(sum(arr[1:]))  # skip construction-year row
    elif kind == "sum20":
        return float(sum(arr[1:21]))  # first 20 operating years
    elif kind == "sumf2":
        return float(sum(arr[2:]))  # skip construction + first op year
    elif kind == "average":
        return float(sum(arr) / len(arr))
    elif kind == "min":
        return float(min(arr))
    elif kind == "max":
        return float(max(arr))
    elif kind == "first":
        return float(arr[0])
    elif kind == "last":
        return float(arr[-1])
    elif kind == "echo":
        return float(arr[-1])  # Last value echo
    else:
        raise ValueError(f"Unknown aggregate kind: {kind}")
