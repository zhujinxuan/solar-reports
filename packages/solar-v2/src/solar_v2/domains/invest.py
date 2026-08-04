"""InvestmentPlanning -- 投资计划与资金筹措表 (construction-period table).

Construction-period domain with 4 period columns (建设期1/建设期2/运营年1/运营年2).
No coupled items; no year-axis frame (period-axis instead).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from solar_v2.schema import DomainSchema, ItemSchema

if TYPE_CHECKING:
    from solar_v2.domains.cost import CostStatics
    from solar_v2.domains.params import ParamsCore

# ── Period axis ──────────────────────────────────────────────────────────────

PERIODS: tuple[str, str, str, str] = ("build1", "build2", "oper1", "oper2")
"""Four construction-period labels matching the workbook D/E/F/G columns."""


# ── Result types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InvestScalars:
    """Aux block outputs (rows 24-32 B-column) and key downstream-facing totals."""

    # Aux block B-column single-cell values
    aux_total_investment: float  # B24 = J32 (total investment, aux block)
    aux_dynamic_investment: float  # B25 = J31 (dynamic investment, aux block)
    aux_static_investment: float  # B26 = J30 (static investment, aux block)
    aux_equity: float  # B27 = J32 * equity_ratio (equity capital, aux block)
    aux_loan_balance: float  # B28 = B26 - B27 (loan balance, aux block)

    # Annual split totals (rows 29-32 B-column = sums over C/F/G period columns)
    static_split_total: float  # B29
    equity_split_total: float  # B30
    loan_split_total: float  # B31
    interest_split_total: float  # B32

    # Downstream-facing totals (C / H column aggregates used by other domains)
    total_investment_total: float  # C5 = C6 + C7 + C8
    dynamic_investment_total: float  # C9 = C6 + C7
    static_investment_total: float  # = B26 = unit_static * capacity
    construction_interest_total: float  # C7 (H7 = C32 + F32 + G32)
    working_capital_total: float  # C8 = params.working_capital_total
    equity_capital_total: float  # C11 = C12 + C13
    long_term_loan_total: float  # C15 = long_term_loan[oper1] (PMT pv for debt)
    working_capital_loan_total: float  # C18 = wc_total * (1 - equity_ratio)

    # Fixed asset original value (cost D29 origin equivalent)
    fixed_asset_original: float

    # Aux-block given echoes (J-column formula cells)
    aux_construction_rate: float  # 建设期利率 = 长期利率 × 建设月数/12
    aux_equity_ratio_echo: float  # 资本金比例回显
    aux_working_capital_echo: float  # 流动资金回显
    equity_ratio_check: float  # 资本金占总投比 = equity / total investment


@dataclass(frozen=True)
class InvestIntermediates:
    """Intermediate results from the aux-block inversion and construction schedule.

    Replaces the naked dict previously returned by ``_compute_intermediates``.
    All fields are typed; the orchestrator accesses them by attribute.
    """

    # ── Period-series tuples (4 values: build1, build2, oper1, oper2) ──
    static_ratios: tuple[float, ...]
    eq_ratio_sched: tuple[float, ...]
    total_inv: tuple[float, ...]
    const_investment: tuple[float, ...]
    const_interest: tuple[float, ...]
    wc_values: tuple[float, ...]
    dynamic_inv: tuple[float, ...]
    funding_vals: tuple[float, ...]
    equity_cap: tuple[float, ...]
    eq_construction: tuple[float, ...]
    eq_wc_values: tuple[float, ...]
    total_loan_vals: tuple[float, ...]
    lt_loan: tuple[float, ...]
    loan_prin: tuple[float, ...]
    loan_int: tuple[float, ...]
    wc_loan: tuple[float, ...]
    st_loan: tuple[float, ...]
    other_funding_vals: tuple[float, ...]

    # ── Annual maps (period-keyed dicts) ──
    annual_static: dict[str, float]
    annual_equity: dict[str, float]
    annual_loan: dict[str, float]
    annual_interest_map: dict[str, float]

    # ── Scalar intermediates ──
    total_aux: float
    dynamic_aux: float
    static_total: float
    equity_aux: float
    loan_aux: float
    static_split_total: float
    equity_split_total: float
    loan_split_total: float
    interest_split_total: float
    total_inv_c5: float
    dynamic_total: float
    const_interest_h7: float
    equity_cap_c11: float
    lt_loan_c15: float
    wc_loan_total: float
    fixed_asset_orig: float


@dataclass(frozen=True)
class InvestResult:
    """Investment planning result: period-keyed frame + aux scalars."""

    periods: tuple[str, ...]  # PERIODS
    frame: pl.DataFrame  # cols: period (str), then one col per series item key
    scalars: InvestScalars


# ── Compute helpers ──────────────────────────────────────────────────────────


def _build_period_series(values: tuple[float, ...]) -> pl.Series:
    """Build a 4-element series for the four construction periods."""
    return pl.Series([values[0], values[1], values[2], values[3]], dtype=pl.Float64)


def _compute_intermediates(
    params: ParamsCore,
    cost_statics: CostStatics,
) -> InvestIntermediates:
    """Compute all intermediate values for the invest sheet."""
    # ── Givens from params ──
    equity_ratio = params.equity_ratio
    construction_months = params.construction_months
    loan_rate = params.loan_rate_long
    wc_total = params.working_capital_total
    static_total = params.static_investment_total
    ratio_b1 = params.aux_static_ratio_build1
    ratio_b2 = params.aux_static_ratio_build2
    ratio_op1 = params.aux_static_ratio_operate

    # Construction interest rate: loan_rate * construction_months / 12
    # (half-year convention for 6-month construction)
    const_rate = loan_rate * construction_months / 12.0

    # ── Static investment ratio schedule (row 3) ──
    static_ratios = (ratio_b1, ratio_b2, ratio_op1, 0.0)

    # ── Working capital (row 8): D/E/F=0, G=total ──
    # 流动资金 per period = equity_for_wc + wc_loan per period
    # Workbook convention: equity share of WC = 0%, loan share = 100%
    # (old invest.py line 53-54: c13 = total * 0.0, c18 = total * 1.0)
    wc_equity_share = 0.0
    wc_loan_share = 1.0
    wc_values = (0.0, 0.0, 0.0, wc_total)

    # ── Equity for working capital (row 13): all zeros ──
    eq_wc_values = (0.0, 0.0, 0.0, wc_total * wc_equity_share)

    # ── Working capital loan (row 18): D/E/F=0, G=wc_total ──
    wc_loan_per_period = (0.0, 0.0, 0.0, wc_total * wc_loan_share)

    # ── Aux block (rows 24-32) ──
    # Defined-name analog: aa=ratio_b1, ab=ratio_b2, ac=ratio_op1, cc=wc_total
    # J26 = const_rate, J27 = equity_ratio, J30 = static_total
    # J28/J28 = aa/ab/ac ratios, J29 = cc

    # J31 动态投资: closed-form inversion of the workbook's circular reference
    # (old invest.py lines ~123-128)
    growth = (
        ratio_b1 * (1.0 + const_rate) ** 2
        + ratio_b2 * (1.0 + const_rate)
        + ratio_op1
    )
    numerator = static_total * (2.0 + const_rate) * growth + 2.0 * wc_total
    denominator = (
        equity_ratio * (2.0 + const_rate) * growth + 2.0 * (1.0 - equity_ratio)
    )
    dynamic_aux = numerator / denominator - wc_total

    # J32 总投资
    total_aux = dynamic_aux + wc_total

    # B27 资本金
    equity_aux = total_aux * equity_ratio

    # B28 贷款
    loan_aux = static_total - equity_aux

    # Annual splits (rows 29-32): workbook columns C(build1), F(oper1), G(oper2)
    # Column mapping: C -> frame period "build1", F -> "oper1", G -> "oper2"
    # Row 29: 年度静态投资 = static_total * ratio per active period
    annual_static = {
        "build1": static_total * ratio_b1,   # C column
        "oper1": static_total * ratio_b2,     # F column
        "oper2": static_total * ratio_op1,    # G column
    }
    # Row 30: 年度资本金 = equity_aux * ratio per active period
    ratio_of = {"build1": ratio_b1, "oper1": ratio_b2, "oper2": ratio_op1}
    annual_equity = {k: equity_aux * ratio_of[k] for k in annual_static}
    # Row 31: 年度贷款 = annual_static - annual_equity per period
    annual_loan = {
        k: annual_static[k] - annual_equity[k] for k in annual_static
    }
    # Row 32: 年度利息 (construction interest by period -- cumulative half-year)
    # C32 = C31/2 * const_rate
    # F32 = (F31/2 + C32 + C31) * rate
    # G32 = (G31/2 + C31 + F31 + C32 + F32) * rate
    # (old invest.py lines ~136-143)
    c32 = annual_loan.get("build1", 0.0) / 2.0 * const_rate
    f32 = (
        annual_loan.get("oper1", 0.0) / 2.0 + c32 + annual_loan.get("build1", 0.0)
    ) * const_rate
    g32 = (
        annual_loan.get("oper2", 0.0) / 2.0
        + annual_loan.get("build1", 0.0)
        + annual_loan.get("oper1", 0.0)
        + c32
        + f32
    ) * const_rate
    annual_interest_map = {"build1": c32, "oper1": f32, "oper2": g32}

    # Total sums for rows 29-32
    static_split_total = sum(annual_static.values())
    equity_split_total = sum(annual_equity.values())
    loan_split_total = sum(annual_loan.values())
    interest_split_total = sum(annual_interest_map.values())
    # ── Row 7 建设期利息: echoes of row 32 per construction period ──
    # Row 7 freeze: H7 = C32 + F32 + G32 (explicit 3-cell sum, not D+E+F+G)
    # (old invest.py line 178)
    const_interest_h7 = interest_split_total
    const_interest = (
        annual_interest_map.get("build1", 0.0),  # D7 = C32
        annual_interest_map.get("oper1", 0.0),   # E7 = F32 (aux "build2" allocation)
        annual_interest_map.get("oper2", 0.0),   # F7 = G32 (aux "oper1" allocation)
        0.0,  # G7 = 0
    )

    # ── Row 12 自有资金用于建设投资: B27 split by row-3 ratios ──
    eq_construction = (
        equity_aux * ratio_b1,
        equity_aux * ratio_b2,
        equity_aux * ratio_op1,
        0.0,
    )

    # -- Row 6 建设投资: split of static_total by row-3 ratios --
    # G period = cost land construction cost (0 in default)
    # (old invest.py lines 216-230)
    land_g6 = cost_statics.construction_land_rent
    const_investment = (
        static_total * ratio_b1,  # D6
        static_total * ratio_b2,  # E6
        static_total * ratio_op1,  # F6
        land_g6,  # G6 = cost land cost
    )
    const_investment_c6 = static_total  # C6 total

    # ── Row 9 动态投资: C9 = C6 + C7 ──
    dynamic_total = const_investment_c6 + const_interest_h7

    # ── Row 5 总投资: sum of rows 6+7+8 per period ──
    total_inv = tuple(
        const_investment[i] + const_interest[i] + wc_values[i]
        for i in range(4)
    )
    total_inv_c5 = const_investment_c6 + const_interest_h7 + wc_total

    # ── Row 11 自有资金: rows 12+13 per period ──
    equity_cap = tuple(
        eq_construction[i] + eq_wc_values[i] for i in range(4)
    )
    equity_cap_c11 = equity_aux + eq_wc_values[3]  # C12 + C13

    # ── Row 4 资本金使用比例: per-period row 11 / C11 ──
    eq_ratio_sched = tuple(
        equity_cap[i] / equity_cap_c11 if equity_cap_c11 != 0.0 else 0.0
        for i in range(4)
    )

    # ── Row 16 长期借款本金: echoes of row 31; G16 = G6 - G12 ──
    loan_prin = (
        annual_loan.get("build1", 0.0),  # D16 = C31
        annual_loan.get("oper1", 0.0),   # E16 = F31 (aux "build2")
        annual_loan.get("oper2", 0.0),   # F16 = G31 (aux "oper1")
        land_g6 - eq_construction[3],     # G16 = G6 - G12
    )

    # ── Row 17 长期借款利息 ──
    loan_int = (
        annual_interest_map.get("build1", 0.0),  # D17 = C32
        annual_interest_map.get("oper1", 0.0),   # E17 = F32 (aux "build2")
        annual_interest_map.get("oper2", 0.0),   # F17 = G32 (aux "oper1")
        0.0,  # G17 = 0
    )

    # ── Row 15 长期借款(含利息): 16+17 per period ──
    lt_loan = tuple(
        loan_prin[i] + loan_int[i] for i in range(4)
    )
    # C15 = oper1 long_term_loan = F15 in workbook (used as PMT pv by debt)
    lt_loan_c15 = lt_loan[2]  # oper1 period

    # ── Row 19 短期贷款: only cumulative H19 = 0 ──
    st_loan = (0.0, 0.0, 0.0, 0.0)

    # ── Row 14 借款: sum of 15-19; F14 = F15 + F18 (only 15 and 18 have non-zero in F)
    # (old invest.py lines 320-329)
    total_loan_vals = tuple(
        lt_loan[i] + wc_loan_per_period[i] + st_loan[i]
        for i in range(4)
    )
    # F14 = F15 + F18 (only non-zero contributors in period oper1)
    # This is already captured by the sum above since F16+F17=F15 and F19=0.

    # ── Row 10 资金筹措: row 11 + row 14; H10 += D17 (old code)
    # (old invest.py lines 332-341)
    funding_vals = tuple(
        equity_cap[i] + total_loan_vals[i] for i in range(4)
    )

    # ── Row 20 其他: G20 = G7, H20 = SUM (old invest.py lines 200-204)
    other_funding_vals = (0.0, 0.0, 0.0, const_interest[3])  # G20 = G7

    # -- Fixed asset original = C9 - deductible_vat - land_rent_E55 --
    # D29 = dynamic_investment - deductible_vat - land_rent_E55
    # Fed into cost's fixed_asset_original computation.
    fixed_asset_orig = (
        dynamic_total
        - cost_statics.deductible_vat
        - cost_statics.land_rent_initial
    )
    dynamic_inv_tuple = (
        const_investment[0] + const_interest[0],
        const_investment[1] + const_interest[1],
        const_investment[2] + const_interest[2],
        const_investment[3] + const_interest[3],
    )
    return InvestIntermediates(
        static_ratios=static_ratios,
        eq_ratio_sched=eq_ratio_sched,
        total_inv=total_inv,
        const_investment=const_investment,
        const_interest=const_interest,
        wc_values=wc_values,
        dynamic_inv=dynamic_inv_tuple,
        funding_vals=funding_vals,
        equity_cap=equity_cap,
        eq_construction=eq_construction,
        eq_wc_values=eq_wc_values,
        total_loan_vals=total_loan_vals,
        lt_loan=lt_loan,
        loan_prin=loan_prin,
        loan_int=loan_int,
        wc_loan=wc_loan_per_period,
        st_loan=st_loan,
        other_funding_vals=other_funding_vals,
        annual_static=annual_static,
        annual_equity=annual_equity,
        annual_loan=annual_loan,
        annual_interest_map=annual_interest_map,
        total_aux=total_aux,
        dynamic_aux=dynamic_aux,
        static_total=static_total,
        equity_aux=equity_aux,
        loan_aux=loan_aux,
        static_split_total=static_split_total,
        equity_split_total=equity_split_total,
        loan_split_total=loan_split_total,
        interest_split_total=interest_split_total,
        total_inv_c5=total_inv_c5,
        dynamic_total=dynamic_total,
        const_interest_h7=const_interest_h7,
        equity_cap_c11=equity_cap_c11,
        lt_loan_c15=lt_loan_c15,
        wc_loan_total=wc_loan_per_period[3],
        fixed_asset_orig=fixed_asset_orig,
    )


# ── Item compute functions ───────────────────────────────────────────────────
#
# Each non-coupled item key has exactly one compute_<key> function.
# They accept ParamsCore + CostStatics and return their value.
# compute_invest_plan is the orchestrator that calls these in dependency order
# and assembles the result.


def _static_ratio_series(params: ParamsCore) -> pl.Series:
    vals = (
        params.aux_static_ratio_build1,
        params.aux_static_ratio_build2,
        params.aux_static_ratio_operate,
        0.0,
    )
    return _build_period_series(vals)


def compute_static_investment_ratio(params: ParamsCore) -> pl.Series:
    """Row 3: 静态投资完成比例 -- per-period allocation of EPC contract price."""
    return _static_ratio_series(params)


def compute_equity_ratio_schedule(
    equity_cap_c11: float,
    equity_cap_vals: tuple[float, ...],
) -> pl.Series:
    """Row 4: 资本金使用比例 -- per-period equity / total equity."""
    vals = tuple(
        v / equity_cap_c11 if equity_cap_c11 != 0.0 else 0.0
        for v in equity_cap_vals
    )
    return _build_period_series(vals)


def compute_total_investment(
    const_investment: tuple[float, ...],
    const_interest: tuple[float, ...],
    wc_values: tuple[float, ...],
) -> pl.Series:
    """Row 5: 总投资 = construction + interest + working_capital."""
    vals = tuple(
        const_investment[i] + const_interest[i] + wc_values[i] for i in range(4)
    )
    return _build_period_series(vals)


def compute_construction_investment(
    params: ParamsCore,
    cost_statics: CostStatics,
) -> pl.Series:
    """Row 6: 建设投资 -- static investment split by ratios; G6 = cost land cost."""
    static_total = params.static_investment_total
    ratios = (
        params.aux_static_ratio_build1,
        params.aux_static_ratio_build2,
        params.aux_static_ratio_operate,
    )
    vals = (
        static_total * ratios[0],
        static_total * ratios[1],
        static_total * ratios[2],
        cost_statics.construction_land_rent,
    )
    return _build_period_series(vals)


def compute_construction_interest(
    annual_interest_map: dict[str, float],
) -> pl.Series:
    """Row 7: 建设期利息 -- echoes of aux block annual_interest per period.

    Irregularity: H7 = C32+F32+G32 (explicit 3-cell sum, not D+E+F+G).
    Frame mapping: build1→C(D7), oper1→F(E7), oper2→G(F7).
    """
    vals = (
        annual_interest_map.get("build1", 0.0),  # D7 = C32
        annual_interest_map.get("oper1", 0.0),   # E7 = F32
        annual_interest_map.get("oper2", 0.0),   # F7 = G32
        0.0,  # G7 = 0
    )
    return _build_period_series(vals)


def compute_working_capital(params: ParamsCore) -> pl.Series:
    """Row 8: 流动资金 -- per-period split of working_capital_total."""
    vals = (0.0, 0.0, 0.0, params.working_capital_total)
    return _build_period_series(vals)


def compute_dynamic_investment(
    const_investment: tuple[float, ...],
    const_interest: tuple[float, ...],
) -> pl.Series:
    """Row 9: 动态投资 -- construction_investment + construction_interest per period."""
    vals = tuple(
        const_investment[i] + const_interest[i] for i in range(4)
    )
    return _build_period_series(vals)


def compute_funding_sources(
    equity_cap: tuple[float, ...],
    total_loan_vals: tuple[float, ...],
) -> pl.Series:
    """Row 10: 资金筹措 -- equity_capital + total_loan per period."""
    vals = tuple(
        equity_cap[i] + total_loan_vals[i] for i in range(4)
    )
    return _build_period_series(vals)


def compute_equity_capital(
    eq_construction: tuple[float, ...],
    eq_wc_values: tuple[float, ...],
) -> pl.Series:
    """Row 11: 自有资金 -- equity_for_construction + equity_for_working_capital."""
    vals = tuple(
        eq_construction[i] + eq_wc_values[i] for i in range(4)
    )
    return _build_period_series(vals)


def compute_equity_for_construction(
    equity_aux: float,
    params: ParamsCore,
) -> pl.Series:
    """Row 12: 自有资金用于建设投资 -- B27 split by static investment ratios."""
    ratios = (
        params.aux_static_ratio_build1,
        params.aux_static_ratio_build2,
        params.aux_static_ratio_operate,
    )
    vals = (
        equity_aux * ratios[0],
        equity_aux * ratios[1],
        equity_aux * ratios[2],
        0.0,
    )
    return _build_period_series(vals)


def compute_equity_for_working_capital() -> pl.Series:
    """Row 13: 自有资金用于流动资金 -- 0 (workbook convention: 0% equity share)."""
    vals = (0.0, 0.0, 0.0, 0.0)
    return _build_period_series(vals)


def compute_total_loan(
    lt_loan: tuple[float, ...],
    wc_loan: tuple[float, ...],
    st_loan: tuple[float, ...],
) -> pl.Series:
    """Row 14: 借款 -- long_term_loan + working_capital_loan + short_term_loan."""
    vals = tuple(
        lt_loan[i] + wc_loan[i] + st_loan[i] for i in range(4)
    )
    return _build_period_series(vals)


def compute_long_term_loan(
    loan_prin: tuple[float, ...],
    loan_int: tuple[float, ...],
) -> pl.Series:
    """Row 15: 长期借款(含利息)-- principal + interest per period.

    C15 = oper1 long_term_loan (used as PMT pv by debt domain).
    """
    vals = tuple(
        loan_prin[i] + loan_int[i] for i in range(4)
    )
    return _build_period_series(vals)


def compute_long_term_loan_principal(
    annual_loan_map: dict[str, float],
    land_g6: float,
    eq_construction_g: float,
) -> pl.Series:
    """Row 16: 长期借款本金 -- echoes of row 31; G16 = G6 - G12.

    Frame mapping: build1→C(D16), oper1→F(E16), oper2→G(F16).
    """
    vals = (
        annual_loan_map.get("build1", 0.0),  # D16 = C31
        annual_loan_map.get("oper1", 0.0),   # E16 = F31
        annual_loan_map.get("oper2", 0.0),   # F16 = G31
        land_g6 - eq_construction_g,          # G16 = G6 - G12
    )
    return _build_period_series(vals)


def compute_long_term_loan_interest(
    annual_interest_map: dict[str, float],
) -> pl.Series:
    """Row 17: 长期借款利息 -- echoes of row 32 per period.

    Frame mapping: build1→C(D17), oper1→F(E17), oper2→G(F17).
    """
    vals = (
        annual_interest_map.get("build1", 0.0),  # D17 = C32
        annual_interest_map.get("oper1", 0.0),   # E17 = F32
        annual_interest_map.get("oper2", 0.0),   # F17 = G32
        0.0,  # G17 = 0
    )
    return _build_period_series(vals)


def compute_working_capital_loan(params: ParamsCore) -> pl.Series:
    """Row 18: 流动资金借款 -- wc_total (100% loan share, workbook convention)."""
    wc_loan_val = params.working_capital_total
    vals = (0.0, 0.0, 0.0, wc_loan_val)
    return _build_period_series(vals)
def compute_short_term_loan() -> pl.Series:
    """Row 19: 其他短期贷款 -- all zeros (only cumulative H19 exists, = 0)."""
    vals = (0.0, 0.0, 0.0, 0.0)
    return _build_period_series(vals)


def compute_other_funding(
    const_interest: tuple[float, ...],
) -> pl.Series:
    """Row 20: 其他 -- G20 = G7, H20 = SUM; all period cells are zero except G."""
    vals = (0.0, 0.0, 0.0, const_interest[3])
    return _build_period_series(vals)


def compute_annual_static_split(
    annual_static: dict[str, float],
) -> pl.Series:
    """Row 29: 年度静态投资 per workbook column mapping.

    Workbook columns: C(build1), F(oper1=ratio_b2), G(oper2=ratio_op1).
    Frame indices: 0=build1→C, 1=build2→no aux, 2=oper1→F, 3=oper2→G.
    """
    vals = (
        annual_static.get("build1", 0.0),
        0.0,
        annual_static.get("oper1", 0.0),
        annual_static.get("oper2", 0.0),
    )
    return _build_period_series(vals)


def compute_annual_equity(
    annual_equity: dict[str, float],
) -> pl.Series:
    """Row 30: 年度资本金 per workbook column mapping."""
    vals = (
        annual_equity.get("build1", 0.0),
        0.0,
        annual_equity.get("oper1", 0.0),
        annual_equity.get("oper2", 0.0),
    )
    return _build_period_series(vals)


def compute_annual_loan(
    annual_loan: dict[str, float],
) -> pl.Series:
    """Row 31: 年度贷款 per workbook column mapping."""
    vals = (
        annual_loan.get("build1", 0.0),
        0.0,
        annual_loan.get("oper1", 0.0),
        annual_loan.get("oper2", 0.0),
    )
    return _build_period_series(vals)


def compute_annual_interest(
    annual_interest_map: dict[str, float],
) -> pl.Series:
    """Row 32: 年度利息 per workbook column mapping."""
    vals = (
        annual_interest_map.get("build1", 0.0),
        0.0,
        annual_interest_map.get("oper1", 0.0),
        annual_interest_map.get("oper2", 0.0),
    )
    return _build_period_series(vals)


# ── Scalar compute functions ─────────────────────────────────────────────────


def compute_aux_total_investment(total_aux: float) -> float:
    """Row 24 B-column: 总投资 (aux block) -- J32 = dynamic_aux + working_capital."""
    return total_aux


def compute_aux_dynamic_investment(dynamic_aux: float) -> float:
    """Row 25 B-column: 动态投资 (aux block) -- J31 closed-form result."""
    return dynamic_aux


def compute_aux_static_investment(params: ParamsCore) -> float:
    """Row 26 B-column: 静态投资 (aux block) -- J30 = static_investment_total."""
    return params.static_investment_total


def compute_aux_equity(equity_aux: float) -> float:
    """Row 27 B-column: 资本金 (aux block) -- B27 = total_aux * equity_ratio."""
    return equity_aux


def compute_aux_loan_balance(
    params: ParamsCore,
    equity_aux: float,
) -> float:
    """Row 28 B-column: 贷款 (aux block) -- B28 = static_total - equity_aux."""
    return params.static_investment_total - equity_aux


# ── Orchestrator ─────────────────────────────────────────────────────────────


def compute_invest_plan(
    params: ParamsCore,
    cost_statics: CostStatics,
) -> InvestResult:
    """Compute the full investment plan (投资计划与资金筹措表).

    Stages:
    1. Aux block closed-form inversion (J31)
    2. Per-period construction schedule
    3. Funding plan assembly
    4. Frame + scalars packaging
    """
    im = _compute_intermediates(params, cost_statics)

    # ── Build frame: period column + all series items ──
    frame = pl.DataFrame({
        "period": list(PERIODS),
        "static_investment_ratio": compute_static_investment_ratio(params),
        "equity_ratio_schedule": compute_equity_ratio_schedule(
            im.equity_cap_c11, im.equity_cap,
        ),
        "total_investment": compute_total_investment(
            im.const_investment, im.const_interest, im.wc_values,
        ),
        "construction_investment": compute_construction_investment(
            params, cost_statics
        ),
        "construction_interest": compute_construction_interest(
            im.annual_interest_map
        ),
        "working_capital": compute_working_capital(params),
        "dynamic_investment": compute_dynamic_investment(
            im.const_investment, im.const_interest,
        ),
        "funding_sources": compute_funding_sources(
            im.equity_cap, im.total_loan_vals,
        ),
        "equity_capital": compute_equity_capital(
            im.eq_construction, im.eq_wc_values,
        ),
        "equity_for_construction": compute_equity_for_construction(
            im.equity_aux, params,
        ),
        "equity_for_working_capital": compute_equity_for_working_capital(),
        "total_loan": compute_total_loan(
            im.lt_loan, im.wc_loan, im.st_loan,
        ),
        "long_term_loan": compute_long_term_loan(
            im.loan_prin, im.loan_int,
        ),
        "long_term_loan_principal": compute_long_term_loan_principal(
            im.annual_loan,
            cost_statics.construction_land_rent,
            im.eq_construction[3],
        ),
        "long_term_loan_interest": compute_long_term_loan_interest(
            im.annual_interest_map
        ),
        "working_capital_loan": compute_working_capital_loan(params),
        "short_term_loan": compute_short_term_loan(),
        "other_funding": compute_other_funding(im.const_interest),
        "annual_static_split": compute_annual_static_split(im.annual_static),
        "annual_equity": compute_annual_equity(im.annual_equity),
        "annual_loan": compute_annual_loan(im.annual_loan),
        "annual_interest": compute_annual_interest(im.annual_interest_map),
    })

    scalars = InvestScalars(
        aux_total_investment=im.total_aux,
        aux_dynamic_investment=im.dynamic_aux,
        aux_static_investment=im.static_total,
        aux_equity=im.equity_aux,
        aux_loan_balance=im.loan_aux,
        static_split_total=im.static_split_total,
        equity_split_total=im.equity_split_total,
        loan_split_total=im.loan_split_total,
        interest_split_total=im.interest_split_total,
        total_investment_total=im.total_inv_c5,
        dynamic_investment_total=im.dynamic_total,
        static_investment_total=im.static_total,
        construction_interest_total=im.const_interest_h7,
        working_capital_total=params.working_capital_total,
        equity_capital_total=im.equity_cap_c11,
        long_term_loan_total=im.lt_loan_c15,
        working_capital_loan_total=im.wc_loan_total,
        fixed_asset_original=im.fixed_asset_orig,
        aux_construction_rate=(
            params.inputs.loan_rate_long * params.inputs.construction_months / 12
        ),
        aux_equity_ratio_echo=params.inputs.equity_ratio,
        aux_working_capital_echo=params.working_capital_total,
        equity_ratio_check=(
            im.equity_cap_c11 / im.total_inv_c5
            if im.total_inv_c5
            else 0.0
        ),
    )

    return InvestResult(
        periods=PERIODS,
        frame=frame,
        scalars=scalars,
    )


# ── Domain schema ────────────────────────────────────────────────────────────

SCHEMA = DomainSchema(
    key="invest",
    sheet="投资计划",
    label="投资计划与资金筹措表 (Invest)",
    depends_on=("params", "cost"),
    items=(
        ItemSchema(
            key="static_investment_ratio",
            label="静态投资完成比例",
            unit="%",
            formula="per-period allocation ratio from params (row 3)",
            inputs=(),
            rows=(3,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="equity_ratio_schedule",
            label="资本金使用比例",
            unit="%",
            formula="per-period equity / total equity per construction period (row 4)",
            inputs=("equity_capital",),
            rows=(4,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="total_investment",
            label="总投资",
            unit="万元",
            formula="construction + interest + working_capital per period (row 5)",
            inputs=(
                "construction_investment",
                "construction_interest",
                "working_capital",
            ),
            rows=(5,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="construction_investment",
            label="建设投资",
            unit="万元",
            formula="static investment split by ratios; G = cost land cost (row 6)",
            inputs=(),
            rows=(6,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="construction_interest",
            label="建设期利息",
            unit="万元",
            formula="annual interest from aux per period; H7 = C32+F32+G32 (row 7)",
            inputs=("annual_interest",),
            rows=(7,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="working_capital",
            label="流动资金",
            unit="万元",
            formula="params.working_capital_total split across periods (row 8)",
            inputs=(),
            rows=(8,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="dynamic_investment",
            label="动态投资",
            unit="万元",
            formula="construction + interest per period (row 9)",
            inputs=("construction_investment", "construction_interest"),
            rows=(9,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="funding_sources",
            label="资金筹措",
            unit="万元",
            formula="equity_capital + total_loan per period (row 10)",
            inputs=("equity_capital", "total_loan"),
            rows=(10,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="equity_capital",
            label="自有资金(资本金)",
            unit="万元",
            formula="equity_for_construction + equity_for_working_capital (row 11)",
            inputs=("equity_for_construction", "equity_for_working_capital"),
            rows=(11,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="equity_for_construction",
            label="自有资金用于建设投资",
            unit="万元",
            formula="aux_equity * static_investment_ratio per period (row 12)",
            inputs=("aux_equity", "static_investment_ratio"),
            rows=(12,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="equity_for_working_capital",
            label="自有资金用于流动资金",
            unit="万元",
            formula="working_capital * equity_ratio (row 13)",
            inputs=("working_capital",),
            rows=(13,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="total_loan",
            label="借款",
            unit="万元",
            formula="long_term_loan + working_capital_loan + short_term_loan (row 14)",
            inputs=("long_term_loan", "working_capital_loan", "short_term_loan"),
            rows=(14,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="long_term_loan",
            label="长期借款(含利息)",
            unit="万元",
            formula="long_term_loan_principal + long_term_loan_interest (row 15)",
            inputs=("long_term_loan_principal", "long_term_loan_interest"),
            rows=(15,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="long_term_loan_principal",
            label="长期借款本金",
            unit="万元",
            formula="annual_loan echoes (row 16); G16 = G6 - G12",
            inputs=(
                "annual_loan",
                "construction_investment",
                "equity_for_construction",
            ),
            rows=(16,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="long_term_loan_interest",
            label="长期借款利息",
            unit="万元",
            formula="annual_interest echoes per period (row 17)",
            inputs=("annual_interest",),
            rows=(17,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="working_capital_loan",
            label="流动资金借款",
            unit="万元",
            formula="working_capital * (1 - equity_ratio) (row 18)",
            inputs=("working_capital",),
            rows=(18,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="short_term_loan",
            label="其他短期贷款",
            unit="万元",
            formula="0 (all periods); only cumulative H19 exists (row 19)",
            inputs=(),
            rows=(19,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="other_funding",
            label="其他",
            unit="万元",
            formula="G20 = G7 (construction_interest echo) (row 20)",
            inputs=("construction_interest",),
            rows=(20,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="aux_total_investment",
            label="辅助表:总投资",
            unit="万元",
            formula="total investment aux block (B24 = J32)",
            inputs=(),
            rows=(24,),
            kind="scalar",
            coupled=False,
        ),
        ItemSchema(
            key="aux_dynamic_investment",
            label="辅助表:动态投资",
            unit="万元",
            formula="dynamic investment aux block (B25 = J31, closed-form)",
            inputs=(),
            rows=(25,),
            kind="scalar",
            coupled=False,
        ),
        ItemSchema(
            key="aux_static_investment",
            label="辅助表:静态投资",
            unit="万元",
            formula="static investment aux block (B26)",
            inputs=(),
            rows=(26,),
            kind="scalar",
            coupled=False,
        ),
        ItemSchema(
            key="aux_equity",
            label="辅助表:资本金",
            unit="万元",
            formula="equity capital aux block (B27 = total_aux * equity_ratio)",
            inputs=(),
            rows=(27,),
            kind="scalar",
            coupled=False,
        ),
        ItemSchema(
            key="aux_loan_balance",
            label="辅助表:贷款",
            unit="万元",
            formula="loan balance aux block (B28 = static_total - equity_aux)",
            inputs=("aux_static_investment", "aux_equity"),
            rows=(28,),
            kind="scalar",
            coupled=False,
        ),
        ItemSchema(
            key="annual_static_split",
            label="年度静态投资",
            unit="万元",
            formula="aux_static * ratio per period (row 29)",
            inputs=("aux_static_investment", "static_investment_ratio"),
            rows=(29,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="annual_equity",
            label="年度资本金",
            unit="万元",
            formula="aux_equity * static_investment_ratio per period (row 30)",
            inputs=("aux_equity", "static_investment_ratio"),
            rows=(30,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="annual_loan",
            label="年度贷款",
            unit="万元",
            formula="annual_static_split - annual_equity per period (row 31)",
            inputs=("annual_static_split", "annual_equity"),
            rows=(31,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="annual_interest",
            label="年度利息",
            unit="万元",
            formula="cumulative half-year loan * construction_interest_rate (row 32)",
            inputs=("annual_loan",),
            rows=(32,),
            kind="series",
            coupled=False,
        ),
    ),
)
