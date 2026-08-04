"""Mutual block — the year-interleaved recurrence solver.

Solves the cross-domain cycle via sequential per-year computation.
Short-term borrowing closes the loop; carry propagates across years.

Phases (per year t):
  A: finplan short_term_repayment = prior short_term_borrowing
  B: debt short_term_principal/interest from repayment
  C: cost short_term_loan_interest → interest_expense → total_operating_cost
  D: pnl total_cost → total_profit → loss_comp → income_tax → loss →
     tax_echo → loss_carry_forward → cum_profit → net_profit →
     surplus_reserve → distributable_profit
  E: cashflow equity_income_tax = pnl income_tax;
     finplan income_tax_outflow → operating_outflow → operating_net_cf;
     finplan interest_outflow = cost interest_expense
  F: finplan distributable_profit_pool → actual_distribution →
     profit_distribution → invest_outflow → deficit bridge →
     short_term_borrowing → invest_inflow → invest_finance_net_cf →
     net_cash_flow → cumulative_surplus

The construction year (year 0) is computed as a one-off prologue before
the 25-year loop.  Three values thread across years as YearCarry:
prior_short_term_borrowing, prior_cum_profit, prior_cumulative_surplus.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solar_v2.domains.cost import CostCore
    from solar_v2.domains.debt import DebtBase
    from solar_v2.domains.invest import InvestResult
    from solar_v2.domains.params import ParamsCore
    from solar_v2.domains.pnl import PnLCore

# ---------------------------------------------------------------------------
# Carrier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YearCarry:
    """Values threaded from year t-1 into year t.

    All three start at 0.0 before the first operating year.
    """

    prior_short_term_borrowing: float = 0.0
    prior_cum_profit: float = 0.0
    prior_cumulative_surplus: float = 0.0


# ---------------------------------------------------------------------------
# YearSlice -- all 31 coupled values for one operating year
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YearSlice:
    """One operating year's coupled values across 5 domains.

    Field names are the coupled schema item keys (the cross-domain contract).
    """

    # -- Phase A: finplan short_term_repayment (row 28) --
    short_term_repayment: float = 0.0

    # -- Phase B: debt (rows 20, 21) --
    short_term_principal: float = 0.0
    short_term_interest: float = 0.0

    # -- Phase C: cost (rows 16, 13, 21) --
    short_term_loan_interest: float = 0.0
    interest_expense: float = 0.0
    total_operating_cost: float = 0.0

    # -- Phase D: pnl (rows 14, 15, 22, 21, 23, 25, 24, 16, 26, 27, 29) --
    total_cost: float = 0.0
    total_profit: float = 0.0
    loss_compensation: float = 0.0
    income_tax: float = 0.0
    loss: float = 0.0
    tax_echo: float = 0.0
    loss_carry_forward: float = 0.0
    cum_profit: float = 0.0
    net_profit: float = 0.0
    surplus_reserve: float = 0.0
    distributable_profit: float = 0.0

    # -- Phase E: cashflow (row 57) + finplan (rows 15, 11, 5, 30) --
    equity_income_tax: float = 0.0
    income_tax_outflow: float = 0.0
    operating_outflow: float = 0.0
    operating_net_cf: float = 0.0
    interest_outflow: float = 0.0

    # -- Phase F: finplan (rows 40, 41, 31, 24, 22, 18, 17, 33, 34) --
    distributable_profit_pool: float = 0.0
    actual_distribution: float = 0.0
    profit_distribution: float = 0.0
    invest_outflow: float = 0.0
    short_term_borrowing: float = 0.0
    invest_inflow: float = 0.0
    invest_finance_net_cf: float = 0.0
    net_cash_flow: float = 0.0
    cumulative_surplus: float = 0.0


# ---------------------------------------------------------------------------
# ConstructionSlice -- year-0 prologue values
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConstructionSlice:
    """Construction-year (year 0) values of coupled finplan rows.

    Only the finplan coupled keys that have non-trivial construction-period
    values.  The remaining coupled keys are zero during construction (no
    operating activity, no distributions, no prior-period bridge).

    Field names are the coupled key names; no collision with YearSlice
    because these live on a separate dataclass.
    """

    invest_inflow: float = 0.0
    invest_outflow: float = 0.0
    invest_finance_net_cf: float = 0.0
    short_term_borrowing: float = 0.0
    net_cash_flow: float = 0.0
    cumulative_surplus: float = 0.0


# ---------------------------------------------------------------------------
# MutualSolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MutualSolution:
    """Complete mutual-block output.

    ``steps`` holds one YearSlice per operating year (25, in order).
    ``construction`` holds the construction-year prologue.
    Domain assemble functions index ``steps[t].<coupled_key>`` to build
    frame columns.
    """

    steps: tuple[YearSlice, ...]
    construction: ConstructionSlice

    # -- per-key column accessors (one tuple per coupled key, year order) --
    @property
    def short_term_repayment(self) -> tuple[float, ...]:
        """短期借款本金偿还, 25 operating years."""
        return tuple(s.short_term_repayment for s in self.steps)

    @property
    def short_term_principal(self) -> tuple[float, ...]:
        """还贷 短期借款还本, 25 operating years."""
        return tuple(s.short_term_principal for s in self.steps)

    @property
    def short_term_interest(self) -> tuple[float, ...]:
        """还贷 短期借款付息, 25 operating years."""
        return tuple(s.short_term_interest for s in self.steps)

    @property
    def short_term_loan_interest(self) -> tuple[float, ...]:
        """成本 短期借款利息, 25 operating years."""
        return tuple(s.short_term_loan_interest for s in self.steps)

    @property
    def interest_expense(self) -> tuple[float, ...]:
        """成本 利息支出, 25 operating years."""
        return tuple(s.interest_expense for s in self.steps)

    @property
    def total_operating_cost(self) -> tuple[float, ...]:
        """成本 总成本费用, 25 operating years."""
        return tuple(s.total_operating_cost for s in self.steps)

    @property
    def total_cost(self) -> tuple[float, ...]:
        """损益 总成本费用, 25 operating years."""
        return tuple(s.total_cost for s in self.steps)

    @property
    def total_profit(self) -> tuple[float, ...]:
        """损益 利润总额, 25 operating years."""
        return tuple(s.total_profit for s in self.steps)

    @property
    def loss_compensation(self) -> tuple[float, ...]:
        """损益 弥补亏损, 25 operating years."""
        return tuple(s.loss_compensation for s in self.steps)

    @property
    def income_tax(self) -> tuple[float, ...]:
        """损益 所得税, 25 operating years."""
        return tuple(s.income_tax for s in self.steps)

    @property
    def loss(self) -> tuple[float, ...]:
        """损益 亏损额, 25 operating years."""
        return tuple(s.loss for s in self.steps)

    @property
    def tax_echo(self) -> tuple[float, ...]:
        """损益 所得税回显, 25 operating years."""
        return tuple(s.tax_echo for s in self.steps)

    @property
    def loss_carry_forward(self) -> tuple[float, ...]:
        """损益 亏损结转, 25 operating years."""
        return tuple(s.loss_carry_forward for s in self.steps)

    @property
    def cum_profit(self) -> tuple[float, ...]:
        """损益 累计利润, 25 operating years."""
        return tuple(s.cum_profit for s in self.steps)

    @property
    def net_profit(self) -> tuple[float, ...]:
        """损益 净利润, 25 operating years."""
        return tuple(s.net_profit for s in self.steps)

    @property
    def surplus_reserve(self) -> tuple[float, ...]:
        """损益 盈余公积金, 25 operating years."""
        return tuple(s.surplus_reserve for s in self.steps)

    @property
    def distributable_profit(self) -> tuple[float, ...]:
        """损益 可分配利润, 25 operating years."""
        return tuple(s.distributable_profit for s in self.steps)

    @property
    def equity_income_tax(self) -> tuple[float, ...]:
        """现金流量 所得税, 25 operating years."""
        return tuple(s.equity_income_tax for s in self.steps)

    @property
    def income_tax_outflow(self) -> tuple[float, ...]:
        """财务计划 所得税流出, 25 operating years."""
        return tuple(s.income_tax_outflow for s in self.steps)

    @property
    def operating_outflow(self) -> tuple[float, ...]:
        """财务计划 经营活动现金流出, 25 operating years."""
        return tuple(s.operating_outflow for s in self.steps)

    @property
    def operating_net_cf(self) -> tuple[float, ...]:
        """财务计划 经营活动净现金流量, 25 operating years."""
        return tuple(s.operating_net_cf for s in self.steps)

    @property
    def interest_outflow(self) -> tuple[float, ...]:
        """财务计划 各种利息支出, 25 operating years."""
        return tuple(s.interest_outflow for s in self.steps)

    @property
    def distributable_profit_pool(self) -> tuple[float, ...]:
        """财务计划 可分配利润, 25 operating years."""
        return tuple(s.distributable_profit_pool for s in self.steps)

    @property
    def actual_distribution(self) -> tuple[float, ...]:
        """财务计划 实际分配利润, 25 operating years."""
        return tuple(s.actual_distribution for s in self.steps)

    @property
    def profit_distribution(self) -> tuple[float, ...]:
        """财务计划 各投资方利润分配, 25 operating years."""
        return tuple(s.profit_distribution for s in self.steps)

    @property
    def invest_outflow(self) -> tuple[float, ...]:
        """财务计划 投筹资现金流出, 25 operating years."""
        return tuple(s.invest_outflow for s in self.steps)

    @property
    def short_term_borrowing(self) -> tuple[float, ...]:
        """财务计划 短期借款, 25 operating years."""
        return tuple(s.short_term_borrowing for s in self.steps)

    @property
    def invest_inflow(self) -> tuple[float, ...]:
        """财务计划 投筹资现金流入, 25 operating years."""
        return tuple(s.invest_inflow for s in self.steps)

    @property
    def invest_finance_net_cf(self) -> tuple[float, ...]:
        """财务计划 投筹资净现金流量, 25 operating years."""
        return tuple(s.invest_finance_net_cf for s in self.steps)

    @property
    def net_cash_flow(self) -> tuple[float, ...]:
        """财务计划 净现金流量, 25 operating years."""
        return tuple(s.net_cash_flow for s in self.steps)

    @property
    def cumulative_surplus(self) -> tuple[float, ...]:
        """财务计划 累计盈余资金, 25 operating years."""
        return tuple(s.cumulative_surplus for s in self.steps)


# ===================================================================
# Loss carry-forward accumulator
# ===================================================================


def _compute_loss_carry_forward(
    year_index: int,
    losses: list[float],
    loss_comps: list[float],
    prior_lcfs: list[float],
) -> float:
    """Compute loss_carry_forward (损益 row 24) for one year.

    Fires from operating year 6 (index 5) onward.  Before that, always 0.

    Formula from old workbook:
      IF cum_loss > cum_r22 + cum_r24,
         cum_loss - (cum_r22 + cum_r24),
         else 0
    where cum_loss = sum of row 23 (loss) from year 1 through this year,
          cum_r22  = sum of row 22 (loss_compensation) through this year,
          cum_r24  = sum of row 24 from year 6 through year-1.
    """
    if year_index < 5:
        return 0.0
    cum_loss = sum(losses[: year_index + 1])
    cum_r22 = sum(loss_comps[: year_index + 1])
    cum_r24 = sum(prior_lcfs[5:year_index])
    total_comp = cum_r22 + cum_r24
    return cum_loss - total_comp if cum_loss > total_comp else 0.0


# ===================================================================
# Construction prologue
# ===================================================================


def _invest_at(invest: InvestResult, column: str, period: str) -> float:
    """One invest frame value at a named construction period.

    The invest frame is period-keyed (build1, build2, oper1, oper2).
    """
    periods = invest.frame["period"].to_list()
    if period not in periods:
        return 0.0
    return float(invest.frame[column].to_list()[periods.index(period)])


# Columns summed into the non-interest part of 总成本费用:
# depreciation, repair, salary, insurance, material, land tax,
# land-rent echo, and other costs (everything except interest).
_NON_INTEREST_COST_COLUMNS = (
    "depreciation_echo",
    "repair_cost",
    "salary_cost",
    "insurance_cost",
    "material_cost",
    "land_tax_cost",
    "land_rent_echo",
    "other_cost",
)


def _construction_prologue(
    invest: InvestResult,
    debt_base: DebtBase,
) -> ConstructionSlice:
    """Compute construction-year (year 0) finplan coupled values.

    During construction there are no operating cash flows, no
    distributions, and no prior-period repayment bridge.  Equity and
    funding arrive at the invest plan's first operating period (the
    workbook maps the finplan construction column to that period).
    """
    eq_inj = _invest_at(invest, "equity_capital", "oper1")
    constr_inv = _invest_at(invest, "funding_sources", "oper1")
    constr_loan = float(debt_base.frame["long_term_loan_balance"][0])
    wc_loan = 0.0
    wc = 0.0

    op_net = 0.0
    st_repay = 0.0
    lt_repay = 0.0
    int_outflow = 0.0
    profit_dist = 0.0
    other_out = 0.0

    # invest_outflow = construction investment + working capital
    inv_out = constr_inv + wc + lt_repay + int_outflow + profit_dist + other_out

    # Deficit bridge (prior cumulative surplus = 0)
    deficit = -op_net - eq_inj - constr_loan - wc_loan + inv_out + st_repay
    st_borrowing = deficit if deficit > 0 else 0.0

    # invest_inflow = equity + constr_loan + wc_loan + short_term_borrowing
    inv_in = eq_inj + constr_loan + wc_loan + st_borrowing

    inv_fin_net = inv_in - inv_out
    net_cf = op_net + inv_fin_net - st_repay
    cum_surplus = net_cf

    return ConstructionSlice(
        invest_inflow=inv_in,
        invest_outflow=inv_out,
        invest_finance_net_cf=inv_fin_net,
        short_term_borrowing=st_borrowing,
        net_cash_flow=net_cf,
        cumulative_surplus=cum_surplus,
    )


# ===================================================================
# Per-year step
# ===================================================================


def step_year(
    params: ParamsCore,
    invest: InvestResult,
    debt_base: DebtBase,
    cost_core: CostCore,
    pnl_core: PnLCore,
    year_index: int,
    carry: YearCarry,
    *,
    loss_carry_forward: float = 0.0,
) -> YearSlice:
    """Compute all 31 coupled values for one operating year.

    Per-year non-coupled financing values are read from invest and
    debt_base attributes (zero for most operating years).  The loss
    carry-forward value is computed by the solver from accumulator
    state and passed in via the keyword argument.

    Parameters
    ----------
    params:
        Constant-folded parameter scalars (short_term_loan_rate,
        surplus_reserve_ratio, dividend_ratio, income_tax_rate).
    invest:
        Construction-period investment plan.  Provides per-year
        working_capital_loan and working_capital (nonzero only at
        year 0 = first operating year); equity_injection and
        construction_investment are zero during operation.
    debt_base:
        Long-term loan schedule.  Provides per-year lt_repayment_schedule
        and construction_loan scalar.
    cost_core:
        Non-coupled cost items per year: long_term_loan_interest,
        working_capital_loan_interest, non_interest_costs,
        operating_cost, land_rent.
    pnl_core:
        Revenue / VAT block per year: sales_revenue, vat_surcharge_total,
        vat_refund, output_vat, city_maintenance_tax,
        education_surcharge, vat_payable.
    year_index:
        Zero-based operating-year index (0 = first operating year).
    carry:
        Values carried in from year t-1.
    loss_carry_forward:
        Pre-computed loss_carry_forward value (default 0.0).

    Returns
    -------
    YearSlice
    """
    # Short aliases
    inputs = params.inputs
    st_rate = inputs.short_term_loan_rate
    sr_ratio = inputs.surplus_reserve_ratio
    div_ratio = inputs.dividend_ratio

    pf = pnl_core.frame
    cf = cost_core.frame

    # Per-year financing values from invest / debt_base.
    # Only the first operating year carries construction-period funding:
    # equity, long-term loan, working-capital loan, and working capital
    # all land at the invest plan's second operating period (the workbook
    # maps the first finplan operating column to that period).
    eq_inj = _invest_at(invest, "equity_capital", "oper2") if year_index == 0 else 0.0
    constr_loan = 0.0
    wc_loan = (
        _invest_at(invest, "working_capital_loan", "oper2")
        if year_index == 0
        else 0.0
    )
    constr_inv = (
        _invest_at(invest, "long_term_loan", "oper2") if year_index == 0 else 0.0
    )
    wc = _invest_at(invest, "working_capital", "oper2") if year_index == 0 else 0.0
    # Long-term principal repayment (debt frame row 10 key, kept from the
    # legacy schema naming): debt frame index 0 is the construction year.
    lt_repay = float(debt_base.frame["long_term_loan_interest_payment"][year_index + 1])
    other_out = 0.0

    # ==================================================================
    # Phase A: finplan short_term_repayment (row 28)
    # ==================================================================
    st_repay = carry.prior_short_term_borrowing

    # ==================================================================
    # Phase B: debt (rows 20, 21)
    # ==================================================================
    st_principal = st_repay
    st_interest = st_principal * st_rate

    # ==================================================================
    # Phase C: cost (rows 16, 13, 21)
    # ==================================================================
    cost_st_interest = st_interest
    lt_int = float(cf["long_term_loan_interest"][year_index])
    wc_int = float(cf["working_capital_loan_interest"][year_index])
    int_expense = lt_int + wc_int + cost_st_interest  # surplus = 0
    non_int = sum(float(cf[c][year_index]) for c in _NON_INTEREST_COST_COLUMNS)
    total_cost_cost = non_int + int_expense

    # ==================================================================
    # Phase D: pnl (rows 14, 15, 22, 21, 23, 25, 24, 16, 26, 27, 29)
    # ==================================================================
    total_cost = total_cost_cost

    revenue = float(pf["sales_revenue"][year_index])
    vat_sur = float(pf["vat_surcharge_total"][year_index])
    vat_ref = float(pf["vat_refund"][year_index])
    total_profit = revenue - vat_sur - total_cost + vat_ref
    p = total_profit

    # Row 22: loss_compensation.
    # IF p < 0: 0; IF prior_cum > 0: 0; ELSE MIN(p, -prior_cum).
    if p < 0 or carry.prior_cum_profit > 0:
        loss_comp = 0.0
    else:
        loss_comp = min(p, -carry.prior_cum_profit)

    # Row 21: income_tax = IF p < 0: 0; ELSE (p - loss_comp) * rate.
    # The rate comes from the PnL tax-rate schedule (holiday ladder plus
    # any preferential branch), already computed per operating year.
    tax_rate = float(pf["tax_rate_schedule"][year_index])
    income_tax = 0.0 if p < 0 else (p - loss_comp) * tax_rate

    # Row 23: loss = max(0, -p).
    loss_val = -p if p < 0 else 0.0

    # Row 25: tax_echo = income_tax.
    tax_echo = income_tax

    # Row 24: loss_carry_forward — supplied by solver.
    lcf = loss_carry_forward

    # Row 16: cum_profit = p - tax_echo + lcf + prior_cum.
    cum_profit = p - tax_echo + lcf + carry.prior_cum_profit

    # Row 26: net_profit = IF p <= 0: 0; ELSE p - loss_comp - tax_echo.
    net_profit = 0.0 if p <= 0 else p - loss_comp - tax_echo

    # Row 27: surplus_reserve = IF cum <= 0: 0; ELSE net * ratio.
    surplus_reserve = 0.0 if cum_profit <= 0 else net_profit * sr_ratio

    # Row 29: distributable_profit = IF cum <= 0: 0; ELSE net - reserve.
    distributable = 0.0 if cum_profit <= 0 else net_profit - surplus_reserve

    # ==================================================================
    # Phase E: cashflow + finplan operating rows
    # ==================================================================
    eq_tax = income_tax
    tax_outflow = eq_tax

    # Operating outflow (row 11) = rows 12 + 13 + 14 + 15 + 16:
    # operating cost, surcharges, land-rent payment, income tax, VAT.
    op_cost = float(cf["operating_cost"][year_index])
    land_rent = float(params.frame["land_rent_payment"][year_index + 1])
    vat_payable = float(pf["vat_payable"][year_index])
    op_outflow = op_cost + vat_sur + land_rent + tax_outflow + vat_payable

    # Operating inflow (row 6) = rows 7 + 8 + 9 - 10: sales revenue
    # (incl. VAT refund), output VAT, subsidy inflow (zero), minus the
    # subsidy shortfall.
    arrival = float(params.frame["subsidy_arrival_rate"][year_index + 1])
    shortfall = (
        (1.0 - arrival)
        * inputs.subsidy_per_kwh
        * float(pf["guaranteed_sales"][year_index])
    )
    op_inflow = revenue + vat_ref + float(pf["output_vat"][year_index]) - shortfall
    op_net = op_inflow - op_outflow

    int_outflow = int_expense

    # ==================================================================
    # Phase F: finplan investment / financing rows
    # ==================================================================
    dist_pool = distributable * div_ratio
    actual_dist = dist_pool
    profit_dist = actual_dist

    # Row 24: invest_outflow = rows 25 + 26 + 27 + 30 + 31 + 32.
    inv_out = (
        constr_inv + wc + lt_repay + int_outflow + profit_dist + other_out
    )

    # Row 22: short_term_borrowing — deficit bridge.
    # Formula from old finplan _fine_row22:
    #   max(0, -prior_cs - op_net - equity - constr_loan - wc_loan
    #          + inv_out + st_repay)
    deficit_term = (
        -carry.prior_cumulative_surplus - op_net - eq_inj
        - constr_loan - wc_loan + inv_out + st_repay
    )
    st_borrowing = deficit_term if deficit_term > 0 else 0.0

    # Row 18: invest_inflow = rows 19 + 20 + 21 + 22 + 23.
    inv_in = eq_inj + constr_loan + wc_loan + st_borrowing

    # Row 17: invest_finance_net_cf = row 18 - row 24.
    inv_fin_net = inv_in - inv_out

    # Row 33: net_cash_flow = row 5 + row 17 - row 28.
    net_cf = op_net + inv_fin_net - st_repay

    # Row 34: cumulative_surplus = prior + net_cash_flow.
    cum_surplus = carry.prior_cumulative_surplus + net_cf

    return YearSlice(
        short_term_repayment=st_repay,
        short_term_principal=st_principal,
        short_term_interest=st_interest,
        short_term_loan_interest=cost_st_interest,
        interest_expense=int_expense,
        total_operating_cost=total_cost_cost,
        total_cost=total_cost,
        total_profit=total_profit,
        loss_compensation=loss_comp,
        income_tax=income_tax,
        loss=loss_val,
        tax_echo=tax_echo,
        loss_carry_forward=lcf,
        cum_profit=cum_profit,
        net_profit=net_profit,
        surplus_reserve=surplus_reserve,
        distributable_profit=distributable,
        equity_income_tax=eq_tax,
        income_tax_outflow=tax_outflow,
        operating_outflow=op_outflow,
        operating_net_cf=op_net,
        interest_outflow=int_outflow,
        distributable_profit_pool=dist_pool,
        actual_distribution=actual_dist,
        profit_distribution=profit_dist,
        invest_outflow=inv_out,
        short_term_borrowing=st_borrowing,
        invest_inflow=inv_in,
        invest_finance_net_cf=inv_fin_net,
        net_cash_flow=net_cf,
        cumulative_surplus=cum_surplus,
    )


# ===================================================================
# Solve -- 25-year loop
# ===================================================================


def solve(
    params: ParamsCore,
    invest: InvestResult,
    debt_base: DebtBase,
    cost_core: CostCore,
    pnl_core: PnLCore,
) -> MutualSolution:
    """Run the 25-year mutual-block recurrence.

    1. Construction prologue (year 0).
    2. Loop 25 operating years, threading YearCarry and loss-carry
       accumulator state.
    """
    # Construction prologue
    construction = _construction_prologue(invest, debt_base)

    # Accumulators for loss_carry_forward.
    losses: list[float] = []
    loss_comps: list[float] = []
    prior_lcfs: list[float] = []

    # Seed carry from construction year.  The cumulative-profit seed is
    # the workbook's hand-entered pre-operating plug (an input given).
    carry = YearCarry(
        prior_short_term_borrowing=construction.short_term_borrowing,
        prior_cum_profit=params.inputs.initial_cum_profit,
        prior_cumulative_surplus=construction.cumulative_surplus,
    )

    steps: list[YearSlice] = []

    for t in range(25):
        # Compute loss_carry_forward BEFORE step_year (needs prior state).
        lcf = _compute_loss_carry_forward(t, losses, loss_comps, prior_lcfs)

        ys = step_year(
            params, invest, debt_base, cost_core, pnl_core, t, carry,
            loss_carry_forward=lcf,
        )

        steps.append(ys)

        # Record accumulators for next year's loss_carry_forward.
        losses.append(ys.loss)
        loss_comps.append(ys.loss_compensation)
        prior_lcfs.append(lcf)

        # Thread carry to next year.
        carry = YearCarry(
            prior_short_term_borrowing=ys.short_term_borrowing,
            prior_cum_profit=ys.cum_profit,
            prior_cumulative_surplus=ys.cumulative_surplus,
        )

    return MutualSolution(steps=tuple(steps), construction=construction)
