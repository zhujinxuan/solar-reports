"""FinancialPlan — 财务计划现金流量表 (sources & uses of funds).

Non-coupled items have compute_<key> functions returning pl.Series (26 rows:
construction year + 25 operating years).  Coupled items are YearSlice fields
filled by mutual.solve; the construction year gets ConstructionSlice values
from MutualSolution.construction.

All cross-sheet column offsets from the original workbook are replaced by
calendar-year-keyed frame joins. Upstream values come from the typed result
objects (invest, debt, cost, pnl, params, solution).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from solar_v2.axis import YearAxis
from solar_v2.schema import DomainSchema, ItemSchema

if TYPE_CHECKING:
    from solar_v2.domains.cost import CostResult
    from solar_v2.domains.debt import DebtResult
    from solar_v2.domains.invest import InvestResult
    from solar_v2.domains.params import ParamsCore
    from solar_v2.domains.pnl import PnLResult
    from solar_v2.mutual import MutualSolution


# ── Error check type ──────────────────────────────────────────────


@dataclass(frozen=True)
class ErrorCheck:
    """Error-cell state for the error-check row.

    `value` is the computed float when the check is finite;
    `error` is the error string (e.g. "#DIV/0!") when the workbook
    semantics produce an error. Exactly one of them is non-None.
    """

    year: int
    value: float | None = None
    error: str | None = None


# ── Result type ───────────────────────────────────────────────────


@dataclass(frozen=True)
class FinPlanScalars:
    """FinPlan has no genuine scalar items."""


@dataclass(frozen=True)
class FinPlanResult:
    """Financial plan — sources & uses of funds per year."""

    years: tuple[int, ...]  # construction year + 25 operating years
    frame: pl.DataFrame  # year column + one column per frame item key
    scalars: FinPlanScalars
    error_checks: tuple[ErrorCheck, ...]  # one per year, 26 total


# ── Helpers ───────────────────────────────────────────────────────


def _series(name: str, values: list[float]) -> pl.Series:
    """Build a named Float64 series from values."""
    return pl.Series(name, values, dtype=pl.Float64)


def _find_year(year: int, years: tuple[int, ...]) -> int | None:
    """Return index of year in years tuple, or None."""
    for i, y in enumerate(years):
        if y == year:
            return i
    return None


def _op_year_val(
    finplan_idx: int,
    axis: YearAxis,
    upstream_years: tuple[int, ...],
    upstream_col: pl.Series,
) -> float:
    """Get upstream value for a finplan operating year index."""
    if finplan_idx < 1 or finplan_idx >= len(axis.all_years):
        return 0.0
    fy = axis.all_years[finplan_idx]
    ui = _find_year(fy, upstream_years)
    if ui is not None:
        return upstream_col[ui]
    return 0.0


# ── Non-coupled compute functions ─────────────────────────────────


def compute_year_labels(axis: YearAxis) -> pl.Series:
    """Row 4: year labels = operating year indices (1-based).

    Construction year = 1, then operating years 1, 2, ..., 25.
    This echoes 成本 row 4 per the workbook convention.
    """
    result = [1.0]  # construction year = 1
    for i in range(1, axis.operating_years + 1):
        result.append(float(i))
    return _series("year_labels", result)


def compute_sales_revenue(axis: YearAxis, pnl: PnLResult) -> pl.Series:
    """Row 7: sales revenue = pnl sales_revenue + pnl vat_refund.

    Echo-through-origin: the workbook reads from the 损益 sheet directly.
    Construction year is zero.
    """
    n = len(axis.all_years)
    result = [0.0] * n
    for idx in range(1, n):
        result[idx] = _op_year_val(
            idx, axis, pnl.years, pnl.frame["sales_revenue"]
        ) + _op_year_val(idx, axis, pnl.years, pnl.frame["vat_refund"])
    return _series("sales_revenue", result)


def compute_vat_refund_inflow(axis: YearAxis, pnl: PnLResult) -> pl.Series:
    """Row 8: VAT refund inflow = pnl output_vat.

    The workbook reads from the 损益 sheet (output VAT row).
    """
    n = len(axis.all_years)
    result = [0.0] * n
    for idx in range(1, n):
        result[idx] = _op_year_val(
            idx, axis, pnl.years, pnl.frame["output_vat"]
        )
    return _series("vat_refund_inflow", result)


def compute_subsidy_shortfall(
    axis: YearAxis,
    pnl: PnLResult,
    params: ParamsCore,
) -> pl.Series:
    """Row 10: subsidy shortfall.

    Formula: (1 - subsidy_arrival_rate) * subsidy_per_kwh * guaranteed_sales.
    subsidy_arrival_rate comes from params frame (100% for all years).
    subsidy_per_kwh is a scalar on params.
    In the default model subsidy_per_kwh = 0, so this is always zero.
    """
    n = len(axis.all_years)
    result = [0.0] * n
    subsidy_per_kwh = getattr(params, "subsidy_per_kwh", 0.0)
    if subsidy_per_kwh == 0.0:
        return _series("subsidy_shortfall", result)

    for idx in range(1, n):
        fy = axis.all_years[idx]
        pi = _find_year(fy, params.years)
        arrival = 1.0
        if pi is not None and "subsidy_arrival_rate" in params.frame.columns:
            arrival = params.frame["subsidy_arrival_rate"][pi]
        guaranteed = _op_year_val(
            idx, axis, pnl.years, pnl.frame["guaranteed_sales"]
        )
        result[idx] = (1.0 - arrival) * subsidy_per_kwh * guaranteed
    return _series("subsidy_shortfall", result)


def compute_operating_inflow(
    axis: YearAxis,
    pnl: PnLResult,
    params: ParamsCore,
) -> pl.Series:
    """Row 6: operating inflow = sales_revenue + vat_refund - subsidy_shortfall.

    Construction year: 0.
    Row 9 (subsidy_inflow) is zero in the current model.
    """
    n = len(axis.all_years)
    sales = compute_sales_revenue(axis, pnl).to_list()
    vat = compute_vat_refund_inflow(axis, pnl).to_list()
    subsidy = compute_subsidy_shortfall(axis, pnl, params).to_list()
    result = [0.0] * n
    for idx in range(1, n):
        result[idx] = sales[idx] + vat[idx] - subsidy[idx]
    return _series("operating_inflow", result)


def compute_operating_cost_outflow(
    axis: YearAxis, cost: CostResult
) -> pl.Series:
    """Row 12: operating cost outflow = cost operating_cost.

    ORIGIN = cost domain, NOT the cashflow mirror.
    """
    n = len(axis.all_years)
    result = [0.0] * n
    for idx in range(1, n):
        result[idx] = _op_year_val(
            idx, axis, cost.years, cost.frame["operating_cost"]
        )
    return _series("operating_cost_outflow", result)


def compute_city_tax(axis: YearAxis, pnl: PnLResult) -> pl.Series:
    """Row 13: city tax & education surcharge = pnl vat_surcharge_total.

    ORIGIN = pnl domain, NOT the cashflow mirror.
    """
    n = len(axis.all_years)
    result = [0.0] * n
    for idx in range(1, n):
        result[idx] = _op_year_val(
            idx, axis, pnl.years, pnl.frame["vat_surcharge_total"]
        )
    return _series("city_tax", result)


def compute_large_rent_payment(
    axis: YearAxis, params: ParamsCore
) -> pl.Series:
    """Row 14: large rent payment = params land-rent payment schedule.

    The workbook reads the land-rent lump-sum payment schedule.
    Zero for construction year.
    """
    # The params frame is all_years-aligned (construction at index 0),
    # so finplan year idx reads params row idx directly.
    n = len(axis.all_years)
    payments = params.frame["land_rent_payment"].to_list()
    result = [0.0] * n
    for idx in range(1, n):
        result[idx] = float(payments[idx])
    return _series("large_rent_payment", result)


def compute_vat_payable_outflow(
    axis: YearAxis, pnl: PnLResult
) -> pl.Series:
    """Row 16: VAT payable outflow = pnl vat_payable.

    ORIGIN = pnl domain, NOT the cashflow mirror.
    """
    n = len(axis.all_years)
    result = [0.0] * n
    for idx in range(1, n):
        result[idx] = _op_year_val(
            idx, axis, pnl.years, pnl.frame["vat_payable"]
        )
    return _series("vat_payable_outflow", result)


def compute_equity_injection(
    axis: YearAxis, invest: InvestResult
) -> pl.Series:
    """Row 19: equity injection from invest during construction period.

    invest frame is period-keyed: build1, build2, oper1, oper2.
    finplan construction year maps to invest oper1 period.
    finplan operating year 1 maps to invest oper2 period.
    """
    n = len(axis.all_years)
    result = [0.0] * n
    periods = invest.frame["period"].to_list()
    ec = invest.frame["equity_capital"].to_list()
    pmap = dict(zip(periods, ec, strict=False))
    result[0] = pmap.get("oper1", 0.0)
    if n > 1:
        result[1] = pmap.get("oper2", 0.0)
    return _series("equity_injection", result)


def compute_construction_loan(
    axis: YearAxis, debt: DebtResult
) -> pl.Series:
    """Row 20: construction loan = debt long_term_loan_balance at construction.

    Only the construction-year cell has a value (D20).
    """
    n = len(axis.all_years)
    result = [0.0] * n
    cy = axis.construction_year
    di = _find_year(cy, debt.years)
    if di is not None:
        result[0] = debt.frame["long_term_loan_balance"][di]
    return _series("construction_loan", result)


def compute_wc_loan(axis: YearAxis, invest: InvestResult) -> pl.Series:
    """Row 21: working capital loan = invest working_capital_loan.

    Only the first operating year has a value (E21).
    finplan operating year 1 maps to invest oper2 period.
    """
    n = len(axis.all_years)
    result = [0.0] * n
    periods = invest.frame["period"].to_list()
    wcl = invest.frame["working_capital_loan"].to_list()
    pmap = dict(zip(periods, wcl, strict=False))
    if n > 1:
        result[1] = pmap.get("oper2", 0.0)
    return _series("wc_loan", result)


def compute_construction_investment_outflow(
    axis: YearAxis, invest: InvestResult
) -> pl.Series:
    """Row 25: construction investment outflow from invest.

    Port of workbook quirk:
    - construction year: invest funding_sources at oper1 period
    - operating year 1: invest long_term_loan at oper2 period
    invest row 10 (funding_sources) and row 15 (long_term_loan)
    map to invest oper1 and oper2 respectively with +2 column offset.
    """
    n = len(axis.all_years)
    result = [0.0] * n
    periods = invest.frame["period"].to_list()
    fs = invest.frame["funding_sources"].to_list()
    ltl = invest.frame["long_term_loan"].to_list()
    fs_map = dict(zip(periods, fs, strict=False))
    ltl_map = dict(zip(periods, ltl, strict=False))
    result[0] = fs_map.get("oper1", 0.0)
    if n > 1:
        result[1] = ltl_map.get("oper2", 0.0)
    return _series("construction_investment_outflow", result)


def compute_working_capital_outflow(
    axis: YearAxis, invest: InvestResult
) -> pl.Series:
    """Row 26: working capital outflow = invest working_capital.

    Only the first operating year has a value (E26).
    finplan operating year 1 maps to invest oper2 period.
    """
    n = len(axis.all_years)
    result = [0.0] * n
    periods = invest.frame["period"].to_list()
    wc = invest.frame["working_capital"].to_list()
    pmap = dict(zip(periods, wc, strict=False))
    if n > 1:
        result[1] = pmap.get("oper2", 0.0)
    return _series("working_capital_outflow", result)


def compute_lt_loan_repay(axis: YearAxis, debt: DebtResult) -> pl.Series:
    """Row 27: long-term loan principal repayment = debt principal repay.

    The workbook reads from the 还贷 sheet same column (no offset).
    """
    n = len(axis.all_years)
    result = [0.0] * n
    for idx in range(1, n):
        result[idx] = _op_year_val(
            idx,
            axis,
            debt.years,
            debt.frame["long_term_loan_interest_payment"],
        )
    return _series("lt_loan_repay", result)


def compute_other_outflow(axis: YearAxis) -> pl.Series:
    """Row 32: other outflow — all zeros."""
    return _series("other_outflow", [0.0] * len(axis.all_years))


# ── Non-coupled items that depend on coupled values ───────────────


def compute_outflow_excl_distribution(
    axis: YearAxis,
    invest: InvestResult,
    debt: DebtResult,
    pnl: PnLResult,
    cost: CostResult,
    solution: MutualSolution,
) -> pl.Series:
    """Row 38: outflow excluding profit distribution.

    Per operating year:
        s = rows 25+26+27+28+29+30
          = construction_investment_outflow + working_capital_outflow
            + lt_loan_repay + short_term_repayment + 0 + interest_outflow
    For first operating year (idx 1): subtract invest_inflow (row 18 quirk).
    """
    n = len(axis.all_years)
    ny = axis.operating_years

    cinv = compute_construction_investment_outflow(axis, invest).to_list()
    wc_out = compute_working_capital_outflow(axis, invest).to_list()
    lt_repay = compute_lt_loan_repay(axis, debt).to_list()

    result = [0.0] * n
    for idx in range(1, n):
        i = idx - 1  # operating year index into solution steps
        st_repay = (
            solution.steps[i].short_term_repayment if i < ny else 0.0
        )
        interest = (
            solution.steps[i].interest_outflow if i < ny else 0.0
        )
        inv_inflow = (
            solution.steps[i].invest_inflow if i < ny else 0.0
        )

        s = (
            cinv[idx]
            + wc_out[idx]
            + lt_repay[idx]
            + st_repay
            + 0.0  # row 29 = 0
            + interest
        )
        if idx == 1:  # row 38 quirk: first op year subtracts invest_inflow
            s -= inv_inflow
        result[idx] = s

    return _series("outflow_excl_distribution", result)


def compute_net_cf_excl_distribution(
    axis: YearAxis,
    invest: InvestResult,
    debt: DebtResult,
    pnl: PnLResult,
    cost: CostResult,
    solution: MutualSolution,
) -> pl.Series:
    """Row 39: net cash flow excluding distribution.

    Formula: operating_net_cf - outflow_excl_distribution per year.
    """
    n = len(axis.all_years)
    ny = axis.operating_years
    outflow = compute_outflow_excl_distribution(
        axis, invest, debt, pnl, cost, solution
    ).to_list()

    result = [0.0] * n
    for idx in range(1, n):
        i = idx - 1
        op_ncf = solution.steps[i].operating_net_cf if i < ny else 0.0
        result[idx] = op_ncf - outflow[idx]
    return _series("net_cf_excl_distribution", result)


def compute_cumulative_surplus_check(
    axis: YearAxis, solution: MutualSolution
) -> pl.Series:
    """Row 42: cumulative surplus check (audit).

    Formula: operating_net_cf + invest_finance_net_cf - short_term_repayment.
    All three are coupled YearSlice fields.
    """
    n = len(axis.all_years)
    ny = axis.operating_years
    result = [0.0] * n
    for idx in range(1, n):
        i = idx - 1
        if i < ny:
            s = solution.steps[i]
            result[idx] = (
                s.operating_net_cf
                + s.invest_finance_net_cf
                - s.short_term_repayment
            )
    return _series("cumulative_surplus_check", result)


# ── Error checks ──────────────────────────────────────────────────


def _error_checks_raw(
    axis: YearAxis, solution: MutualSolution
) -> tuple[ErrorCheck, ...]:
    """Row 36: error-check IF-chain.

    Port the old logic faithfully:
    - construction year (idx 0): value 0.0
    - first operating year (idx 1): value 0.0
    - operating year t>=2 (idx >= 2):
        prev = st_repay[idx-1], curr = st_repay[idx]
        if prev + curr == 0 or curr > 0:
            value = 0.0
        elif st_repay[idx-2] == 0:
            error = "#DIV/0!"
        else:
            value = year_labels[idx-2] + prev / st_repay[idx-2]
    """
    n = len(axis.all_years)
    ny = axis.operating_years

    # Build short_term_repayment array: [0 (construction), ... op years]
    st_repay: list[float] = [0.0]
    for i in range(ny):
        st_repay.append(solution.steps[i].short_term_repayment)
    while len(st_repay) < n:
        st_repay.append(0.0)

    checks: list[ErrorCheck] = []
    # Construction year
    checks.append(ErrorCheck(year=axis.construction_year, value=0.0))

    # First operating year
    if n > 1:
        checks.append(ErrorCheck(year=axis.years[0], value=0.0))

    # Remaining operating years
    for i in range(2, n):
        yr = axis.all_years[i]
        prev = st_repay[i - 1]
        curr = st_repay[i]
        if prev + curr == 0 or curr > 0:
            checks.append(ErrorCheck(year=yr, value=0.0))
        else:
            two_back = st_repay[i - 2]
            if two_back == 0:
                checks.append(ErrorCheck(year=yr, error="#DIV/0!"))
            else:
                val = axis.all_years[i - 2] + prev / two_back
                checks.append(ErrorCheck(year=yr, value=val))

    return tuple(checks)


def compute_error_checks(
    axis: YearAxis, solution: MutualSolution
) -> pl.Series:
    """Row 36: error-check IF-chain as pl.Series.

    Numeric values where check is finite, NaN where the workbook
    would produce an error (e.g. #DIV/0!).
    The full ErrorCheck tuple is on FinPlanResult.error_checks.
    """
    n = len(axis.all_years)
    result = [0.0] * n
    checks = _error_checks_raw(axis, solution)
    for c in checks:
        idx = axis.all_years.index(c.year)
        if c.error is not None:
            result[idx] = float("nan")
        elif c.value is not None:
            result[idx] = c.value
    return _series("error_checks", result)


# ── Main compute function ─────────────────────────────────────────

# Items that appear in the frame (all non-coupled series + coupled series).
FRAME_ITEM_KEYS: tuple[str, ...] = (
    "year_labels",
    "operating_net_cf",
    "operating_inflow",
    "sales_revenue",
    "vat_refund_inflow",
    "subsidy_shortfall",
    "operating_outflow",
    "operating_cost_outflow",
    "city_tax",
    "large_rent_payment",
    "income_tax_outflow",
    "vat_payable_outflow",
    "invest_finance_net_cf",
    "invest_inflow",
    "equity_injection",
    "construction_loan",
    "wc_loan",
    "short_term_borrowing",
    "invest_outflow",
    "construction_investment_outflow",
    "working_capital_outflow",
    "lt_loan_repay",
    "short_term_repayment",
    "interest_outflow",
    "profit_distribution",
    "other_outflow",
    "net_cash_flow",
    "cumulative_surplus",
    "outflow_excl_distribution",
    "net_cf_excl_distribution",
    "distributable_profit_pool",
    "actual_distribution",
    "cumulative_surplus_check",
    "error_checks",
)

# Coupled keys (computed by mutual.step_year, NO compute_<key> fn)
COUPLED_KEYS: frozenset[str] = frozenset(
    {
        "operating_net_cf",
        "operating_outflow",
        "income_tax_outflow",
        "invest_finance_net_cf",
        "invest_inflow",
        "short_term_borrowing",
        "invest_outflow",
        "short_term_repayment",
        "interest_outflow",
        "profit_distribution",
        "net_cash_flow",
        "cumulative_surplus",
        "distributable_profit_pool",
        "actual_distribution",
    }
)

# Construction-year default zeros for coupled keys
_CS_ZEROS: dict[str, float] = {
    "operating_net_cf": 0.0,
    "operating_outflow": 0.0,
    "income_tax_outflow": 0.0,
    "short_term_repayment": 0.0,
    "interest_outflow": 0.0,
    "profit_distribution": 0.0,
    "distributable_profit_pool": 0.0,
    "actual_distribution": 0.0,
    "short_term_borrowing": 0.0,
}


def compute_finplan(
    params: ParamsCore,
    invest: InvestResult,
    debt: DebtResult,
    cost: CostResult,
    pnl: PnLResult,
    solution: MutualSolution,
) -> FinPlanResult:
    """Compute the full financial plan (sources & uses of funds).

    Non-coupled items are computed directly from upstream results.
    Coupled items come from MutualSolution: operating years from
    solution.steps[i].<key>, construction year from solution.construction.
    """
    axis = params.axis
    n = len(axis.all_years)
    ny = axis.operating_years
    cs = solution.construction

    # ── Non-coupled series ──
    nc: dict[str, pl.Series] = {
        "year_labels": compute_year_labels(axis),
        "sales_revenue": compute_sales_revenue(axis, pnl),
        "vat_refund_inflow": compute_vat_refund_inflow(axis, pnl),
        "subsidy_shortfall": compute_subsidy_shortfall(axis, pnl, params),
        "operating_cost_outflow": compute_operating_cost_outflow(
            axis, cost
        ),
        "city_tax": compute_city_tax(axis, pnl),
        "large_rent_payment": compute_large_rent_payment(axis, params),
        "vat_payable_outflow": compute_vat_payable_outflow(axis, pnl),
        "equity_injection": compute_equity_injection(axis, invest),
        "construction_loan": compute_construction_loan(axis, debt),
        "wc_loan": compute_wc_loan(axis, invest),
        "construction_investment_outflow": (
            compute_construction_investment_outflow(axis, invest)
        ),
        "working_capital_outflow": compute_working_capital_outflow(
            axis, invest
        ),
        "lt_loan_repay": compute_lt_loan_repay(axis, debt),
        "other_outflow": compute_other_outflow(axis),
    }
    nc["operating_inflow"] = compute_operating_inflow(axis, pnl, params)

    # ── Coupled series from solution ──
    cpl: dict[str, pl.Series] = {}
    for key in FRAME_ITEM_KEYS:
        if key not in COUPLED_KEYS:
            continue
        vals = [0.0] * n

        # Construction year
        if hasattr(cs, key):
            vals[0] = getattr(cs, key)
        elif key in _CS_ZEROS:
            vals[0] = _CS_ZEROS[key]

        # Operating years
        for i in range(ny):
            vals[i + 1] = getattr(solution.steps[i], key)

        cpl[key] = _series(key, vals)

    # ── Dependent non-coupled rows (reference coupled values) ──
    nc["outflow_excl_distribution"] = compute_outflow_excl_distribution(
        axis, invest, debt, pnl, cost, solution
    )
    nc["net_cf_excl_distribution"] = compute_net_cf_excl_distribution(
        axis, invest, debt, pnl, cost, solution
    )
    nc["cumulative_surplus_check"] = compute_cumulative_surplus_check(
        axis, solution
    )
    nc["error_checks"] = compute_error_checks(axis, solution)

    # ── Build frame: year column first, then items in FRAME_ITEM_KEYS order ──
    all_series = {**nc, **cpl}
    ordered: dict[str, pl.Series] = {
        "year": pl.Series("year", list(axis.all_years), dtype=pl.Int64),
    }
    for key in FRAME_ITEM_KEYS:
        if key in all_series:
            ordered[key] = all_series[key]

    frame = pl.DataFrame(ordered)

    # ── Error checks ──
    error_checks = _error_checks_raw(axis, solution)

    return FinPlanResult(
        years=axis.all_years,
        frame=frame,
        scalars=FinPlanScalars(),
        error_checks=error_checks,
    )


# ── Domain calculation schema ─────────────────────────────────────

SCHEMA = DomainSchema(
    key="finplan",
    sheet="财务计划",
    label="财务计划现金流量表 (FinPlan)",
    depends_on=("params", "invest", "debt", "cost", "pnl", "mutual"),
    items=(
        ItemSchema(
            key="year_labels",
            label="运营年度",
            unit="-",
            formula="Calendar years from the axis (construction + 25 operating)",
            inputs=("cost:year_labels",),
            rows=(4,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="operating_net_cf",
            label="经营活动净现金流量",
            unit="万元",
            formula="operating_inflow - operating_outflow (coupled)",
            inputs=("operating_inflow", "operating_outflow"),
            rows=(5,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="operating_inflow",
            label="经营活动：现金流入",
            unit="万元",
            formula="sales_revenue + vat_refund_inflow - subsidy_shortfall",
            inputs=(
                "sales_revenue",
                "vat_refund_inflow",
                "subsidy_shortfall",
            ),
            rows=(6,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="sales_revenue",
            label="经营活动：销售收入",
            unit="万元",
            formula=(
                "pnl sales_revenue + pnl vat_refund "
                "(echo-through-origin from 损益)"
            ),
            inputs=("pnl:sales_revenue", "pnl:vat_refund"),
            rows=(7,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="vat_refund_inflow",
            label="经营活动：增值税退税",
            unit="万元",
            formula="pnl output_vat (origin: 损益 output VAT row)",
            inputs=("pnl:output_vat",),
            rows=(8,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="subsidy_shortfall",
            label="经营活动：补贴未到位资金",
            unit="万元",
            formula=(
                "(1 - subsidy_arrival_rate) * subsidy_per_kwh "
                "* guaranteed_sales"
            ),
            inputs=(
                "pnl:guaranteed_sales",
                "params:subsidy_arrival_rate",
                "params:subsidy_per_kwh",
            ),
            rows=(10,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="operating_outflow",
            label="经营活动：现金流出",
            unit="万元",
            formula="SUM of rows 12-16 (coupled)",
            inputs=(
                "operating_cost_outflow",
                "city_tax",
                "large_rent_payment",
                "income_tax_outflow",
                "vat_payable_outflow",
            ),
            rows=(11,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="operating_cost_outflow",
            label="经营活动：经营成本",
            unit="万元",
            formula="cost operating_cost (ORIGIN, not cashflow mirror)",
            inputs=("cost:operating_cost",),
            rows=(12,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="city_tax",
            label="经营活动：城建税及教育附加",
            unit="万元",
            formula="pnl vat_surcharge_total (ORIGIN, not cashflow mirror)",
            inputs=("pnl:vat_surcharge_total",),
            rows=(13,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="large_rent_payment",
            label="经营活动：大额租金",
            unit="万元",
            formula="params land_rent_payment schedule (lump-sum per payment year)",
            inputs=("params:land_rent_payment",),
            rows=(14,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="income_tax_outflow",
            label="经营活动：所得税",
            unit="万元",
            formula="pnl income_tax (coupled)",
            inputs=("pnl:income_tax",),
            rows=(15,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="vat_payable_outflow",
            label="经营活动：应缴增值税",
            unit="万元",
            formula="pnl vat_payable (ORIGIN, not cashflow mirror)",
            inputs=("pnl:vat_payable",),
            rows=(16,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="invest_finance_net_cf",
            label="投资筹资活动净现金流量",
            unit="万元",
            formula="invest_inflow - invest_outflow (coupled)",
            inputs=("invest_inflow", "invest_outflow"),
            rows=(17,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="invest_inflow",
            label="投筹资：现金流入",
            unit="万元",
            formula=(
                "SUM(equity_injection, construction_loan, wc_loan, "
                "short_term_borrowing) (coupled)"
            ),
            inputs=(
                "equity_injection",
                "construction_loan",
                "wc_loan",
                "short_term_borrowing",
            ),
            rows=(18,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="equity_injection",
            label="投筹资：项目资本金投入",
            unit="万元",
            formula=(
                "invest equity_capital at oper1/oper2 periods "
                "(non-coupled construction period values)"
            ),
            inputs=("invest:equity_capital",),
            rows=(19,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="construction_loan",
            label="投筹资：建设投资借款",
            unit="万元",
            formula="debt long_term_loan_balance at construction (D20 only)",
            inputs=("debt:long_term_loan_balance",),
            rows=(20,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="wc_loan",
            label="投筹资：流动资金借款",
            unit="万元",
            formula="invest working_capital_loan at oper2 period (E21 only)",
            inputs=("invest:working_capital_loan",),
            rows=(21,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="short_term_borrowing",
            label="投筹资：短期借款",
            unit="万元",
            formula="cumulative cash shortfall bridge loan (coupled)",
            inputs=(),
            rows=(22,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="invest_outflow",
            label="投筹资：现金流出",
            unit="万元",
            formula=(
                "SUM of construction_investment_outflow, "
                "working_capital_outflow, lt_loan_repay, "
                "short_term_repayment, interest_outflow, "
                "profit_distribution, other_outflow (coupled)"
            ),
            inputs=(
                "construction_investment_outflow",
                "working_capital_outflow",
                "lt_loan_repay",
                "short_term_repayment",
                "interest_outflow",
                "profit_distribution",
                "other_outflow",
            ),
            rows=(24,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="construction_investment_outflow",
            label="投筹资：建设投资",
            unit="万元",
            formula=(
                "invest funding_sources at oper1, "
                "invest long_term_loan at oper2 "
                "(quirk: D maps to oper1 funding_sources row 10, "
                "E maps to oper2 long_term_loan row 15)"
            ),
            inputs=("invest:funding_sources", "invest:long_term_loan"),
            rows=(25,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="working_capital_outflow",
            label="投筹资：流动资金",
            unit="万元",
            formula="invest working_capital at oper2 period (E26 only)",
            inputs=("invest:working_capital",),
            rows=(26,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="lt_loan_repay",
            label="投筹资：长期借款本金偿还",
            unit="万元",
            formula="debt long_term_loan_principal_repay per year",
            inputs=("debt:long_term_loan_principal_repay",),
            rows=(27,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="short_term_repayment",
            label="投筹资：短期借款本金偿还",
            unit="万元",
            formula="prior year short_term_borrowing (coupled)",
            inputs=("short_term_borrowing",),
            rows=(28,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="interest_outflow",
            label="投筹资：各种利息支出",
            unit="万元",
            formula="cost interest_expense (coupled)",
            inputs=("cost:interest_expense",),
            rows=(30,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="profit_distribution",
            label="投筹资：各投资方利润分配",
            unit="万元",
            formula=(
                "pnl distributable_profit * dividend_ratio (coupled)"
            ),
            inputs=("pnl:distributable_profit", "params:dividend_ratio"),
            rows=(31,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="other_outflow",
            label="投筹资：其他流出",
            unit="万元",
            formula="0 (all years)",
            inputs=(),
            rows=(32,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="net_cash_flow",
            label="净现金流量",
            unit="万元",
            formula=(
                "operating_net_cf + invest_finance_net_cf "
                "- short_term_repayment (coupled)"
            ),
            inputs=(
                "operating_net_cf",
                "invest_finance_net_cf",
                "short_term_repayment",
            ),
            rows=(33,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="cumulative_surplus",
            label="累计盈余资金",
            unit="万元",
            formula="cumulative sum of net_cash_flow (coupled)",
            inputs=("net_cash_flow",),
            rows=(34,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="error_checks",
            label="错误检查行",
            unit="-",
            formula=(
                "Error check IF-chain on short_term_repayment: "
                "may produce #DIV/0! where prior two repayments are zero"
            ),
            inputs=("short_term_repayment",),
            rows=(36,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="outflow_excl_distribution",
            label="不含利润分配的流出",
            unit="万元",
            formula=(
                "invest_outflow - profit_distribution - other_outflow "
                "+ short_term_repayment; "
                "first operating year also - invest_inflow (row 38 quirk)"
            ),
            inputs=(
                "invest_outflow",
                "profit_distribution",
                "short_term_repayment",
                "invest_inflow",
            ),
            rows=(38,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="net_cf_excl_distribution",
            label="净现金流（不含利润分配）",
            unit="万元",
            formula=(
                "operating_net_cf - outflow_excl_distribution"
            ),
            inputs=(
                "operating_net_cf",
                "outflow_excl_distribution",
            ),
            rows=(39,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="distributable_profit_pool",
            label="可分配利润",
            unit="万元",
            formula=(
                "pnl distributable_profit * dividend_ratio (coupled)"
            ),
            inputs=(
                "pnl:distributable_profit",
                "params:dividend_ratio",
            ),
            rows=(40,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="actual_distribution",
            label="实际分配利润",
            unit="万元",
            formula="echo of distributable_profit_pool (coupled)",
            inputs=("distributable_profit_pool",),
            rows=(41,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="cumulative_surplus_check",
            label="累计盈余资金(审计)",
            unit="万元",
            formula=(
                "operating_net_cf + invest_finance_net_cf "
                "- short_term_repayment (audit check)"
            ),
            inputs=(
                "operating_net_cf",
                "invest_finance_net_cf",
                "short_term_repayment",
            ),
            rows=(42,),
            kind="series",
            coupled=False,
        ),
    ),
)
