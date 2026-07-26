"""Test oracle for solar-v2 slices.

Development harness ONLY: substitutes foreign sheets' steps with cached-value
emitters so a slice can verify its own sheet against the workbook oracle
before the other slices land. The production compute() path never uses this.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import yaml
from solar_v2.params import Params
from solar_v2.pipeline import FineStepFn, ValueView
from solar_v2.schedule import STEPS, Step
from xlsx_core.model import Scalar

DAG_PATH = "dag/solar.dag.yaml"
StepFn = Callable[[Params, ValueView], Mapping[str, Scalar]]


def load_cached() -> dict[str, Scalar]:
    with open(DAG_PATH, encoding="utf-8") as f:
        dag = yaml.safe_load(f)
    return {n["id"]: n["value"] for n in dag["nodes"]}


def oracle_registry(real_sheets: set[str]) -> dict[Step, StepFn]:
    """Step registry of cached-value emitters for every COARSE step whose
    sheet is NOT in real_sheets. Values come from dag cached cells (oracle).
    """
    by_step: dict[Step, list[tuple[str, Scalar]]] = {}
    with open(DAG_PATH, encoding="utf-8") as f:
        dag = yaml.safe_load(f)
    step_of: dict[tuple[str, int], Step] = {}
    for s in STEPS:
        if len(s) == 3:
            continue  # fine steps handled by oracle_fine_registry
        rows = s[1] if isinstance(s[1], tuple) else (s[1],)
        for r in rows:
            step_of[(s[0], r)] = s
    for n in dag["nodes"]:
        if n["type"] not in ("formula", "error"):
            continue
        step = step_of.get((n["sheet"], n["row"]))
        if step is None or n["sheet"] in real_sheets:
            continue
        by_step.setdefault(step, []).append((n["id"], n["value"]))

    def make_emitter(items: list[tuple[str, Scalar]]) -> StepFn:
        def emit(params: Params, view: ValueView) -> Mapping[str, Scalar]:
            _ = params, view
            return dict(items)

        return emit

    return {step: make_emitter(items) for step, items in by_step.items()}


def oracle_fine_registry(
    real_sheets: set[str],
) -> dict[tuple[str, int], FineStepFn]:
    """Fine-step cached emitters for foreign sheets' split rows."""
    with open(DAG_PATH, encoding="utf-8") as f:
        dag = yaml.safe_load(f)
    fine_rows: set[tuple[str, int]] = set()
    for s in STEPS:
        if len(s) == 3 and s[0] not in real_sheets:
            fine_rows.add((s[0], s[1]))
    cells: dict[tuple[str, int], dict[str, Scalar]] = {}
    for n in dag["nodes"]:
        key = (n["sheet"], n["row"])
        if n["type"] in ("formula", "error") and key in fine_rows:
            cells.setdefault(key, {})[n["id"]] = n["value"]

    def make_emitter(items: dict[str, Scalar]) -> FineStepFn:
        def emit(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
            _ = params, view
            return {nid: v for nid, v in items.items() if _col_of(nid) == col}

        return emit

    return {key: make_emitter(items) for key, items in cells.items()}


def _col_of(node_id: str) -> str:
    return node_id.split("!")[1].rstrip("0123456789")


def diff_sheet(
    sheet: str,
    values: Mapping[str, Scalar],
    rel_tol: float = 1e-6,
    abs_tol: float = 1e-9,
) -> list[str]:
    """Mismatch descriptions for one sheet vs cached values (contract rule)."""
    from xlsx_core.model import ErrorValue

    cached = load_cached()
    out: list[str] = []
    prefix = f"{sheet}!"
    for nid, expected in cached.items():
        if not nid.startswith(prefix):
            continue
        got = values.get(nid)
        if isinstance(expected, str) and expected.startswith("#"):
            ok = isinstance(got, ErrorValue) and got.error == expected
            if not ok:
                out.append(f"{nid}: expected error {expected}, got {got!r}")
        elif isinstance(expected, (int, float)) and isinstance(got, (int, float)):
            if abs(got - expected) > max(rel_tol * abs(expected), abs_tol):
                out.append(f"{nid}: expected {expected}, got {got}")
        elif got != expected:
            out.append(f"{nid}: expected {expected!r}, got {got!r}")
    return out
