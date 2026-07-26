"""Valuation + KPI slice test: 估值结果 + 指标汇总 against the workbook oracle."""

from __future__ import annotations

import helpers
from solar_v2 import invest, param_steps, valuation
from solar_v2.params import load_params
from solar_v2.pipeline import StepFn, run_pipeline
from solar_v2.schedule import Step
from xlsx_core.model import NodeValues, Scalar

REAL_SHEETS = {"估值结果", "指标汇总", "参数表", "投资计划"}


def _run() -> NodeValues:
    registry: dict[Step, StepFn] = {}
    registry.update(helpers.oracle_registry(REAL_SHEETS))
    registry.update(param_steps.UNITS)
    registry.update(invest.UNITS)
    registry.update(valuation.UNITS)
    params = load_params(helpers.DAG_PATH)
    fine = helpers.oracle_fine_registry(REAL_SHEETS)
    return run_pipeline(params, registry, helpers.DAG_PATH, fine_registry=fine)


def _values() -> dict[str, Scalar]:
    return dict(_run().values)


def test_valuation_sheet_matches_oracle() -> None:
    mismatches = helpers.diff_sheet("估值结果", _values())
    assert mismatches == [], f"{len(mismatches)} mismatches: {mismatches[:30]}"


def test_kpi_sheet_matches_oracle() -> None:
    mismatches = helpers.diff_sheet("指标汇总", _values())
    assert mismatches == [], f"{len(mismatches)} mismatches: {mismatches[:30]}"
