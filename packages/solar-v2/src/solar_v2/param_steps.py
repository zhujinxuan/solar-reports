"""参数表 step fns — scalar echoes, year-axis series, land-rent schedule.

Owns the 参数表 units in the schedule. Year-axis = 26 columns C..AB
(2020 construction year + 2021..2045 operating years).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping

import polars as pl
from xlsx_core.model import Scalar

from solar_v2.cols import col_letters
from solar_v2.params import Params
from solar_v2.pipeline import ValueView
from solar_v2.schedule import Step

StepFn = Callable[[Params, ValueView], Mapping[str, Scalar]]

SHEET = "参数表"
# C..AB — the 26 year columns (construction year + 25 operating years)
YEAR_COLS = col_letters("C", 26)


def _nid(col: str, row: int) -> str:
    return f"{SHEET}!{col}{row}"


def _scalar_step(field: str, row: int) -> StepFn:
    """Step emitting one scalar cell C<row> from a Params field."""

    def step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
        _ = view
        return {_nid("C", row): getattr(params, field)}

    return step


def _years_copy_step(row: int) -> StepFn:
    """Rows 12/51/66: the modeler copies the year row (=C4 across)."""

    def step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
        _ = view
        return {
            _nid(c, row): float(y)
            for c, y in zip(YEAR_COLS, params.years, strict=True)
        }

    return step


def _load_rate_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 6: 负荷率 — C6 literal 0, D6 = 100%*0.95, E6:AB6 literals 1."""
    _ = params, view
    return {_nid("D", 6): 1.0 * 0.95}


def _payment_period_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 67: land-rent payment period index INT((year-first)/freq)+1."""
    _ = view
    first = params.years[0]
    freq = params.rent_payment_freq
    return {
        _nid(c, 67): float(math.floor((y - first) / freq) + 1)
        for c, y in zip(YEAR_COLS, params.years, strict=True)
    }


def _land_rent_frame(params: Params) -> pl.DataFrame:
    """Land-rent year-series (rows 66-69) as one polars frame — the domain
    computation behind the payment/amortization schedule."""
    first = params.years[0]
    years = list(params.years)
    frame = pl.DataFrame({"year": years}).with_columns(
        period=((pl.col("year") - first) / params.rent_payment_freq).cast(pl.Float64),
        escalation_period=((pl.col("year") - first) / params.rent_escalation_freq)
        .floor()
        .cast(pl.Float64),
    )
    frame = frame.with_columns(
        period_index=pl.col("period").floor() + 1,
        amortization=params.first_year_land_rent
        * (1 + params.rent_escalation_rate) ** pl.col("escalation_period"),
        is_payment_year=(pl.col("period") - pl.col("period").floor() == 0),
    )
    # payment: in a payment year, SUMIF(period_index row, this period+1, amortization)
    amort = frame.get_column("amortization").to_list()
    pidx = frame.get_column("period_index").to_list()
    payments: list[float] = []
    for is_pay, period in zip(
        frame.get_column("is_payment_year").to_list(),
        frame.get_column("period").to_list(),
        strict=True,
    ):
        if is_pay:
            target = period + 1
            payments.append(
                sum(a for a, p in zip(amort, pidx, strict=True) if p == target)
            )
        else:
            payments.append(0.0)
    return frame.with_columns(payment=pl.Series(payments))


def _land_rent_amort_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 69: 土地租金年摊销 = C59*(1+C64)^INT((year-first)/C63)."""
    _ = view
    frame = _land_rent_frame(params)
    return {
        _nid(c, 69): a
        for c, a in zip(
            YEAR_COLS, frame.get_column("amortization").to_list(), strict=True
        )
    }


def _land_rent_payment_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 68: 土地租金支付 — lump payment every rent_payment_freq years."""
    _ = view
    frame = _land_rent_frame(params)
    return {
        _nid(c, 68): p
        for c, p in zip(YEAR_COLS, frame.get_column("payment").to_list(), strict=True)
    }


def _annual_full_hours_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """C7 (deferred): 年发电小时数 = SUM(损益!G5:AE5)/25/C2."""
    gen_cols = col_letters("G", 25)  # G..AE
    total = 0.0
    for c in gen_cols:
        v = view.get(f"损益!{c}5")
        if isinstance(v, (int, float)):
            total += v
    return {_nid("C", 7): total / 25 / params.installed_capacity_mw}


def _first_year_om_rate_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """C50 (deferred): 首年运维费费率 = (成本!E7+E8+E10+E18)/C2."""

    def n(row: int) -> float:
        v = view.get(f"成本!E{row}")
        return float(v) if isinstance(v, (int, float)) else 0.0

    return {_nid("C", 50): (n(7) + n(8) + n(10) + n(18)) / params.installed_capacity_mw}


def _static_investment_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """C15: 静态投资 = C16+C17+C18+C22+C68 (first land-rent payment included)."""
    v = view.get(_nid("C", 68))
    first_payment = float(v) if isinstance(v, (int, float)) else 0.0
    static = (
        params.construction_cost
        + params.equipment_cost
        + params.other_cost
        + params.contingency
        + first_payment
    )
    return {_nid("C", 15): static}


UNITS: dict[Step, StepFn] = {
    ("参数表", 2): _scalar_step("installed_capacity_mw", 2),
    ("参数表", 6): _load_rate_step,
    ("参数表", 8): _scalar_step("feed_in_tariff", 8),
    ("参数表", 12): _years_copy_step(12),
    ("参数表", 18): _scalar_step("other_cost", 18),
    ("参数表", 19): _scalar_step("land_use_fee", 19),
    ("参数表", 23): _scalar_step("unit_static_investment", 23),
    ("参数表", 24): _scalar_step("epc_unit_price", 24),
    ("参数表", 25): _scalar_step("deductible_vat_construction", 25),
    ("参数表", 29): _scalar_step("working_capital_total", 29),
    ("参数表", 43): _scalar_step("land_use_tax", 43),
    ("参数表", 47): _scalar_step("depreciation_rate", 47),
    ("参数表", 51): _years_copy_step(51),
    ("参数表", 59): _scalar_step("first_year_land_rent", 59),
    ("参数表", 61): _scalar_step("land_area", 61),
    ("参数表", 66): _years_copy_step(66),
    ("参数表", 67): _payment_period_step,
    ("参数表", 68): _land_rent_payment_step,
    ("参数表", 69): _land_rent_amort_step,
    ("参数表", 15): _static_investment_step,
    ("参数表", 73): _scalar_step("epc_contract_price", 73),
    ("参数表", 7): _annual_full_hours_step,  # deferred: needs 损益 row 5
    ("参数表", 50): _first_year_om_rate_step,  # deferred: needs 成本 col E
}
