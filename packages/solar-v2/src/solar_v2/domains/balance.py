"""BalanceSheet — 资产负债.

Asset side: current_assets + construction_in_progress + fixed_assets_net
    + intangible_assets_net + accounts_receivable.
Liability side: current_liabilities + long_term_loan_balance
    + short_term_loan_balance.
Equity side: registered_capital + accumulated_surplus_reserves
    + accumulated_retained_earnings.
Asset-liability ratio = total_liabilities / total_assets.

Reads from invest, debt, cost, pnl, finplan, cashflow — all computed
before this domain per engine dataflow stage 10.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from solar_v2.schema import DomainSchema, ItemSchema

if TYPE_CHECKING:
    from solar_v2.domains.cashflow import CashFlowResult
    from solar_v2.domains.cost import CostResult
    from solar_v2.domains.debt import DebtResult
    from solar_v2.domains.finplan import FinPlanResult
    from solar_v2.domains.invest import InvestResult
    from solar_v2.domains.params import ParamsCore
    from solar_v2.domains.pnl import PnLResult


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BalanceScalars:
    """Scalar (non-year-series) balance-sheet items."""

    max_asset_liability_ratio: float


@dataclass(frozen=True)
class BalanceResult:
    """Balance sheet: construction year + 25 operating years.

    Frame columns: year (Int64) then item keys in schema order.
    No aggregate/summary column.
    """

    years: tuple[int, ...]  # construction year + 25 operating years
    frame: pl.DataFrame
    scalars: BalanceScalars


# ---------------------------------------------------------------------------
# Item computers — one compute_<key> per non-coupled schema item
# ---------------------------------------------------------------------------


def compute_year_labels(
    params: ParamsCore,
) -> pl.Series:
    """Year label: 1 at construction year, 0 for operating years.

    Echo of cost year label; kept for schema compatibility only.
    """
    all_years = params.axis.all_years
    const_year = params.axis.construction_year
    return pl.Series(
        "year_labels",
        [1.0 if y == const_year else 0.0 for y in all_years],
    )


def _invest_at(invest: InvestResult, column: str, period: str) -> float:
    """One invest frame value at a named construction period."""
    periods = invest.frame["period"].to_list()
    if period not in periods:
        return 0.0
    return float(invest.frame[column].to_list()[periods.index(period)])


def compute_current_assets(
    params: ParamsCore,
    invest: InvestResult,
) -> pl.Series:
    """Current year working capital: constant per year.

    Value is the invest working-capital total, constant over the
    operating years.  The construction-year cell is blank in the workbook.
    """
    wc = invest.scalars.working_capital_total
    return pl.Series(
        "current_assets",
        [
            0.0 if y == params.axis.construction_year else wc
            for y in params.axis.all_years
        ],
    )


def compute_accumulated_surplus_cash(
    params: ParamsCore,
    finplan: FinPlanResult,
) -> pl.Series:
    """Accumulated surplus cash: echo finplan cumulative_surplus per year.

    Echo-through-origin: reads finplan directly.
    """
    return _align_from_finplan(
        params, finplan.frame, "cumulative_surplus"
    )


def compute_accounts_receivable(
    params: ParamsCore,
    finplan: FinPlanResult,
) -> pl.Series:
    """Accounts receivable: running cumulative sum of finplan subsidy_shortfall."""
    return _cumulative_from_finplan(
        params, finplan.frame, "subsidy_shortfall"
    )


def compute_intangible_assets_net(
    params: ParamsCore,
    cost: CostResult,
) -> pl.Series:
    """Intangible and other assets net = deferred VAT net + land-rent net.

    The balance reads the cost sheet's shifted land-rent section one
    operating year ahead (its land-rent column spans 26 cells), while
    the deferred-VAT section aligns same-year.  The final operating year
    uses the cost domain's final-tail scalars.
    """
    all_years = params.axis.all_years
    const_year = params.axis.construction_year

    deferred = cost.frame["deferred_vat_net"].to_list()
    land_net = cost.frame["land_rent_net"].to_list()
    n_op = len(deferred)

    values: list[float] = []
    for y in all_years:
        if y == const_year:
            values.append(0.0)
            continue
        i = y - const_year - 1  # 0-based operating year
        lr = land_net[i + 1] if i + 1 < n_op else cost.scalars.land_rent_net_final
        dnet = deferred[i] if i < n_op else 0.0
        values.append(dnet + lr)

    return pl.Series("intangible_assets_net", values)


def compute_current_liabilities(
    params: ParamsCore,
    invest: InvestResult,
) -> pl.Series:
    """Current liabilities: constant per year.

    Value is the invest working-capital-loan total, constant over the
    operating years.  The construction-year cell is blank in the workbook.
    """
    wc_loan = invest.scalars.working_capital_loan_total
    return pl.Series(
        "current_liabilities",
        [
            0.0 if y == params.axis.construction_year else wc_loan
            for y in params.axis.all_years
        ],
    )


def compute_construction_in_progress(
    params: ParamsCore,
    invest: InvestResult,
) -> pl.Series:
    """Construction in progress: construction year only, else 0.

    Construction year value = invest total investment at the first
    operating period (the workbook's mapping).  Operating years = 0.
    """
    all_years = params.axis.all_years
    const_year = params.axis.construction_year
    total_inv = _invest_at(invest, "total_investment", "oper1")
    return pl.Series(
        "construction_in_progress",
        [total_inv if y == const_year else 0.0 for y in all_years],
    )


def compute_fixed_assets_net(
    params: ParamsCore,
    cost: CostResult,
) -> pl.Series:
    """Fixed assets net = cost fixed_asset_net_value.

    First 20 operating years have fresh values from cost;
    years 21-25 freeze at year 20 value.
    Construction year = 0.
    """
    const_year = params.axis.construction_year
    all_years = params.axis.all_years
    cost_frame = cost.frame

    cost_lookup = dict(
        zip(
            cost_frame["year"].to_list(),
            cost_frame["fixed_asset_net_value"].to_list(),
        strict=False,
        )
    )

    values: list[float] = []
    for y in all_years:
        if y == const_year:
            values.append(0.0)
        else:
            op_idx = y - const_year
            if op_idx <= 20:
                v = cost_lookup.get(y, 0.0)
                values.append(v)
            else:
                freeze_year = const_year + 20
                v = cost_lookup.get(freeze_year, 0.0)
                values.append(v)

    return pl.Series("fixed_assets_net", values)


def compute_long_term_loan_balance(
    params: ParamsCore,
    debt: DebtResult,
) -> pl.Series:
    """Long-term loan balance (end-of-year alignment).

    Debt long_term_loan_balance is beginning-of-year balance per the
    debt module.  Balance sheet shows end-of-year balance:
    - Construction year: debt construction-year value (= end-of-construction
      balance, aligned with old 还贷 D column).
    - Operating year t (1..24): debt year-(t+1) value (= end-of-year-t).
    - Operating year 25: 0 (no year beyond).

    Year-alignment decision (2026-07-26): the old workbook reads
    资产负债 C15 = 还贷 D6 (construction), D15 = 还贷 F6 (op yr 2), ...
    The new debt frame has year=construction_year for the 建设 column
    and year=op_year_1 for the first operating column.  So:
    balance[construction_year] = debt[construction_year]
    balance[op_year_t] = debt[op_year_{t+1}] for t < 25, else 0.
    """
    all_years = params.axis.all_years
    const_year = params.axis.construction_year
    debt_frame = debt.frame

    debt_lookup = dict(
        zip(
            debt_frame["year"].to_list(),
            debt_frame["long_term_loan_balance"].to_list(),
        strict=False,
        )
    )

    values: list[float] = []
    for y in all_years:
        if y == const_year:
            # Construction year: read debt construction-year value directly
            values.append(debt_lookup.get(y, 0.0))
        else:
            # Operating year: read next year's beginning balance
            next_year = y + 1
            if next_year in debt_lookup:
                values.append(debt_lookup[next_year])
            else:
                values.append(0.0)

    return pl.Series("long_term_loan_balance", values)


def compute_short_term_loan_balance(
    params: ParamsCore,
    finplan: FinPlanResult,
) -> pl.Series:
    """Short-term loan balance = finplan short_term_borrowing per year.

    Echo-through-origin: reads finplan directly.
    """
    return _align_from_finplan(
        params, finplan.frame, "short_term_borrowing"
    )


def compute_registered_capital(
    params: ParamsCore,
    invest: InvestResult,
    cashflow: CashFlowResult,
) -> pl.Series:
    """Registered capital: cumulative equity capital.

    Construction year = invest equity for construction.
    First operating year = construction + invest equity for working capital.
    Subsequent years = previous + cashflow equity capital invest for that year.
    """
    const_year = params.axis.construction_year
    all_years = params.axis.all_years
    op_years = params.axis.years

    eq_construction = _invest_at(invest, "equity_for_construction", "oper1")
    eq_wc = _invest_at(invest, "equity_for_working_capital", "oper2")

    cf_frame = cashflow.frame
    cf_lookup = dict(
        zip(
            cf_frame["year"].to_list(),
            cf_frame["equity_capital_invest"].to_list(),
        strict=False,
        )
    )

    values: list[float] = []
    running = 0.0

    for y in all_years:
        if y == const_year:
            running = eq_construction
        elif y == op_years[0]:
            running = eq_construction + eq_wc
        else:
            running += cf_lookup.get(y, 0.0)
        values.append(running)

    return pl.Series("registered_capital", values)


def compute_accumulated_surplus_reserves(
    params: ParamsCore,
    pnl: PnLResult,
) -> pl.Series:
    """Accumulated surplus reserves = cumulative sum of pnl items.

    Sum = pnl surplus_reserve + the second reserve fund (a workbook row
    whose year cells are literal zero; only its zero total is a formula
    cell, carried as the pnl scalar ``row28_total``).
    """
    all_years = params.axis.all_years
    const_year = params.axis.construction_year

    pnl_frame = pnl.frame
    pnl_lookup = dict(
        zip(
            pnl_frame["year"].to_list(),
            pnl_frame["surplus_reserve"].to_list(),
            strict=False,
        ),
    )
    second_reserve = pnl.scalars.row28_total

    running = 0.0
    values: list[float] = []
    for y in all_years:
        if y == const_year:
            values.append(0.0)
        else:
            running += pnl_lookup.get(y, 0.0) + second_reserve
            values.append(running)

    return pl.Series("accumulated_surplus_reserves", values)


def compute_accumulated_retained_earnings(
    params: ParamsCore,
    pnl: PnLResult,
) -> pl.Series:
    """Accumulated retained earnings = cumulative sum of pnl undistributed_profit.

    Operating years only; construction year = 0.
    """
    all_years = params.axis.all_years
    const_year = params.axis.construction_year

    pnl_frame = pnl.frame
    pnl_lookup = dict(
        zip(
            pnl_frame["year"].to_list(),
            pnl_frame["undistributed_profit"].to_list(),
        strict=False,
        )
    )

    running = 0.0
    values: list[float] = []
    for y in all_years:
        if y == const_year:
            values.append(0.0)
        else:
            running += pnl_lookup.get(y, 0.0)
            values.append(running)

    return pl.Series("accumulated_retained_earnings", values)


# ---------------------------------------------------------------------------
# Derivative items (computed from own-domain items above)
# ---------------------------------------------------------------------------


def compute_current_assets_total(
    params: ParamsCore,
    invest: InvestResult,
    finplan: FinPlanResult,
) -> pl.Series:
    """Total current assets = current_assets + accumulated_surplus_cash."""
    ca = compute_current_assets(params, invest)
    asc = compute_accumulated_surplus_cash(params, finplan)
    return _add_series(ca, asc, "current_assets_total")


def compute_total_assets(
    params: ParamsCore,
    invest: InvestResult,
    cost: CostResult,
    finplan: FinPlanResult,
) -> pl.Series:
    """Total assets = sum of all asset items.

    = current_assets_total + construction_in_progress + fixed_assets_net
      + intangible_assets_net + accounts_receivable.
    Construction year = construction_in_progress only (other items are 0).
    """
    cat = compute_current_assets_total(params, invest, finplan)
    cip = compute_construction_in_progress(params, invest)
    fan = compute_fixed_assets_net(params, cost)
    ian = compute_intangible_assets_net(params, cost)
    ar = compute_accounts_receivable(params, finplan)

    result = pl.Series("total_assets", [0.0] * len(cat))
    for s in [cat, cip, fan, ian, ar]:
        result = _add_series_inplace(result, s)
    return result


def compute_total_liabilities(
    params: ParamsCore,
    invest: InvestResult,
    debt: DebtResult,
    finplan: FinPlanResult,
) -> pl.Series:
    """Total liabilities = current_liabilities + long_term + short_term."""
    cl = compute_current_liabilities(params, invest)
    lt = compute_long_term_loan_balance(params, debt)
    st = compute_short_term_loan_balance(params, finplan)

    result = pl.Series("total_liabilities", [0.0] * len(cl))
    for s in [cl, lt, st]:
        result = _add_series_inplace(result, s)
    return result


def compute_total_equity(
    params: ParamsCore,
    invest: InvestResult,
    cashflow: CashFlowResult,
    pnl: PnLResult,
) -> pl.Series:
    """Total equity = registered_capital + surplus_reserves + retained_earnings."""
    rc = compute_registered_capital(params, invest, cashflow)
    asr = compute_accumulated_surplus_reserves(params, pnl)
    are = compute_accumulated_retained_earnings(params, pnl)

    result = pl.Series("total_equity", [0.0] * len(rc))
    for s in [rc, asr, are]:
        result = _add_series_inplace(result, s)
    return result


def compute_total_liabilities_equity(
    params: ParamsCore,
    invest: InvestResult,
    debt: DebtResult,
    finplan: FinPlanResult,
    cashflow: CashFlowResult,
    pnl: PnLResult,
) -> pl.Series:
    """Total liabilities + equity = total_liabilities + total_equity.

    Must equal total_assets (fundamental accounting identity).
    """
    tl = compute_total_liabilities(params, invest, debt, finplan)
    te = compute_total_equity(params, invest, cashflow, pnl)
    return _add_series(tl, te, "total_liabilities_equity")


def compute_asset_liability_ratio(
    params: ParamsCore,
    invest: InvestResult,
    cost: CostResult,
    debt: DebtResult,
    finplan: FinPlanResult,
    cashflow: CashFlowResult,
    pnl: PnLResult,
) -> pl.Series:
    """Asset-liability ratio (%) = total_liabilities / total_assets.

    Raw fraction (not multiplied by 100).
    """
    tl = compute_total_liabilities(params, invest, debt, finplan)
    ta = compute_total_assets(params, invest, cost, finplan)

    values: list[float] = []
    for liab, assets in zip(tl.to_list(), ta.to_list(), strict=True):
        if assets != 0.0:
            values.append(liab / assets)
        else:
            values.append(0.0)
    return pl.Series("asset_liability_ratio", values)


def compute_balance_check(
    params: ParamsCore,
    invest: InvestResult,
    cost: CostResult,
    debt: DebtResult,
    finplan: FinPlanResult,
    cashflow: CashFlowResult,
    pnl: PnLResult,
) -> pl.Series:
    """Balance check = total_assets - total_liabilities_equity.

    Should be approximately 0 for all years (accounting identity).
    """
    ta = compute_total_assets(params, invest, cost, finplan)
    tle = compute_total_liabilities_equity(
        params, invest, debt, finplan, cashflow, pnl
    )

    result = pl.Series("balance_check", ta.to_list())
    result = _sub_series_inplace(result, tle)
    return result


def compute_balance_check_diff(
    params: ParamsCore,
    invest: InvestResult,
    cost: CostResult,
    debt: DebtResult,
    finplan: FinPlanResult,
    cashflow: CashFlowResult,
    pnl: PnLResult,
) -> pl.Series:
    """Period-over-period diff of balance_check.

    Construction year: current_assets - current_liabilities (not a diff).
    Operating years: current year balance_check - previous year balance_check.
    """
    bc = compute_balance_check(
        params, invest, cost, debt, finplan, cashflow, pnl
    )
    ca = compute_current_assets(params, invest)
    cl = compute_current_liabilities(params, invest)

    all_years = params.axis.all_years
    const_year = params.axis.construction_year

    bc_vals = bc.to_list()
    ca_vals = ca.to_list()
    cl_vals = cl.to_list()

    values: list[float] = []
    for i, y in enumerate(all_years):
        if y == const_year:
            values.append(ca_vals[i] - cl_vals[i])
        else:
            values.append(bc_vals[i] - bc_vals[i - 1])

    return pl.Series("balance_check_diff", values)


def compute_max_asset_liability_ratio(
    params: ParamsCore,
    invest: InvestResult,
    cost: CostResult,
    debt: DebtResult,
    finplan: FinPlanResult,
    cashflow: CashFlowResult,
    pnl: PnLResult,
) -> float:
    """Maximum asset-liability ratio across all operating years.

    Scalar: MAX(asset_liability_ratio over operating years).
    """
    alr = compute_asset_liability_ratio(
        params, invest, cost, debt, finplan, cashflow, pnl
    )
    op_ratios = alr.to_list()[1:]  # skip construction year
    return max(op_ratios) if op_ratios else 0.0


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def compute_balance(
    params: ParamsCore,
    invest: InvestResult,
    debt: DebtResult,
    cost: CostResult,
    pnl: PnLResult,
    finplan: FinPlanResult,
    cashflow: CashFlowResult,
) -> BalanceResult:
    """Assemble balance sheet from all non-coupled item computers.

    Frame column order: year, then items in SCHEMA order.
    """
    all_years = params.axis.all_years

    frame = pl.DataFrame(
        {"year": pl.Series("year", list(all_years), dtype=pl.Int64)}
    )

    # Each compute_* call returns a pl.Series of length len(all_years).
    # Add columns in schema item order.
    frame = frame.with_columns(
        compute_year_labels(params).alias("year_labels"),
        compute_total_assets(params, invest, cost, finplan).alias("total_assets"),
        compute_current_assets_total(params, invest, finplan).alias(
            "current_assets_total"
        ),
        compute_current_assets(params, invest).alias("current_assets"),
        compute_accumulated_surplus_cash(params, finplan).alias(
            "accumulated_surplus_cash"
        ),
        compute_accounts_receivable(params, finplan).alias("accounts_receivable"),
        compute_construction_in_progress(params, invest).alias(
            "construction_in_progress"
        ),
        compute_fixed_assets_net(params, cost).alias("fixed_assets_net"),
        compute_intangible_assets_net(params, cost).alias("intangible_assets_net"),
        compute_total_liabilities_equity(
            params, invest, debt, finplan, cashflow, pnl
        ).alias("total_liabilities_equity"),
        compute_current_liabilities(params, invest).alias("current_liabilities"),
        compute_long_term_loan_balance(params, debt).alias("long_term_loan_balance"),
        compute_short_term_loan_balance(params, finplan).alias(
            "short_term_loan_balance"
        ),
        compute_total_liabilities(params, invest, debt, finplan).alias(
            "total_liabilities"
        ),
        compute_total_equity(params, invest, cashflow, pnl).alias("total_equity"),
        compute_registered_capital(params, invest, cashflow).alias(
            "registered_capital"
        ),
        compute_accumulated_surplus_reserves(params, pnl).alias(
            "accumulated_surplus_reserves"
        ),
        compute_accumulated_retained_earnings(params, pnl).alias(
            "accumulated_retained_earnings"
        ),
        compute_asset_liability_ratio(
            params, invest, cost, debt, finplan, cashflow, pnl
        ).alias("asset_liability_ratio"),
        compute_balance_check(
            params, invest, cost, debt, finplan, cashflow, pnl
        ).alias("balance_check"),
        compute_balance_check_diff(
            params, invest, cost, debt, finplan, cashflow, pnl
        ).alias("balance_check_diff"),
    )

    scalars = BalanceScalars(
        max_asset_liability_ratio=compute_max_asset_liability_ratio(
            params, invest, cost, debt, finplan, cashflow, pnl
        ),
    )

    return BalanceResult(
        years=all_years,
        frame=frame,
        scalars=scalars,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _align_from_finplan(
    params: ParamsCore,
    finplan_frame: pl.DataFrame,
    column: str,
) -> pl.Series:
    """Align a finplan column to balance-sheet years by year-keyed lookup."""
    all_years = params.axis.all_years
    lookup = dict(
        zip(
            finplan_frame["year"].to_list(),
            finplan_frame[column].to_list(),
            strict=False,
        ),
    )
    return pl.Series(column, [lookup.get(y, 0.0) for y in all_years])


def _cumulative_from_finplan(
    params: ParamsCore,
    finplan_frame: pl.DataFrame,
    column: str,
) -> pl.Series:
    """Running cumulative sum of a finplan column, mapped to balance years.

    Construction year = 0, operating years = cumulative sum.
    """
    all_years = params.axis.all_years
    const_year = params.axis.construction_year

    lookup = dict(
        zip(
            finplan_frame["year"].to_list(),
            finplan_frame[column].to_list(),
            strict=False,
        ),
    )

    running = 0.0
    values: list[float] = []
    for y in all_years:
        if y == const_year:
            values.append(0.0)
        else:
            running += lookup.get(y, 0.0)
            values.append(running)
    return pl.Series(column, values)


def _add_from_cost_shifted(
    params: ParamsCore,
    cost_frame: pl.DataFrame,
    col_a: str,
    col_b: str,
) -> pl.Series:
    """Sum two cost columns, mapped to balance years.

    Construction year = 0. Operating years = col_a + col_b per year.
    """
    all_years = params.axis.all_years
    const_year = params.axis.construction_year

    lookup_a = dict(
        zip(cost_frame["year"].to_list(), cost_frame[col_a].to_list(), strict=False),
    )
    lookup_b = dict(
        zip(cost_frame["year"].to_list(), cost_frame[col_b].to_list(), strict=False),
    )

    values: list[float] = []
    for y in all_years:
        if y == const_year:
            values.append(0.0)
        else:
            values.append(lookup_a.get(y, 0.0) + lookup_b.get(y, 0.0))

    return pl.Series(f"{col_a}_plus_{col_b}", values)


def _add_series(
    a: pl.Series,
    b: pl.Series,
    name: str,
) -> pl.Series:
    """Element-wise a + b, returning a new named Series."""
    result = pl.Series(
        name,
        [av + bv for av, bv in zip(a.to_list(), b.to_list(), strict=True)],
    )
    return result


def _add_series_inplace(
    base: pl.Series,
    other: pl.Series,
) -> pl.Series:
    """base += other element-wise, returning a new Series (pl.Series is immutable)."""
    return pl.Series(
        base.name,
        [bv + ov for bv, ov in zip(base.to_list(), other.to_list(), strict=True)],
    )


def _sub_series_inplace(
    base: pl.Series,
    other: pl.Series,
) -> pl.Series:
    """base -= other element-wise, returning a new Series."""
    return pl.Series(
        base.name,
        [bv - ov for bv, ov in zip(base.to_list(), other.to_list(), strict=True)],
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = DomainSchema(
    key="balance",
    sheet="资产负债",
    label="资产负债表 (Balance)",
    depends_on=("params", "invest", "debt", "cost", "pnl", "finplan", "cashflow"),
    items=(
        ItemSchema(
            key="year_labels",
            label="运营年度",
            unit="-",
            formula="construction year = 1, operating years = 0",
            inputs=("params:construction_year",),
            rows=(4,),
        ),
        ItemSchema(
            key="total_assets",
            label="资产总计",
            unit="万元",
            formula="current_assets_total + construction_in_progress "
            "+ fixed_assets_net + intangible_assets_net + accounts_receivable",
            inputs=(
                "current_assets_total",
                "construction_in_progress",
                "fixed_assets_net",
                "intangible_assets_net",
                "accounts_receivable",
            ),
            rows=(5,),
        ),
        ItemSchema(
            key="current_assets_total",
            label="流动资产总值",
            unit="万元",
            formula="current_assets + accumulated_surplus_cash",
            inputs=("current_assets", "accumulated_surplus_cash"),
            rows=(6,),
        ),
        ItemSchema(
            key="current_assets",
            label="流动资产",
            unit="万元",
            formula="invest:working_capital per year (constant)",
            inputs=("invest:working_capital",),
            rows=(7,),
        ),
        ItemSchema(
            key="accumulated_surplus_cash",
            label="累计盈余资金",
            unit="万元",
            formula="finplan:cumulative_surplus per year (echo-through-origin)",
            inputs=("finplan:cumulative_surplus",),
            rows=(8,),
        ),
        ItemSchema(
            key="accounts_receivable",
            label="应收账款",
            unit="万元",
            formula="cumulative sum of finplan:subsidy_shortfall per year",
            inputs=("finplan:subsidy_shortfall",),
            rows=(9,),
        ),
        ItemSchema(
            key="construction_in_progress",
            label="在建工程",
            unit="万元",
            formula="invest:total_investment (construction year only, else 0)",
            inputs=("invest:total_investment",),
            rows=(10,),
        ),
        ItemSchema(
            key="fixed_assets_net",
            label="固定资产净值",
            unit="万元",
            formula="cost:fixed_asset_net_value; years 21-25 freeze at year 20",
            inputs=("cost:fixed_asset_net_value",),
            rows=(11,),
        ),
        ItemSchema(
            key="intangible_assets_net",
            label="无形及其他资产净值",
            unit="万元",
            formula="cost:deferred_vat_net + cost:land_rent_net per year",
            inputs=("cost:deferred_vat_net", "cost:land_rent_net"),
            rows=(12,),
        ),
        ItemSchema(
            key="total_liabilities_equity",
            label="负债及所有者权益",
            unit="万元",
            formula="total_liabilities + total_equity (must equal total_assets)",
            inputs=("total_liabilities", "total_equity"),
            rows=(13,),
        ),
        ItemSchema(
            key="current_liabilities",
            label="流动负债总值",
            unit="万元",
            formula="invest:working_capital_loan per year (constant)",
            inputs=("invest:working_capital_loan",),
            rows=(14,),
        ),
        ItemSchema(
            key="long_term_loan_balance",
            label="长期借款",
            unit="万元",
            formula="debt:long_term_loan_balance, end-of-year alignment: "
            "balance end-of-y reads debt beginning-of-(y+1); final year = 0",
            inputs=("debt:long_term_loan_balance",),
            rows=(15,),
        ),
        ItemSchema(
            key="short_term_loan_balance",
            label="短期借款",
            unit="万元",
            formula="finplan:short_term_borrowing per year (echo-through-origin)",
            inputs=("finplan:short_term_borrowing",),
            rows=(16,),
        ),
        ItemSchema(
            key="total_liabilities",
            label="负债小计",
            unit="万元",
            formula="current_liabilities + long_term_loan_balance "
            "+ short_term_loan_balance",
            inputs=(
                "current_liabilities",
                "long_term_loan_balance",
                "short_term_loan_balance",
            ),
            rows=(17,),
        ),
        ItemSchema(
            key="total_equity",
            label="所有者权益",
            unit="万元",
            formula="registered_capital + accumulated_surplus_reserves "
            "+ accumulated_retained_earnings",
            inputs=(
                "registered_capital",
                "accumulated_surplus_reserves",
                "accumulated_retained_earnings",
            ),
            rows=(18,),
        ),
        ItemSchema(
            key="registered_capital",
            label="资本金",
            unit="万元",
            formula="invest equity cumulative + cashflow equity_capital_invest "
            "cumulative per year",
            inputs=(
                "invest:equity_for_construction",
                "invest:equity_for_working_capital",
                "cashflow:equity_capital_invest",
            ),
            rows=(19,),
        ),
        ItemSchema(
            key="accumulated_surplus_reserves",
            label="累计三金",
            unit="万元",
            formula="cumulative sum of (pnl:surplus_reserve + pnl:row28_total) "
            "per year",
            inputs=("pnl:surplus_reserve", "pnl:row28_total"),
            rows=(20,),
        ),
        ItemSchema(
            key="accumulated_retained_earnings",
            label="累计未分配利润",
            unit="万元",
            formula="cumulative sum of pnl:undistributed_profit per year",
            inputs=("pnl:undistributed_profit",),
            rows=(21,),
        ),
        ItemSchema(
            key="asset_liability_ratio",
            label="资产负债率",
            unit="%",
            formula="total_liabilities / total_assets per year (raw fraction)",
            inputs=("total_liabilities", "total_assets"),
            rows=(23,),
        ),
        ItemSchema(
            key="balance_check",
            label="资产负债表平衡检查",
            unit="万元",
            formula="total_assets - total_liabilities_equity (should be ~0)",
            inputs=("total_assets", "total_liabilities_equity"),
            rows=(25,),
        ),
        ItemSchema(
            key="balance_check_diff",
            label="资产负债表平衡差(期差)",
            unit="万元",
            formula="period-over-period diff of balance_check; "
            "construction year = current_assets - current_liabilities",
            inputs=("balance_check", "current_assets", "current_liabilities"),
            rows=(26,),
        ),
        ItemSchema(
            key="max_asset_liability_ratio",
            label="最大资产负债率",
            unit="%",
            formula="MAX(asset_liability_ratio across all operating years)",
            inputs=("asset_liability_ratio",),
            rows=(28,),
            kind="scalar",
        ),
    ),
)
