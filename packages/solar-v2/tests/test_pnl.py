"""Test 损益 (PnL) slice against workbook oracle."""

from __future__ import annotations

import helpers
from solar_v2 import invest, param_steps, pnl
from solar_v2.params import load_params
from solar_v2.pipeline import FineStepFn, StepFn, run_pipeline
from solar_v2.schedule import Step
from xlsx_core.model import NodeValues, Scalar

REAL_SHEETS = {"损益", "参数表", "投资计划"}


def _run() -> NodeValues:
    registry: dict[Step, StepFn] = {}
    registry.update(helpers.oracle_registry(REAL_SHEETS))
    registry.update(param_steps.UNITS)
    registry.update(invest.UNITS)
    registry.update(pnl.UNITS)

    fine: dict[tuple[str, int], FineStepFn] = {}
    fine.update(helpers.oracle_fine_registry(REAL_SHEETS))
    fine.update(pnl.UNITS_FINE)

    params = load_params(helpers.DAG_PATH)
    return run_pipeline(params, registry, helpers.DAG_PATH, fine_registry=fine)


def _values() -> dict[str, Scalar]:
    return dict(_run().values)


def test_pnl_sheet_matches_oracle() -> None:
    mismatches = helpers.diff_sheet("损益", _values())
    assert mismatches == [], f"{len(mismatches)} mismatches: {mismatches[:30]}"
