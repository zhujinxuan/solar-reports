"""OperatingCost — 总成本估算表 + 折旧/摊销明细 (cost sheet).

Implements every 成本 schedule step. Cross-sheet refs: 还贷 rows 11/16/21,
损益 row 8, 投资计划 C9. Defined names: 增值税率 → params.vat_rate.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from xlsx_core.model import Scalar

from solar_v2.cols import col_letters
from solar_v2.params import Params
from solar_v2.pipeline import FineStepFn, ValueView
from solar_v2.schedule import Step

StepFn = Callable[[Params, ValueView], Mapping[str, Scalar]]

SHEET = "成本"
# Top section: D=construction, E-AC=25 operating years
OP_COLS: list[str] = col_letters("E", 25)  # E..AC
# Depreciation section: E-AC = 25 operating years (same layout)
DEP_COLS: list[str] = col_letters("E", 25)  # E..AC
# Deferred-VAT section: F-AD = 25 operating years
DEF_COLS: list[str] = col_letters("F", 25)  # F..AD
# Long-term deferred amortization cols: F-AD
LTD_AMORT_COLS: list[str] = col_letters("F", 25)  # F..AD


def _nid(col: str, row: int) -> str:
    return f"{SHEET}!{col}{row}"


def _num(view: ValueView, node_id: str) -> float:
    """Numeric value of a node; blank/absent = 0.0 (Excel semantics)."""
    v = view.get(node_id)
    return float(v) if isinstance(v, (int, float)) else 0.0


# ── Step implementations ───────────────────────────────────────────────

def _year_row4_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 4: year numbers. E4=1, F4=E4+1, ..., AC4=AB4+1."""
    _ = params, view
    out: dict[str, Scalar] = {}
    out[_nid("E", 4)] = 1
    for i in range(1, 25):
        out[_nid(OP_COLS[i], 4)] = i + 1
    return out


def _salary_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 8: 工资及福利等 = staff * salary * (1 + welfare)."""
    _ = view
    val = params.staff_count * params.avg_salary * (1 + params.welfare_rate)
    return {_nid(c, 8): val for c in OP_COLS} | {_nid("AD", 8): 25 * val}


def _material_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 10: 材料费 = material_rate * capacity."""
    _ = view
    val = params.material_cost_rate * params.installed_capacity_mw
    return {_nid(c, 10): val for c in OP_COLS} | {_nid("AD", 10): 25 * val}


def _land_tax_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 11: 城镇土地使用税 = land_use_tax (0)."""
    _ = view
    val = params.land_use_tax
    return {_nid(c, 11): val for c in OP_COLS} | {_nid("AD", 11): 25 * val}


def _wc_loan_interest_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 15: 流动资金贷款利息 = 还贷!E16:AC16."""
    _ = params
    out: dict[str, Scalar] = {}
    ad_sum = 0.0
    for c in OP_COLS:
        v = _num(view, f"还贷!{c}16")
        out[_nid(c, 15)] = v
        ad_sum += v
    out[_nid("AD", 15)] = ad_sum
    return out


def _surplus_interest_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 17: 盈余资金利息收入 — all zeros."""
    _ = params, view
    out: dict[str, Scalar] = {}
    for c in OP_COLS:
        out[_nid(c, 17)] = 0.0
    out[_nid("AD", 17)] = 0.0
    return out


def _other_cost_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 18: 其他费用 = other_cost_rate * capacity."""
    _ = view
    val = params.other_cost_rate * params.installed_capacity_mw
    return {_nid(c, 18): val for c in OP_COLS} | {_nid("AD", 18): 25 * val}


def _fixed_cost_label_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 19: 固定成本 — AD label only (0)."""
    _ = params, view
    return {_nid("AD", 19): 0.0}


def _variable_cost_label_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 20: 可变成本 — AD label only (0)."""
    _ = params, view
    return {_nid("AD", 20): 0.0}


def _year_row26_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 26: year numbers (depreciation section). E26=1, ..., AC26=25."""
    _ = params, view
    out: dict[str, Scalar] = {_nid("E", 26): 1}
    for i in range(1, 25):
        out[_nid(DEP_COLS[i], 26)] = i + 1
    out[_nid("AD", 26)] = 0
    return out


def _deductible_vat_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 28: 待抵扣固定资产进项税额 D28 = 参数表!C25."""
    _ = view
    return {_nid("D", 28): params.deductible_vat_construction}


def _year_row48_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 48: year numbers (deferred-VAT section).
    E48=1 (const), F48=1 (op yr 1), then G48=2, ..., AC48=24, AD48=25.
    """
    _ = params, view
    out: dict[str, Scalar] = {
        _nid("E", 48): 1,
        _nid("F", 48): 1,
    }
    r48_cols = col_letters("G", 23)  # G..AC, 23 cols with values 2..24
    for i, c in enumerate(r48_cols):
        out[_nid(c, 48)] = i + 2
    out[_nid("AD", 48)] = 25
    return out


def _deferred_original_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 50: 递延资产原值 D50 = D28."""
    _ = params
    return {_nid("D", 50): _num(view, _nid("D", 28))}


def _land_rent_original_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 55: 长期待摊费用原值 = 参数表!C68:AA68."""
    _ = params
    param_cols = col_letters("C", 25)  # C..AA → E..AC
    out: dict[str, Scalar] = {
        _nid(c, 55): _num(view, f"参数表!{param_cols[i]}68")
        for i, c in enumerate(OP_COLS)
    }
    out[_nid("AD", 55)] = _num(view, "参数表!AB68")
    return out

def _land_rent_amort_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 56: 长期待摊费用摊销 = 参数表!D69:AB69 (F56=参数表!D69, ...)."""
    _ = params
    param_cols = col_letters("D", 25)  # D..AB = 25 cols
    out: dict[str, Scalar] = {}
    for i, c in enumerate(LTD_AMORT_COLS):
        out[_nid(c, 56)] = _num(view, f"参数表!{param_cols[i]}69")
    return out


def _land_rent_echo_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 12: 长期待摊费用 (top-section echo). E12=F56, F12=G56, ..."""
    _ = params
    out: dict[str, Scalar] = {}
    for i, c in enumerate(OP_COLS):
        out[_nid(c, 12)] = _num(view, _nid(LTD_AMORT_COLS[i], 56))
    ad = 0.0
    for v in out.values():
        ad += float(v) if isinstance(v, (int, float)) else 0.0
    out[_nid("AD", 12)] = ad
    return out


def _land_rent_net_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 57: 长期待摊费用净值. E57 = -E56 + E55 (E56 blank=0).
    F57 = E57 - F56 + F55, etc. (carry chain)."""
    _ = params
    out: dict[str, Scalar] = {}
    prev_net = 0.0
    for _i, c in enumerate(OP_COLS):
        orig = _num(view, _nid(c, 55))
        amort = _num(view, _nid(c, 56))  # E56 blank → 0
        net = prev_net - amort + orig
        out[_nid(c, 57)] = net
        prev_net = net
    # AD57 = AC57 - AD56 + AD55. AD56 = 参数表!AB69, AD55 = 参数表!AB68
    ad55 = _num(view, "参数表!AB68")
    ad56 = _num(view, "参数表!AB69")
    out[_nid("AD", 57)] = prev_net - ad56 + ad55
    return out

def _deferred_vat_scc_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Rows 51-52 SCC: 递延资产(进项税额)摊销+净值.

    Row 51 (摊销): F51 = 损益!G8 * vat_rate (first year).
      G51..AD51 = min(prev_net, 损益!col8 * vat_rate).
    Row 52 (净值): F52 = D50 - F51; G52..AD52 = prev_net - cur_amort.
    Purely sequential per column — no mutual intra-column dependency.
    """
    vat_rate = params.vat_rate
    d50 = _num(view, _nid("D", 50))

    # 损益 row 8: G..AE (25 cols) mapped to 成本 deferred F..AD
    pnl_cols = col_letters("G", 25)

    out: dict[str, Scalar] = {}
    prev_net = d50

    for i, c in enumerate(DEF_COLS):
        vat_from_pnl = _num(view, f"损益!{pnl_cols[i]}8") * vat_rate
        amort = vat_from_pnl if i == 0 else min(prev_net, vat_from_pnl)
        net = prev_net - amort
        out[_nid(c, 51)] = amort
        out[_nid(c, 52)] = net
        prev_net = net

    return out


def _long_term_loan_interest_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 14: 长期贷款利息 = 还贷!E11:AC11."""
    _ = params
    out: dict[str, Scalar] = {}
    ad_sum = 0.0
    for c in OP_COLS:
        v = _num(view, f"还贷!{c}11")
        out[_nid(c, 14)] = v
        ad_sum += v
    out[_nid("AD", 14)] = ad_sum
    return out
def _interest_fine(
    params: Params, view: ValueView, col: str,
) -> Mapping[str, Scalar]:
    """Row 13 fine: 利息支出 = SUM(col14:col17) for one column or AD sum."""
    _ = params
    if col == "AD":
        ad16 = sum(_num(view, f"还贷!{c}21") for c in OP_COLS)
        ad = (
            _num(view, _nid("AD", 14))
            + _num(view, _nid("AD", 15))
            + ad16
            + _num(view, _nid("AD", 17))
        )
        return {_nid("AD", 13): ad}
    v = sum(_num(view, _nid(col, r)) for r in (14, 15, 16, 17))
    return {_nid(col, 13): v}
def _total_cost_fine(
    params: Params, view: ValueView, col: str,
) -> Mapping[str, Scalar]:
    """Row 21 fine: 总成本费用 = SUM(col6:col13) + col18 for one column or AD."""
    _ = params
    if col == "AD":
        ad = sum(
            _num(view, _nid("AD", r))
            for r in range(6, 14)
        ) + _num(view, _nid("AD", 18))
        return {_nid("AD", 21): ad}
    v = sum(_num(view, _nid(col, r)) for r in range(6, 14)) + _num(view, _nid(col, 18))
    return {_nid(col, 21): v}


def _fixed_asset_original_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 29: 固定资产原值 D29 = 投资计划!C9 - D28 - E55."""
    _ = params
    c9 = _num(view, "投资计划!C9")
    d28 = _num(view, _nid("D", 28))
    e55 = _num(view, _nid("E", 55))
    return {_nid("D", 29): c9 - d28 - e55}


def _repair_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 7: 修理费 = D29 * 参数表!D52:AB52 (repair rate series)."""
    _ = params
    d29 = _num(view, _nid("D", 29))
    param_cols = col_letters("D", 25)  # D..AB
    out: dict[str, Scalar] = {}
    ad_sum = 0.0
    for i, c in enumerate(OP_COLS):
        rate = _num(view, f"参数表!{param_cols[i]}52")
        v = d29 * rate
        out[_nid(c, 7)] = v
        ad_sum += v
    out[_nid("AD", 7)] = ad_sum
    return out


def _depreciation_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 30: 当期折旧费.
    IF(dep_years - year_num >= 0, D29 * dep_rate * load_rate, 0).
    dep_years=20 → years 1-20 get depreciation; 21-25 = 0.
    """
    d29 = _num(view, _nid("D", 29))
    dep_rate = params.depreciation_rate
    dep_years = int(params.depreciation_years)
    out: dict[str, Scalar] = {}

    for i, c in enumerate(DEP_COLS):
        year_num = i + 1  # E26=1, F26=2, ...
        load_idx = i + 1
        load = (
            params.load_rate[load_idx]
            if load_idx < len(params.load_rate)
            else 1.0
        )
        dep = d29 * dep_rate * load if dep_years - year_num >= 0 else 0.0
        out[_nid(c, 30)] = dep

    ad = 0.0
    for v in out.values():
        ad += float(v) if isinstance(v, (int, float)) else 0.0
    out[_nid("AD", 30)] = ad

    return out

def _depreciation_echo_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 6: 折旧费 = row 30 echo."""
    _ = params
    out: dict[str, Scalar] = {}
    ad_sum = 0.0
    for c in OP_COLS:
        v = _num(view, _nid(c, 30))
        out[_nid(c, 6)] = v
        ad_sum += v
    out[_nid("AD", 6)] = ad_sum
    return out



def _net_value_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 31: 固定资产净值 (carry chain).
    E31 = D29 - E30, F31 = E31 - F30, ...
    """
    _ = params
    d29 = _num(view, _nid("D", 29))
    out: dict[str, Scalar] = {}
    prev_net = d29
    for c in DEP_COLS:
        dep = _num(view, _nid(c, 30))
        net = prev_net - dep
        out[_nid(c, 31)] = net
        prev_net = net
    return out


def _insurance_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 9: 保险费 = row 31 (净值) * insurance_rate."""
    _ = params
    ins_rate = params.insurance_rate
    out: dict[str, Scalar] = {}
    ad_sum = 0.0
    for c in OP_COLS:
        v = _num(view, _nid(c, 31)) * ins_rate
        out[_nid(c, 9)] = v
        ad_sum += v
    out[_nid("AD", 9)] = ad_sum
    return out


def _operating_cost_step(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 22: 经营成本 = E7+E8+E9+E10+E11+E18."""
    _ = params
    out: dict[str, Scalar] = {}
    ad_sum = 0.0
    for c in OP_COLS:
        v = sum(_num(view, _nid(c, r)) for r in (7, 8, 9, 10, 11, 18))
        out[_nid(c, 22)] = v
        ad_sum += v
    out[_nid("AD", 22)] = ad_sum
    return out


def _short_term_fine(
    params: Params, view: ValueView, col: str,
) -> Mapping[str, Scalar]:
    """Row 16 fine: 短期借款利息 = 还贷!col21 for one column or AD sum."""
    _ = params
    if col == "AD":
        ad = sum(_num(view, f"还贷!{c}21") for c in OP_COLS)
        return {_nid("AD", 16): ad}
    return {_nid(col, 16): _num(view, f"还贷!{col}21")}



# ── Unit registry ──────────────────────────────────────────────────────

UNITS: dict[Step, StepFn] = {
    ("成本", 4): _year_row4_step,
    ("成本", 8): _salary_step,
    ("成本", 10): _material_step,
    ("成本", 11): _land_tax_step,
    ("成本", 15): _wc_loan_interest_step,
    ("成本", 17): _surplus_interest_step,
    ("成本", 18): _other_cost_step,
    ("成本", 19): _fixed_cost_label_step,
    ("成本", 20): _variable_cost_label_step,
    ("成本", 26): _year_row26_step,
    ("成本", 28): _deductible_vat_step,
    ("成本", 48): _year_row48_step,
    ("成本", 50): _deferred_original_step,
    ("成本", 55): _land_rent_original_step,
    ("成本", 56): _land_rent_amort_step,
    ("成本", 12): _land_rent_echo_step,
    ("成本", 57): _land_rent_net_step,
    ("成本", (51, 52)): _deferred_vat_scc_step,
    ("成本", 14): _long_term_loan_interest_step,
    ("成本", 29): _fixed_asset_original_step,
    ("成本", 7): _repair_step,
    ("成本", 30): _depreciation_step,
    ("成本", 6): _depreciation_echo_step,
    ("成本", 31): _net_value_step,
    ("成本", 9): _insurance_step,
    ("成本", 22): _operating_cost_step,
}

UNITS_FINE: dict[tuple[str, int], FineStepFn] = {
    ("成本", 13): _interest_fine,
    ("成本", 16): _short_term_fine,
    ("成本", 21): _total_cost_fine,
}
