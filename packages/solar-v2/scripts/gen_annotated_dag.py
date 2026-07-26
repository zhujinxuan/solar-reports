"""Generate dag/solar.v2.annotated.yaml — v1 dag nodes + description + code_ref.

code_ref is derived from the registered step fns (their names carry the domain
concept, e.g. _row8_sales_revenue → solar_v2.pnl:sales_revenue). description
combines the sheet row label (col A/B literals) with the domain name. Literal
nodes get code_ref "input". Error nodes keep their error string in `value`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import cast

from solar_v2 import (
    balance,
    cashflow,
    cost,
    debt,
    finplan,
    invest,
    param_steps,
    pnl,
    valuation,
)
from solar_v2.params import Params
from solar_v2.pipeline import ValueView
from xlsx_core.model import Scalar
from xlsx_core.yamlutil import dump_doc, load_dag_doc

REPO = Path(__file__).resolve().parents[3]
DAG_IN = REPO / "dag" / "solar.dag.yaml"
DAG_OUT = REPO / "dag" / "solar.v2.annotated.yaml"

StepFn = Callable[[Params, ValueView], Mapping[str, Scalar]]

MODULES: dict[str, ModuleType] = {
    "param_steps": param_steps,
    "invest": invest,
    "debt": debt,
    "cost": cost,
    "pnl": pnl,
    "cashflow": cashflow,
    "finplan": finplan,
    "balance": balance,
    "valuation": valuation,
}


def _fn_ref(module: str, fn: object) -> str:
    name = getattr(fn, "__name__", "step")
    for prefix in ("_row", "_scc_", "_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    return f"solar_v2.{module}:{name}"


def _step_fn_map() -> dict[tuple[str, int], str]:
    """(sheet,row) -> code_ref for coarse and fine registered steps."""
    out: dict[tuple[str, int], str] = {}
    for mod_name, mod in MODULES.items():
        units = cast(
            "dict[tuple[str, int | tuple[int, ...]], object]",
            getattr(mod, "UNITS", {}),
        )
        for step, fn in units.items():
            sheet = step[0]
            rows = step[1] if isinstance(step[1], tuple) else (step[1],)
            for r in rows:
                out[(sheet, r)] = _fn_ref(mod_name, fn)
        fine = cast(
            "dict[tuple[str, int], object]",
            getattr(mod, "UNITS_FINE", {}),
        )
        for (sheet, row), fn in fine.items():
            out[(sheet, row)] = _fn_ref(mod_name, fn)
    return out


def main() -> None:
    dag = load_dag_doc(DAG_IN)
    labels: dict[tuple[str, int], str] = {}
    for n in dag["nodes"]:
        if (
            n["type"] == "literal"
            and n["col"] in ("A", "B")
            and isinstance(n["value"], str)
        ):
            key = (n["sheet"], n["row"])
            label = n["value"].strip()
            if label:
                labels[key] = (labels.get(key, "") + " " + label).strip()

    refs = _step_fn_map()
    missing: list[str] = []
    out_nodes = []
    for n in dag["nodes"]:
        node = dict(n)
        key = (n["sheet"], n["row"])
        label = labels.get(key, "")
        if n["type"] == "literal":
            node["description"] = label or "input"
            node["code_ref"] = "input"
        else:
            ref = refs.get(key)
            if ref is None:
                missing.append(n["id"])
                ref = "MISSING"
            domain = ref.split(":", 1)[1]
            node["description"] = f"{label} — {domain}" if label else domain
            node["code_ref"] = ref
        out_nodes.append(node)
    if missing:
        raise SystemExit(f"nodes without code_ref: {missing[:20]} ({len(missing)})")

    doc = {
        "version": dag.get("version", 1),
        "source": dag.get("source"),
        "annotated": "solar-v2 domain distillation (description + code_ref per node)",
        "nodes": out_nodes,
    }
    dump_doc(doc, DAG_OUT)
    print(f"wrote {DAG_OUT} with {len(out_nodes)} annotated nodes")


if __name__ == "__main__":
    main()
