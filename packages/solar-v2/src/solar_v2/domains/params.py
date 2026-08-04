"""ProjectParameters domain — 参数表 scalar echoes, year-series echoes,
repair-rate echo, land-rent schedule, and deferred back-edge scalars.

Stage  2: compute_core  → ParamsCore  (DerivedParams + year-echo frame + stage-2 scalars)
Stage 12: compute_backedges → ParamsCore (back-edge scalars filled: annual_full_hours,
         first_year_om_rate, static_investment)

``ParamsCore`` is both the stage-2 output and the final domain result; the
back-edge scalars default to 0.0 at stage 2 and are filled at stage 12 via
``dataclasses.replace``, producing a new frozen instance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import polars as pl

from solar_v2.axis import YearAxis
from solar_v2.inputs import ModelInputs
from solar_v2.schema import DomainSchema, ItemSchema

if TYPE_CHECKING:
    from solar_v2.domains.cost import CostResult
    from solar_v2.domains.pnl import PnLResult


# ---------------------------------------------------------------------------
# DerivedParams — constant-folded scalars from ModelInputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DerivedParams:
    """Constant-folded scalars computed from ModelInputs givens.

    These are the values produced by ``load_params()`` in the old code —
    purely algebraic folds of literal givens with no workbook formula cells.
    """

    installed_capacity_mw: float
    """装机容量（直流侧），万kW (= inputs.installed_capacity_mw)"""

    feed_in_tariff: float
    """上网电价（含税）= base_tariff + subsidy_per_kwh，元/kW·h"""

    other_cost: float
    """其他费用 = other_cost_base + farmland_occupation_tax，万元"""

    land_use_fee: float
    """建设用地费 = 180.0（常数），万元"""

    unit_static_investment: float
    """单位静态投资 = (construction + equipment + other_cost + contingency) / capacity，元/kW"""

    epc_unit_price: float
    """EPC单价 = (construction + equipment + survey) / capacity，元/kW"""

    epc_contract_price: float
    """EPC签约价 = epc_unit_price，万元（C73 = C24 echo）"""

    deductible_vat_construction: float
    """建设期可抵扣增值税 = Σ cost_i / (1+vat_i) × vat_i，万元"""

    working_capital_total: float
    """流动资金总额 = capacity × 30，万元"""

    land_use_tax: float
    """城镇土地使用税 = land_use_tax_rate × land_taxed_area / 10000，万元"""

    depreciation_rate: float
    """折旧率 = (1 - salvage_rate) / depreciation_years"""

    first_year_land_rent: float
    """首年土地租金 = land_area × land_rent_per_mu / 10000，万元"""

    land_area: float
    """占地面积 = capacity × land_per_mw × 10000 / (1000 × 2/3)，亩"""

    @classmethod
    def from_inputs(cls, inputs: ModelInputs) -> DerivedParams:
        """Fold constant scalars from givens."""
        cap = inputs.installed_capacity_mw
        other = inputs.other_cost_base + inputs.farmland_occupation_tax
        area = cap * inputs.land_per_mw * 10000 / (1000 * 2 / 3)
        first_rent = area * inputs.land_rent_per_mu / 10000
        epc_unit = (
            inputs.construction_cost
            + inputs.equipment_cost
            + inputs.survey_design_fee
        ) / cap
        deductible = (
            inputs.construction_cost
            / (1 + inputs.vat_rate_construction)
            * inputs.vat_rate_construction
            + inputs.equipment_cost
            / (1 + inputs.vat_rate_equipment)
            * inputs.vat_rate_equipment
            + inputs.survey_design_fee
            / (1 + inputs.vat_rate_survey)
            * inputs.vat_rate_survey
        )
        return cls(
            installed_capacity_mw=cap,
            feed_in_tariff=inputs.base_tariff + inputs.subsidy_per_kwh,
            other_cost=other,
            land_use_fee=inputs.land_use_fee,
            unit_static_investment=(
                inputs.construction_cost
                + inputs.equipment_cost
                + other
                + inputs.contingency
            ) / cap,
            epc_unit_price=epc_unit,
            epc_contract_price=epc_unit,
            deductible_vat_construction=deductible,
            working_capital_total=cap * 30,
            land_use_tax=inputs.land_use_tax_rate
            * inputs.land_taxed_area
            / 10000,
            depreciation_rate=(1 - inputs.salvage_rate)
            / inputs.depreciation_years,
            first_year_land_rent=first_rent,
            land_area=area,
        )


# ---------------------------------------------------------------------------
# ParamsScalars — scalar items on the domain result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParamsScalars:
    """All scalar items for the params domain.

    Back-edge fields (annual_full_hours, first_year_om_rate, static_investment)
    are 0.0 at stage 2 and filled at stage 12 via :func:`compute_backedges`.
    """

    installed_capacity_mw: float
    """装机容量（直流侧），万kW"""
    feed_in_tariff: float
    """上网电价（含税），元/kW·h"""
    other_cost: float
    """其他费用，万元"""
    land_use_fee: float
    """建设用地费，万元"""
    unit_static_investment: float
    """单位静态投资，元/kW"""
    epc_unit_price: float
    """EPC单价，元/kW"""
    epc_contract_price: float
    """EPC签约价，万元"""
    deductible_vat_construction: float
    """建设期可抵扣增值税，万元"""
    working_capital_total: float
    """流动资金总额，万元"""
    land_use_tax: float
    """城镇土地使用税，万元"""
    depreciation_rate: float
    """折旧率"""
    first_year_land_rent: float
    """首年土地租金，万元"""
    land_area: float
    """占地面积，亩"""
    # --- back-edge fields (0.0 until stage 12) ---
    annual_full_hours: float = 0.0
    """年发电小时数（back-edge: 由损益 row 5 反算）"""
    first_year_om_rate: float = 0.0
    """首年运维费费率（back-edge: 由成本首个运营年反算）"""
    static_investment: float = 0.0
    """静态投资（back-edge: 含首年土地租金支付）"""


# ---------------------------------------------------------------------------
# ParamsCore — the domain result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParamsCore:
    """Params domain result.

    ``scalars`` back-edge fields are 0.0 after stage 2 and replaced by a new
    ``ParamsCore`` instance at stage 12 via :func:`compute_backedges`.
    """

    axis: YearAxis
    """Year axis — construction year and operating years."""
    inputs: ModelInputs
    """The givens this result was computed from."""
    derived: DerivedParams
    """Constant-folded scalars from givens."""
    frame: pl.DataFrame
    """Year-series frame (26 rows = all_years).
    Columns: year, load_rate, subsidy_arrival_rate, repair_rate,
    year_labels, rent_payment_period, land_rent_payment,
    land_rent_amortization."""
    scalars: ParamsScalars
    """All scalar items; back-edge fields 0.0 until stage 12."""

    @property
    def years(self) -> tuple[int, ...]:
        """Operating calendar years."""
        return self.axis.years

    @property
    def construction_year(self) -> int:
        """Construction calendar year."""
        return self.axis.construction_year

    @property
    def operating_years(self) -> int:
        """Number of operating years."""
        return self.axis.operating_years

    # --- given accessors (delegate to inputs) ---
    @property
    def installed_capacity_mw(self) -> float:
        """装机容量, 万kW."""
        return float(self.inputs.installed_capacity_mw)

    @property
    def equity_ratio(self) -> float:
        """资本金比例."""
        return float(self.inputs.equity_ratio)

    @property
    def base_tariff(self) -> float:
        """无补贴上网电价, 元/kW·h."""
        return float(self.inputs.base_tariff)

    @property
    def loan_years(self) -> int:
        """长期借款年限."""
        return int(self.inputs.loan_years)

    @property
    def epc_cost_price(self) -> float:
        """EPC成本价, 元/kW."""
        return float(self.inputs.epc_cost_price)

    @property
    def mgmt_allocation_ratio(self) -> float:
        """管理费分摊比率."""
        return float(self.inputs.mgmt_allocation_ratio)

    @property
    def equity_sale_tax_rate(self) -> float:
        """股权出售所得税税率."""
        return float(self.inputs.equity_sale_tax_rate)

    @property
    def buyer_benchmark_rate(self) -> float:
        """购买方基准收益率."""
        return float(self.inputs.buyer_benchmark_rate)

    @property
    def subsidy_per_kwh(self) -> float:
        """度电补贴强度, 元/kW·h."""
        return float(self.inputs.subsidy_per_kwh)

    @property
    def construction_months(self) -> int:
        """建设周期, 月."""
        return int(self.inputs.construction_months)

    @property
    def depreciation_years(self) -> int:
        """折旧年限, 年."""
        return int(self.inputs.depreciation_years)

    @property
    def income_tax_rate(self) -> float:
        """所得税税率."""
        return float(self.inputs.income_tax_rate)

    @property
    def loan_rate_long(self) -> float:
        """长期借款利率."""
        return float(self.inputs.loan_rate_long)

    @property
    def provisional_sum(self) -> float:
        """暂列金, 万元."""
        return float(self.inputs.provisional_sum)

    @property
    def load_rate(self) -> tuple[float, ...]:
        """负荷率系列 (建设年 + 运营年)."""
        return tuple(float(v) for v in self.inputs.load_rate)

    @property
    def aux_static_ratio_build1(self) -> float:
        """静态投资完成比例 — 建设期1."""
        return float(self.inputs.aux_static_ratio_build1)

    @property
    def aux_static_ratio_build2(self) -> float:
        """静态投资完成比例 — 建设期2."""
        return float(self.inputs.aux_static_ratio_build2)

    @property
    def aux_static_ratio_operate(self) -> float:
        """静态投资完成比例 — 运营期."""
        return float(self.inputs.aux_static_ratio_operate)

    # --- derived accessors ---
    @property
    def unit_static_investment(self) -> float:
        """单位静态投资, 元/kW."""
        return self.derived.unit_static_investment

    @property
    def epc_contract_price(self) -> float:
        """EPC签约价, 万元."""
        return self.derived.epc_contract_price

    @property
    def depreciation_rate(self) -> float:
        """折旧率."""
        return self.derived.depreciation_rate

    @property
    def working_capital_total(self) -> float:
        """流动资金总额, 万元."""
        return self.derived.working_capital_total

    @property
    def static_investment_total(self) -> float:
        """静态投资合计 (单位静态投资 × 容量 + 首年土地租金支付), 万元.

        Computable at stage 2 — identical to the stage-12 back-edge
        ``static_investment`` but available before PnL/cost exist.
        """
        return (
            self.derived.unit_static_investment * self.inputs.installed_capacity_mw
            + float(self.frame["land_rent_payment"][0])
        )

    # --- scalar accessors ---
    @property
    def annual_full_hours(self) -> float:
        """年发电小时数 (stage-12 back-edge)."""
        return self.scalars.annual_full_hours

    @property
    def static_investment(self) -> float:
        """静态投资 (stage-12 back-edge, 含首年土地租金支付)."""
        return self.scalars.static_investment


# ---------------------------------------------------------------------------
# Land-rent schedule frame builder
# ---------------------------------------------------------------------------


def _build_land_rent(
    inputs: ModelInputs, axis: YearAxis
) -> pl.DataFrame:
    """Build land-rent year-series columns (rows 67-69).

    Returns a DataFrame with columns: year, rent_payment_period,
    land_rent_payment, land_rent_amortization.
    """
    first = axis.construction_year
    years = list(axis.all_years)
    freq = float(inputs.rent_payment_freq)
    esc_freq = float(inputs.rent_escalation_freq)

    # First compute the raw land-rent frame (26 rows)
    frame = pl.DataFrame({"year": years}).with_columns(
        period=((pl.col("year") - first) / freq).cast(pl.Float64),
        escalation_period=(
            (pl.col("year") - first) / esc_freq
        )
        .floor()
        .cast(pl.Float64),
    )

    first_rent = (
        inputs.land_per_mw
        * inputs.installed_capacity_mw
        * 10000
        / (1000 * 2 / 3)
        * inputs.land_rent_per_mu
        / 10000
    )

    frame = frame.with_columns(
        rent_payment_period=pl.col("period").floor() + 1,
        land_rent_amortization=first_rent
        * (1 + inputs.rent_escalation_rate)
        ** pl.col("escalation_period"),
        is_payment_year=(
            pl.col("period") - pl.col("period").floor() == 0
        ),
    )

    # Compute land_rent_payment: in a payment year, SUMIF amortization
    # by payment period index
    amort = frame.get_column("land_rent_amortization").to_list()
    pidx = frame.get_column("rent_payment_period").to_list()
    is_pay = frame.get_column("is_payment_year").to_list()

    payments: list[float] = []
    for pay_flag, period_val in zip(is_pay, frame.get_column("period").to_list(), strict=True):
        if pay_flag:
            target = period_val + 1  # SUMIF period_index == target
            payments.append(
                sum(a for a, p in zip(amort, pidx, strict=True) if p == target)
            )
        else:
            payments.append(0.0)

    frame = frame.with_columns(land_rent_payment=pl.Series(payments))

    return frame.select(
        "year",
        "rent_payment_period",
        "land_rent_payment",
        "land_rent_amortization",
    )


# ---------------------------------------------------------------------------
# Individual item computers (one compute_<key> per non-coupled schema item)
# ---------------------------------------------------------------------------


def compute_installed_capacity_mw(
    derived: DerivedParams,
) -> float:
    """Row 2: 装机容量（直流侧）— scalar echo of the given."""
    return derived.installed_capacity_mw


def compute_load_rate(
    inputs: ModelInputs, axis: YearAxis
) -> pl.Series:
    """Row 6: 负荷率 — 26 values (construction=0, operating year 1=0.95, rest=1.0)."""
    return pl.Series("load_rate", list(inputs.load_rate), dtype=pl.Float64)


def compute_feed_in_tariff(
    derived: DerivedParams,
) -> float:
    """Row 8: 上网电价（含税）— base_tariff + subsidy_per_kwh."""
    return derived.feed_in_tariff


def compute_subsidy_arrival_rate(
    axis: YearAxis,
) -> pl.Series:
    """Row 12: 补贴到位率 — year labels copy (construction year + 25 op years)."""
    return pl.Series(
        "subsidy_arrival_rate", list(axis.all_years), dtype=pl.Float64
    )


def compute_other_cost(
    derived: DerivedParams,
) -> float:
    """Row 18: 其他费用 — echo of other_cost_base + farmland_occupation_tax."""
    return derived.other_cost


def compute_land_use_fee(
    derived: DerivedParams,
) -> float:
    """Row 19: 建设用地费 — echo of 180.0."""
    return derived.land_use_fee


def compute_unit_static_investment(
    derived: DerivedParams,
) -> float:
    """Row 23: 单位静态投资 — (C16+C17+C18+C22)/C2."""
    return derived.unit_static_investment


def compute_epc_unit_price(
    derived: DerivedParams,
) -> float:
    """Row 24: EPC单价 — (construction + equipment + survey) / capacity."""
    return derived.epc_unit_price


def compute_deductible_vat_construction(
    derived: DerivedParams,
) -> float:
    """Row 25: 建设期可抵扣增值税 — Σ cost_i/(1+vat_i)×vat_i."""
    return derived.deductible_vat_construction


def compute_working_capital_total(
    derived: DerivedParams,
) -> float:
    """Row 29: 流动资金总额 — capacity × 30."""
    return derived.working_capital_total


def compute_land_use_tax(
    derived: DerivedParams,
) -> float:
    """Row 43: 城镇土地使用税 — rate × area / 10000."""
    return derived.land_use_tax


def compute_depreciation_rate(
    derived: DerivedParams,
) -> float:
    """Row 47: 折旧率 — (1 - salvage_rate) / depreciation_years."""
    return derived.depreciation_rate


def compute_repair_rate(
    axis: YearAxis,
) -> pl.Series:
    """Row 51: 年修理费率（标题行）— year labels copy (construction year + 25 op years).

    In the workbook row 51 is a year-label header above the repair-rate row 52.
    """
    return pl.Series(
        "repair_rate", list(axis.all_years), dtype=pl.Float64
    )


def compute_repair_rate_series(
    inputs: ModelInputs, axis: YearAxis
) -> pl.Series:
    """Row 52: 年修理费率系列 — 25 operating-year repair-rate values.

    Construction-year value is 0.0 (row 52 has no construction-year cell;
    the 25 values span D52..AB52 in the workbook).
    """
    rates = [0.0, *list(inputs.repair_rate_series)]
    return pl.Series("repair_rate_series", rates, dtype=pl.Float64)


def compute_first_year_land_rent(
    derived: DerivedParams,
) -> float:
    """Row 59: 首年土地租金 — land_area × rent_per_mu / 10000."""
    return derived.first_year_land_rent


def compute_land_area(
    derived: DerivedParams,
) -> float:
    """Row 61: 占地面积 — capacity × land_per_mw × 10000 / (1000 × 2/3)."""
    return derived.land_area


def compute_year_labels(
    axis: YearAxis,
) -> pl.Series:
    """Row 66: 运营年度（年份行）— calendar year labels for all 26 years."""
    return pl.Series("year_labels", list(axis.all_years), dtype=pl.Float64)


def compute_rent_payment_period(
    inputs: ModelInputs, axis: YearAxis
) -> pl.Series:
    """Row 67: 租金支付期序号 — INT((year − first) / rent_payment_freq) + 1."""
    first = axis.construction_year
    freq = float(inputs.rent_payment_freq)
    vals = [
        float(math.floor((y - first) / freq) + 1)
        for y in axis.all_years
    ]
    return pl.Series("rent_payment_period", vals, dtype=pl.Float64)


def compute_land_rent_payment(
    inputs: ModelInputs, axis: YearAxis
) -> pl.Series:
    """Row 68: 土地租金支付 — lump-sum payment every rent_payment_freq years.

    Quirk: the first payment (construction year) is included in static_investment.
    """
    frame = _build_land_rent(inputs, axis)
    return pl.Series(
        "land_rent_payment",
        frame.get_column("land_rent_payment").to_list(),
        dtype=pl.Float64,
    )


def compute_land_rent_amortization(
    inputs: ModelInputs, axis: YearAxis
) -> pl.Series:
    """Row 69: 土地租金年摊销 — first_year_rent × (1 + escalation)^INT((year−first)/freq)."""
    frame = _build_land_rent(inputs, axis)
    return pl.Series(
        "land_rent_amortization",
        frame.get_column("land_rent_amortization").to_list(),
        dtype=pl.Float64,
    )


def compute_epc_contract_price(
    derived: DerivedParams,
) -> float:
    """Row 73: EPC签约价 — echo of epc_unit_price."""
    return derived.epc_contract_price


# ---------------------------------------------------------------------------
# Stage-2 entry point: compute_core
# ---------------------------------------------------------------------------


def compute_core(
    inputs: ModelInputs, axis: YearAxis
) -> ParamsCore:
    """Build the params domain core (stage 2).

    Computes DerivedParams, year-echo frame, and all stage-2 scalar items.
    Back-edge scalars (annual_full_hours, first_year_om_rate, static_investment)
    are set to 0.0 — they are filled at stage 12 by :func:`compute_backedges`.
    """
    derived = DerivedParams.from_inputs(inputs)
    scalars = ParamsScalars(
        installed_capacity_mw=derived.installed_capacity_mw,
        feed_in_tariff=derived.feed_in_tariff,
        other_cost=derived.other_cost,
        land_use_fee=derived.land_use_fee,
        unit_static_investment=derived.unit_static_investment,
        epc_unit_price=derived.epc_unit_price,
        epc_contract_price=derived.epc_contract_price,
        deductible_vat_construction=derived.deductible_vat_construction,
        working_capital_total=derived.working_capital_total,
        land_use_tax=derived.land_use_tax,
        depreciation_rate=derived.depreciation_rate,
        first_year_land_rent=derived.first_year_land_rent,
        land_area=derived.land_area,
    )

    # Build the year-series frame: 26 rows = all_years
    land = _build_land_rent(inputs, axis)
    frame = pl.DataFrame({"year": pl.Series("year", list(axis.all_years), dtype=pl.Int64)})
    frame = frame.with_columns(
        load_rate=compute_load_rate(inputs, axis),
        subsidy_arrival_rate=compute_subsidy_arrival_rate(axis),
        repair_rate=compute_repair_rate(axis),
        repair_rate_series=compute_repair_rate_series(inputs, axis),
        year_labels=compute_year_labels(axis),
        rent_payment_period=land.get_column("rent_payment_period"),
        land_rent_payment=land.get_column("land_rent_payment"),
        land_rent_amortization=land.get_column("land_rent_amortization"),
    )

    return ParamsCore(
        axis=axis, inputs=inputs, derived=derived, frame=frame, scalars=scalars
    )


# ---------------------------------------------------------------------------
# Stage-12: back-edge scalar computations
# ---------------------------------------------------------------------------


def compute_backedges(
    core: ParamsCore,
    pnl: PnLResult,
    cost: CostResult,
) -> ParamsCore:
    """Fill the three back-edge scalar fields (stage 12).

    Requires PnLResult (for power_generation column) and CostResult (for
    operating-year cost item columns). Returns a new ``ParamsCore`` with
    ``annual_full_hours``, ``first_year_om_rate``, and ``static_investment``
    filled.

    Quirk — static_investment includes the first land-rent payment (C68):
      static = construction_cost + equipment_cost + other_cost + contingency
             + land_rent_payment(first_year)
    from the old ``_static_investment_step``.
    """
    annual_full_hours = compute_annual_full_hours(pnl, core.derived)
    first_year_om_rate = compute_first_year_om_rate(cost, core.derived)
    static_investment = compute_static_investment(core)

    new_scalars = replace(
        core.scalars,
        annual_full_hours=annual_full_hours,
        first_year_om_rate=first_year_om_rate,
        static_investment=static_investment,
    )
    return replace(core, scalars=new_scalars)


def compute_annual_full_hours(
    pnl: PnLResult, derived: DerivedParams
) -> float:
    """Row 7: 年发电小时数 = SUM(power_generation over 25 op years) / 25 / capacity.

    Reads ``pnl.frame["power_generation"]`` (25 operating-year values).
    """
    # pnl.frame["power_generation"] is a Series of 25 values
    frame = pnl.frame
    gen: pl.Series = frame.get_column("power_generation")
    total = gen.sum()
    return float(total) / 25 / derived.installed_capacity_mw


def compute_first_year_om_rate(
    cost: CostResult, derived: DerivedParams
) -> float:
    """Row 50: 首年运维费费率 = (repair + salary + material + other) / capacity.

    Reads cost.frame columns for the first operating year (index 0):
    repair_cost, salary_cost, material_cost, other_cost.
    """
    frame = cost.frame
    repair = float(frame.get_column("repair_cost")[0])
    salary = float(frame.get_column("salary_cost")[0])
    material = float(frame.get_column("material_cost")[0])
    other = float(frame.get_column("other_cost")[0])
    return (repair + salary + material + other) / derived.installed_capacity_mw


def compute_static_investment(core: ParamsCore) -> float:
    """Row 15: 静态投资 = construction + equipment + other_cost + contingency
    + first land-rent payment (construction year, index 0).

    Quirk: includes the first-year land-rent PAYMENT (not amortization),
    even though the payment is a lump sum covering multiple future years.
    """
    derived = core.derived
    # land_rent_payment at construction year (row 0 of the 26-row frame)
    first_payment = float(
        core.frame.get_column("land_rent_payment")[0]
    )
    static_ex_land = (
        derived.unit_static_investment
        * derived.installed_capacity_mw
    )
    return static_ex_land + first_payment


# ---------------------------------------------------------------------------
# depends_on includes ("cost", "pnl") — these are explicit late-binding
# stage-12 back-edges (compute_backedges reads PnLResult.power_generation
# and CostResult cost columns).  Params is normally a supplier-only domain;
# these back-edges are a documented exception.

# Domain calculation schema
# ---------------------------------------------------------------------------

SCHEMA = DomainSchema(
    key="params",
    sheet="参数表",
    label="参数表 (Params)",
    depends_on=("cost", "pnl"),
    items=(
        ItemSchema(
            key="installed_capacity_mw",
            label="装机容量（直流侧）",
            unit="万kW",
            formula="params:installed_capacity_mw (constant 15)",
            inputs=("params:installed_capacity_mw",),
            rows=(2,),
            kind="scalar",
        ),
        ItemSchema(
            key="load_rate",
            label="负荷率",
            unit="%",
            formula="C6=0, D6=95%, E6:AB6=100% (按建设/运营年限阶梯)",
            inputs=(),
            rows=(6,),
            kind="series",
        ),
        ItemSchema(
            key="annual_full_hours",
            label="年发电小时数",
            unit="小时",
            formula="SUM(损益 power_generation) / 25 / installed_capacity_mw",
            inputs=(
                "params:installed_capacity_mw",
                "pnl:power_generation",
            ),
            rows=(7,),
            kind="scalar",
        ),
        ItemSchema(
            key="feed_in_tariff",
            label="上网电价（含税）",
            unit="元/kWh",
            formula="params:feed_in_tariff = base_tariff + subsidy_per_kwh",
            inputs=("params:feed_in_tariff",),
            rows=(8,),
            kind="scalar",
        ),
        ItemSchema(
            key="subsidy_arrival_rate",
            label="补贴到位率",
            unit="%",
            formula="100% (year labels copied from row 4)",
            inputs=(),
            rows=(12,),
            kind="series",
        ),
        ItemSchema(
            key="static_investment",
            label="静态投资",
            unit="万元",
            formula=(
                "construction + equipment + survey + contingency "
                "+ first land_rent_payment (construction year)"
            ),
            inputs=(
                "params:construction_cost",
                "params:equipment_cost",
                "params:contingency",
                "land_rent_payment",
            ),
            rows=(15,),
            kind="scalar",
        ),
        ItemSchema(
            key="other_cost",
            label="其他费用",
            unit="万元",
            formula="params:other_cost = other_cost_base + farmland_occupation_tax",
            inputs=("params:other_cost",),
            rows=(18,),
            kind="scalar",
        ),
        ItemSchema(
            key="land_use_fee",
            label="其中：建设用地费",
            unit="万元",
            formula="params:land_use_fee (=180, constant)",
            inputs=("params:land_use_fee",),
            rows=(19,),
            kind="scalar",
        ),
        ItemSchema(
            key="unit_static_investment",
            label="单位静态投资",
            unit="元/kW",
            formula="(construction + equipment + other_cost + contingency) / capacity",
            inputs=("params:unit_static_investment",),
            rows=(23,),
            kind="scalar",
        ),
        ItemSchema(
            key="epc_unit_price",
            label="EPC单价",
            unit="元/kW",
            formula="(construction + equipment + survey) / capacity",
            inputs=("params:epc_unit_price",),
            rows=(24,),
            kind="scalar",
        ),
        ItemSchema(
            key="deductible_vat_construction",
            label="建设期可抵扣增值税",
            unit="万元",
            formula=(
                "construction×vat_rate_c/(1+vat_rate_c) "
                "+ equipment×vat_rate_e/(1+vat_rate_e) "
                "+ survey×vat_rate_s/(1+vat_rate_s)"
            ),
            inputs=(
                "params:vat_rate_construction",
                "params:vat_rate_equipment",
                "params:vat_rate_survey",
            ),
            rows=(25,),
            kind="scalar",
        ),
        ItemSchema(
            key="working_capital_total",
            label="流动资金总额",
            unit="万元",
            formula="capacity × 30",
            inputs=("params:working_capital_total",),
            rows=(29,),
            kind="scalar",
        ),
        ItemSchema(
            key="land_use_tax",
            label="城镇土地使用税",
            unit="万元",
            formula="land_use_tax_rate × land_taxed_area / 10000",
            inputs=("params:land_use_tax",),
            rows=(43,),
            kind="scalar",
        ),
        ItemSchema(
            key="depreciation_rate",
            label="折旧率",
            unit="%",
            formula="(1 - salvage_rate) / depreciation_years",
            inputs=("params:depreciation_rate",),
            rows=(47,),
            kind="scalar",
        ),
        ItemSchema(
            key="first_year_om_rate",
            label="首年运维费费率",
            unit="万元/MW",
            formula=(
                "(cost repair_cost + salary_cost + material_cost "
                "+ other_cost) / capacity (deferred, stage 12)"
            ),
            inputs=(
                "params:installed_capacity_mw",
                "cost:repair_cost",
                "cost:salary_cost",
                "cost:material_cost",
                "cost:other_cost",
            ),
            rows=(50,),
            kind="scalar",
        ),
        ItemSchema(
            key="repair_rate",
            label="年修理费率（标题行）",
            unit="-",
            formula="year labels copy (row 51 header above repair rate values)",
            inputs=(),
            rows=(51,),
            kind="series",
        ),
        ItemSchema(
            key="repair_rate_series",
            label="年修理费率",
            unit="%",
            formula="25 operating-year values from repair_rate_series (0.002×3, 0.004×5, 0.006×6, 0.01×11)",
            inputs=("params:repair_rate",),
            rows=(52,),
            kind="series",
        ),
        ItemSchema(
            key="first_year_land_rent",
            label="首年土地租金",
            unit="万元",
            formula="land_area × land_rent_per_mu / 10000",
            inputs=("params:first_year_land_rent",),
            rows=(59,),
            kind="scalar",
        ),
        ItemSchema(
            key="land_area",
            label="占地面积",
            unit="亩",
            formula="capacity × land_per_mw × 10000 / (1000 × 2/3)",
            inputs=("params:land_area",),
            rows=(61,),
            kind="scalar",
        ),
        ItemSchema(
            key="year_labels",
            label="运营年度（年份行）",
            unit="-",
            formula="construction_year + 25 operating years (calendar-year labels)",
            inputs=("params:years",),
            rows=(66,),
            kind="series",
        ),
        ItemSchema(
            key="rent_payment_period",
            label="租金支付期序号",
            unit="-",
            formula="INT((year − construction_year) / rent_payment_freq) + 1",
            inputs=("params:rent_payment_freq",),
            rows=(67,),
            kind="series",
        ),
        ItemSchema(
            key="land_rent_payment",
            label="土地租金支付",
            unit="万元",
            formula=(
                "lump-sum payment every rent_payment_freq years "
                "= SUMIF(amortization by payment period)"
            ),
            inputs=(
                "first_year_land_rent",
                "rent_payment_period",
                "params:rent_escalation_rate",
                "params:rent_payment_freq",
            ),
            rows=(68,),
            kind="series",
        ),
        ItemSchema(
            key="land_rent_amortization",
            label="土地租金年摊销",
            unit="万元",
            formula=(
                "first_year_land_rent "
                "× (1 + escalation_rate) ^ INT((year − first) / escalation_freq)"
            ),
            inputs=(
                "first_year_land_rent",
                "params:rent_escalation_rate",
                "params:rent_escalation_freq",
            ),
            rows=(69,),
            kind="series",
        ),
        ItemSchema(
            key="epc_contract_price",
            label="EPC签约价",
            unit="万元",
            formula="params:epc_contract_price (= epc_unit_price)",
            inputs=("params:epc_contract_price",),
            rows=(73,),
            kind="scalar",
        ),
    ),
)
