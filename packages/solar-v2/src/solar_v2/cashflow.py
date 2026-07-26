"""CashFlow — 现金流量表 (project/equity/investor cash flow statements).

Three sections:
  - 项目投资现金流量表 (rows 4-33): project cash flow (pre-tax/post-tax)
  - 资本金财务现金流量表 (rows 40-69): equity cash flow
  - 投资方财务现金流量表 (rows 80-98): investor cash flow
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from xlsx_core.model import ErrorValue, Scalar

from solar_v2.cols import col_index, col_letters, col_name
from solar_v2.params import Params
from solar_v2.pipeline import FineStepFn, ValueView
from solar_v2.schedule import Step

SHEET = "现金流量"

# Column ranges
YR_COLS_D_AC = col_letters("D", 26)   # D..AC  (26 cols: yr0 + op yrs 1-25)
YR_COLS_E_AC = col_letters("E", 25)   # E..AC  (25 op year cols)
YR_COLS_X_AC = col_letters("X", 6)    # X..AC  (op years 19-25)
YR_COLS_D_X = col_letters("D", 21)    # D..X   (for 20yr IRR: yr0..yr20)
YR_COLS_D_Y = col_letters("D", 22)     # D..Y   (for equity 20yr IRR: yr0..yr21)
YR_COLS_F_AC = col_letters("F", 24)   # F..AC  (op years 2-25)
YR_COLS_E_W = col_letters("E", 19)    # E..W   (op years 1-19)
StepFn = Callable[[Params, ValueView], Mapping[str, Scalar]]


# ── helpers ──────────────────────────────────────────────────────────────────

def _nid(col: str, row: int) -> str:
    return f"{SHEET}!{col}{row}"


def _num(view: ValueView, node_id: str) -> float:
    """Numeric value of a node; blank/absent → 0.0 (Excel semantics)."""
    v = view.get(node_id)
    if isinstance(v, ErrorValue):
        return 0.0
    return float(v) if isinstance(v, (int, float)) else 0.0


def _f(v: Scalar) -> float:
    """Coerce a computed Scalar to float; non-numeric → 0.0."""
    return float(v) if isinstance(v, (int, float)) else 0.0


def _npv(rate: float, cashflows: list[float]) -> float:
    """Net present value: Σ CF_t / (1+r)^(t+1), t starting from 0 (Excel convention)."""
    return sum(cf / ((1.0 + rate) ** (t + 1)) for t, cf in enumerate(cashflows))


def _npv_deriv(rate: float, cashflows: list[float]) -> float:
    """Derivative of _npv w.r.t. rate: Σ -(t+1)·CF_t / (1+r)^(t+2)."""
    s = 0.0
    for t, cf in enumerate(cashflows):
        s -= (t + 1) * cf / ((1.0 + rate) ** (t + 2))
    return s


def _irr(cashflows: list[float], guess: float = 0.1, max_iter: int = 100) -> float:
    """Internal rate of return: Newton-Raphson with bisection fallback."""
    if len(cashflows) < 2 or all(cf == 0.0 for cf in cashflows):
        return 0.0

    # Find bounds with sign change
    lo, hi = -0.999, 10.0
    for _ in range(100):
        npv_lo = _npv(lo, cashflows)
        npv_hi = _npv(hi, cashflows)
        if npv_lo * npv_hi <= 0:
            break
        lo -= 0.5
        hi += 1.0
    else:
        return 0.0

    if _npv(lo, cashflows) > 0:
        lo, hi = hi, lo

    r = guess
    for _ in range(max_iter):
        f_r = _npv(r, cashflows)
        if abs(f_r) < 1e-10:
            return r
        if not (lo < r < hi):
            r = (lo + hi) / 2.0
            f_r = _npv(r, cashflows)
            if abs(f_r) < 1e-10:
                return r
        d = _npv_deriv(r, cashflows)
        r_new = (lo + hi) / 2.0 if abs(d) < 1e-12 else r - f_r / d
        if not (lo <= r_new <= hi):
            r_new = (lo + hi) / 2.0
        f_new = _npv(r_new, cashflows)
        if abs(f_new) < 1e-10:
            return r_new
        if f_new * _npv(lo, cashflows) < 0:
            hi = r_new
        else:
            lo = r_new
        r = r_new
    return r


def _invest_col_for_row14(proj_col: str) -> str:
    """Map project column to 投资计划 column for row 14 (流动资金)."""
    # D→H, E→I, F→J, G→I(repeat), H→J(repeat), I..AC→offset+2
    ci = col_index(proj_col)
    if ci <= 5:  # D(3), E(4), F(5)
        return col_name(ci + 4)
    if ci <= 7:  # G(6)→I(8), H(7)→J(9)
        return col_name(ci + 2)
    return col_name(ci + 2)  # I(8)→K(10), ..., AC(28)→AE(30)


def _compute_salvage(params: Params, view: ValueView) -> float:
    """Compute 成本!Y31 salvage value from available data.

    D29 = 投资计划!C9 - 成本!D28 - 成本!E55
        = (unit_static * capacity + E55 + C7) - D28 - E55
        = unit_static * capacity + C7 - D28

    C7 (construction interest) is available early (step 26).
    D28 = params.deductible_vat_construction.

    Salvage = D29 * (1 - depreciation_rate * sum(load_rate[1:dep_years+1])).
    """
    total_static = params.unit_static_investment * params.installed_capacity_mw
    c7 = _num(view, "投资计划!C7")  # construction interest
    d29 = total_static + c7 - params.deductible_vat_construction

    dep_years = int(params.depreciation_years)
    load_sum = sum(params.load_rate[1 : dep_years + 1])
    salvage_ratio = 1.0 - params.depreciation_rate * load_sum
    return d29 * salvage_ratio


# ── project cash flow section ────────────────────────────────────────────────

def _year_labels_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 4: D4 = 成本!D4 (formula). E4..AC4 are literal year numbers."""
    _ = params
    return {_nid("D", 4): _num(view, "成本!D4")}


def _cash_inflow_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 5: per-year SUM of rows 6..10, E..AC + AD.
    Row 9 (salvage) is a forward ref (step 154 > step 98); compute inline."""
    op_years = params.operating_years
    salvage = _compute_salvage(params, view)
    out: dict[str, Scalar] = {}
    for c in YR_COLS_E_AC:
        last_yr = (c == "Y" and op_years == 20) or (c == "AC" and op_years == 25)
        r9 = salvage if last_yr else 0.0
        s = sum(_num(view, _nid(c, r)) for r in (6, 7, 8, 10)) + r9
        out[_nid(c, 5)] = s
    out[_nid("AD", 5)] = sum(_f(out[_nid(c, 5)]) for c in YR_COLS_E_AC)
    return out
def _power_sales_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 6: 发电销售收入 = 损益!row8 - 财务计划!row10 per year, E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c, fc in zip(YR_COLS_E_AC, col_letters("G", 25), strict=False):
        out[_nid(c, 6)] = _num(view, f"损益!{fc}8") - _num(view, f"财务计划!{c}10")
    out[_nid("AD", 6)] = sum(_f(out[_nid(c, 6)]) for c in YR_COLS_E_AC)
    return out


def _vat_refund_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 7: 增值税即征即退补贴 = 损益!row12 per year, E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c, fc in zip(YR_COLS_E_AC, col_letters("G", 25), strict=False):
        out[_nid(c, 7)] = view.get(f"损益!{fc}12")
    out[_nid("AD", 7)] = sum(_f(out[_nid(c, 7)]) for c in YR_COLS_E_AC)
    return out


def _vat_output_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 8: 增值税销项税额 = 损益!row37 per year, E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c, fc in zip(YR_COLS_E_AC, col_letters("G", 25), strict=False):
        out[_nid(c, 8)] = view.get(f"损益!{fc}37")
    out[_nid("AD", 8)] = sum(_f(out[_nid(c, 8)]) for c in YR_COLS_E_AC)
    return out


def _salvage_recovery_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 9: 回收固定资产余值 — 0 except Y9/AC9 depending on operating_years.
    Formula cols: Y9, AC9, AD9."""
    op_years = params.operating_years
    salvage = _num(view, "成本!Y31")
    out: dict[str, Scalar] = {}
    out[_nid("Y", 9)] = salvage if op_years == 20 else 0.0
    out[_nid("AC", 9)] = salvage if op_years == 25 else 0.0
    out[_nid("AD", 9)] = _f(out[_nid("Y", 9)]) + _f(out[_nid("AC", 9)])
    return out


def _wc_recovery_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 10: 回收流动资金 — 0 except Y10/AC10 depending on operating_years.
    Formula cols: Y10, AC10, AD10."""
    op_years = params.operating_years
    wc = _num(view, "参数表!C29")
    out: dict[str, Scalar] = {}
    out[_nid("Y", 10)] = wc if op_years == 20 else 0.0
    out[_nid("AC", 10)] = wc if op_years == 25 else 0.0
    out[_nid("AD", 10)] = _f(out[_nid("Y", 10)]) + _f(out[_nid("AC", 10)])
    return out


def _row11_sum_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 11: AD11 = SUM(E11:AC11) — blank range, always 0."""
    _ = params, view
    return {_nid("AD", 11): 0.0}


def _cash_outflow_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 12: per-year SUM of rows 13..19, D..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    sub_rows = (13, 14, 15, 16, 17, 18, 19)
    for c in YR_COLS_D_AC:
        out[_nid(c, 12)] = sum(_num(view, _nid(c, r)) for r in sub_rows)
    out[_nid("AD", 12)] = sum(_f(out[_nid(c, 12)]) for c in YR_COLS_E_AC)
    return out


def _fixed_asset_invest_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 13: 固定资产投资 = 投资计划!F6/G6 (D,E). Formula cols: D13, E13, AD13."""
    _ = params
    d13 = _num(view, "投资计划!F6")
    e13 = _num(view, "投资计划!G6")
    return {_nid("D", 13): d13, _nid("E", 13): e13, _nid("AD", 13): e13}


def _working_capital_step_proj(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 14: 流动资金 = 投资计划!row8 per year, D..AC + AD (all formulas)."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_D_AC:
        ic = _invest_col_for_row14(c)
        out[_nid(c, 14)] = _num(view, f"投资计划!{ic}8")
    out[_nid("AD", 14)] = sum(_f(out[_nid(c, 14)]) for c in YR_COLS_D_AC)
    return out


def _vat_payable_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 15: 应交增值税金 = 损益!row40 per year, E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c, fc in zip(YR_COLS_E_AC, col_letters("G", 25), strict=False):
        out[_nid(c, 15)] = view.get(f"损益!{fc}40")
    out[_nid("AD", 15)] = sum(_f(out[_nid(c, 15)]) for c in YR_COLS_E_AC)
    return out


def _land_rent_payment_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 16: 土地租金 = 财务计划!row14 per year, E..AC only (no AD)."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_E_AC:
        out[_nid(c, 16)] = view.get(f"财务计划!{c}14")
    return out


def _operating_cost_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 17: blank label row = 成本!row22 per year, E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_E_AC:
        out[_nid(c, 17)] = view.get(f"成本!{c}22")
    out[_nid("AD", 17)] = sum(_f(out[_nid(c, 17)]) for c in YR_COLS_E_AC)
    return out


def _sales_tax_surcharge_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 18: 销售税金附加 = 损益!row9 per year, E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c, fc in zip(YR_COLS_E_AC, col_letters("G", 25), strict=False):
        out[_nid(c, 18)] = view.get(f"损益!{fc}9")
    out[_nid("AD", 18)] = sum(_f(out[_nid(c, 18)]) for c in YR_COLS_E_AC)
    return out


def _adjusted_income_tax_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 19: 调整所得税 = row20 * 所得税率, first 3 op years halved.
    Formula cols: H..AC + AD (23 cells). E..G are literal 0."""
    tax_rate = params.income_tax_rate
    r20 = [_num(view, _nid(c, 20)) for c in YR_COLS_E_AC]
    half_years = 3
    out: dict[str, Scalar] = {}
    # Only emit H19..AC19 (skip E19..G19 which are literal 0)
    formula_cols = col_letters("H", 22)  # H..AC = 22 cols
    for i, fc in enumerate(formula_cols):
        yr_idx = half_years + i  # index into YR_COLS_E_AC
        factor = 0.5 if i < 3 else 1.0  # H,I,J halved; K+ full
        out[_nid(fc, 19)] = r20[yr_idx] * tax_rate * factor
    out[_nid("AD", 19)] = sum(_f(out[_nid(c, 19)]) for c in formula_cols)
    return out


def _ebit_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 20: 息税前利润 = 损益!row15 + 成本!row13 per year, E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c, fc in zip(YR_COLS_E_AC, col_letters("G", 25), strict=False):
        out[_nid(c, 20)] = _num(view, f"损益!{fc}15") + _num(view, f"成本!{c}13")
    out[_nid("AD", 20)] = sum(_f(out[_nid(c, 20)]) for c in YR_COLS_E_AC)
    return out


def _row21_sum_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 21: AD21 = SUM(E21:Y21) — blank range, always 0."""
    _ = params, view
    return {_nid("AD", 21): 0.0}


def _net_cash_flow_proj_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 22: 净现金流量 = row5 - row12 per year, D..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_D_AC:
        out[_nid(c, 22)] = _num(view, _nid(c, 5)) - _num(view, _nid(c, 12))
    out[_nid("AD", 22)] = sum(_f(out[_nid(c, 22)]) for c in YR_COLS_E_AC)
    return out


def _cum_net_cf_proj_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 23: 累计净现金流量 = cumulative sum of row22, D..AC only (no AD)."""
    _ = params
    r22 = [_num(view, _nid(c, 22)) for c in YR_COLS_D_AC]
    cum = 0.0
    out: dict[str, Scalar] = {}
    for c, v in zip(YR_COLS_D_AC, r22, strict=False):
        cum += v
        out[_nid(c, 23)] = cum
    return out


def _payback_proj_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 24: 所得税后投资回收年 — IF(cum crosses 0, year - cum_before/net_cf).
    Formula cols: J24..AC24, AD24."""
    _ = params
    r22 = [_num(view, _nid(c, 22)) for c in YR_COLS_D_AC]
    r23 = [_num(view, _nid(c, 23)) for c in YR_COLS_D_AC]
    year_labels = [0, *list(range(1, 26))]
    out: dict[str, Scalar] = {}
    total = 0.0
    for i in range(1, len(YR_COLS_D_AC)):
        c = YR_COLS_D_AC[i]
        prev_cum = r23[i - 1]
        curr_cum = r23[i]
        if prev_cum < 0 and curr_cum > 0:
            result = year_labels[i - 1] - prev_cum / r22[i]
            out[_nid(c, 24)] = result
            total += result
        else:
            out[_nid(c, 24)] = 0.0
    out[_nid("AD", 24)] = total
    return out


def _pre_tax_net_cf_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 25: 所得税前净现金流量 = row22 + row19, D..AC only (no AD)."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_D_AC:
        out[_nid(c, 25)] = _num(view, _nid(c, 22)) + _num(view, _nid(c, 19))
    return out


def _cum_pre_tax_cf_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 26: 累计税前净现金流量 = cumulative sum of row25, D..AC only."""
    _ = params
    r25 = [_num(view, _nid(c, 25)) for c in YR_COLS_D_AC]
    cum = 0.0
    out: dict[str, Scalar] = {}
    for c, v in zip(YR_COLS_D_AC, r25, strict=False):
        cum += v
        out[_nid(c, 26)] = cum
    return out


def _payback_pre_tax_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 27: 所得税前投资回收年 — D27=0, E27..AC27 + AD27."""
    _ = params
    r25 = [_num(view, _nid(c, 25)) for c in YR_COLS_D_AC]
    r26 = [_num(view, _nid(c, 26)) for c in YR_COLS_D_AC]
    year_labels = [0, *list(range(1, 26))]
    out: dict[str, Scalar] = {_nid("D", 27): 0.0}
    total = 0.0
    for i in range(1, len(YR_COLS_D_AC)):
        c = YR_COLS_D_AC[i]
        prev_cum = r26[i - 1]
        curr_cum = r26[i]
        if prev_cum < 0 and curr_cum > 0:
            result = year_labels[i - 1] - prev_cum / r25[i]
            out[_nid(c, 27)] = result
            total += result
        else:
            out[_nid(c, 27)] = 0.0
    out[_nid("AD", 27)] = total
    return out


def _project_irr_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 29: IRR(D22:AC22)*100 and IRR(D25:AC25)*100. Formula cols: I29, L29."""
    _ = params
    r22 = [_num(view, _nid(c, 22)) for c in YR_COLS_D_AC]
    r25 = [_num(view, _nid(c, 25)) for c in YR_COLS_D_AC]
    return {
        _nid("I", 29): _irr(r22) * 100.0,
        _nid("L", 29): _irr(r25) * 100.0,
    }


def _project_npv_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 30: NPV(5%, D22:AC22) and NPV(5%, D25:AC25). Formula cols: I30, L30."""
    _ = params
    r22 = [_num(view, _nid(c, 22)) for c in YR_COLS_D_AC]
    r25 = [_num(view, _nid(c, 25)) for c in YR_COLS_D_AC]
    return {
        _nid("I", 30): _npv(0.05, r22),
        _nid("L", 30): _npv(0.05, r25),
    }


def _payback_period_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 31: 投资回收期 = AD24 and AD27. Formula cols: I31, L31."""
    _ = params
    return {
        _nid("I", 31): view.get(_nid("AD", 24)),
        _nid("L", 31): view.get(_nid("AD", 27)),
    }


def _project_20yr_irr_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 33: 20-year IRR(D22:X22)*100 and IRR(D25:X25)*100. I33, L33."""
    _ = params
    r22_20 = [_num(view, _nid(c, 22)) for c in YR_COLS_D_X]
    r25_20 = [_num(view, _nid(c, 25)) for c in YR_COLS_D_X]
    return {
        _nid("I", 33): _irr(r22_20) * 100.0,
        _nid("L", 33): _irr(r25_20) * 100.0,
    }


# ── equity (资本金) cash flow section ────────────────────────────────────────

def _eq_year_labels_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 40: D..AC = D4..AC4. All 26 cols are formulas."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_D_AC:
        out[_nid(c, 40)] = view.get(_nid(c, 4))
    return out


def _eq_cash_inflow_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 42: per-year SUM of rows 43..47, E..AC + AD.
    Row 46 (salvage) is a forward ref (step 170 > step 100); inline it."""
    op_years = params.operating_years
    salvage = _compute_salvage(params, view)
    f9 = _num(view, _nid("F", 9))
    out: dict[str, Scalar] = {}
    for c in YR_COLS_E_AC:
        r46 = 0.0
        if c == "F":
            r46 = f9
        elif (c == "Y" and op_years == 20) or (c == "AC" and op_years == 25):
            r46 = salvage
        out[_nid(c, 42)] = (
            sum(_num(view, _nid(c, r)) for r in (43, 44, 45, 47)) + r46
        )
    out[_nid("AD", 42)] = sum(_f(out[_nid(c, 42)]) for c in YR_COLS_E_AC)
    return out


def _eq_power_sales_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 43: 发电销售收入 = row6. E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_E_AC:
        out[_nid(c, 43)] = view.get(_nid(c, 6))
    out[_nid("AD", 43)] = sum(_f(out[_nid(c, 43)]) for c in YR_COLS_E_AC)
    return out


def _eq_vat_refund_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 44: 增值税即征即退补贴 = 损益!row12. E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c, fc in zip(YR_COLS_E_AC, col_letters("G", 25), strict=False):
        out[_nid(c, 44)] = view.get(f"损益!{fc}12")
    out[_nid("AD", 44)] = sum(_f(out[_nid(c, 44)]) for c in YR_COLS_E_AC)
    return out


def _eq_vat_output_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 45: 增值税销项税额 = 损益!row37. E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c, fc in zip(YR_COLS_E_AC, col_letters("G", 25), strict=False):
        out[_nid(c, 45)] = view.get(f"损益!{fc}37")
    out[_nid("AD", 45)] = sum(_f(out[_nid(c, 45)]) for c in YR_COLS_E_AC)
    return out


def _eq_salvage_recovery_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 46: 回收固定资产余值. Formula cols: F46, Y46, AC46, AD46."""
    op_years = params.operating_years
    salvage = _num(view, "成本!Y31")
    out: dict[str, Scalar] = {}
    out[_nid("F", 46)] = view.get(_nid("F", 9))
    out[_nid("Y", 46)] = salvage if op_years == 20 else 0.0
    out[_nid("AC", 46)] = salvage if op_years == 25 else 0.0
    out[_nid("AD", 46)] = (
        _f(out[_nid("F", 46)])
        + _f(out[_nid("Y", 46)])
        + _f(out[_nid("AC", 46)])
    )
    return out


def _eq_wc_recovery_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 47: 回收流动资金. Formula col: AD47 only."""
    _ = params
    return {_nid("AD", 47): 0.0}


def _row48_sum_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 48: AD48 = SUM(E48:AC48) — blank range, always 0."""
    _ = params, view
    return {_nid("AD", 48): 0.0}


def _eq_cash_outflow_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 49: per-year SUM of rows 50..58, D..AC + AD.
    Note: row 51 is a forward ref (step 211 > step 176); its values are blank/0
    when this step runs. This is a known schedule limitation."""
    _ = params
    out: dict[str, Scalar] = {}
    sub_rows = (50, 51, 52, 53, 54, 55, 56, 57, 58)
    for c in YR_COLS_D_AC:
        out[_nid(c, 49)] = sum(_num(view, _nid(c, r)) for r in sub_rows)
    out[_nid("AD", 49)] = sum(_f(out[_nid(c, 49)]) for c in YR_COLS_D_AC)
    return out


def _equity_capital_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 50: 资本金 = 投资计划!row11, D/E/AD only (3 formula cells)."""
    _ = params
    d50 = _num(view, "投资计划!F11")
    e50 = _num(view, "投资计划!G11")
    return {
        _nid("D", 50): d50,
        _nid("E", 50): e50,
        _nid("AD", 50): d50 + e50,
    }


def _loan_principal_repay_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 51: 借款本金偿还. E..W: 还贷!10-财务计划!22+财务计划!28;
    X..AC: 还贷!10-还贷!18+还贷!20. E..AC + AD (26 formulas)."""
    _ = params
    out: dict[str, Scalar] = {}
    # E..W pattern
    for c in YR_COLS_E_W:
        out[_nid(c, 51)] = (
            _num(view, f"还贷!{c}10")
            - _num(view, f"财务计划!{c}22")
            + _num(view, f"财务计划!{c}28")
        )
    # X..AC pattern
    for c in YR_COLS_X_AC:
        out[_nid(c, 51)] = (
            _num(view, f"还贷!{c}10")
            - _num(view, f"还贷!{c}18")
            + _num(view, f"还贷!{c}20")
        )
    out[_nid("AD", 51)] = sum(_f(out[_nid(c, 51)]) for c in YR_COLS_E_AC)
    return out


def _loan_interest_payment_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 52: 借款利息支付 = 成本!row13 per year, E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_E_AC:
        out[_nid(c, 52)] = view.get(f"成本!{c}13")
    out[_nid("AD", 52)] = sum(_f(out[_nid(c, 52)]) for c in YR_COLS_E_AC)
    return out


def _eq_operating_cost_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 53: 经营成本 = 成本!row22 per year, E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_E_AC:
        out[_nid(c, 53)] = view.get(f"成本!{c}22")
    out[_nid("AD", 53)] = sum(_f(out[_nid(c, 53)]) for c in YR_COLS_E_AC)
    return out


def _eq_land_rent_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 54: 土地租金 = row16. E..AC only (no AD)."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_E_AC:
        out[_nid(c, 54)] = view.get(_nid(c, 16))
    return out


def _eq_vat_payable_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 55: 应交增值税 = 损益!row40 per year, E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c, fc in zip(YR_COLS_E_AC, col_letters("G", 25), strict=False):
        out[_nid(c, 55)] = view.get(f"损益!{fc}40")
    out[_nid("AD", 55)] = sum(_f(out[_nid(c, 55)]) for c in YR_COLS_E_AC)
    return out


def _eq_sales_tax_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 56: 销售税金附加 = 损益!row9 per year, E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c, fc in zip(YR_COLS_E_AC, col_letters("G", 25), strict=False):
        out[_nid(c, 56)] = view.get(f"损益!{fc}9")
    out[_nid("AD", 56)] = sum(_f(out[_nid(c, 56)]) for c in YR_COLS_E_AC)
    return out


def _eq_income_tax_fine(
    params: Params, view: ValueView, col: str
) -> Mapping[str, Scalar]:
    """Row 57 fine step: per-cell income tax from 损益!row21.
    E..AC: direct ref; AD: SUM of all year cols; AE: AD57 + AD55 + AD56."""
    _ = params
    if col in YR_COLS_E_AC:
        ci = col_index(col)
        # 损益 col offset: E→G = +2
        pl_col = col_name(ci + 2)
        return {_nid(col, 57): view.get(f"损益!{pl_col}21")}
    if col == "AD":
        total = sum(_num(view, _nid(c, 57)) for c in YR_COLS_E_AC)
        return {_nid("AD", 57): total}
    if col == "AE":
        ad57 = _num(view, _nid("AD", 57))
        ad55 = _num(view, _nid("AD", 55))
        ad56 = _num(view, _nid("AD", 56))
        return {_nid("AE", 57): ad57 + ad55 + ad56}
    return {}


def _long_term_rent_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 58: 长期待摊租金 = E13. Formula col: E58 only."""
    _ = params
    return {_nid("E", 58): view.get(_nid("E", 13))}


def _eq_net_cf_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 59: 净现金流量 = row42 - row49 per year, D..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_D_AC:
        out[_nid(c, 59)] = _num(view, _nid(c, 42)) - _num(view, _nid(c, 49))
    out[_nid("AD", 59)] = sum(_f(out[_nid(c, 59)]) for c in YR_COLS_D_AC)
    return out


def _eq_cum_cf_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 60: 累计净现金流量 = cumulative sum of row59, D..AC only."""
    _ = params
    r59 = [_num(view, _nid(c, 59)) for c in YR_COLS_D_AC]
    cum = 0.0
    out: dict[str, Scalar] = {}
    for c, v in zip(YR_COLS_D_AC, r59, strict=False):
        cum += v
        out[_nid(c, 60)] = cum
    return out


def _eq_irr_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 61: 资本金财务内部收益率 IRR(D59:AC59). Formula col: H61."""
    _ = params
    r59 = [_num(view, _nid(c, 59)) for c in YR_COLS_D_AC]
    return {_nid("H", 61): _irr(r59)}


def _eq_npv_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 62: 资本金财务净现值 NPV(8%, D59:AC59). Formula col: H62."""
    _ = params
    r59 = [_num(view, _nid(c, 59)) for c in YR_COLS_D_AC]
    return {_nid("H", 62): _npv(0.08, r59)}


def _eq_20yr_irr_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 64: 20-year IRR(D59:Y59)*100. Formula col: H64."""
    _ = params
    r59_20 = [_num(view, _nid(c, 59)) for c in YR_COLS_D_Y]
    return {_nid("H", 64): _irr(r59_20) * 100.0}


def _eq_adjustment_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 67: (C77 + C78/(1.09)*(1-0.09*0.1)) * (1-C72). Formula col: D67."""
    _ = params
    c77 = _num(view, "参数表!C77")
    c78 = _num(view, "参数表!C78")
    c72 = _num(view, "参数表!C72")
    result = (c77 + c78 / 1.09 * (1.0 - 0.09 * 0.1)) * (1.0 - c72)
    return {_nid("D", 67): result}


def _eq_adjusted_cf_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 68: 调整后净现金流 = row67 + row59 per year, D..AC only.
    Only D67 has a formula; E67..AC67 are blank → 0."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_D_AC:
        r67 = _num(view, _nid(c, 67))
        out[_nid(c, 68)] = r67 + _num(view, _nid(c, 59))
    return out

def _eq_adjusted_irr_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 69: IRR(D68:AC68). Formula col: D69."""
    _ = params
    r68 = [_num(view, _nid(c, 68)) for c in YR_COLS_D_AC]
    return {_nid("D", 69): _irr(r68)}


# ── investor (投资方) cash flow section ─────────────────────────────────────

def _inv_year_labels_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 83: D..AC = D40..AC40. All 26 cols are formulas."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_D_AC:
        out[_nid(c, 83)] = view.get(_nid(c, 40))
    return out


def _inv_cash_inflow_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 84: 现金流入 = row85 + row86 per year, E..AC only (no D, no AD)."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_E_AC:
        out[_nid(c, 84)] = _num(view, _nid(c, 85)) + _num(view, _nid(c, 86))
    return out


def _profit_distribution_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 85: 利润分配 = 损益!row32 per year, E..AC + AD."""
    _ = params
    out: dict[str, Scalar] = {}
    for c, fc in zip(YR_COLS_E_AC, col_letters("G", 25), strict=False):
        out[_nid(c, 85)] = view.get(f"损益!{fc}32")
    out[_nid("AD", 85)] = sum(_f(out[_nid(c, 85)]) for c in YR_COLS_E_AC)
    return out


def _asset_disposal_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 86: 资产处置收益分配 = SUM(rows 87..90), F..AC only (no E, no AD)."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_F_AC:
        out[_nid(c, 86)] = sum(_num(view, _nid(c, r)) for r in (87, 88, 89, 90))
    return out


def _inv_salvage_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 87: 回收固定资产和无形资产余值 = AC9. Formula col: AC87."""
    _ = params
    return {_nid("AC", 87): view.get(_nid("AC", 9))}


def _inv_surplus_fund_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 88: 回收累计盈余资金 = 财务计划!AC34. Formula col: AC88."""
    return {_nid("AC", 88): view.get("财务计划!AC34")}


def _inv_cash_outflow_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 91: 现金流出 = row92 + row93. Formula cols: D91, E91."""
    _ = params
    return {
        _nid("D", 91): _num(view, _nid("D", 92)) + _num(view, _nid("D", 93)),
        _nid("E", 91): _num(view, _nid("E", 92)) + _num(view, _nid("E", 93)),
    }


def _inv_construction_equity_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 92: 建设投资资本金 = D50. Formula col: D92."""
    _ = params
    return {_nid("D", 92): view.get(_nid("D", 50))}


def _inv_own_wc_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 93: 自有流动资金 = 投资计划!G13. Formula col: E93."""
    return {_nid("E", 93): view.get("投资计划!G13")}


def _inv_net_cf_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 94: 净现金流量 = row84 - row91 per year, D..AC only (no AD)."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in YR_COLS_D_AC:
        out[_nid(c, 94)] = _num(view, _nid(c, 84)) - _num(view, _nid(c, 91))
    return out


def _inv_cum_cf_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 95: 累计净现金流 = cumulative sum of row94, D..AC only."""
    _ = params
    r94 = [_num(view, _nid(c, 94)) for c in YR_COLS_D_AC]
    cum = 0.0
    out: dict[str, Scalar] = {}
    for c, v in zip(YR_COLS_D_AC, r94, strict=False):
        cum += v
        out[_nid(c, 95)] = cum
    return out


def _inv_irr_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 97: 投资方财务内部收益率 IRR(D94:AC94). Formula col: H97."""
    _ = params
    r94 = [_num(view, _nid(c, 94)) for c in YR_COLS_D_AC]
    return {_nid("H", 97): _irr(r94)}


def _inv_npv_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 98: 投资方财务净现值 NPV(8%, D94:AC94). Formula col: H98."""
    _ = params
    r94 = [_num(view, _nid(c, 94)) for c in YR_COLS_D_AC]
    return {_nid("H", 98): _npv(0.08, r94)}


# ── UNITS registry ───────────────────────────────────────────────────────────


UNITS_FINE: dict[tuple[str, int], FineStepFn] = {
    ("现金流量", 57): _eq_income_tax_fine,
}

UNITS: dict[Step, StepFn] = {
    # Project cash flow (early)
    ("现金流量", 4): _year_labels_step,
    ("现金流量", 7): _vat_refund_step,
    ("现金流量", 8): _vat_output_step,
    ("现金流量", 10): _wc_recovery_step,
    ("现金流量", 11): _row11_sum_step,
    ("现金流量", 14): _working_capital_step_proj,
    ("现金流量", 15): _vat_payable_step,
    ("现金流量", 18): _sales_tax_surcharge_step,
    ("现金流量", 21): _row21_sum_step,
    ("现金流量", 40): _eq_year_labels_step,
    ("现金流量", 44): _eq_vat_refund_step,
    ("现金流量", 45): _eq_vat_output_step,
    ("现金流量", 47): _eq_wc_recovery_step,
    ("现金流量", 48): _row48_sum_step,
    ("现金流量", 55): _eq_vat_payable_step,
    ("现金流量", 56): _eq_sales_tax_step,
    ("现金流量", 67): _eq_adjustment_step,
    ("现金流量", 83): _inv_year_labels_step,
    ("现金流量", 93): _inv_own_wc_step,
    # After 财务计划 rows 4,7,8,10
    ("现金流量", 6): _power_sales_step,
    ("现金流量", 5): _cash_inflow_step,
    ("现金流量", 43): _eq_power_sales_step,
    ("现金流量", 16): _land_rent_payment_step,
    ("现金流量", 54): _eq_land_rent_step,
    # After 财务计划 + upstream
    ("现金流量", 9): _salvage_recovery_step,
    ("现金流量", 13): _fixed_asset_invest_step,
    ("现金流量", 17): _operating_cost_step,
    ("现金流量", 46): _eq_salvage_recovery_step,
    ("现金流量", 42): _eq_cash_inflow_step,
    ("现金流量", 50): _equity_capital_step,
    ("现金流量", 53): _eq_operating_cost_step,
    ("现金流量", 58): _long_term_rent_step,
    ("现金流量", 87): _inv_salvage_step,
    ("现金流量", 92): _inv_construction_equity_step,
    ("现金流量", 91): _inv_cash_outflow_step,
    # Row 57 is now handled by UNITS_FINE (fine per-column steps)
    # After 57 + upstream
    ("现金流量", 20): _ebit_step,
    ("现金流量", 19): _adjusted_income_tax_step,
    ("现金流量", 12): _cash_outflow_step,
    ("现金流量", 22): _net_cash_flow_proj_step,
    ("现金流量", 23): _cum_net_cf_proj_step,
    ("现金流量", 24): _payback_proj_step,
    ("现金流量", 25): _pre_tax_net_cf_step,
    ("现金流量", 26): _cum_pre_tax_cf_step,
    ("现金流量", 27): _payback_pre_tax_step,
    ("现金流量", 29): _project_irr_step,
    ("现金流量", 30): _project_npv_step,
    ("现金流量", 31): _payback_period_step,
    ("现金流量", 33): _project_20yr_irr_step,
    ("现金流量", 52): _loan_interest_payment_step,
    # After 损益 row 32
    ("现金流量", 85): _profit_distribution_step,
    # After 还贷 / 财务计划 deeper steps
    ("现金流量", 51): _loan_principal_repay_step,
    ("现金流量", 49): _eq_cash_outflow_step,
    ("现金流量", 59): _eq_net_cf_step,
    ("现金流量", 60): _eq_cum_cf_step,
    ("现金流量", 61): _eq_irr_step,
    ("现金流量", 62): _eq_npv_step,
    ("现金流量", 64): _eq_20yr_irr_step,
    ("现金流量", 68): _eq_adjusted_cf_step,
    ("现金流量", 69): _eq_adjusted_irr_step,
    ("现金流量", 88): _inv_surplus_fund_step,
    ("现金流量", 86): _asset_disposal_step,
    ("现金流量", 84): _inv_cash_inflow_step,
    ("现金流量", 94): _inv_net_cf_step,
    ("现金流量", 95): _inv_cum_cf_step,
    ("现金流量", 97): _inv_irr_step,
    ("现金流量", 98): _inv_npv_step,
}
