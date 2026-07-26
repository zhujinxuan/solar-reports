"""G2 integration test: full pipeline, NO oracle, vs workbook cached values.

This is the distilled model's golden check: every node of every sheet must
match the cached values through pure domain computation (v1 matches cached
at 0/5059, so cached equivalence = v1 equivalence; the formal v1-vs-v2 diff
runs via `solar-cli verify` path 1.2).
"""

from __future__ import annotations

import helpers
from solar_v2.api import compute
from xlsx_core.model import ErrorValue

SHEETS = [
    "参数表",
    "投资计划",
    "还贷",
    "成本",
    "损益",
    "现金流量",
    "财务计划",
    "资产负债",
    "估值结果",
    "指标汇总",
]


def test_full_pipeline_zero_diff() -> None:
    values = dict(compute().values)
    for sheet in SHEETS:
        mismatches = helpers.diff_sheet(sheet, values)
        assert mismatches == [], (
            f"{sheet}: {len(mismatches)} mismatches: {mismatches[:15]}"
        )


def test_error_nodes_reproduced() -> None:
    values = compute().values
    expected = {
        "损益!D4": "#REF!",
        "损益!E4": "#REF!",
        "财务计划!U36": "#DIV/0!",
        "财务计划!AD36": "#REF!",
    }
    for nid, err in expected.items():
        got = values[nid]
        assert isinstance(got, ErrorValue) and got.error == err, f"{nid}: {got!r}"
    assert values["财务计划!E36"] == 0 or values["财务计划!E36"] == 0.0
