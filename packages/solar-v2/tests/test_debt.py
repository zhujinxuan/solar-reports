"""Debt slice test: 还贷 + 参数表 + 投资计划 against the workbook oracle.

Foreign sheets are substituted by cached-value emitters (tests/helpers.py);
the real debt units must reproduce every cached node of 还贷 exactly.
"""

from __future__ import annotations

import helpers
from solar_v2 import debt, invest, param_steps
from solar_v2.params import load_params
from solar_v2.pipeline import FineStepRegistry, StepFn, run_pipeline
from solar_v2.schedule import Step
from xlsx_core.model import NodeValues, Scalar

REAL_SHEETS = {"还贷", "参数表", "投资计划"}


def _run() -> NodeValues:
    registry: dict[Step, StepFn] = {}
    registry.update(helpers.oracle_registry(REAL_SHEETS))
    registry.update(param_steps.UNITS)
    registry.update(invest.UNITS)
    registry.update(debt.UNITS)
    fine: FineStepRegistry = {}
    fine.update(helpers.oracle_fine_registry(REAL_SHEETS))
    fine.update(debt.UNITS_FINE)
    params = load_params(helpers.DAG_PATH)
    return run_pipeline(params, registry, helpers.DAG_PATH, fine_registry=fine)


def _values() -> dict[str, Scalar]:
    return dict(_run().values)


def test_debt_sheet_matches_oracle() -> None:
    mismatches = helpers.diff_sheet("还贷", _values())
    assert mismatches == [], f"{len(mismatches)} mismatches: {mismatches[:20]}"
