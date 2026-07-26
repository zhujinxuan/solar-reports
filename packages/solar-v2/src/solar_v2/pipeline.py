"""Pipeline — executes the static unit schedule against registered step fns.

Each sheet module registers `UNITS: dict[Step, StepFn]`; the pipeline runs
STEPS in order, accumulating node values. Step fns receive (params, view)
where view reads every value computed so far (plus all literal givens).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, cast

from xlsx_core.model import NodeValues, Scalar
from xlsx_core.yamlutil import load_dag_doc

from solar_v2.params import Params
from solar_v2.schedule import STEPS, Step


class ValueView(Protocol):
    """Read-only access to values computed so far (literals + prior steps)."""

    def get(self, node_id: str) -> Scalar:
        """Value of one node, e.g. view.get("损益!G8"). None if blank/absent."""
        ...

    def row(self, sheet: str, row: int) -> dict[str, Scalar]:
        """All computed values of one sheet row, keyed by column letter."""
        ...


StepFn = Callable[[Params, ValueView], Mapping[str, Scalar]]
StepRegistry = Mapping[Step, StepFn]
FineStepFn = Callable[[Params, ValueView, str], Mapping[str, Scalar]]
FineStepRegistry = Mapping[tuple[str, int], FineStepFn]


class _Store:
    """Mutable accumulation behind the frozen ValueView facade."""

    def __init__(self, literals: Mapping[str, Scalar]) -> None:
        self._values: dict[str, Scalar] = dict(literals)

    def get(self, node_id: str) -> Scalar:
        return self._values.get(node_id)

    def row(self, sheet: str, row: int) -> dict[str, Scalar]:
        prefix = f"{sheet}!"
        suffix = str(row)
        return {
            nid[len(prefix) : -len(suffix)]: v
            for nid, v in self._values.items()
            if nid.startswith(prefix) and nid.endswith(suffix)
        }

    def put_all(self, values: Mapping[str, Scalar]) -> None:
        self._values.update(values)

    def values_snapshot(self) -> Mapping[str, Scalar]:
        return dict(self._values)


def load_literals(dag_path: str) -> dict[str, Scalar]:
    """All literal-node values (the givens) from the extracted dag."""
    dag = load_dag_doc(dag_path)
    out: dict[str, Scalar] = {}
    for n in dag["nodes"]:
        if n["type"] == "literal":
            out[n["id"]] = cast(Scalar, n["value"])
    return out


def _dag_node_ids(dag_path: str) -> set[str]:
    dag = load_dag_doc(dag_path)
    return {n["id"] for n in dag["nodes"]}


def run_pipeline(
    params: Params,
    registry: StepRegistry,
    dag_path: str,
    steps: tuple[Step, ...] = STEPS,
    fine_registry: FineStepRegistry | None = None,
) -> NodeValues:
    """Execute the schedule. Every step MUST have a registered fn.

    Coarse steps (sheet, row)/(sheet, (rows)) dispatch via registry[step];
    fine steps (sheet, row, col) dispatch via fine_registry[(sheet, row)](
    params, view, col).
    """
    fine: FineStepRegistry = fine_registry if fine_registry is not None else {}
    store = _Store(load_literals(dag_path))
    missing: list[Step] = []
    for s in steps:
        if len(s) == 3:
            if (s[0], s[1]) not in fine:
                missing.append(s)
        elif s not in registry:
            missing.append(s)
    if missing:
        raise KeyError(f"Unregistered steps: {missing[:10]} ({len(missing)} total)")
    for step in steps:
        if len(step) == 3:
            sheet, row, col = step
            store.put_all(fine[(sheet, row)](params, store, col))
        else:
            store.put_all(registry[step](params, store))
    node_ids = _dag_node_ids(dag_path)
    snapshot = {
        k: v for k, v in store.values_snapshot().items() if k in node_ids
    }
    return NodeValues(values=dict(snapshot))
