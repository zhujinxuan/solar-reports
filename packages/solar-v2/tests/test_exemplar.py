"""Exemplar slice test: 参数表 + 投资计划 against the workbook oracle.

Foreign sheets are substituted by cached-value emitters (tests/helpers.py);
the real param_steps + invest units must reproduce every cached node of
their sheets exactly (contract matching rule).
"""

from __future__ import annotations

import helpers
from solar_v2 import invest, param_steps
from solar_v2.params import load_params
from solar_v2.pipeline import StepFn, run_pipeline
from solar_v2.schedule import Step
from xlsx_core.model import NodeValues, Scalar

REAL_SHEETS = {"参数表", "投资计划"}


def _run() -> NodeValues:
    registry: dict[Step, StepFn] = {}
    registry.update(helpers.oracle_registry(REAL_SHEETS))
    registry.update(param_steps.UNITS)
    registry.update(invest.UNITS)
    fine = helpers.oracle_fine_registry(REAL_SHEETS)
    params = load_params(helpers.DAG_PATH)
    return run_pipeline(params, registry, helpers.DAG_PATH, fine_registry=fine)


def _values() -> dict[str, Scalar]:
    return dict(_run().values)


def test_params_sheet_matches_oracle() -> None:
    mismatches = helpers.diff_sheet("参数表", _values())
    assert mismatches == [], f"{len(mismatches)} mismatches: {mismatches[:20]}"


def test_invest_sheet_matches_oracle() -> None:
    mismatches = helpers.diff_sheet("投资计划", _values())
    assert mismatches == [], f"{len(mismatches)} mismatches: {mismatches[:20]}"
