"""Profit & Loss -- 损益表 (income statement).

Year-series implementation for the 损益 sheet. Columns:
  D, E   -- construction years (#REF! errors)
  F      -- 2020 (partial first operating year)
  G..AE  -- 25 full operating years (2021..2045)
  AF     -- totals row
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from xlsx_core.model import ErrorValue, Scalar

from solar_v2.cols import col_index, col_letters
from solar_v2.params import Params
from solar_v2.pipeline import FineStepFn, ValueView
from solar_v2.schedule import Step

StepFn = Callable[[Params, ValueView], Mapping[str, Scalar]]
SHEET = "损益"
OP_COLS = col_letters("G", 25)  # G..AE: 25 operating years
ALL_YEAR_COLS = ["F", *OP_COLS]  # F, G..AE


def _nid(col: str, row: int) -> str:
    return f"{SHEET}!{col}{row}"


def _num(view: ValueView, node_id: str) -> float:
    v = view.get(node_id)
    return float(v) if isinstance(v, (int, float)) else 0.0


# ============================================================================
# Coarse step functions (entire rows at once)
# ============================================================================

def _row4_year_labels(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 4: year labels. D4/E4 are #REF!; F..AE are sequential years."""
    _ = view
    out: dict[str, Scalar] = {}
    out[_nid("D", 4)] = ErrorValue(error="#REF!")
    out[_nid("E", 4)] = ErrorValue(error="#REF!")
    for i, col in enumerate(ALL_YEAR_COLS):
        out[_nid(col, 4)] = 2020 + i
    return out


def _row5_generation(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 5: generation = hours x degradation x load_rate x capacity."""
    _ = view
    out: dict[str, Scalar] = {}
    h = params.first_year_full_hours
    cap = params.installed_capacity_mw
    for i, col in enumerate(ALL_YEAR_COLS):
        gen = h * params.degradation_factor[i] * params.load_rate[i] * cap
        out[_nid(col, 5)] = gen
    return out


def _row13_total(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 13: =SUM(D13:AE13). All per-year cells = 0 (no other income)."""
    _ = params, view
    return {_nid("AF", 13): 0.0}


def _row20_tax_rates(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 20: tax rates. G/H/I are literal 0. J/K/L = half. M+ = full."""
    _ = view
    out: dict[str, Scalar] = {}
    full = params.income_tax_rate
    half = full / 2
    for col in OP_COLS[3:6]:  # J, K, L
        out[_nid(col, 20)] = half
    for col in OP_COLS[6:]:
        out[_nid(col, 20)] = full
    return out


def _row28_total(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 28: AF28 = SUM(D28:AE28). All cells are literal 0."""
    _ = params, view
    return {_nid("AF", 28): 0.0}


def _row36_depreciation(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 36: depreciation = 成本!D28 (single value from cost sheet)."""
    _ = params
    return {_nid("G", 36): _num(view, "成本!D28")}


# --- Tariff block: rows 47, 48, 49 ---

def _row47_guaranteed_sales(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 47: guaranteed sales = MIN(guaranteed_hours x capacity, generation)."""
    out: dict[str, Scalar] = {}
    ceiling = params.guaranteed_hours * params.installed_capacity_mw
    for col in OP_COLS:
        gen = _num(view, _nid(col, 5))
        out[_nid(col, 47)] = min(ceiling, gen)
    return out


def _row48_market_sales(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 48: market sales = generation - guaranteed."""
    _ = params
    out: dict[str, Scalar] = {}
    for col in OP_COLS:
        gen = _num(view, _nid(col, 5))
        guaranteed = _num(view, _nid(col, 47))
        out[_nid(col, 48)] = gen - guaranteed
    return out


def _row49_blended_price(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 49: blended price = guaranteed/gen x ft + market/gen x mt."""
    _ = params
    out: dict[str, Scalar] = {}
    ft = params.feed_in_tariff
    mt = params.market_tariff
    for col in OP_COLS:
        gen = _num(view, _nid(col, 5))
        guaranteed = _num(view, _nid(col, 47))
        market = _num(view, _nid(col, 48))
        price = (guaranteed / gen) * ft + (market / gen) * mt if gen > 0 else 0.0
        out[_nid(col, 49)] = price
    return out


# --- Revenue block: rows 6, 7, 8 ---

def _row6_price(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 6: on-grid price (incl VAT) = row 49 (blended price)."""
    _ = params
    out: dict[str, Scalar] = {}
    for col in OP_COLS:
        out[_nid(col, 6)] = _num(view, _nid(col, 49))
    return out


def _row7_ex_vat_price(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 7: on-grid price (excl VAT).

    G7 = G6/(1+vat), H7 = H6/(1+vat), I+ = H7 frozen.
    """
    _ = params
    out: dict[str, Scalar] = {}
    g6 = _num(view, _nid("G", 6))
    h6 = _num(view, _nid("H", 6))
    g7 = g6 / (1 + params.vat_rate)
    h7 = h6 / (1 + params.vat_rate)
    out[_nid("G", 7)] = g7
    out[_nid("H", 7)] = h7
    for col in OP_COLS[2:]:
        out[_nid(col, 7)] = h7
    return out


def _row8_sales_revenue(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 8: sales revenue = generation x ex-VAT price."""
    _ = params
    out: dict[str, Scalar] = {}
    total = 0.0
    for col in OP_COLS:
        gen = _num(view, _nid(col, 5))
        price = _num(view, _nid(col, 7))
        rev = gen * price
        out[_nid(col, 8)] = rev
        total += rev
    out[_nid("AF", 8)] = total
    return out


# --- VAT block: rows 37, 38, 39, 40, 41, 10, 11, 9, 12 ---

def _row37_output_vat(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 37: output VAT = row 8 x vat_rate."""
    _ = params
    out: dict[str, Scalar] = {}
    for col in OP_COLS:
        rev = _num(view, _nid(col, 8))
        out[_nid(col, 37)] = rev * params.vat_rate
    return out


def _row38_vat_credit_balance(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 38: input VAT credit running balance."""
    _ = params
    out: dict[str, Scalar] = {}
    pool = _num(view, _nid("G", 36))
    prev_balance = pool
    for col in OP_COLS:
        output_vat = _num(view, _nid(col, 37))
        if col == "G":
            balance = pool - output_vat
        else:
            balance = max(prev_balance - output_vat, 0.0)
        out[_nid(col, 38)] = balance
        prev_balance = balance
    return out


def _row39_vat_credit_used(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 39: actual VAT credit used this year."""
    _ = params
    out: dict[str, Scalar] = {}
    out[_nid("G", 39)] = _num(view, _nid("G", 37))
    for i, col in enumerate(OP_COLS[1:], 1):
        prev_balance = _num(view, _nid(OP_COLS[i - 1], 38))
        output_vat = _num(view, _nid(col, 37))
        out[_nid(col, 39)] = min(output_vat, prev_balance)
    return out


def _row40_vat_payable(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 40: VAT payable. G/H: (37-39)/2, I+: 37-39."""
    _ = params
    out: dict[str, Scalar] = {}
    for i, col in enumerate(OP_COLS):
        vat_out = _num(view, _nid(col, 37))
        credit = _num(view, _nid(col, 39))
        diff = vat_out - credit
        out[_nid(col, 40)] = diff / 2 if i < 2 else diff
    return out


def _row10_city_maintenance(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 10: city maintenance tax = row 40 x city_maintenance_tax_rate."""
    _ = params
    out: dict[str, Scalar] = {}
    total = 0.0
    for col in OP_COLS:
        v = _num(view, _nid(col, 40)) * params.city_maintenance_tax_rate
        out[_nid(col, 10)] = v
        total += v
    out[_nid("AF", 10)] = total
    return out


def _row11_education_surcharge(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 11: education surcharge = row 40 x education_surcharge_rate."""
    _ = params
    out: dict[str, Scalar] = {}
    total = 0.0
    for col in OP_COLS:
        v = _num(view, _nid(col, 40)) * params.education_surcharge_rate
        out[_nid(col, 11)] = v
        total += v
    out[_nid("AF", 11)] = total
    return out


def _row9_vat_surcharge_total(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 9: VAT surcharges = row 10 + row 11."""
    _ = params
    out: dict[str, Scalar] = {}
    total = 0.0
    for col in OP_COLS:
        v = _num(view, _nid(col, 10)) + _num(view, _nid(col, 11))
        out[_nid(col, 9)] = v
        total += v
    out[_nid("AF", 9)] = total
    return out


def _row41_surcharge_base(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 41: surcharge base = (row 37 - row 39) / 2 (always half)."""
    _ = params
    out: dict[str, Scalar] = {}
    for col in OP_COLS:
        vat_out = _num(view, _nid(col, 37))
        credit = _num(view, _nid(col, 39))
        out[_nid(col, 41)] = (vat_out - credit) / 2
    return out


def _row12_vat_refund(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 12: VAT refund (dead branch, all years > 2020 -> 0)."""
    _ = params
    out: dict[str, Scalar] = {}
    for col in OP_COLS:
        out[_nid(col, 12)] = 0.0
    out[_nid("AF", 12)] = 0.0
    return out


def _row32_dividend(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 32: dividend = 财务计划!E31 (cross-sheet)."""
    _ = params
    out: dict[str, Scalar] = {}
    fp_cols = col_letters("E", 25)
    for i, col in enumerate(OP_COLS):
        out[_nid(col, 32)] = _num(view, f"财务计划!{fp_cols[i]}31")
    return out


def _row33_undistributed_profit(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 33: undistributed = dist - dividend + IF(p<0, p, row22)."""
    _ = params
    out: dict[str, Scalar] = {}
    for col in OP_COLS:
        dist = _num(view, _nid(col, 29))
        dividend = _num(view, _nid(col, 32))
        profit = _num(view, _nid(col, 15))
        r22 = _num(view, _nid(col, 22))
        adj = profit if profit < 0 else r22
        out[_nid(col, 33)] = dist - dividend + adj
    return out


def _row43_adjusted_profit(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 43: adjusted profit = net + cost_E13*0.75 - bs_D13*wacc."""
    _ = params
    out: dict[str, Scalar] = {}
    cost_cols = col_letters("E", 25)
    bs_cols = col_letters("D", 25)
    equity_cost = _num(view, _nid("G", 44))  # 0.044
    loan_rate = params.loan_rate_long

    for i, col in enumerate(OP_COLS):
        net = _num(view, _nid(col, 26))
        cost_13 = _num(view, f"成本!{cost_cols[i]}13")
        bs_13 = _num(view, f"资产负债!{bs_cols[i]}13")
        bs_23 = _num(view, f"资产负债!{bs_cols[i]}23")
        wacc = bs_23 * loan_rate + (1 - bs_23) * equity_cost
        adj = net + cost_13 * 0.75 - bs_13 * wacc
        out[_nid(col, 43)] = adj
    return out


# ============================================================================
# Fine step functions (per-column, rows 14-29)
# ============================================================================

def _prev_col(col: str) -> str:
    """Previous column letter, e.g. 'H'->'G', 'AA'->'Z'."""
    return col_letters("A", col_index(col))[-1]


def _col_idx(col: str) -> int:
    """Index into OP_COLS (0 for G, 1 for H, ...)."""
    return OP_COLS.index(col)


def _row14_cost_col(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    """Row 14: total cost = 成本!E21 for column G, etc."""
    _ = params
    cost_cols = col_letters("E", 25)
    i = _col_idx(col)
    return {_nid(col, 14): _num(view, f"成本!{cost_cols[i]}21")}


def _row14_cost_af(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    """Row 14 AF: SUM(G14:AE14)."""
    _ = params
    total = sum(_num(view, _nid(c, 14)) for c in OP_COLS)
    return {_nid("AF", 14): total}


def _row15_profit_col(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    _ = params
    rev = _num(view, _nid(col, 8))
    vat_sur = _num(view, _nid(col, 9))
    cost = _num(view, _nid(col, 14))
    refund = _num(view, _nid(col, 12))
    return {_nid(col, 15): rev - vat_sur - cost + refund}


def _row15_profit_af(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    """Row 15 AF: SUM(G15:AE15)."""
    _ = params
    total = sum(_num(view, _nid(c, 15)) for c in OP_COLS)
    return {_nid("AF", 15): total}


def _row22_loss_comp_col(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    """Row 22: loss compensation = IF(p<0,0, IF(prev_cum>0,0, MIN(p, -prev_cum)))."""
    _ = params
    p = _num(view, _nid(col, 15))
    if col == "G":
        prev_cum = _num(view, _nid("F", 16))
    else:
        prev_cum = _num(view, _nid(_prev_col(col), 16))
    r22 = 0.0 if p < 0 or prev_cum > 0 else min(p, -prev_cum)
    return {_nid(col, 22): r22}


def _row21_tax_col(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    """Row 21: income tax = IF(p<0, 0, (p - r22) * tax_rate)."""
    _ = params
    p = _num(view, _nid(col, 15))
    r22 = _num(view, _nid(col, 22))
    rate = _num(view, _nid(col, 20))
    r21 = 0.0 if p < 0 else (p - r22) * rate
    return {_nid(col, 21): r21}


def _row21_tax_af(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    """Row 21 AF: SUM(D21:AE21)."""
    _ = params
    total = sum(_num(view, _nid(c, 21)) for c in OP_COLS)
    return {_nid("AF", 21): total}


def _row23_loss_col(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    """Row 23: loss = IF(p < 0, -p, 0)."""
    _ = params
    p = _num(view, _nid(col, 15))
    return {_nid(col, 23): -p if p < 0 else 0.0}


def _row25_tax_echo_col(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    """Row 25: = row 21 (echo)."""
    _ = params
    return {_nid(col, 25): _num(view, _nid(col, 21))}


def _row24_loss_carry_col(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    """Row 24: loss carry-forward compensation (starts at L).

    Formula: IF(cum_loss > cum_r22 + cum_r24, cum_loss - (cum_r22 + cum_r24), 0)
    where cum_* means SUM from G to current column.
    """
    _ = params
    idx = _col_idx(col)
    if idx < 5:  # Shouldn't be called for G..K (row 24 starts at L)
        return {_nid(col, 24): 0.0}
    cum_loss = sum(_num(view, _nid(OP_COLS[i], 23)) for i in range(idx + 1))
    cum_r22 = sum(_num(view, _nid(OP_COLS[i], 22)) for i in range(idx + 1))
    cum_r24 = sum(_num(view, _nid(OP_COLS[i], 24)) for i in range(5, idx))
    total_comp = cum_r22 + cum_r24
    return {_nid(col, 24): cum_loss - total_comp if cum_loss > total_comp else 0.0}


def _row16_cum_profit_col(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    """Row 16: cumulative profit = p - r25 + r24 + prev_cum."""
    _ = params
    p = _num(view, _nid(col, 15))
    r25 = _num(view, _nid(col, 25))
    r24 = _num(view, _nid(col, 24)) if _col_idx(col) >= 5 else 0.0
    if col == "G":
        prev_cum = _num(view, _nid("F", 16))
    else:
        prev_cum = _num(view, _nid(_prev_col(col), 16))
    cum = p - r25 + r24 + prev_cum
    return {_nid(col, 16): cum}


def _row16_cum_profit_af(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    """Row 16 AF: MIN(G16:AE16)."""
    _ = params
    return {_nid("AF", 16): min(_num(view, _nid(c, 16)) for c in OP_COLS)}


def _row26_net_profit_col(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    """Row 26: net profit = IF(p <= 0, 0, p - r22 - r25)."""
    _ = params
    p = _num(view, _nid(col, 15))
    r22 = _num(view, _nid(col, 22))
    r25 = _num(view, _nid(col, 25))
    net = 0.0 if p <= 0 else p - r22 - r25
    return {_nid(col, 26): net}


def _row26_net_profit_af(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    """Row 26 AF: SUM(D26:AE26)."""
    _ = params
    total = sum(_num(view, _nid(c, 26)) for c in OP_COLS)
    return {_nid("AF", 26): total}


def _row27_surplus_col(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    """Row 27: surplus reserve = IF(cum<=0, 0, net * ratio)."""
    _ = params
    cum = _num(view, _nid(col, 16))
    net = _num(view, _nid(col, 26))
    reserve = 0.0 if cum <= 0 else net * params.surplus_reserve_ratio
    return {_nid(col, 27): reserve}


def _row27_surplus_af(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    """Row 27 AF: SUM(D27:AE27)."""
    _ = params
    total = sum(_num(view, _nid(c, 27)) for c in OP_COLS)
    return {_nid("AF", 27): total}


def _row29_distributable_col(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    """Row 29: distributable profit = IF(cum<=0, 0, net - reserve)."""
    _ = params
    cum = _num(view, _nid(col, 16))
    net = _num(view, _nid(col, 26))
    reserve = _num(view, _nid(col, 27))
    dist = 0.0 if cum <= 0 else net - reserve
    return {_nid(col, 29): dist}


def _row29_distributable_af(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    """Row 29 AF: SUM(D29:AE29)."""
    _ = params
    total = sum(_num(view, _nid(c, 29)) for c in OP_COLS)
    return {_nid("AF", 29): total}


# ============================================================================
# Dispatch helpers — route to column vs AF
# ============================================================================

def _make_fine_dispatch(
    col_fn: Callable[[Params, ValueView, str], Mapping[str, Scalar]],
    af_fn: Callable[[Params, ValueView, str], Mapping[str, Scalar]] | None = None,
) -> FineStepFn:
    """Return a FineStepFn that dispatches on col: if AF uses af_fn."""
    def dispatch(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
        if col == "AF" and af_fn is not None:
            return af_fn(params, view, col)
        return col_fn(params, view, col)
    return dispatch


# ============================================================================
# Registries
# ============================================================================

UNITS: dict[Step, StepFn] = {
    ("损益", 4): _row4_year_labels,
    ("损益", 5): _row5_generation,
    ("损益", 13): _row13_total,
    ("损益", 20): _row20_tax_rates,
    ("损益", 28): _row28_total,
    ("损益", 36): _row36_depreciation,
    ("损益", 47): _row47_guaranteed_sales,
    ("损益", 48): _row48_market_sales,
    ("损益", 49): _row49_blended_price,
    ("损益", 6): _row6_price,
    ("损益", 7): _row7_ex_vat_price,
    ("损益", 8): _row8_sales_revenue,
    ("损益", 37): _row37_output_vat,
    ("损益", 38): _row38_vat_credit_balance,
    ("损益", 39): _row39_vat_credit_used,
    ("损益", 40): _row40_vat_payable,
    ("损益", 10): _row10_city_maintenance,
    ("损益", 11): _row11_education_surcharge,
    ("损益", 9): _row9_vat_surcharge_total,
    ("损益", 41): _row41_surcharge_base,
    ("损益", 12): _row12_vat_refund,
    ("损益", 32): _row32_dividend,
    ("损益", 33): _row33_undistributed_profit,
    ("损益", 43): _row43_adjusted_profit,
}

UNITS_FINE: dict[tuple[str, int], FineStepFn] = {
    ("损益", 14): _make_fine_dispatch(_row14_cost_col, _row14_cost_af),
    ("损益", 15): _make_fine_dispatch(_row15_profit_col, _row15_profit_af),
    ("损益", 22): _make_fine_dispatch(_row22_loss_comp_col),
    ("损益", 21): _make_fine_dispatch(_row21_tax_col, _row21_tax_af),
    ("损益", 23): _make_fine_dispatch(_row23_loss_col),
    ("损益", 25): _make_fine_dispatch(_row25_tax_echo_col),
    ("损益", 24): _make_fine_dispatch(_row24_loss_carry_col),
    ("损益", 16): _make_fine_dispatch(_row16_cum_profit_col, _row16_cum_profit_af),
    ("损益", 26): _make_fine_dispatch(_row26_net_profit_col, _row26_net_profit_af),
    ("损益", 27): _make_fine_dispatch(_row27_surplus_col, _row27_surplus_af),
    ("损益", 29): _make_fine_dispatch(
        _row29_distributable_col, _row29_distributable_af
    ),
}


# ── Domain calculation schema ─────────────────────────────────────

from solar_v2.schema import DomainSchema, ItemSchema  # noqa: E402

SCHEMA = DomainSchema(
    key="pnl",
    sheet="损益",
    label="损益表 (PnL)",
    depends_on=("params", "cost", "finplan", "balance"),
    items=(
        ItemSchema(
            key="year_labels",
            label="运营年度",
            unit="-",
            formula="参数表 years row (2021..2045); D4/E4 are #REF! errors",
            inputs=("params:years",),
            rows=(4,),
        ),
        ItemSchema(
            key="power_generation",
            label="年发电量",
            unit="MWh",
            formula=(
                "installed_capacity_mw × first_year_full_hours "
                "× degradation_factor × load_rate"
            ),
            inputs=("params:installed_capacity_mw", "params:first_year_full_hours"),
            rows=(5,),
        ),
        ItemSchema(
            key="guaranteed_sales",
            label="保障利用小时售电量",
            unit="MWh",
            formula="min(guaranteed_hours × installed_capacity_mw, power_generation)",
            inputs=("power_generation", "params:guaranteed_hours"),
            rows=(47,),
        ),
        ItemSchema(
            key="market_sales",
            label="市场化售电量",
            unit="MWh",
            formula="power_generation − guaranteed_sales",
            inputs=("power_generation", "guaranteed_sales"),
            rows=(48,),
        ),
        ItemSchema(
            key="blended_price",
            label="综合上网电价(含税)",
            unit="元/kWh",
            formula=(
                "(guaranteed_sales / generation) × feed_in_tariff "
                "+ (market_sales / generation) × market_tariff"
            ),
            inputs=("guaranteed_sales", "market_sales", "params:feed_in_tariff"),
            rows=(49,),
        ),
        ItemSchema(
            key="on_grid_price_incl_vat",
            label="上网电价(含税)",
            unit="元/kWh",
            formula="blended_price",
            inputs=("blended_price",),
            rows=(6,),
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
        ),
        ItemSchema(
            key="sales_revenue",
            label="销售收入",
            unit="万元",
            formula="power_generation × on_grid_price_excl_vat",
            inputs=("power_generation", "on_grid_price_excl_vat"),
            rows=(8,),
        ),
        ItemSchema(
            key="output_vat",
            label="销项增值税",
            unit="万元",
            formula="sales_revenue × vat_rate",
            inputs=("sales_revenue", "params:vat_rate"),
            rows=(37,),
        ),
        ItemSchema(
            key="vat_credit_balance",
            label="进项税留抵余额",
            unit="万元",
            formula=(
                "max(0, deductible_vat_construction "
                "− cumulative output_vat offset)"
            ),
            inputs=("output_vat", "params:deductible_vat_construction"),
            rows=(38,),
        ),
        ItemSchema(
            key="vat_credit_used",
            label="进项税抵扣额",
            unit="万元",
            formula="min(output_vat, prior vat_credit_balance)",
            inputs=("output_vat", "vat_credit_balance"),
            rows=(39,),
        ),
        ItemSchema(
            key="vat_payable",
            label="应缴增值税",
            unit="万元",
            formula=(
                "(output_vat − vat_credit_used) "
                "— half during credit-recovery years"
            ),
            inputs=("output_vat", "vat_credit_used"),
            rows=(40,),
        ),
        ItemSchema(
            key="city_maintenance_tax",
            label="城市维护建设税",
            unit="万元",
            formula="surcharge_base × city_maintenance_tax_rate",
            inputs=("surcharge_base", "params:city_maintenance_tax_rate"),
            rows=(10,),
        ),
        ItemSchema(
            key="education_surcharge",
            label="教育费附加",
            unit="万元",
            formula="surcharge_base × education_surcharge_rate",
            inputs=("surcharge_base", "params:education_surcharge_rate"),
            rows=(11,),
        ),
        ItemSchema(
            key="vat_surcharge_total",
            label="税金及附加合计",
            unit="万元",
            formula="city_maintenance_tax + education_surcharge",
            inputs=("city_maintenance_tax", "education_surcharge"),
            rows=(9,),
        ),
        ItemSchema(
            key="surcharge_base",
            label="附加税计税基础",
            unit="万元",
            formula="(output_vat − vat_credit_used) ÷ 2",
            inputs=("output_vat", "vat_credit_used"),
            rows=(41,),
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
        ),
        ItemSchema(
            key="total_cost",
            label="总成本费用",
            unit="万元",
            formula="cost:total_operating_cost (成本!21 row)",
            inputs=("cost:total_operating_cost",),
            rows=(14,),
        ),
        ItemSchema(
            key="total_profit",
            label="利润总额",
            unit="万元",
            formula="sales_revenue − vat_surcharge_total − total_cost + vat_refund",
            inputs=("sales_revenue", "vat_surcharge_total", "total_cost", "vat_refund"),
            rows=(15,),
        ),
        ItemSchema(
            key="cum_profit",
            label="累计利润",
            unit="万元",
            formula="cumulative total_profit; AF16 = MIN over years",
            inputs=("total_profit",),
            rows=(16,),
        ),
        ItemSchema(
            key="tax_rate_schedule",
            label="所得税税率(优惠阶梯)",
            unit="%",
            formula="years 1-3: 0, years 4-6: half, then full income_tax_rate",
            inputs=("params:income_tax_rate",),
            rows=(20,),
        ),
        ItemSchema(
            key="income_tax",
            label="所得税",
            unit="万元",
            formula="taxable income after loss carry-forward × tax_rate_schedule",
            inputs=("total_profit", "loss_carry_forward", "tax_rate_schedule"),
            rows=(21,),
        ),
        ItemSchema(
            key="loss_compensation",
            label="弥补亏损",
            unit="万元",
            formula="offset of prior losses against current profit before tax",
            inputs=("total_profit", "loss_carry_forward"),
            rows=(22,),
        ),
        ItemSchema(
            key="loss",
            label="亏损额",
            unit="万元",
            formula="max(0, −total_profit)",
            inputs=("total_profit",),
            rows=(23,),
        ),
        ItemSchema(
            key="loss_carry_forward",
            label="亏损结转",
            unit="万元",
            formula="prior unrecouped losses carried into this year's tax computation",
            inputs=("loss", "loss_compensation"),
            rows=(24,),
        ),
        ItemSchema(
            key="tax_echo",
            label="所得税(回显)",
            unit="万元",
            formula="income_tax echoed for downstream sheets",
            inputs=("income_tax",),
            rows=(25,),
        ),
        ItemSchema(
            key="net_profit",
            label="净利润",
            unit="万元",
            formula="max(0, total_profit − loss_compensation − income_tax)",
            inputs=("total_profit", "loss_compensation", "income_tax"),
            rows=(26,),
        ),
        ItemSchema(
            key="surplus_reserve",
            label="盈余公积金",
            unit="万元",
            formula="net_profit × surplus_reserve_ratio when cumulative profit > 0",
            inputs=("net_profit", "params:surplus_reserve_ratio"),
            rows=(27,),
        ),
        ItemSchema(
            key="distributable_profit",
            label="可分配利润",
            unit="万元",
            formula="net_profit − surplus_reserve when cumulative profit > 0",
            inputs=("net_profit", "surplus_reserve"),
            rows=(29,),
        ),
        ItemSchema(
            key="dividend",
            label="分红",
            unit="万元",
            formula="finplan:profit_distribution (财务计划!31 row)",
            inputs=("finplan:profit_distribution",),
            rows=(32,),
        ),
        ItemSchema(
            key="undistributed_profit",
            label="未分配利润",
            unit="万元",
            formula="distributable_profit − dividend + loss-side adjustments",
            inputs=("distributable_profit", "dividend"),
            rows=(33,),
        ),
        ItemSchema(
            key="depreciation_echo",
            label="折旧(回显)",
            unit="万元",
            formula="cost:depreciation (成本!28 row)",
            inputs=("cost:depreciation",),
            rows=(36,),
        ),
        ItemSchema(
            key="adjusted_profit",
            label="调整后利润(估值口径)",
            unit="万元",
            formula=(
                "net_profit + cost interest × (1−tax) "
                "− balance-sheet debt × benchmark rate"
            ),
            inputs=("net_profit", "balance:total_liabilities"),
            rows=(43,),
        ),
        ItemSchema(
            key="row13_total",
            label="合计行13",
            unit="万元",
            formula="row total (0)",
            inputs=(),
            rows=(13,),
        ),
        ItemSchema(
            key="row28_total",
            label="合计行28",
            unit="万元",
            formula="row total (0)",
            inputs=(),
            rows=(28,),
        ),
    ),
)
