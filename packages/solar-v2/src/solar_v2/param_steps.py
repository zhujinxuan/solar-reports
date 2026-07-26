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


# -- Domain calculation schema -----------------------------------------------

from solar_v2.schema import DomainSchema, ItemSchema  # noqa: E402

SCHEMA = DomainSchema(
    key="params",
    sheet="参数表",
    label="参数表 (Params)",
    depends_on=(),
    items=(
        ItemSchema(
            key="installed_capacity_mw",
            label="装机容量（直流侧）",
            unit="万kW",
            formula="params:installed_capacity_mw (constant 15)",
            inputs=("params:installed_capacity_mw",),
            rows=(2,),
        ),
        ItemSchema(
            key="load_rate",
            label="负荷率",
            unit="%",
            formula="C6=0, D6=95%, E6:AB6=100% (按建设/运营年限阶梯)",
            inputs=(),
            rows=(6,),
        ),
        ItemSchema(
            key="annual_full_hours",
            label="年发电小时数",
            unit="小时",
            formula="SUM(损益 row 5) / 25 / installed_capacity_mw",
            inputs=("params:installed_capacity_mw", "pnl:power_generation"),
            rows=(7,),
        ),
        ItemSchema(
            key="feed_in_tariff",
            label="上网电价（含税）",
            unit="元/kWh",
            formula="params:feed_in_tariff",
            inputs=("params:feed_in_tariff",),
            rows=(8,),
        ),
        ItemSchema(
            key="subsidy_arrival_rate",
            label="补贴到位率",
            unit="%",
            formula="100% (year labels copied)",
            inputs=(),
            rows=(12,),
        ),
        ItemSchema(
            key="static_investment",
            label="静态投资",
            unit="万元",
            formula="construction + equipment + survey + contingency + land_rent_payment (首年)",
            inputs=("params:construction_cost", "params:equipment_cost", "params:contingency", "land_rent_payment"),
            rows=(15,),
        ),
        ItemSchema(
            key="other_cost",
            label="其他费用",
            unit="万元",
            formula="params:other_cost",
            inputs=("params:other_cost",),
            rows=(18,),
        ),
        ItemSchema(
            key="land_use_fee",
            label="其中：建设用地费",
            unit="万元",
            formula="params:land_use_fee",
            inputs=("params:land_use_fee",),
            rows=(19,),
        ),
        ItemSchema(
            key="unit_static_investment",
            label="单位静态投资",
            unit="元/kW",
            formula="params:unit_static_investment",
            inputs=("params:unit_static_investment",),
            rows=(23,),
        ),
        ItemSchema(
            key="epc_unit_price",
            label="EPC单价",
            unit="元/kW",
            formula="params:epc_unit_price",
            inputs=("params:epc_unit_price",),
            rows=(24,),
        ),
        ItemSchema(
            key="deductible_vat_construction",
            label="建设期可抵扣增值税",
            unit="万元",
            formula="construction × vat_rate_c + equipment × vat_rate_e + survey × vat_rate_s",
            inputs=("params:vat_rate_construction", "params:vat_rate_equipment", "params:vat_rate_survey"),
            rows=(25,),
        ),
        ItemSchema(
            key="working_capital_total",
            label="流动资金总额",
            unit="万元",
            formula="params:working_capital_total",
            inputs=("params:working_capital_total",),
            rows=(29,),
        ),
        ItemSchema(
            key="land_use_tax",
            label="城镇土地使用税",
            unit="万元",
            formula="params:land_use_tax",
            inputs=("params:land_use_tax",),
            rows=(43,),
        ),
        ItemSchema(
            key="depreciation_rate",
            label="折旧率",
            unit="%",
            formula="params:depreciation_rate",
            inputs=("params:depreciation_rate",),
            rows=(47,),
        ),
        ItemSchema(
            key="first_year_om_rate",
            label="首年运维费费率",
            unit="万元/MW",
            formula="(cost repair + salary + material + other_cost) / capacity (deferred)",
            inputs=("params:installed_capacity_mw", "cost:repair_cost", "cost:salary_cost", "cost:material_cost", "cost:other_cost"),
            rows=(50,),
        ),
        ItemSchema(
            key="repair_rate",
            label="年修理费率",
            unit="%",
            formula="params:repair_rate (year series from 参数表 row 51)",
            inputs=("params:repair_rate",),
            rows=(51,),
        ),
        ItemSchema(
            key="first_year_land_rent",
            label="首年土地租金",
            unit="万元",
            formula="land_area × rent_per_mu / 10000",
            inputs=("params:first_year_land_rent",),
            rows=(59,),
        ),
        ItemSchema(
            key="land_area",
            label="占地面积",
            unit="亩",
            formula="params:land_area",
            inputs=("params:land_area",),
            rows=(61,),
        ),
        ItemSchema(
            key="year_labels",
            label="运营年度（年份行）",
            unit="-",
            formula="2021..2045 year labels (copied from row 4)",
            inputs=("params:years",),
            rows=(66,),
        ),
        ItemSchema(
            key="rent_payment_period",
            label="租金支付期序号",
            unit="-",
            formula="INT((year − first_year) / rent_payment_freq) + 1",
            inputs=("params:rent_payment_freq",),
            rows=(67,),
        ),
        ItemSchema(
            key="land_rent_payment",
            label="土地租金支付",
            unit="万元",
            formula="lump-sum payment every rent_payment_freq years = first_year_land_rent × (1+escalation)^periods",
            inputs=("first_year_land_rent", "rent_payment_period", "params:rent_escalation_rate"),
            rows=(68,),
        ),
        ItemSchema(
            key="land_rent_amortization",
            label="土地租金年摊销",
            unit="万元",
            formula="first_year_land_rent × (1 + escalation_rate) ^ INT((year − first) / escalation_freq)",
            inputs=("first_year_land_rent", "params:rent_escalation_rate", "params:rent_escalation_freq"),
            rows=(69,),
        ),
        ItemSchema(
            key="epc_contract_price",
            label="EPC签约价",
            unit="万元",
            formula="params:epc_contract_price",
            inputs=("params:epc_contract_price",),
            rows=(73,),
        ),
    ),
)
