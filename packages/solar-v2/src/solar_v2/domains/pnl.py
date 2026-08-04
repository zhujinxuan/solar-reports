"""PnL -- 损益表 (income statement).

Non-coupled items are computed in ``compute_core`` before the mutual block.
Coupled items are filled by ``assemble`` from ``MutualSolution``.
Adjusted profit (估值口径) is computed in ``compute_valuation_aux`` after the
balance sheet is available (stage 11 of the engine dataflow).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from solar_v2.axis import YearAxis
from solar_v2.inputs import ModelInputs
from solar_v2.schema import DomainSchema, ItemSchema

if TYPE_CHECKING:
    from solar_v2.domains.balance import BalanceResult
    from solar_v2.domains.cost import CostResult, CostStatics
    from solar_v2.domains.params import DerivedParams, ParamsCore
    from solar_v2.mutual import MutualSolution

# Workbook constant — equity cost of capital used in adjusted profit
_EQUITY_COST_OF_CAPITAL: float = 0.044


# ═══════════════════════════════════════════════════════════════════════════
# Result types
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PnLScalars:
    """Scalar items from the 损益 sheet."""

    depreciation_echo: float
    row13_total: float
    row28_total: float


@dataclass(frozen=True)
class PnLCore:
    """Non-coupled PnL items computed before the mutual block.

    ``frame`` columns (in schema order after ``year``):
    year_labels, power_generation, guaranteed_sales, market_sales,
    blended_price, on_grid_price_incl_vat, on_grid_price_excl_vat,
    sales_revenue, output_vat, vat_credit_balance, vat_credit_used,
    vat_payable, surcharge_base, city_maintenance_tax, education_surcharge,
    vat_surcharge_total, vat_refund, tax_rate_schedule.
    """

    years: tuple[int, ...]
    frame: pl.DataFrame
    scalars: PnLScalars


@dataclass(frozen=True)
class PnLResult:
    """Full PnL result after mutual block assembly + valuation aux.

    ``frame`` includes all PnLCore columns plus coupled columns from
    MutualSolution, dividend, undistributed_profit, and adjusted_profit.
    """

    years: tuple[int, ...]
    frame: pl.DataFrame
    scalars: PnLScalars


# ═══════════════════════════════════════════════════════════════════════════
# Non-coupled item computers (called by compute_core)
# ═══════════════════════════════════════════════════════════════════════════


def compute_year_labels(axis: YearAxis) -> pl.Series:
    """Row 4: calendar year labels for the 25 operating years."""
    return pl.Series(
        "year_labels",
        list(axis.years),
        dtype=pl.Int64,
    )


def compute_power_generation(inputs: ModelInputs) -> pl.Series:
    """Row 5: 年发电量 = hours × degradation × load_rate × capacity.

    Uses degradation_factor[1:] and load_rate[1:] (skipping construction
    year at index 0).
    """
    h = inputs.first_year_full_hours
    cap = inputs.installed_capacity_mw
    deg = inputs.degradation_factor
    ld = inputs.load_rate
    values = [
        h * deg[i + 1] * ld[i + 1] * cap
        for i in range(inputs.operating_years)
    ]
    return pl.Series("power_generation", values, dtype=pl.Float64)


def compute_guaranteed_sales(
    inputs: ModelInputs, power_generation: pl.Series,
) -> pl.Series:
    """Row 47: 保障利用小时售电量 = MIN(guaranteed_hours × capacity, generation)."""
    ceiling = inputs.guaranteed_hours * inputs.installed_capacity_mw
    values = [min(ceiling, gen) for gen in power_generation.to_list()]
    return pl.Series("guaranteed_sales", values, dtype=pl.Float64)


def compute_market_sales(
    power_generation: pl.Series, guaranteed_sales: pl.Series,
) -> pl.Series:
    """Row 48: 市场化售电量 = generation − guaranteed."""
    gen_list = power_generation.to_list()
    guar_list = guaranteed_sales.to_list()
    values = [g - guar_list[i] for i, g in enumerate(gen_list)]
    return pl.Series("market_sales", values, dtype=pl.Float64)


def compute_blended_price(
    derived: DerivedParams,
    inputs: ModelInputs,
    power_generation: pl.Series,
    guaranteed_sales: pl.Series,
    market_sales: pl.Series,
) -> pl.Series:
    """Row 49: 综合上网电价(含税).

    blended = (guaranteed / gen) × feed_in_tariff + (market / gen) × market_tariff.
    Falls back to feed_in_tariff when generation is zero.
    """
    ft = derived.feed_in_tariff
    mt = inputs.market_tariff
    gen_list = power_generation.to_list()
    guar_list = guaranteed_sales.to_list()
    mkt_list = market_sales.to_list()
    values: list[float] = []
    for i, gen in enumerate(gen_list):
        if gen <= 0:
            values.append(ft)
        else:
            values.append(
                (guar_list[i] / gen) * ft + (mkt_list[i] / gen) * mt
            )
    return pl.Series("blended_price", values, dtype=pl.Float64)


def compute_on_grid_price_incl_vat(blended_price: pl.Series) -> pl.Series:
    """Row 6: 上网电价(含税) = blended_price (direct echo)."""
    return pl.Series(
        "on_grid_price_incl_vat",
        blended_price.to_list(),
        dtype=pl.Float64,
    )


def compute_on_grid_price_excl_vat(
    inputs: ModelInputs, on_grid_price_incl_vat: pl.Series,
) -> pl.Series:
    """Row 7: 上网电价(不含税).

    Years 1-2: computed as incl_vat / (1 + vat_rate).
    Years 3+: frozen at year-2 value (column-freeze quirk).
    """
    vat = inputs.vat_rate
    divisor = 1.0 + vat
    incl_list = on_grid_price_incl_vat.to_list()
    values: list[float] = []
    for i, incl in enumerate(incl_list):
        if i < 2:
            values.append(incl / divisor)
        else:
            # Freeze at year-2 value (index 1)
            values.append(values[1])
    return pl.Series(
        "on_grid_price_excl_vat", values, dtype=pl.Float64,
    )


def compute_sales_revenue(
    power_generation: pl.Series, on_grid_price_excl_vat: pl.Series,
) -> pl.Series:
    """Row 8: 销售收入 = power_generation × on_grid_price_excl_vat."""
    gen_list = power_generation.to_list()
    price_list = on_grid_price_excl_vat.to_list()
    values = [gen_list[i] * price_list[i] for i in range(len(gen_list))]
    return pl.Series("sales_revenue", values, dtype=pl.Float64)


def compute_output_vat(
    inputs: ModelInputs, sales_revenue: pl.Series,
) -> pl.Series:
    """Row 37: 销项增值税 = sales_revenue × vat_rate."""
    vat = inputs.vat_rate
    values = [rev * vat for rev in sales_revenue.to_list()]
    return pl.Series("output_vat", values, dtype=pl.Float64)


def compute_vat_credit_balance(
    cost_statics: CostStatics, output_vat: pl.Series,
) -> pl.Series:
    """Row 38: 进项税留抵余额 — running balance of deductible input VAT.

    Initial pool = cost_statics.deductible_vat (待抵扣固定资产进项税额).
    Year 1: pool − output_vat.
    Year t: max(prev_balance − output_vat, 0).
    """
    pool = cost_statics.deductible_vat
    out_list = output_vat.to_list()
    values: list[float] = []
    prev_balance = pool
    for i, out_vat in enumerate(out_list):
        balance = pool - out_vat if i == 0 else max(prev_balance - out_vat, 0.0)
        values.append(balance)
        prev_balance = balance
    return pl.Series("vat_credit_balance", values, dtype=pl.Float64)


def compute_vat_credit_used(
    output_vat: pl.Series, vat_credit_balance: pl.Series,
) -> pl.Series:
    """Row 39: 进项税抵扣额.

    Year 1: = output_vat.
    Year t: = min(output_vat, prior-year vat_credit_balance).
    """
    out_list = output_vat.to_list()
    bal_list = vat_credit_balance.to_list()
    values: list[float] = []
    for i, out_vat in enumerate(out_list):
        if i == 0:
            values.append(out_vat)
        else:
            values.append(min(out_vat, bal_list[i - 1]))
    return pl.Series("vat_credit_used", values, dtype=pl.Float64)


def compute_vat_payable(
    output_vat: pl.Series, vat_credit_used: pl.Series,
) -> pl.Series:
    """Row 40: 应缴增值税.

    Years 1-2 (credit-recovery phase): (output_vat − credit_used) / 2.
    Years 3+: output_vat − credit_used (full).
    """
    out_list = output_vat.to_list()
    used_list = vat_credit_used.to_list()
    values: list[float] = []
    for i in range(len(out_list)):
        diff = out_list[i] - used_list[i]
        values.append(diff / 2.0 if i < 2 else diff)
    return pl.Series("vat_payable", values, dtype=pl.Float64)


def compute_surcharge_base(
    output_vat: pl.Series, vat_credit_used: pl.Series,
) -> pl.Series:
    """Row 41: 附加税计税基础 = (output_vat − credit_used) / 2 (always half)."""
    out_list = output_vat.to_list()
    used_list = vat_credit_used.to_list()
    values = [(out_list[i] - used_list[i]) / 2.0 for i in range(len(out_list))]
    return pl.Series("surcharge_base", values, dtype=pl.Float64)


def compute_city_maintenance_tax(
    inputs: ModelInputs, vat_payable: pl.Series,
) -> pl.Series:
    """Row 10: 城市维护建设税 = vat_payable × city_maintenance_tax_rate.

    Per the workbook, the tax base is vat_payable (row 40), not the surcharge
    base (row 41). This matches the old per-cell formulas.
    """
    rate = inputs.city_maintenance_tax_rate
    values = [vp * rate for vp in vat_payable.to_list()]
    return pl.Series("city_maintenance_tax", values, dtype=pl.Float64)


def compute_education_surcharge(
    inputs: ModelInputs, vat_payable: pl.Series,
) -> pl.Series:
    """Row 11: 教育费附加 = vat_payable × education_surcharge_rate."""
    rate = inputs.education_surcharge_rate
    values = [vp * rate for vp in vat_payable.to_list()]
    return pl.Series("education_surcharge", values, dtype=pl.Float64)


def compute_vat_surcharge_total(
    city_maintenance_tax: pl.Series, education_surcharge: pl.Series,
) -> pl.Series:
    """Row 9: 税金及附加合计 = city_maintenance_tax + education_surcharge."""
    city_list = city_maintenance_tax.to_list()
    edu_list = education_surcharge.to_list()
    values = [city_list[i] + edu_list[i] for i in range(len(city_list))]
    return pl.Series("vat_surcharge_total", values, dtype=pl.Float64)


def compute_vat_refund(axis: YearAxis) -> pl.Series:
    """Row 12: 增值税即征即退 — dead branch, all operating years = 0.

    The vat_exempt_year (2020) is the construction year, which precedes all
    operating years, so no refund applies during operation.
    """
    values = [0.0] * axis.operating_years
    return pl.Series("vat_refund", values, dtype=pl.Float64)


def compute_tax_rate_schedule(inputs: ModelInputs) -> pl.Series:
    """Row 20: 所得税税率(优惠阶梯).

    3-3-half ladder with western-dev branch:
    - Years 1-3: 0%
    - Years 4-6: half of applicable full rate
    - Years 7+: full applicable rate

    The applicable full rate is income_tax_rate (default 0.25), or
    western_dev_tax_rate (0.15) when western_dev_preferential is True.
    """
    full_rate = (
        inputs.western_dev_tax_rate
        if inputs.western_dev_preferential
        else inputs.income_tax_rate
    )
    half_rate = full_rate / 2.0
    values: list[float] = []
    for i in range(inputs.operating_years):
        if i < 3:
            values.append(0.0)
        elif i < 6:
            values.append(half_rate)
        else:
            values.append(full_rate)
    return pl.Series("tax_rate_schedule", values, dtype=pl.Float64)


# ═══════════════════════════════════════════════════════════════════════════
# Non-coupled scalar computers
# ═══════════════════════════════════════════════════════════════════════════


def compute_row13_total() -> float:
    """Row 13 AF: total = 0 (no other income in this model)."""
    return 0.0


def compute_row28_total() -> float:
    """Row 28 AF: total = 0 (placeholder row)."""
    return 0.0


def compute_depreciation_echo(cost_statics: CostStatics) -> float:
    """Row 36: 折旧(回显) = cost_statics.deductible_vat (from cost sheet D28)."""
    return float(cost_statics.deductible_vat)


# ═══════════════════════════════════════════════════════════════════════════
# Post-mutual non-coupled computers (used in assemble)
# ═══════════════════════════════════════════════════════════════════════════


def compute_dividend(solution: MutualSolution) -> pl.Series:
    """Row 32: 分红 = finplan:profit_distribution (from mutual solution)."""
    values = [step.profit_distribution for step in solution.steps]
    return pl.Series("dividend", values, dtype=pl.Float64)


def compute_undistributed_profit(
    solution: MutualSolution, dividend: pl.Series,
) -> pl.Series:
    """Row 33: 未分配利润.

    undistributed = distributable_profit − dividend
                    + (total_profit if total_profit < 0 else loss_compensation).

    When the current year is a loss (total_profit < 0), the loss itself is
    added as an adjustment (reducing undistributed profit further).  When
    profit is non-negative, loss_compensation (offsetting prior losses) is
    added.
    """
    div_list = dividend.to_list()
    values: list[float] = []
    for i, step in enumerate(solution.steps):
        dist = step.distributable_profit
        div = div_list[i]
        profit = step.total_profit
        adj = profit if profit < 0 else step.loss_compensation
        values.append(dist - div + adj)
    return pl.Series("undistributed_profit", values, dtype=pl.Float64)


# ═══════════════════════════════════════════════════════════════════════════
# Orchestration
# ═══════════════════════════════════════════════════════════════════════════


def compute_core(params: ParamsCore, cost_statics: CostStatics) -> PnLCore:
    """Stage 7: compute all non-coupled PnL items before the mutual block.

    Revenue, VAT/surcharge block, tax rate schedule, and scalars are computed
    here.  Coupled items (total_cost through distributable_profit) are
    deferred to the mutual block and filled by ``assemble``.
    """
    inputs: ModelInputs = params.inputs
    axis: YearAxis = params.axis
    derived: DerivedParams = params.derived

    # --- generation & tariff block ---
    year_labels = compute_year_labels(axis)
    power_gen = compute_power_generation(inputs)
    guaranteed = compute_guaranteed_sales(inputs, power_gen)
    market = compute_market_sales(power_gen, guaranteed)
    blended = compute_blended_price(derived, inputs, power_gen, guaranteed, market)
    price_incl = compute_on_grid_price_incl_vat(blended)
    price_excl = compute_on_grid_price_excl_vat(inputs, price_incl)
    revenue = compute_sales_revenue(power_gen, price_excl)

    # --- VAT / surcharge block ---
    out_vat = compute_output_vat(inputs, revenue)
    credit_bal = compute_vat_credit_balance(cost_statics, out_vat)
    credit_used = compute_vat_credit_used(out_vat, credit_bal)
    vat_pay = compute_vat_payable(out_vat, credit_used)
    surch_base = compute_surcharge_base(out_vat, credit_used)
    city_tax = compute_city_maintenance_tax(inputs, vat_pay)
    edu_sur = compute_education_surcharge(inputs, vat_pay)
    vat_sur_total = compute_vat_surcharge_total(city_tax, edu_sur)
    vat_ref = compute_vat_refund(axis)
    tax_rates = compute_tax_rate_schedule(inputs)

    # --- scalars ---
    scalars = PnLScalars(
        depreciation_echo=compute_depreciation_echo(cost_statics),
        row13_total=compute_row13_total(),
        row28_total=compute_row28_total(),
    )

    # --- frame ---
    frame = pl.DataFrame({
        "year": list(axis.years),
        "year_labels": year_labels,
        "power_generation": power_gen,
        "guaranteed_sales": guaranteed,
        "market_sales": market,
        "blended_price": blended,
        "on_grid_price_incl_vat": price_incl,
        "on_grid_price_excl_vat": price_excl,
        "sales_revenue": revenue,
        "output_vat": out_vat,
        "vat_credit_balance": credit_bal,
        "vat_credit_used": credit_used,
        "vat_payable": vat_pay,
        "surcharge_base": surch_base,
        "city_maintenance_tax": city_tax,
        "education_surcharge": edu_sur,
        "vat_surcharge_total": vat_sur_total,
        "vat_refund": vat_ref,
        "tax_rate_schedule": tax_rates,
    })

    return PnLCore(years=axis.years, frame=frame, scalars=scalars)


def assemble(core: PnLCore, solution: MutualSolution) -> PnLResult:
    """Stage 9: merge coupled columns + dividend/undistributed_profit.

    Reads the 11 PnL-coupled fields from MutualSolution year-by-year and
    computes dividend + undistributed_profit from the solution.
    """
    steps = solution.steps

    # Extract coupled columns from solution
    coupled_cols: dict[str, list[float]] = {
        "total_cost": [],
        "total_profit": [],
        "loss_compensation": [],
        "income_tax": [],
        "loss": [],
        "tax_echo": [],
        "loss_carry_forward": [],
        "cum_profit": [],
        "net_profit": [],
        "surplus_reserve": [],
        "distributable_profit": [],
    }
    for step in steps:
        coupled_cols["total_cost"].append(step.total_cost)
        coupled_cols["total_profit"].append(step.total_profit)
        coupled_cols["loss_compensation"].append(step.loss_compensation)
        coupled_cols["income_tax"].append(step.income_tax)
        coupled_cols["loss"].append(step.loss)
        coupled_cols["tax_echo"].append(step.tax_echo)
        coupled_cols["loss_carry_forward"].append(step.loss_carry_forward)
        coupled_cols["cum_profit"].append(step.cum_profit)
        coupled_cols["net_profit"].append(step.net_profit)
        coupled_cols["surplus_reserve"].append(step.surplus_reserve)
        coupled_cols["distributable_profit"].append(step.distributable_profit)

    # Non-coupled post-mutual items
    dividend = compute_dividend(solution)
    undistributed = compute_undistributed_profit(solution, dividend)

    # Build full frame: core columns + coupled + dividend + undistributed
    core_df = core.frame
    full_df = core_df.with_columns([
        pl.Series(
            "total_cost", coupled_cols["total_cost"], dtype=pl.Float64,
        ),
        pl.Series(
            "total_profit", coupled_cols["total_profit"], dtype=pl.Float64,
        ),
        pl.Series(
            "loss_compensation",
            coupled_cols["loss_compensation"], dtype=pl.Float64,
        ),
        pl.Series(
            "income_tax", coupled_cols["income_tax"], dtype=pl.Float64,
        ),
        pl.Series("loss", coupled_cols["loss"], dtype=pl.Float64),
        pl.Series(
            "tax_echo", coupled_cols["tax_echo"], dtype=pl.Float64,
        ),
        pl.Series(
            "loss_carry_forward",
            coupled_cols["loss_carry_forward"], dtype=pl.Float64,
        ),
        pl.Series(
            "cum_profit", coupled_cols["cum_profit"], dtype=pl.Float64,
        ),
        pl.Series(
            "net_profit", coupled_cols["net_profit"], dtype=pl.Float64,
        ),
        pl.Series(
            "surplus_reserve",
            coupled_cols["surplus_reserve"], dtype=pl.Float64,
        ),
        pl.Series(
            "distributable_profit",
            coupled_cols["distributable_profit"], dtype=pl.Float64,
        ),
        dividend.alias("dividend"),
        undistributed.alias("undistributed_profit"),
    ])

    return PnLResult(
        years=core.years,
        frame=full_df,
        scalars=core.scalars,
    )


def compute_adjusted_profit(
    pnl: PnLResult,
    balance: BalanceResult,
    cost: CostResult,
    params: ParamsCore,
) -> pl.Series:
    r"""Row 43: 调整后利润(估值口径).

    .. math::

        \begin{aligned}
        \text{WACC}_t &= d_t \cdot r_d + (1 - d_t) \cdot r_e \\
        \text{adj\_profit}_t &= \text{net\_profit}_t
            + \text{interest}_t \cdot (1 - 0.25)
            - \text{total\_assets}_t \cdot \text{WACC}_t
        \end{aligned}

    where:
    - :math:`d_t` = asset_liability_ratio (debt ratio, balance row 23)
    - :math:`r_d` = loan_rate_long (from params)
    - :math:`r_e` = 0.044 (workbook constant, equity cost of capital)
    - total_assets = total_liabilities_equity (balance row 13)
    - interest = interest_expense (cost row 13)

    The tax rate used for the after-tax interest adjustment is 0.25
    (hard-coded per the workbook formula), NOT the year-varying
    tax_rate_schedule — this is a valuation-standard adjustment.
    """
    net_profit = pnl.frame["net_profit"].to_list()
    # Balance frame holds construction + 25 operating years; the PnL
    # frame holds only the 25 operating years, so balance reads shift by 1.
    total_assets = balance.frame["total_liabilities_equity"].to_list()[1:]
    debt_ratio = balance.frame["asset_liability_ratio"].to_list()[1:]
    interest = cost.frame["interest_expense"].to_list()

    loan_rate: float = params.inputs.loan_rate_long
    equity_cost: float = _EQUITY_COST_OF_CAPITAL
    tax_rate: float = 0.25

    values: list[float] = []
    for i in range(len(net_profit)):
        wacc = debt_ratio[i] * loan_rate + (
            1.0 - debt_ratio[i]
        ) * equity_cost
        adj = (
            net_profit[i]
            + interest[i] * (1.0 - tax_rate)
            - total_assets[i] * wacc
        )
        values.append(adj)

    return pl.Series("adjusted_profit", values, dtype=pl.Float64)


def compute_valuation_aux(
    pnl: PnLResult,
    balance: BalanceResult,
    cost: CostResult,
    params: ParamsCore,
) -> PnLResult:
    """Stage 11: append adjusted_profit column, return new PnLResult."""
    adj = compute_adjusted_profit(pnl, balance, cost, params)
    new_frame = pnl.frame.with_columns(adj)
    return PnLResult(
        years=pnl.years,
        frame=new_frame,
        scalars=pnl.scalars,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Domain calculation schema
# ═══════════════════════════════════════════════════════════════════════════

SCHEMA = DomainSchema(
    key="pnl",
    sheet="损益",
    label="损益表 (PnL)",
    depends_on=("params", "cost", "balance", "mutual", "finplan"),
    items=(
        ItemSchema(
            key="year_labels",
            label="运营年度",
            unit="-",
            formula="Calendar years from axis (2021..2045)",
            inputs=("params:years",),
            rows=(4,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="power_generation",
            label="年发电量",
            unit="MWh",
            formula=(
                "installed_capacity_mw × first_year_full_hours "
                "× degradation_factor[i+1] × load_rate[i+1]"
            ),
            inputs=("params:installed_capacity_mw", "params:first_year_full_hours"),
            rows=(5,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="guaranteed_sales",
            label="保障利用小时售电量",
            unit="MWh",
            formula="min(guaranteed_hours × installed_capacity_mw, power_generation)",
            inputs=("power_generation", "params:guaranteed_hours"),
            rows=(47,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="market_sales",
            label="市场化售电量",
            unit="MWh",
            formula="power_generation − guaranteed_sales",
            inputs=("power_generation", "guaranteed_sales"),
            rows=(48,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="blended_price",
            label="综合上网电价(含税)",
            unit="元/kWh",
            formula=(
                "(guaranteed_sales / power_generation) × feed_in_tariff "
                "+ (market_sales / power_generation) × market_tariff"
            ),
            inputs=(
                "guaranteed_sales", "market_sales",
                "params:feed_in_tariff", "params:market_tariff",
            ),
            rows=(49,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="on_grid_price_incl_vat",
            label="上网电价(含税)",
            unit="元/kWh",
            formula="blended_price (echo)",
            inputs=("blended_price",),
            rows=(6,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="on_grid_price_excl_vat",
            label="上网电价(不含税)",
            unit="元/kWh",
            formula=(
                "on_grid_price_incl_vat ÷ (1 + vat_rate); "
                "frozen at year-2 value from year 3 on"
            ),
            inputs=("on_grid_price_incl_vat", "params:vat_rate"),
            rows=(7,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="sales_revenue",
            label="销售收入",
            unit="万元",
            formula="power_generation × on_grid_price_excl_vat",
            inputs=("power_generation", "on_grid_price_excl_vat"),
            rows=(8,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="output_vat",
            label="销项增值税",
            unit="万元",
            formula="sales_revenue × vat_rate",
            inputs=("sales_revenue", "params:vat_rate"),
            rows=(37,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="vat_credit_balance",
            label="进项税留抵余额",
            unit="万元",
            formula=(
                "Running balance: initial pool = cost:deductible_vat; "
                "year 1 = pool − output_vat; "
                "year t = max(prev_balance − output_vat, 0)"
            ),
            inputs=("output_vat", "cost:deductible_vat"),
            rows=(38,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="vat_credit_used",
            label="进项税抵扣额",
            unit="万元",
            formula=(
                "Year 1 = output_vat; "
                "year t = min(output_vat, prior vat_credit_balance)"
            ),
            inputs=("output_vat", "vat_credit_balance"),
            rows=(39,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="vat_payable",
            label="应缴增值税",
            unit="万元",
            formula=(
                "(output_vat − vat_credit_used) "
                "— half during first 2 years (credit-recovery phase); "
                "full from year 3"
            ),
            inputs=("output_vat", "vat_credit_used"),
            rows=(40,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="surcharge_base",
            label="附加税计税基础",
            unit="万元",
            formula="(output_vat − vat_credit_used) ÷ 2 (always half)",
            inputs=("output_vat", "vat_credit_used"),
            rows=(41,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="city_maintenance_tax",
            label="城市维护建设税",
            unit="万元",
            formula="vat_payable × city_maintenance_tax_rate",
            inputs=("vat_payable", "params:city_maintenance_tax_rate"),
            rows=(10,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="education_surcharge",
            label="教育费附加",
            unit="万元",
            formula="vat_payable × education_surcharge_rate",
            inputs=("vat_payable", "params:education_surcharge_rate"),
            rows=(11,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="vat_surcharge_total",
            label="税金及附加合计",
            unit="万元",
            formula="city_maintenance_tax + education_surcharge",
            inputs=("city_maintenance_tax", "education_surcharge"),
            rows=(9,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="vat_refund",
            label="增值税即征即退",
            unit="万元",
            formula=(
                "0 for all operating years "
                "(vat_exempt_year 2020 precedes operation; dead branch)"
            ),
            inputs=("params:vat_exempt_year",),
            rows=(12,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="tax_rate_schedule",
            label="所得税税率(优惠阶梯)",
            unit="%",
            formula=(
                "3-3-half ladder: years 1-3 = 0, 4-6 = half, 7+ = full. "
                "Full rate = western_dev_tax_rate if western_dev_preferential, "
                "else income_tax_rate."
            ),
            inputs=(
                "params:income_tax_rate", "params:western_dev_preferential",
                "params:western_dev_tax_rate",
            ),
            rows=(20,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="total_cost",
            label="总成本费用",
            unit="万元",
            formula="cost:total_operating_cost (mutual block)",
            inputs=("cost:total_operating_cost",),
            rows=(14,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="total_profit",
            label="利润总额",
            unit="万元",
            formula=(
                "sales_revenue − vat_surcharge_total − total_cost + vat_refund "
                "(mutual block)"
            ),
            inputs=(
                "sales_revenue", "vat_surcharge_total", "total_cost", "vat_refund",
            ),
            rows=(15,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="loss_compensation",
            label="弥补亏损",
            unit="万元",
            formula=(
                "IF total_profit <= 0 OR prior cum_profit >= 0 THEN 0 "
                "ELSE MIN(total_profit, −prior_cum_profit) (mutual block)"
            ),
            inputs=("total_profit", "cum_profit"),
            rows=(22,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="income_tax",
            label="所得税",
            unit="万元",
            formula=(
                "IF total_profit < 0 THEN 0 "
                "ELSE (total_profit − loss_compensation) × tax_rate_schedule "
                "(mutual block)"
            ),
            inputs=("total_profit", "loss_compensation", "tax_rate_schedule"),
            rows=(21,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="loss",
            label="亏损额",
            unit="万元",
            formula="max(0, −total_profit) (mutual block)",
            inputs=("total_profit",),
            rows=(23,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="tax_echo",
            label="所得税(回显)",
            unit="万元",
            formula="income_tax (echo for downstream sheets) (mutual block)",
            inputs=("income_tax",),
            rows=(25,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="loss_carry_forward",
            label="亏损结转",
            unit="万元",
            formula=(
                "Cumulative loss − cumulative compensation; "
                "fires from operating year 6 (mutual block quirk)"
            ),
            inputs=("loss", "loss_compensation"),
            rows=(24,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="cum_profit",
            label="累计利润",
            unit="万元",
            formula=(
                "total_profit − tax_echo + loss_carry_forward "
                "+ prior_cum_profit (recurrence, mutual block)"
            ),
            inputs=("total_profit", "tax_echo", "loss_carry_forward"),
            rows=(16,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="net_profit",
            label="净利润",
            unit="万元",
            formula=(
                "IF total_profit <= 0 THEN 0 "
                "ELSE total_profit − loss_compensation − income_tax "
                "(mutual block)"
            ),
            inputs=("total_profit", "loss_compensation", "income_tax"),
            rows=(26,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="surplus_reserve",
            label="盈余公积金",
            unit="万元",
            formula=(
                "IF cum_profit <= 0 THEN 0 "
                "ELSE net_profit × surplus_reserve_ratio (mutual block)"
            ),
            inputs=("net_profit", "cum_profit", "params:surplus_reserve_ratio"),
            rows=(27,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="distributable_profit",
            label="可分配利润",
            unit="万元",
            formula=(
                "IF cum_profit <= 0 THEN 0 "
                "ELSE net_profit − surplus_reserve (mutual block)"
            ),
            inputs=("net_profit", "surplus_reserve", "cum_profit"),
            rows=(29,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="dividend",
            label="分红",
            unit="万元",
            formula="finplan:profit_distribution (from mutual solution)",
            inputs=("finplan:profit_distribution",),
            rows=(32,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="undistributed_profit",
            label="未分配利润",
            unit="万元",
            formula=(
                "distributable_profit − dividend "
                "+ (total_profit if total_profit < 0 else loss_compensation)"
            ),
            inputs=(
                "distributable_profit", "dividend",
                "total_profit", "loss_compensation",
            ),
            rows=(33,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="depreciation_echo",
            label="折旧(回显)",
            unit="万元",
            formula="cost:deductible_vat (成本 D28, single scalar)",
            inputs=("cost:deductible_vat",),
            rows=(36,),
            kind="scalar",
            coupled=False,
        ),
        ItemSchema(
            key="adjusted_profit",
            label="调整后利润(估值口径)",
            unit="万元",
            formula=(
                "net_profit + interest_expense × (1 − 0.25) "
                "− total_assets × [debt_ratio × loan_rate + (1−debt_ratio) × 0.044]"
            ),
            inputs=(
                "net_profit", "balance:total_liabilities_equity",
                "balance:asset_liability_ratio", "cost:interest_expense",
                "params:loan_rate_long",
            ),
            rows=(43,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="row13_total",
            label="合计行13",
            unit="万元",
            formula="0 (no other income)",
            inputs=(),
            rows=(13,),
            kind="scalar",
            coupled=False,
        ),
        ItemSchema(
            key="row28_total",
            label="合计行28",
            unit="万元",
            formula="0 (placeholder row)",
            inputs=(),
            rows=(28,),
            kind="scalar",
            coupled=False,
        ),
    ),
)
