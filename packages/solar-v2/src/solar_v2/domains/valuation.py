"""Valuation domain — 估值结果 (equity valuation) + 指标汇总 (KPI summary).

Dual-axis: income approach uses 25-year operating series (B..Z),
market approach uses 20-year series (B..U). KPI items are all scalars.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from solar_v2.schema import DomainSchema, ItemSchema

if TYPE_CHECKING:
    from solar_v2.domains.balance import BalanceResult
    from solar_v2.domains.cashflow import CashFlowResult
    from solar_v2.domains.cost import CostResult
    from solar_v2.domains.debt import DebtResult
    from solar_v2.domains.finplan import FinPlanResult
    from solar_v2.domains.invest import InvestResult
    from solar_v2.domains.params import ParamsCore
    from solar_v2.domains.pnl import PnLResult


# ---------------------------------------------------------------------------
# IRR / NPV utilities (ported from old valuation.py)
# ---------------------------------------------------------------------------


def _npv_at(rate: float, cashflows: list[float]) -> float:
    """NPV of cash flows at rate r, t=0 aligned."""
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cashflows))


def _irr(
    cashflows: list[float],
    guess: float = 0.1,
    tol: float = 1e-10,
    max_iter: int = 200,
) -> float:
    """Internal rate of return: Newton-Raphson with bisection fallback."""
    if (
        not cashflows
        or all(c <= 0 for c in cashflows)
        or all(c >= 0 for c in cashflows)
    ):
        return 0.0
    r = guess
    for _ in range(max_iter):
        fv = 0.0
        dv = 0.0
        for t, cf in enumerate(cashflows):
            d = (1.0 + r) ** t
            fv += cf / d
            if t > 0:
                dv -= t * cf / (d * (1.0 + r))
        if abs(fv) < tol:
            return r
        if dv == 0.0:
            break
        r_next = r - fv / dv
        if r_next <= -1.0:
            r_next = -0.999
        if abs(r_next - r) < tol:
            return r_next
        r = r_next
    lo, hi = -0.999, 10.0
    flo = _npv_at(lo, cashflows)
    fhi = _npv_at(hi, cashflows)
    if flo * fhi > 0:
        return 0.0
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        fmid = _npv_at(mid, cashflows)
        if abs(fmid) < tol:
            return mid
        if flo * fmid < 0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValuationScalars:
    """All 指标汇总 KPI items — one field per kpi_ key."""

    benchmark_rate: float

    # Row 5
    kpi_capacity: float
    kpi_annual_generation: float

    # Row 6
    kpi_unit_static_investment: float
    kpi_static_investment: float

    # Row 7
    kpi_equity_ratio_pct: float
    kpi_dynamic_investment: float

    # Row 8
    kpi_feed_in_tariff: float

    # Row 9
    kpi_annual_full_hours: float
    kpi_project_irr_pre_tax: float

    # Row 10
    kpi_epc_unit_cost: float
    kpi_equity_irr_after_tax: float

    # Row 11
    kpi_adjusted_equity_irr: float

    # Row 12
    kpi_annual_operating_cost: float

    # Row 13
    kpi_operating_cost_per_kwh: float
    kpi_max_leverage_ratio_pct: float

    # Row 14
    kpi_operating_cost_per_kw: float
    kpi_max_short_term_borrowing: float

    # Row 15
    kpi_loan_years: float

    # Row 21
    kpi_summary_capacity: float

    # Row 22
    kpi_annual_generation_raw: float
    kpi_project_payback_period: float

    # Row 23
    kpi_total_investment: float
    kpi_project_irr_pre_tax_dup: float

    # Row 24
    kpi_construction_interest: float
    kpi_project_npv_pre_tax: float

    # Row 25
    kpi_working_capital: float

    # Row 26
    kpi_project_irr_after_tax: float

    # Row 27
    kpi_tariff_excl_vat: float
    kpi_equity_irr_after_tax_dup: float

    # Row 28
    kpi_tariff_incl_vat: float
    kpi_investor_irr: float

    # Row 30
    kpi_sales_revenue_total: float
    kpi_project_npv_after_tax: float

    # Row 31
    kpi_total_operating_cost_total: float
    kpi_equity_npv: float

    # Row 32
    kpi_vat_surcharge_total: float
    kpi_investor_npv: float

    # Row 33
    kpi_total_profit_total: float
    kpi_epc_unit_cost_dup: float

    # Row 34
    kpi_annual_operating_cost_dup: float
    kpi_investment_profit_rate: float

    # Row 35
    kpi_operating_cost_per_kwh_dup: float
    kpi_equity_net_profit_rate: float

    # Row 36
    kpi_operating_cost_per_kw_dup: float
    kpi_equity_net_profit_rate_dup: float

    # Row 38
    kpi_annual_full_hours_dup: float
    kpi_max_leverage_ratio_pct_dup: float

    # Row 39
    kpi_unit_invest_per_kwh: float
    kpi_max_cumulative_loss: float

    # Row 40
    kpi_unit_static_investment_dup: float
    kpi_max_short_term_borrowing_dup: float

    # Row 41
    kpi_equity_ratio_pct_dup: float
    kpi_long_term_loan_years: float

    # Row 42
    kpi_all_loan_years: float

    # Row 43
    kpi_equity_capital_total: float
    kpi_icr_average: float

    # Row 44
    kpi_transfer_net_profit: float
    kpi_dscr: float

    # Row 45
    kpi_engineering_profit: float
    kpi_roi: float

    # Row 46
    kpi_total_return: float

    # Row 50+52 (SCC)
    kpi_scc_repair: float
    kpi_scc_label: str
    kpi_scc_amort: float
    kpi_scc_unit_label: str

    # Row 51
    kpi_depreciation_total: float
    kpi_income_tax_total: float

    # Row 52
    kpi_scc_amort_dup: float
    kpi_scc_amort_plus_tax: float

    # Row 53
    kpi_total_profit_dup: float

    # Row 54
    kpi_interest_expense_total: float
    kpi_subsidy_per_kwh: float

    # Row 55
    kpi_cash_cost_total: float
    kpi_cash_cost_per_kwh: float

    # Row 56
    kpi_investment_95pct: float
    kpi_coverage_numerator: float

    # Row 57
    kpi_coverage_ratio: float

    # Row 58
    kpi_epc_check: float

    # Row 60
    kpi_total_epc_cost: float

    # Row 64
    kpi_20yr_project_irr_pre_tax: float

    # Row 65
    kpi_20yr_equity_irr_after_tax: float


@dataclass(frozen=True)
class ValuationResult:
    """Valuation domain result — dual-axis frames + KPI scalars."""

    income: pl.DataFrame  # 25 operating years, income-approach items
    market: pl.DataFrame  # 20 operating years, market-approach items
    scalars: ValuationScalars


# ---------------------------------------------------------------------------
# Income approach compute functions (25-year axis)
# ---------------------------------------------------------------------------


def compute_val_net_cashflow(
    cashflow: CashFlowResult,
    years: tuple[int, ...],
) -> pl.Series:
    """Echo 25 operating years of equity net cash flow (现金流量 row 59).

    The cashflow frame holds construction + 25 operating years; the
    income axis is the 25 operating years.
    """
    return cashflow.frame["equity_net_cf"].tail(25).alias("val_net_cashflow")


def compute_val_terminal_value(
    val_net_cashflow: pl.Series,
    benchmark_rate: float,
    years: tuple[int, ...],
) -> pl.Series:
    """Terminal value = net_cf * (1 + benchmark_rate) ^ (25 - year_index)."""
    r = benchmark_rate
    n = len(years)
    vals = [
        val_net_cashflow[i] * (1.0 + r) ** (n - (i + 1))
        for i in range(n)
    ]
    return pl.Series("val_terminal_value", vals, dtype=pl.Float64)


def compute_val_sale_price_inc(
    val_terminal_value: pl.Series,
    benchmark_rate: float,
    years: tuple[int, ...],
) -> pl.Series:
    """Sale price = SUM(trailing terminal values) / (1 + r) ^ exponent."""
    r = benchmark_rate
    n = len(years)
    tvs = val_terminal_value.to_list()
    vals = []
    for i in range(n):
        year = i + 1
        trailing = sum(tvs[i:])
        exp = float(n) if year == 1 else float(n - year)
        vals.append(trailing / (1.0 + r) ** exp)
    return pl.Series("val_sale_price_inc", vals, dtype=pl.Float64)


def compute_val_full_equity_price(
    val_sale_price_inc: pl.Series,
) -> pl.Series:
    """100% equity sale price = echo of sale_price_inc."""
    return val_sale_price_inc.alias("val_full_equity_price")


def compute_val_capital(
    balance: BalanceResult,
) -> pl.Series:
    """Registered capital echoed from balance sheet (row 19), op years only."""
    return balance.frame["registered_capital"].tail(25).alias("val_capital")


def compute_val_undistributed_profit(
    balance: BalanceResult,
) -> pl.Series:
    """Accumulated undistributed profit for the equity-sale price base.

    The workbook reads the balance sheet's accumulated-reserves row
    (surplus reserves), operating years only.
    """
    return balance.frame["accumulated_surplus_reserves"].tail(25).alias(
        "val_undistributed_profit"
    )


def compute_val_equity_plus_profit(
    val_sale_price_inc: pl.Series,
    val_undistributed_profit: pl.Series,
) -> pl.Series:
    """Equity + profit distribution = sale_price_inc + undistributed_profit."""
    return (val_sale_price_inc + val_undistributed_profit).alias(
        "val_equity_plus_profit"
    )


def compute_val_income_tax(
    val_full_equity_price: pl.Series,
    val_capital: pl.Series,
    params: ParamsCore,
) -> pl.Series:
    """Income tax = MAX((full_equity - capital) x equity_sale_tax_rate, 0)."""
    tax_rate = params.equity_sale_tax_rate
    vals = [
        max((val_full_equity_price[i] - val_capital[i]) * tax_rate, 0.0)
        for i in range(len(val_full_equity_price))
    ]
    return pl.Series("val_income_tax", vals, dtype=pl.Float64)


def compute_val_stamp_duty(
    val_equity_plus_profit: pl.Series,
) -> pl.Series:
    """Stamp duty = equity_plus_profit x 0.05%."""
    return (val_equity_plus_profit * 0.0005).alias("val_stamp_duty")


def compute_val_after_tax_return(
    val_full_equity_price: pl.Series,
    val_income_tax: pl.Series,
    val_stamp_duty: pl.Series,
) -> pl.Series:
    """After-tax return = full_equity - income_tax - stamp_duty."""
    return (val_full_equity_price - val_income_tax - val_stamp_duty).alias(
        "val_after_tax_return"
    )


def compute_val_premium_rate(
    val_sale_price_inc: pl.Series,
    val_undistributed_profit: pl.Series,
    val_capital: pl.Series,
) -> pl.Series:
    """Premium rate (income approach) = (sale_price + undist.profit) / capital - 1."""
    vals = [
        (val_sale_price_inc[i] + val_undistributed_profit[i]) / val_capital[i] - 1.0
        for i in range(len(val_sale_price_inc))
    ]
    return pl.Series("val_premium_rate", vals, dtype=pl.Float64)


def compute_val_owners_equity(
    balance: BalanceResult,
) -> pl.Series:
    """Total equity echoed from balance sheet (row 18), op years only."""
    return balance.frame["total_equity"].tail(25).alias("val_owners_equity")


def compute_val_net_profit(
    val_after_tax_return: pl.Series,
    val_capital: pl.Series,
) -> pl.Series:
    """Transfer net profit = after_tax_return - capital."""
    return (val_after_tax_return - val_capital).alias("val_net_profit")


def compute_val_discounted_cf(
    val_net_cashflow: pl.Series,
    benchmark_rate: float,
) -> pl.Series:
    """Discounted net cash flow at benchmark rate (year 1 = undiscounted)."""
    r = benchmark_rate
    vals = [val_net_cashflow[0]]
    for i in range(1, len(val_net_cashflow)):
        vals.append(val_net_cashflow[i] / (1.0 + r) ** i)
    return pl.Series("val_discounted_cf", vals, dtype=pl.Float64)


# ---------------------------------------------------------------------------
# Market approach compute functions (20-year axis)
# ---------------------------------------------------------------------------


def compute_val_premium_rate2(
    val_equity_plus_profit_20: pl.Series,
    val_capital_20: pl.Series,
) -> pl.Series:
    """Premium rate (market approach, 20-year) = equity_plus / capital - 1."""
    vals = [
        val_equity_plus_profit_20[i] / val_capital_20[i] - 1.0
        for i in range(len(val_equity_plus_profit_20))
    ]
    return pl.Series("val_premium_rate2", vals, dtype=pl.Float64)


def compute_val_capex(
    cost: CostResult,
) -> pl.Series:
    """Capital expenditure = fixed_asset_net_value over first 20 op years."""
    return cost.frame["fixed_asset_net_value"].head(20).alias("val_capex")


def compute_val_fcf_in(
    cashflow: CashFlowResult,
    cost: CostResult,
) -> pl.Series:
    """FCF in = (ebit - adjusted_income_tax) + depreciation_echo (20 years).

    Cashflow frame rows 1..20 (op years 1-20, skipping construction);
    cost frame rows 0..19 (already operating-year aligned).
    """
    ebit_less_tax = cashflow.frame["project_ebit"].to_list()[1:21]
    adj_tax = cashflow.frame["project_adjusted_income_tax"].to_list()[1:21]
    dep = cost.frame["depreciation_echo"].to_list()[:20]
    vals = [
        ebit_less_tax[i] - adj_tax[i] + dep[i]
        for i in range(min(len(ebit_less_tax), len(adj_tax), len(dep)))
    ]
    return pl.Series("val_fcf_in", vals, dtype=pl.Float64)


def compute_val_fcf_out(
    val_fcf_in: pl.Series,
) -> pl.Series:
    """FCF out = echo of fcf_in (same formula for all 20 years)."""
    return val_fcf_in.alias("val_fcf_out")


def compute_val_fcf_terminal(
    val_fcf_out: pl.Series,
    benchmark_rate: float,
    years_20: tuple[int, ...],
) -> pl.Series:
    """FCF terminal value = fcf_out * (1 + rate) ^ (20 - year)."""
    r = benchmark_rate
    n = len(years_20)
    vals = [
        val_fcf_out[i] * (1.0 + r) ** (n - (i + 1))
        for i in range(n)
    ]
    return pl.Series("val_fcf_terminal", vals, dtype=pl.Float64)


def compute_val_fcf_sale_price(
    val_fcf_terminal: pl.Series,
    benchmark_rate: float,
    years_20: tuple[int, ...],
) -> pl.Series:
    """FCF sale price = SUM(trailing terminal) / (1 + rate) ^ exponent."""
    r = benchmark_rate
    n = len(years_20)
    tvs = val_fcf_terminal.to_list()
    vals = []
    for i in range(n):
        year = i + 1
        trailing = sum(tvs[i:])
        exp = float(n - year)
        vals.append(trailing / (1.0 + r) ** exp)
    return pl.Series("val_fcf_sale_price", vals, dtype=pl.Float64)


# ---------------------------------------------------------------------------
# KPI scalar compute functions (指标汇总)
# ---------------------------------------------------------------------------



def compute_benchmark_rate(params: ParamsCore) -> float:
    """Buyer benchmark internal rate of return."""
    return params.buyer_benchmark_rate


def compute_kpi_capacity(params: ParamsCore) -> float:
    return params.installed_capacity_mw


def compute_kpi_annual_generation(
    params: ParamsCore,
) -> float:
    return params.installed_capacity_mw * params.annual_full_hours


def compute_kpi_unit_static_investment(
    params: ParamsCore,
) -> float:
    return params.unit_static_investment


def compute_kpi_static_investment(
    params: ParamsCore,
) -> float:
    return params.static_investment


def compute_kpi_equity_ratio_pct(
    params: ParamsCore,
) -> float:
    return params.equity_ratio * 100.0


def compute_kpi_dynamic_investment(
    invest: InvestResult,
) -> float:
    return invest.scalars.aux_dynamic_investment


def compute_kpi_feed_in_tariff(
    params: ParamsCore,
) -> float:
    return params.base_tariff


def compute_kpi_annual_full_hours(
    params: ParamsCore,
) -> float:
    return params.annual_full_hours


def compute_kpi_project_irr_pre_tax(
    cashflow: CashFlowResult,
) -> float:
    return cashflow.scalars.project_irr_pre_tax


def compute_kpi_epc_unit_cost(
    dynam_invest: float,
    ann_gen: float,
) -> float:
    return dynam_invest / ann_gen


def compute_kpi_equity_irr_after_tax(
    cashflow: CashFlowResult,
) -> float:
    return cashflow.scalars.equity_irr * 100.0


def compute_kpi_adjusted_equity_irr(
    cashflow: CashFlowResult,
) -> float:
    return cashflow.scalars.equity_adjusted_irr * 100.0


def compute_kpi_annual_operating_cost(
    cost: CostResult,
) -> float:
    return float(cost.frame["operating_cost"].sum()) / 25.0


def compute_kpi_operating_cost_per_kwh(
    ann_op_cost: float,
    ann_gen: float,
) -> float:
    return ann_op_cost / ann_gen


def compute_kpi_max_leverage_ratio_pct(
    balance: BalanceResult,
) -> float:
    return balance.scalars.max_asset_liability_ratio * 100.0


def compute_kpi_operating_cost_per_kw(
    ann_op_cost: float,
    cap: float,
) -> float:
    return ann_op_cost / cap


def compute_kpi_max_short_term_borrowing(
    finplan: FinPlanResult,
) -> float:
    _max_raw = finplan.frame["short_term_borrowing"].max()
    assert isinstance(_max_raw, (float, int))
    return float(_max_raw)


def compute_kpi_loan_years(
    params: ParamsCore,
) -> float:
    return float(params.loan_years)


def compute_kpi_summary_capacity(
    params: ParamsCore,
) -> float:
    return params.installed_capacity_mw


def compute_kpi_annual_generation_raw(
    cap: float,
    hours: float,
) -> float:
    return cap * hours


def compute_kpi_project_payback_period(
    cashflow: CashFlowResult,
) -> float:
    return cashflow.scalars.project_payback_after_tax


def compute_kpi_total_investment(
    invest: InvestResult,
) -> float:
    return invest.scalars.aux_total_investment


def compute_kpi_construction_interest(
    invest: InvestResult,
) -> float:
    return invest.scalars.construction_interest_total


def compute_kpi_project_npv_pre_tax(
    cashflow: CashFlowResult,
) -> float:
    return cashflow.scalars.project_npv_pre_tax


def compute_kpi_working_capital(
    invest: InvestResult,
) -> float:
    return invest.scalars.working_capital_total


def compute_kpi_project_irr_after_tax(
    cashflow: CashFlowResult,
) -> float:
    return cashflow.scalars.project_irr_after_tax


def compute_kpi_tariff_excl_vat(
    pnl: PnLResult,
) -> float:
    return pnl.frame["on_grid_price_excl_vat"][0]


def compute_kpi_tariff_incl_vat(
    params: ParamsCore,
) -> float:
    return params.base_tariff


def compute_kpi_investor_irr(
    cashflow: CashFlowResult,
) -> float:
    return cashflow.scalars.investor_irr * 100.0


def compute_kpi_sales_revenue_total(
    pnl: PnLResult,
) -> float:
    return float(pnl.frame["sales_revenue"].sum())


def compute_kpi_project_npv_after_tax(
    cashflow: CashFlowResult,
) -> float:
    return cashflow.scalars.project_npv_after_tax


def compute_kpi_total_operating_cost_total(
    cost: CostResult,
) -> float:
    return float(cost.frame["total_operating_cost"].sum())


def compute_kpi_equity_npv(
    cashflow: CashFlowResult,
) -> float:
    return cashflow.scalars.equity_npv


def compute_kpi_vat_surcharge_total(
    pnl: PnLResult,
) -> float:
    return float(pnl.frame["vat_surcharge_total"].sum())


def compute_kpi_investor_npv(
    cashflow: CashFlowResult,
) -> float:
    return cashflow.scalars.investor_npv


def compute_kpi_total_profit_total(
    pnl: PnLResult,
) -> float:
    return float(pnl.frame["total_profit"].sum())


def compute_kpi_investment_profit_rate(
    total_profit: float,
    total_invest: float,
) -> float:
    return total_profit / total_invest / 25.0 * 100.0


def compute_kpi_equity_net_profit_rate(
    scc_amort: float,
    inc_tax_total: float,
    total_invest: float,
) -> float:
    return (scc_amort + inc_tax_total) / 25.0 / total_invest * 100.0


def compute_kpi_unit_invest_per_kwh(
    total_invest: float,
    ann_gen: float,
) -> float:
    return total_invest / ann_gen


def compute_kpi_max_cumulative_loss(
    pnl: PnLResult,
) -> float:
    _min_raw = pnl.frame["cum_profit"].min()
    assert isinstance(_min_raw, (float, int))
    return float(min(0.0, float(_min_raw)))


def compute_kpi_long_term_loan_years(
    params: ParamsCore,
) -> float:
    return float(params.loan_years)


def compute_kpi_all_loan_years(
    params: ParamsCore,
) -> float:
    return float(params.loan_years)


def compute_kpi_equity_capital_total(
    invest: InvestResult,
) -> float:
    return invest.scalars.aux_equity


def compute_kpi_icr_average(
    debt: DebtResult,
) -> float:
    return debt.scalars.icr_average


def compute_kpi_transfer_net_profit(
    val_after_tax_return: pl.Series,
    val_capital: pl.Series,
) -> float:
    return val_after_tax_return[0] - val_capital[0]


def compute_kpi_dscr(
    debt: DebtResult,
) -> float:
    return debt.scalars.dscr_average


def compute_kpi_engineering_profit(
    params: ParamsCore,
) -> float:
    """Engineering profit from EPC contract margin.

    ((epc_contract - epc_cost) * capacity
     - epc_contract * capacity / 1.12 * mgmt_ratio
     - (epc_contract - epc_cost) * capacity / 1.12 * 0.12 * 1.12)
    * (1 - equity_sale_tax_rate)
    """
    epc = params.epc_contract_price
    epc_cost = params.epc_cost_price
    cap = params.installed_capacity_mw
    mgmt = params.mgmt_allocation_ratio
    tax = params.equity_sale_tax_rate
    result = (
        cap
        * (
            (epc - epc_cost)
            - epc / 1.12 * mgmt
            - (epc - epc_cost) / 1.12 * 0.12 * 1.12
        )
        * (1.0 - tax)
    )
    return result


def compute_kpi_roi(
    cashflow: CashFlowResult,
    total_invest: float,
) -> float:
    return float(cashflow.frame["project_ebit"].sum()) / 25.0 / total_invest


def compute_kpi_total_return(
    transfer_profit: float,
    eng_profit: float,
) -> float:
    return transfer_profit + eng_profit


def compute_kpi_scc_repair(
    cost: CostResult,
) -> float:
    return float(cost.frame["salary_cost"].sum())


def compute_kpi_scc_amort(
    cashflow: CashFlowResult,
) -> float:
    # 现金流量 VAT-payable + sales-tax rows summed over all years
    return float(
        float(cashflow.frame["equity_vat_payable"].sum())
        + float(cashflow.frame["equity_sales_tax"].sum())
    )


def compute_kpi_depreciation_total(
    cost: CostResult,
) -> float:
    return float(cost.frame["depreciation_echo"].sum()) + float(cost.frame[
        "land_rent_echo"
    ].sum())


def compute_kpi_income_tax_total(
    pnl: PnLResult,
) -> float:
    return float(pnl.frame["income_tax"].sum())


def compute_kpi_scc_amort_plus_tax(
    scc_amort: float,
    inc_tax_total: float,
) -> float:
    return scc_amort + inc_tax_total


def compute_kpi_interest_expense_total(
    cost: CostResult,
) -> float:
    return float(cost.frame["interest_expense"].sum())


def compute_kpi_subsidy_per_kwh(
    ann_gen: float,
) -> float:
    return 306.9 * ann_gen / 1_000_000.0


def compute_kpi_cash_cost_total(
    total_profit: float,
    scc_amort: float,
    dep_total: float,
    scc_repair: float,
    interest_total: float,
) -> float:
    return total_profit + scc_amort + dep_total + scc_repair + interest_total


def compute_kpi_cash_cost_per_kwh(
    subsidy: float,
) -> float:
    return subsidy * 2.7


def compute_kpi_investment_95pct(
    total_invest: float,
) -> float:
    return total_invest * 0.95


def compute_kpi_coverage_numerator() -> float:
    return 115152.0 / 111000.0


def compute_kpi_coverage_ratio(
    cash_cost_kwh: float,
    cov_num: float,
) -> float:
    return cash_cost_kwh / cov_num


def compute_kpi_epc_check(
    invest_95: float,
) -> float:
    return invest_95 * 0.3


def compute_kpi_total_epc_cost(
    epc_check: float,
    cash_cost_total: float,
) -> float:
    return epc_check + cash_cost_total + 4392.0


def compute_kpi_20yr_project_irr_pre_tax(
    cashflow: CashFlowResult,
) -> float:
    return cashflow.scalars.project_20yr_irr_pre_tax


def compute_kpi_20yr_equity_irr_after_tax(
    cashflow: CashFlowResult,
) -> float:
    return cashflow.scalars.equity_20yr_irr


# ---------------------------------------------------------------------------

# Duplicate-cell KPI wrappers (same value as base field, distinct spreadsheet cell)

def compute_kpi_project_irr_pre_tax_dup(
    cashflow: CashFlowResult,
    ) -> float:
    """Duplicate of kpi_project_irr_pre_tax at row 23 H."""
    return compute_kpi_project_irr_pre_tax(cashflow)


def compute_kpi_equity_irr_after_tax_dup(
    cashflow: CashFlowResult,
    ) -> float:
    """Duplicate of kpi_equity_irr_after_tax at row 27 H."""
    return compute_kpi_equity_irr_after_tax(cashflow)


def compute_kpi_epc_unit_cost_dup(
    dynam_invest: float,
    cap: float,
    ) -> float:
    """Duplicate of kpi_epc_unit_cost at row 16."""
    return compute_kpi_epc_unit_cost(dynam_invest, cap)


def compute_kpi_annual_operating_cost_dup(
    cost: CostResult,
    ) -> float:
    """Duplicate of kpi_annual_operating_cost at row 17."""
    return compute_kpi_annual_operating_cost(cost)


def compute_kpi_operating_cost_per_kwh_dup(
    ann_op_cost: float,
    ann_gen: float,
    ) -> float:
    """Duplicate of kpi_operating_cost_per_kwh at row 35 D."""
    return compute_kpi_operating_cost_per_kwh(ann_op_cost, ann_gen)


def compute_kpi_operating_cost_per_kw_dup(
    ann_op_cost: float,
    cap: float,
    ) -> float:
    """Duplicate of kpi_operating_cost_per_kw at row 36 D."""
    return compute_kpi_operating_cost_per_kw(ann_op_cost, cap)


def compute_kpi_equity_net_profit_rate_dup(
    pnl: PnLResult,
    invest: InvestResult,
    ) -> float:
    """Net-profit-to-equity rate (row 36 H): net profit / equity per year."""
    np_total = float(pnl.frame["net_profit"].sum())
    ec_total = invest.scalars.aux_equity
    return np_total / 25.0 / ec_total * 100.0


def compute_kpi_annual_full_hours_dup(
    params: ParamsCore,
    ) -> float:
    """Duplicate of kpi_annual_full_hours at row 38 D."""
    return compute_kpi_annual_full_hours(params)


def compute_kpi_max_leverage_ratio_pct_dup(
    balance: BalanceResult,
    ) -> float:
    """Duplicate of kpi_max_leverage_ratio_pct at row 18."""
    return compute_kpi_max_leverage_ratio_pct(balance)


def compute_kpi_unit_static_investment_dup(
    params: ParamsCore,
    ) -> float:
    """Duplicate of kpi_unit_static_investment at row 40 D."""
    return compute_kpi_unit_static_investment(params)


def compute_kpi_max_short_term_borrowing_dup(
    finplan: FinPlanResult,
    ) -> float:
    """Duplicate of kpi_max_short_term_borrowing at row 19."""
    return compute_kpi_max_short_term_borrowing(finplan)


def compute_kpi_equity_ratio_pct_dup(
    params: ParamsCore,
    ) -> float:
    """Duplicate of kpi_equity_ratio_pct at row 41 D."""
    return compute_kpi_equity_ratio_pct(params)


def compute_kpi_scc_amort_dup(
    cashflow: CashFlowResult,
    ) -> float:
    """Duplicate of kpi_scc_amort at row 53."""
    return compute_kpi_scc_amort(cashflow)


def compute_kpi_total_profit_dup(
    pnl: PnLResult,
    ) -> float:
    """Duplicate of kpi_total_profit_total at row 33 H."""
    return compute_kpi_total_profit_total(pnl)


# String-constant KPI fields

def compute_kpi_scc_label() -> str:
    """Fixed label for production tax row."""
    return "生产税（增值税、增值税附加税等）金额"


def compute_kpi_scc_unit_label() -> str:
    """Fixed unit label for production tax row."""
    return "万元"

# Main compute_valuation function (stage 13)
# ---------------------------------------------------------------------------


def compute_valuation(
    params: ParamsCore,
    invest: InvestResult,
    debt: DebtResult,
    cost: CostResult,
    pnl: PnLResult,
    cashflow: CashFlowResult,
    finplan: FinPlanResult,
    balance: BalanceResult,
) -> ValuationResult:
    """Compute valuation results (income + market frames) and KPI scalars."""

    years = params.axis.years  # 25 operating calendar years
    years_20 = years[:20]  # 20-year market approach axis
    benchmark_rate = compute_benchmark_rate(params)

    # --- Income approach (25-year) ---
    val_net_cf = compute_val_net_cashflow(cashflow, years)
    val_terminal = compute_val_terminal_value(val_net_cf, benchmark_rate, years)
    val_sale_price = compute_val_sale_price_inc(val_terminal, benchmark_rate, years)
    val_full_equity = compute_val_full_equity_price(val_sale_price)
    val_cap = compute_val_capital(balance)
    val_undist = compute_val_undistributed_profit(balance)
    val_equity_plus = compute_val_equity_plus_profit(val_sale_price, val_undist)
    val_tax = compute_val_income_tax(val_full_equity, val_cap, params)
    val_stamp = compute_val_stamp_duty(val_equity_plus)
    val_after_tax = compute_val_after_tax_return(val_full_equity, val_tax, val_stamp)
    val_prem = compute_val_premium_rate(val_sale_price, val_undist, val_cap)
    val_owners = compute_val_owners_equity(balance)
    val_net_prof = compute_val_net_profit(val_after_tax, val_cap)
    val_disc = compute_val_discounted_cf(val_net_cf, benchmark_rate)

    income = pl.DataFrame({
        "year": list(years),
        "val_net_cashflow": val_net_cf,
        "val_terminal_value": val_terminal,
        "val_sale_price_inc": val_sale_price,
        "val_full_equity_price": val_full_equity,
        "val_income_tax": val_tax,
        "val_stamp_duty": val_stamp,
        "val_after_tax_return": val_after_tax,
        "val_premium_rate": val_prem,
        "val_capital": val_cap,
        "val_undistributed_profit": val_undist,
        "val_equity_plus_profit": val_equity_plus,
        "val_owners_equity": val_owners,
        "val_net_profit": val_net_prof,
        "val_discounted_cf": val_disc,
    })

    # --- Market approach (20-year) ---
    val_cap_20 = pl.Series(
        "val_capital_20", val_cap.to_list()[:20], dtype=pl.Float64
    )
    val_ep_20 = pl.Series(
        "val_equity_plus_profit_20",
        val_equity_plus.to_list()[:20],
        dtype=pl.Float64,
    )
    val_prem2 = compute_val_premium_rate2(val_ep_20, val_cap_20)
    val_cpx = compute_val_capex(cost)
    val_fin = compute_val_fcf_in(cashflow, cost)
    val_fout = compute_val_fcf_out(val_fin)
    val_fterm = compute_val_fcf_terminal(val_fout, benchmark_rate, years_20)
    val_fsale = compute_val_fcf_sale_price(val_fterm, benchmark_rate, years_20)

    market = pl.DataFrame({
        "year": list(years_20),
        "val_premium_rate2": val_prem2,
        "val_capex": val_cpx,
        "val_fcf_in": val_fin,
        "val_fcf_out": val_fout,
        "val_fcf_terminal": val_fterm,
        "val_fcf_sale_price": val_fsale,
    })

    # --- KPI scalars ---
    cap = compute_kpi_capacity(params)
    ann_gen = compute_kpi_annual_generation(params)
    ann_op_cost = compute_kpi_annual_operating_cost(cost)
    total_inv = compute_kpi_total_investment(invest)
    total_profit = compute_kpi_total_profit_total(pnl)
    scc_amort = compute_kpi_scc_amort(cashflow)
    dep_total = compute_kpi_depreciation_total(cost)
    scc_repair = compute_kpi_scc_repair(cost)
    interest_total = compute_kpi_interest_expense_total(cost)
    inc_tax_total = compute_kpi_income_tax_total(pnl)
    transfer_profit = compute_kpi_transfer_net_profit(val_after_tax, val_cap)
    eng_profit = compute_kpi_engineering_profit(params)
    cash_cost_total = compute_kpi_cash_cost_total(
        total_profit, scc_amort, dep_total, scc_repair, interest_total
    )
    subsidy_kwh = compute_kpi_subsidy_per_kwh(ann_gen)
    cash_cost_kwh = compute_kpi_cash_cost_per_kwh(subsidy_kwh)
    invest_95 = compute_kpi_investment_95pct(total_inv)
    cov_num = compute_kpi_coverage_numerator()
    epc_check = compute_kpi_epc_check(invest_95)

    scalars = ValuationScalars(
        benchmark_rate=benchmark_rate,
        kpi_capacity=cap,
        kpi_annual_generation=ann_gen,
        kpi_unit_static_investment=compute_kpi_unit_static_investment(params),
        kpi_static_investment=compute_kpi_static_investment(params),
        kpi_equity_ratio_pct=compute_kpi_equity_ratio_pct(params),
        kpi_dynamic_investment=compute_kpi_dynamic_investment(invest),
        kpi_feed_in_tariff=compute_kpi_feed_in_tariff(params),
        kpi_annual_full_hours=compute_kpi_annual_full_hours(params),
        kpi_project_irr_pre_tax=compute_kpi_project_irr_pre_tax(cashflow),
        kpi_epc_unit_cost=compute_kpi_epc_unit_cost(
            compute_kpi_dynamic_investment(invest), ann_gen
        ),
        kpi_equity_irr_after_tax=compute_kpi_equity_irr_after_tax(cashflow),
        kpi_adjusted_equity_irr=compute_kpi_adjusted_equity_irr(cashflow),
        kpi_annual_operating_cost=ann_op_cost,
        kpi_operating_cost_per_kwh=compute_kpi_operating_cost_per_kwh(
            ann_op_cost, ann_gen
        ),
        kpi_max_leverage_ratio_pct=compute_kpi_max_leverage_ratio_pct(balance),
        kpi_operating_cost_per_kw=compute_kpi_operating_cost_per_kw(ann_op_cost, cap),
        kpi_max_short_term_borrowing=compute_kpi_max_short_term_borrowing(finplan),
        kpi_loan_years=compute_kpi_loan_years(params),
        kpi_summary_capacity=compute_kpi_summary_capacity(params),
        kpi_annual_generation_raw=compute_kpi_annual_generation_raw(
            cap, ann_gen / cap
        ),
        kpi_project_payback_period=compute_kpi_project_payback_period(cashflow),
        kpi_total_investment=total_inv,
        kpi_project_irr_pre_tax_dup=compute_kpi_project_irr_pre_tax(cashflow),
        kpi_construction_interest=compute_kpi_construction_interest(invest),
        kpi_project_npv_pre_tax=compute_kpi_project_npv_pre_tax(cashflow),
        kpi_working_capital=compute_kpi_working_capital(invest),
        kpi_project_irr_after_tax=compute_kpi_project_irr_after_tax(cashflow),
        kpi_tariff_excl_vat=compute_kpi_tariff_excl_vat(pnl),
        kpi_equity_irr_after_tax_dup=compute_kpi_equity_irr_after_tax(cashflow),
        kpi_tariff_incl_vat=compute_kpi_tariff_incl_vat(params),
        kpi_investor_irr=compute_kpi_investor_irr(cashflow),
        kpi_sales_revenue_total=compute_kpi_sales_revenue_total(pnl),
        kpi_project_npv_after_tax=compute_kpi_project_npv_after_tax(cashflow),
        kpi_total_operating_cost_total=compute_kpi_total_operating_cost_total(cost),
        kpi_equity_npv=compute_kpi_equity_npv(cashflow),
        kpi_vat_surcharge_total=compute_kpi_vat_surcharge_total(pnl),
        kpi_investor_npv=compute_kpi_investor_npv(cashflow),
        kpi_total_profit_total=total_profit,
        kpi_epc_unit_cost_dup=compute_kpi_epc_unit_cost(
            compute_kpi_dynamic_investment(invest), ann_gen
        ),
        kpi_annual_operating_cost_dup=compute_kpi_annual_operating_cost_dup(cost),
        kpi_investment_profit_rate=compute_kpi_investment_profit_rate(
            total_profit, total_inv
        ),
        kpi_operating_cost_per_kwh_dup=compute_kpi_operating_cost_per_kwh(
            ann_op_cost, ann_gen
        ),
        kpi_equity_net_profit_rate=compute_kpi_equity_net_profit_rate(
            scc_amort, inc_tax_total, total_inv
        ),
        kpi_operating_cost_per_kw_dup=compute_kpi_operating_cost_per_kw(
            ann_op_cost, cap
        ),
        kpi_equity_net_profit_rate_dup=compute_kpi_equity_net_profit_rate_dup(
            pnl, invest
        ),
        kpi_annual_full_hours_dup=compute_kpi_annual_full_hours(params),
        kpi_max_leverage_ratio_pct_dup=compute_kpi_max_leverage_ratio_pct(balance),
        kpi_unit_invest_per_kwh=compute_kpi_unit_invest_per_kwh(total_inv, ann_gen),
        kpi_max_cumulative_loss=compute_kpi_max_cumulative_loss(pnl),
        kpi_unit_static_investment_dup=compute_kpi_unit_static_investment(params),
        kpi_max_short_term_borrowing_dup=compute_kpi_max_short_term_borrowing(finplan),
        kpi_equity_ratio_pct_dup=compute_kpi_equity_ratio_pct(params),
        kpi_long_term_loan_years=compute_kpi_long_term_loan_years(params),
        kpi_all_loan_years=compute_kpi_all_loan_years(params),
        kpi_equity_capital_total=compute_kpi_equity_capital_total(invest),
        kpi_icr_average=compute_kpi_icr_average(debt),
        kpi_transfer_net_profit=transfer_profit,
        kpi_dscr=compute_kpi_dscr(debt),
        kpi_engineering_profit=eng_profit,
        kpi_roi=compute_kpi_roi(cashflow, total_inv),
        kpi_total_return=compute_kpi_total_return(transfer_profit, eng_profit),
        kpi_scc_repair=scc_repair,
        kpi_scc_label=compute_kpi_scc_label(),
        kpi_scc_amort=scc_amort,
        kpi_scc_unit_label=compute_kpi_scc_unit_label(),
        kpi_depreciation_total=dep_total,
        kpi_income_tax_total=inc_tax_total,
        kpi_scc_amort_dup=compute_kpi_scc_amort_dup(cashflow),
        kpi_scc_amort_plus_tax=compute_kpi_scc_amort_plus_tax(
            scc_amort, inc_tax_total
        ),
        kpi_total_profit_dup=compute_kpi_total_profit_dup(pnl),
        kpi_interest_expense_total=interest_total,
        kpi_subsidy_per_kwh=subsidy_kwh,
        kpi_cash_cost_total=cash_cost_total,
        kpi_cash_cost_per_kwh=cash_cost_kwh,
        kpi_investment_95pct=invest_95,
        kpi_coverage_numerator=cov_num,
        kpi_coverage_ratio=compute_kpi_coverage_ratio(cash_cost_kwh, cov_num),
        kpi_epc_check=epc_check,
        kpi_total_epc_cost=compute_kpi_total_epc_cost(epc_check, cash_cost_total),
        kpi_20yr_project_irr_pre_tax=compute_kpi_20yr_project_irr_pre_tax(cashflow),
        kpi_20yr_equity_irr_after_tax=compute_kpi_20yr_equity_irr_after_tax(cashflow),
    )

    return ValuationResult(income=income, market=market, scalars=scalars)


# ---------------------------------------------------------------------------
# Domain calculation schema
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Domain calculation schema
# ---------------------------------------------------------------------------

SCHEMA = DomainSchema(
    key="valuation",
    sheet="估值结果",
    label="估值结果 + 指标汇总 (Valuation)",
    depends_on=(
        "params",
        "invest",
        "debt",
        "cost",
        "pnl",
        "cashflow",
        "finplan",
        "balance",
    ),
    items=(
        # ── 估值结果 sheet ──
        ItemSchema(
            key="benchmark_rate",
            label="基准内部收益率 [估值结果]",
            unit="%",
            formula="params:buyer_benchmark_rate",
            inputs=("params:buyer_benchmark_rate",),
            rows=(1,),
            kind="scalar",
        ),
        ItemSchema(
            key="val_net_cashflow",
            label="净现金流量 [估值结果]",
            unit="万元",
            formula="cashflow:equity_net_cf echoed over 25 years",
            inputs=("cashflow:equity_net_cf",),
            rows=(5,),
            kind="series",
        ),
        ItemSchema(
            key="val_terminal_value",
            label="终值 [估值结果]",
            unit="万元",
            formula="net_cf × (1 + benchmark_rate) ^ (25 − year)",
            inputs=("val_net_cashflow", "benchmark_rate"),
            rows=(6,),
            kind="series",
        ),
        ItemSchema(
            key="val_sale_price_inc",
            label="该年末卖出价格(收益法) [估值结果]",
            unit="万元",
            formula="SUM(trailing terminal) / (1 + benchmark_rate) ^ exponent",
            inputs=("val_terminal_value", "benchmark_rate"),
            rows=(7,),
            kind="series",
        ),
        ItemSchema(
            key="val_full_equity_price",
            label="100%股权卖出价格 [估值结果]",
            unit="万元",
            formula="val_sale_price_inc echoed",
            inputs=("val_sale_price_inc",),
            rows=(8,),
            kind="series",
        ),
        ItemSchema(
            key="val_income_tax",
            label="所得税 [估值结果]",
            unit="万元",
            formula="MAX((full_equity-captl) × tax_rate, 0)",
            inputs=("val_full_equity_price",
                "val_capital", "params:equity_sale_tax_rate"),
            rows=(9,),
            kind="series",
        ),
        ItemSchema(
            key="val_stamp_duty",
            label="印花税 [估值结果]",
            unit="万元",
            formula="val_equity_plus_profit × 0.05%",
            inputs=("val_equity_plus_profit",),
            rows=(10,),
            kind="series",
        ),
        ItemSchema(
            key="val_after_tax_return",
            label="税后转让净收益 [估值结果]",
            unit="万元",
            formula="val_full_equity_price − val_income_tax − val_stamp_duty",
            inputs=("val_full_equity_price", "val_income_tax", "val_stamp_duty"),
            rows=(11,),
            kind="series",
        ),
        ItemSchema(
            key="val_premium_rate",
            label="溢价率(收益法) [估值结果]",
            unit="%",
            formula="(val_sale_price_inc + val_undistributed_profit) / val_capital − 1",
            inputs=("val_sale_price_inc", "val_undistributed_profit", "val_capital"),
            rows=(12,),
            kind="series",
        ),
        ItemSchema(
            key="val_capital",
            label="实收资本 [估值结果]",
            unit="万元",
            formula="balance:registered_capital echoed over 25 years",
            inputs=("balance:registered_capital",),
            rows=(14,),
            kind="series",
        ),
        ItemSchema(
            key="val_undistributed_profit",
            label="累计未分配利润 [估值结果]",
            unit="万元",
            formula="balance:accumulated_retained_earnings echoed",
            inputs=("balance:accumulated_retained_earnings",),
            rows=(15,),
            kind="series",
        ),
        ItemSchema(
            key="val_equity_plus_profit",
            label="股权+利润分配 [估值结果]",
            unit="万元",
            formula="val_sale_price_inc + val_undistributed_profit",
            inputs=("val_sale_price_inc", "val_undistributed_profit"),
            rows=(16,),
            kind="series",
        ),
        ItemSchema(
            key="val_premium_rate2",
            label="溢价率(市场法) [估值结果]",
            unit="%",
            formula="val_equity_plus_profit / val_capital − 1",
            inputs=("val_equity_plus_profit", "val_capital"),
            rows=(17,),
            kind="series",
        ),
        ItemSchema(
            key="val_capex",
            label="资本性支出 [估值结果]",
            unit="万元",
            formula="cost:fixed_asset_net_value over 20 years",
            inputs=("cost:fixed_asset_net_value",),
            rows=(20,),
            kind="series",
        ),
        ItemSchema(
            key="val_fcf_in",
            label="自由现金流入 [估值结果]",
            unit="万元",
            formula="(project_ebit − adj_tax) + depreciation_echo (20yr)",
            inputs=("cashflow:project_ebit",
                "cashflow:adjusted_income_tax", "cost:depreciation_echo"),
            rows=(21,),
            kind="series",
        ),
        ItemSchema(
            key="val_fcf_out",
            label="自由现金流出 [估值结果]",
            unit="万元",
            formula="Echo of val_fcf_in",
            inputs=("val_fcf_in",),
            rows=(22,),
            kind="series",
        ),
        ItemSchema(
            key="val_fcf_terminal",
            label="FCF终值 [估值结果]",
            unit="万元",
            formula="val_fcf_out × (1 + benchmark_rate) ^ (20 − year)",
            inputs=("val_fcf_out", "benchmark_rate"),
            rows=(23,),
            kind="series",
        ),
        ItemSchema(
            key="val_fcf_sale_price",
            label="FCF卖出价格(市场法) [估值结果]",
            unit="万元",
            formula="SUM(trailing val_fcf_terminal) / (1 + benchmark_rate) ^ exponent",
            inputs=("val_fcf_terminal", "benchmark_rate"),
            rows=(24,),
            kind="series",
        ),
        ItemSchema(
            key="val_owners_equity",
            label="所有者权益 [估值结果]",
            unit="万元",
            formula="balance:total_equity echoed over 25 years",
            inputs=("balance:total_equity",),
            rows=(26,),
            kind="series",
        ),
        ItemSchema(
            key="val_net_profit",
            label="转让净利润 [估值结果]",
            unit="万元",
            formula="val_after_tax_return − val_capital over 25 years",
            inputs=("val_after_tax_return", "val_capital"),
            rows=(27,),
            kind="series",
        ),
        ItemSchema(
            key="val_discounted_cf",
            label="折现净现金流 [估值结果]",
            unit="万元",
            formula="val_net_cashflow discounted at benchmark_rate per year",
            inputs=("val_net_cashflow", "benchmark_rate"),
            rows=(28,),
            kind="series",
        ),

        # ── 指标汇总 sheet ──
        ItemSchema(
            key="kpi_annual_generation",
            label="年发电量(总) [指标汇总]",
            unit="万kWh",
            formula="params:capacity × annual_full_hours",
            inputs=("kpi_annual_generation",),
            rows=(3,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_capacity",
            label="装机容量 [指标汇总]",
            unit="万kW",
            formula="params:installed_capacity_mw",
            inputs=("kpi_capacity",),
            rows=(5,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_static_investment",
            label="静态投资 [指标汇总]",
            unit="万元",
            formula="params:static_investment",
            inputs=("kpi_static_investment",),
            rows=(6,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_unit_static_investment",
            label="单位千瓦投资(静态) [指标汇总]",
            unit="元/kW",
            formula="params:unit_static_investment",
            inputs=("kpi_unit_static_investment",),
            rows=(6,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_dynamic_investment",
            label="动态投资 [指标汇总]",
            unit="万元",
            formula="invest:aux_dynamic_investment",
            inputs=("kpi_dynamic_investment",),
            rows=(7,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_equity_ratio_pct",
            label="资本金比例 [指标汇总]",
            unit="%",
            formula="params:equity_ratio × 100",
            inputs=("kpi_equity_ratio_pct",),
            rows=(7,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_feed_in_tariff",
            label="上网电价(含税) [指标汇总]",
            unit="元/kWh",
            formula="params:base_tariff",
            inputs=("kpi_feed_in_tariff",),
            rows=(8,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_annual_full_hours",
            label="年发电小时数 [指标汇总]",
            unit="h",
            formula="params:annual_full_hours",
            inputs=("kpi_annual_full_hours",),
            rows=(9,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_project_irr_pre_tax",
            label="项目投资IRR(税前) [指标汇总]",
            unit="%",
            formula="cashflow:project_irr_pre_tax",
            inputs=("kpi_project_irr_pre_tax",),
            rows=(9,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_epc_unit_cost",
            label="EPC造价 [指标汇总]",
            unit="元/W",
            formula="dynamic_investment / capacity",
            inputs=("kpi_epc_unit_cost",),
            rows=(10,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_equity_irr_after_tax",
            label="资本金IRR(税后) [指标汇总]",
            unit="%",
            formula="cashflow:equity_irr × 100",
            inputs=("kpi_equity_irr_after_tax",),
            rows=(10,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_adjusted_equity_irr",
            label="调整后资本金IRR [指标汇总]",
            unit="%",
            formula="cashflow:equity_adjusted_irr × 100",
            inputs=("kpi_adjusted_equity_irr",),
            rows=(11,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_annual_operating_cost",
            label="年经营成本 [指标汇总]",
            unit="万元/年",
            formula="cost:operating_cost total / 25",
            inputs=("kpi_annual_operating_cost",),
            rows=(12,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_operating_cost_per_kwh",
            label="度电经营成本 [指标汇总]",
            unit="元/kWh",
            formula="annual_operating_cost / annual_generation",
            inputs=("kpi_operating_cost_per_kwh",),
            rows=(13,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_operating_cost_per_kw",
            label="单位千瓦经营成本 [指标汇总]",
            unit="元/kW",
            formula="annual_operating_cost / capacity",
            inputs=("kpi_operating_cost_per_kw",),
            rows=(14,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_loan_years",
            label="还款年限 [指标汇总]",
            unit="年",
            formula="params:loan_years",
            inputs=("kpi_loan_years",),
            rows=(15,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_epc_unit_cost_dup",
            label="EPC造价 [指标汇总]",
            unit="元/W",
            formula="Same as epc_unit_cost (duplicate cell, row 16)",
            inputs=("kpi_epc_unit_cost_dup",),
            rows=(16,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_annual_operating_cost_dup",
            label="年经营成本 [指标汇总]",
            unit="万元/年",
            formula="Same as annual_operating_cost (duplicate cell, row 17)",
            inputs=("kpi_annual_operating_cost_dup",),
            rows=(17,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_max_leverage_ratio_pct_dup",
            label="最大资产负债率 [指标汇总]",
            unit="%",
            formula="Same as max_leverage_ratio_pct (duplicate cell, row 18)",
            inputs=("kpi_max_leverage_ratio_pct_dup",),
            rows=(18,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_max_short_term_borrowing_dup",
            label="最大短期借款 [指标汇总]",
            unit="万元",
            formula="Same as max_short_term_borrowing (duplicate cell, row 19)",
            inputs=("kpi_max_short_term_borrowing_dup",),
            rows=(19,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_summary_capacity",
            label="装机容量 [指标汇总]",
            unit="万kW",
            formula="params:installed_capacity_mw",
            inputs=("kpi_summary_capacity",),
            rows=(21,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_annual_generation_raw",
            label="年发电量 [指标汇总]",
            unit="万kWh",
            formula="annual_full_hours × capacity",
            inputs=("kpi_annual_generation_raw",),
            rows=(22,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_project_payback_period",
            label="项目投资回收期 [指标汇总]",
            unit="年",
            formula="cashflow:project_payback_after_tax",
            inputs=("kpi_project_payback_period",),
            rows=(22,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_project_irr_pre_tax_dup",
            label="项目投资IRR(税前) [指标汇总]",
            unit="%",
            formula="Same as project_irr_pre_tax (duplicate cell, row 23 H)",
            inputs=("kpi_project_irr_pre_tax_dup",),
            rows=(23,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_total_investment",
            label="总投资 [指标汇总]",
            unit="万元",
            formula="invest:aux_total_investment",
            inputs=("kpi_total_investment",),
            rows=(23,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_construction_interest",
            label="建设期利息 [指标汇总]",
            unit="万元",
            formula="invest:construction_interest_total",
            inputs=("kpi_construction_interest",),
            rows=(24,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_project_npv_pre_tax",
            label="项目投资NPV(税前) [指标汇总]",
            unit="万元",
            formula="cashflow:project_npv_pre_tax",
            inputs=("kpi_project_npv_pre_tax",),
            rows=(24,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_working_capital",
            label="流动资金 [指标汇总]",
            unit="万元",
            formula="invest:working_capital_total",
            inputs=("kpi_working_capital",),
            rows=(25,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_project_irr_after_tax",
            label="项目投资IRR(税后) [指标汇总]",
            unit="%",
            formula="cashflow:project_irr_after_tax",
            inputs=("kpi_project_irr_after_tax",),
            rows=(26,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_equity_irr_after_tax_dup",
            label="资本金IRR [指标汇总]",
            unit="%",
            formula="Same as equity_irr_after_tax (duplicate cell, row 27 H)",
            inputs=("kpi_equity_irr_after_tax_dup",),
            rows=(27,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_tariff_excl_vat",
            label="不含税电价 [指标汇总]",
            unit="元/kWh",
            formula="pnl:on_grid_price_excl_vat[0]",
            inputs=("kpi_tariff_excl_vat",),
            rows=(27,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_investor_irr",
            label="投资方IRR [指标汇总]",
            unit="%",
            formula="cashflow:investor_irr × 100",
            inputs=("kpi_investor_irr",),
            rows=(28,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_tariff_incl_vat",
            label="含税电价 [指标汇总]",
            unit="元/kWh",
            formula="params:base_tariff",
            inputs=("kpi_tariff_incl_vat",),
            rows=(28,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_project_npv_after_tax",
            label="项目NPV(税后) [指标汇总]",
            unit="万元",
            formula="cashflow:project_npv_after_tax",
            inputs=("kpi_project_npv_after_tax",),
            rows=(30,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_sales_revenue_total",
            label="销售收入总额 [指标汇总]",
            unit="万元",
            formula="pnl:sales_revenue total",
            inputs=("kpi_sales_revenue_total",),
            rows=(30,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_equity_npv",
            label="资本金NPV [指标汇总]",
            unit="万元",
            formula="cashflow:equity_npv",
            inputs=("kpi_equity_npv",),
            rows=(31,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_total_operating_cost_total",
            label="总成本费用总额 [指标汇总]",
            unit="万元",
            formula="cost:total_operating_cost total",
            inputs=("kpi_total_operating_cost_total",),
            rows=(31,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_investor_npv",
            label="投资方NPV [指标汇总]",
            unit="万元",
            formula="cashflow:investor_npv",
            inputs=("kpi_investor_npv",),
            rows=(32,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_vat_surcharge_total",
            label="销售税金附加总额 [指标汇总]",
            unit="万元",
            formula="pnl:vat_surcharge_total total",
            inputs=("kpi_vat_surcharge_total",),
            rows=(32,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_total_profit_dup",
            label="发电利润总额 [指标汇总]",
            unit="万元",
            formula="Same as total_profit_total (duplicate cell, row 33 H)",
            inputs=("kpi_total_profit_dup",),
            rows=(33,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_total_profit_total",
            label="发电利润总额 [指标汇总]",
            unit="万元",
            formula="pnl:total_profit total",
            inputs=("kpi_total_profit_total",),
            rows=(33,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_investment_profit_rate",
            label="投资利润率 [指标汇总]",
            unit="%",
            formula="total_profit / total_invest / 25 × 100",
            inputs=("kpi_investment_profit_rate",),
            rows=(34,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_equity_net_profit_rate",
            label="资本金净利润率 [指标汇总]",
            unit="%",
            formula="net_profit_total / 25 / equity_capital × 100",
            inputs=("kpi_equity_net_profit_rate",),
            rows=(35,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_operating_cost_per_kwh_dup",
            label="度电经营成本 [指标汇总]",
            unit="元/kWh",
            formula="Same as operating_cost_per_kwh (duplicate cell, row 35 D)",
            inputs=("kpi_operating_cost_per_kwh_dup",),
            rows=(35,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_equity_net_profit_rate_dup",
            label="单位千瓦经营成本 [指标汇总]",
            unit="%",
            formula="Same as equity_net_profit_rate (duplicate cell, row 36 H)",
            inputs=("kpi_equity_net_profit_rate_dup",),
            rows=(36,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_operating_cost_per_kw_dup",
            label="度电总成本 [指标汇总]",
            unit="元/kW",
            formula="Same as operating_cost_per_kw (duplicate cell, row 36 D)",
            inputs=("kpi_operating_cost_per_kw_dup",),
            rows=(36,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_annual_full_hours_dup",
            label="年发电小时数 [指标汇总]",
            unit="h",
            formula="Same as annual_full_hours (duplicate cell, row 38 D)",
            inputs=("kpi_annual_full_hours_dup",),
            rows=(38,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_max_leverage_ratio_pct",
            label="最大资产负债率 [指标汇总]",
            unit="%",
            formula="balance:max_asset_liability_ratio × 100",
            inputs=("kpi_max_leverage_ratio_pct",),
            rows=(38,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_max_cumulative_loss",
            label="最大累计亏损 [指标汇总]",
            unit="万元",
            formula="MIN(0, pnl:cum_profit min)",
            inputs=("kpi_max_cumulative_loss",),
            rows=(39,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_unit_invest_per_kwh",
            label="度电投资 [指标汇总]",
            unit="元/kWh",
            formula="total_investment / annual_generation",
            inputs=("kpi_unit_invest_per_kwh",),
            rows=(39,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_max_short_term_borrowing",
            label="最大短期借款 [指标汇总]",
            unit="万元",
            formula="MAX(finplan:short_term_borrowing)",
            inputs=("kpi_max_short_term_borrowing",),
            rows=(40,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_unit_static_investment_dup",
            label="单位千瓦投资(静态) [指标汇总]",
            unit="元/kW",
            formula="Same as unit_static_investment (duplicate cell, row 40 D)",
            inputs=("kpi_unit_static_investment_dup",),
            rows=(40,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_equity_ratio_pct_dup",
            label="资本金比例 [指标汇总]",
            unit="%",
            formula="Same as equity_ratio_pct (duplicate cell, row 41 D)",
            inputs=("kpi_equity_ratio_pct_dup",),
            rows=(41,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_long_term_loan_years",
            label="长期借款年限 [指标汇总]",
            unit="年",
            formula="params:loan_years",
            inputs=("kpi_long_term_loan_years",),
            rows=(41,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_all_loan_years",
            label="还贷年限 [指标汇总]",
            unit="年",
            formula="params:loan_years",
            inputs=("kpi_all_loan_years",),
            rows=(42,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_equity_capital_total",
            label="资本金出资额 [指标汇总]",
            unit="万元",
            formula="invest:aux_equity",
            inputs=("kpi_equity_capital_total",),
            rows=(43,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_icr_average",
            label="利息备付率(ICR) [指标汇总]",
            unit="",
            formula="debt:icr_average",
            inputs=("kpi_icr_average",),
            rows=(43,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_dscr",
            label="偿债备付率(DSCR) [指标汇总]",
            unit="",
            formula="debt:dscr_average",
            inputs=("kpi_dscr",),
            rows=(44,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_transfer_net_profit",
            label="电站转让净利润 [指标汇总]",
            unit="万元",
            formula="val_after_tax_return[0] − val_capital[0]",
            inputs=("kpi_transfer_net_profit",),
            rows=(44,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_engineering_profit",
            label="工程收益 [指标汇总]",
            unit="万元",
            formula="EPC contract margin from params",
            inputs=("kpi_engineering_profit",),
            rows=(45,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_roi",
            label="ROI [指标汇总]",
            unit="%",
            formula="Σ(cashflow:project_ebit) / 25 / total_investment",
            inputs=("kpi_roi",),
            rows=(45,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_total_return",
            label="投资回报 [指标汇总]",
            unit="万元",
            formula="transfer_net_profit + engineering_profit",
            inputs=("kpi_total_return",),
            rows=(46,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_scc_label",
            label="生产税说明 [指标汇总]",
            unit="",
            formula="String constant: 生产税（增值税、增值税附加税等）金额",
            inputs=("kpi_scc_label",),
            rows=(50,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_scc_repair",
            label="维修费 [指标汇总]",
            unit="万元",
            formula="cost:salary_cost total",
            inputs=("kpi_scc_repair",),
            rows=(50,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_scc_unit_label",
            label="单位 [指标汇总]",
            unit="",
            formula="String constant: 万元",
            inputs=("kpi_scc_unit_label",),
            rows=(50,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_depreciation_total",
            label="折旧总额 [指标汇总]",
            unit="万元",
            formula="cost:depreciation_echo total + cost:land_rent_echo total",
            inputs=("kpi_depreciation_total",),
            rows=(51,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_income_tax_total",
            label="所得税总额 [指标汇总]",
            unit="万元",
            formula="pnl:income_tax total",
            inputs=("kpi_income_tax_total",),
            rows=(51,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_scc_amort",
            label="其他摊销 [指标汇总]",
            unit="万元",
            formula="Σ(cashflow VAT-payable + sales-tax rows)",
            inputs=("kpi_scc_amort",),
            rows=(52,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_scc_amort_plus_tax",
            label="其他摊销+税 [指标汇总]",
            unit="万元",
            formula="scc_amort + income_tax_total",
            inputs=("kpi_scc_amort_plus_tax",),
            rows=(52,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_scc_amort_dup",
            label="其他摊销(重复) [指标汇总]",
            unit="万元",
            formula="Same as scc_amort (duplicate cell, row 53)",
            inputs=("kpi_scc_amort_dup",),
            rows=(53,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_interest_expense_total",
            label="利息总额 [指标汇总]",
            unit="万元",
            formula="cost:interest_expense total",
            inputs=("kpi_interest_expense_total",),
            rows=(54,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_subsidy_per_kwh",
            label="度电补贴 [指标汇总]",
            unit="元/kWh",
            formula="306.9 × annual_generation / 1e6",
            inputs=("kpi_subsidy_per_kwh",),
            rows=(54,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_cash_cost_per_kwh",
            label="度电成本 [指标汇总]",
            unit="元/kWh",
            formula="subsidy_per_kwh × 2.7",
            inputs=("kpi_cash_cost_per_kwh",),
            rows=(55,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_cash_cost_total",
            label="现金成本合计 [指标汇总]",
            unit="万元",
            formula="profit + amort + depr + repair + interest",
            inputs=("kpi_cash_cost_total",),
            rows=(55,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_coverage_numerator",
            label="覆盖分子 [指标汇总]",
            unit="",
            formula="115152 / 111000",
            inputs=("kpi_coverage_numerator",),
            rows=(56,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_investment_95pct",
            label="投资95% [指标汇总]",
            unit="万元",
            formula="total_investment × 0.95",
            inputs=("kpi_investment_95pct",),
            rows=(56,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_coverage_ratio",
            label="覆盖比率 [指标汇总]",
            unit="",
            formula="cash_cost_per_kwh / coverage_numerator",
            inputs=("kpi_coverage_ratio",),
            rows=(57,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_epc_check",
            label="EPC校验 [指标汇总]",
            unit="万元",
            formula="investment_95pct × 0.3",
            inputs=("kpi_epc_check",),
            rows=(58,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_total_epc_cost",
            label="EPC总成本 [指标汇总]",
            unit="万元",
            formula="epc_check + cash_cost_total + 4392",
            inputs=("kpi_total_epc_cost",),
            rows=(60,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_20yr_project_irr_pre_tax",
            label="项目投资IRR(税前,20年) [指标汇总]",
            unit="%",
            formula="cashflow:project_20yr_irr_pre_tax",
            inputs=("kpi_20yr_project_irr_pre_tax",),
            rows=(64,),
            kind="scalar",
        ),
        ItemSchema(
            key="kpi_20yr_equity_irr_after_tax",
            label="资本金IRR(税后,20年) [指标汇总]",
            unit="%",
            formula="cashflow:equity_20yr_irr",
            inputs=("kpi_20yr_equity_irr_after_tax",),
            rows=(65,),
            kind="scalar",
        ),
    ),
)
