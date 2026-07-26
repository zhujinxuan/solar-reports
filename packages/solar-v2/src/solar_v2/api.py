"""solar-v2 API — DDD-distilled domain model.

compute(settings) runs the unit pipeline (schedule.py) over the registered
context modules and returns NodeValues keyed by dag node id for the G2
node-by-node diff against solar-v1. No formula parsing/evaluation anywhere
in this path; upstream values flow through the pipeline ValueView.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from xlsx_core.model import NodeValues

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
from solar_v2.params import load_params
from solar_v2.pipeline import FineStepFn, StepFn, run_pipeline
from solar_v2.schedule import Step

if TYPE_CHECKING:
    from xlsx_core.settings import Settings

_MODULES = (
    param_steps,
    invest,
    debt,
    cost,
    pnl,
    cashflow,
    finplan,
    balance,
    valuation,
)


def _registry() -> tuple[dict[Step, StepFn], dict[tuple[str, int], FineStepFn]]:
    """All registered step fns across context modules (coarse + fine)."""
    coarse: dict[Step, StepFn] = {}
    fine: dict[tuple[str, int], FineStepFn] = {}
    for mod in _MODULES:
        coarse.update(mod.UNITS)  # type: ignore[attr-defined]
        fine.update(getattr(mod, "UNITS_FINE", {}))
    return coarse, fine


def compute(settings: Settings | None = None) -> NodeValues:
    """Run the full distilled model; one value per dag node."""
    from xlsx_core.settings import Settings as _Settings

    s = settings if settings is not None else _Settings()
    params = load_params(str(s.dag_path))
    coarse, fine = _registry()
    return run_pipeline(params, coarse, str(s.dag_path), fine_registry=fine)
