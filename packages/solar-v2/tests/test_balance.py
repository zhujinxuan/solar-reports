"""Balance sheet slice test: 资产负债 against the workbook oracle.

Foreign sheets are substituted by cached-value emitters (tests/helpers.py).
"""

from __future__ import annotations

import helpers
from solar_v2 import balance
from solar_v2.params import load_params
from solar_v2.pipeline import StepFn, run_pipeline
from solar_v2.schedule import Step
from xlsx_core.model import NodeValues, Scalar

REAL_SHEETS = {"资产负债"}


def _run() -> NodeValues:
    registry: dict[Step, StepFn] = {}
    registry.update(helpers.oracle_registry(REAL_SHEETS))
    registry.update(balance.UNITS)
    params = load_params(helpers.DAG_PATH)
    fine = helpers.oracle_fine_registry(REAL_SHEETS)
    return run_pipeline(params, registry, helpers.DAG_PATH, fine_registry=fine)


def _values() -> dict[str, Scalar]:
    return dict(_run().values)


def test_balance_sheet_matches_oracle() -> None:
    mismatches = helpers.diff_sheet("资产负债", _values())
    assert mismatches == [], f"{len(mismatches)} mismatches: {mismatches[:20]}"
