"""BalanceSheet — 资产负债表 (balance sheet).

Asset = current_assets + construction_in_progress + fixed_assets_net
      + intangible_and_other_net + accounts_receivable.
Liability = current_liabilities + long_term_loan + short_term_loan.
Equity = capital + accumulated_surplus_funds + accumulated_retained_earnings.
Asset-liability ratio = total_liabilities / total_assets.

Heavy cross-refs to 财务计划, 损益, 成本, 还贷, 投资计划, 现金流量 — all
scheduled before 资产负债.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from xlsx_core.model import Scalar

from solar_v2.cols import col_letters
from solar_v2.params import Params
from solar_v2.pipeline import ValueView
from solar_v2.schedule import Step

StepFn = Callable[[Params, ValueView], Mapping[str, Scalar]]

SHEET = "资产负债"
# C = construction year; D..AB = 25 operating years (1..25)
ALL_COLS = col_letters("C", 26)  # C..AB (26 columns)
OP_COLS = col_letters("D", 25)  # D..AB (25 columns)


def _nid(col: str, row: int) -> str:
    return f"{SHEET}!{col}{row}"


def _num(view: ValueView, node_id: str) -> float:
    """Numeric value of a node; blank/absent = 0.0 (Excel semantics)."""
    v = view.get(node_id)
    return float(v) if isinstance(v, (int, float)) else 0.0


def _f(v: Scalar) -> float:
    """Coerce a computed Scalar to float; non-numeric = 0.0."""
    return float(v) if isinstance(v, (int, float)) else 0.0


# ---------------------------------------------------------------------------
# Column-mapping helpers
# ---------------------------------------------------------------------------

def _echo_row(
    view: ValueView,
    src_sheet: str,
    src_row: int,
    balance_cols: list[str],
    src_cols: list[str],
    bal_row: int,
) -> Mapping[str, Scalar]:
    """Echo src_sheet!<src_col><src_row> → 资产负债!<bal_col><bal_row>."""
    out: dict[str, Scalar] = {}
    for bc, sc in zip(balance_cols, src_cols, strict=True):
        out[_nid(bc, bal_row)] = view.get(f"{src_sheet}!{sc}{src_row}")
    return out


# ---------------------------------------------------------------------------
# Step 1: Row 4 — year label
# ---------------------------------------------------------------------------

def _row4_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """C4 = 成本!D4 (construction year label = 1)."""
    _ = params
    return {_nid("C", 4): view.get("成本!D4")}


# ---------------------------------------------------------------------------
# Step 2: Row 7 — 流动资产 (current assets = working capital, constant)
# ---------------------------------------------------------------------------

def _row7_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """流动资产: D7=投资计划!C8 (working capital), then chain rightward."""
    _ = params
    out: dict[str, Scalar] = {}
    # D7 = construction-period working capital loan
    wc = _num(view, "投资计划!C8")
    out[_nid("D", 7)] = wc
    # E7..AB7: each = prior column (constant 450)
    for i in range(1, len(OP_COLS)):
        out[_nid(OP_COLS[i], 7)] = wc
    return out


# ---------------------------------------------------------------------------
# Step 3: Row 9 — 应收账款 (accounts receivable = cumulative sum of 财务计划 row 10)
# ---------------------------------------------------------------------------

def _row9_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """应收账款: running cumulative sum of 财务计划 row 10 (E10..AC10)."""
    _ = params
    out: dict[str, Scalar] = {}
    # Balance D→AB (25 cols) maps to 财务计划 E→AC (25 cols)
    finplan_cols = col_letters("E", 25)  # E..AC
    running = 0.0
    for bc, fc in zip(OP_COLS, finplan_cols, strict=True):
        running += _num(view, f"财务计划!{fc}10")
        out[_nid(bc, 9)] = running
    return out


# ---------------------------------------------------------------------------
# Step 4: Row 12 — 无形及其他资产净值 (intangible and other assets, net)
# ---------------------------------------------------------------------------

def _row12_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """无形及其他资产净值 = 成本!row52 + 成本!row57 (amortization net values).
    Balance D..AB (25 cols) ↔ 成本 F..AD (25 cols).
    """
    _ = params
    out: dict[str, Scalar] = {}
    cost_cols = col_letters("F", 25)  # F..AD
    for bc, cc in zip(OP_COLS, cost_cols, strict=True):
        v52 = _num(view, f"成本!{cc}52")
        v57 = _num(view, f"成本!{cc}57")
        out[_nid(bc, 12)] = v52 + v57
    return out


# ---------------------------------------------------------------------------
# Step 5: Row 14 — 流动负债总值 (current liabilities, constant)
# ---------------------------------------------------------------------------

def _row14_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """流动负债总值 = 投资计划!G18 (working capital short-term loan, ~450)."""
    _ = params
    wc_loan = _num(view, "投资计划!G18")
    return {_nid(c, 14): wc_loan for c in OP_COLS}


# ---------------------------------------------------------------------------
# Step 6: Row 8 — 累计盈余资金 (accumulated surplus cash)
# ---------------------------------------------------------------------------

def _row8_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """累计盈余资金 = 财务计划 row 34 echo (E34..AC34)."""
    _ = params
    finplan_cols = col_letters("E", 25)  # E..AC
    return _echo_row(view, "财务计划", 34, OP_COLS, finplan_cols, bal_row=8)


# ---------------------------------------------------------------------------
# Step 7: Row 6 — 流动资产总值 (total current assets = row7 + row8)
# ---------------------------------------------------------------------------

def _row6_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """流动资产总值 = SUM(流动资产, 累计盈余资金) = row7 + row8."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in OP_COLS:
        v7 = _num(view, _nid(c, 7))
        v8 = _num(view, _nid(c, 8))
        out[_nid(c, 6)] = v7 + v8
    return out


# ---------------------------------------------------------------------------
# Step 8: Row 10 — 在建工程 (construction in progress)
# ---------------------------------------------------------------------------

def _row10_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """在建工程: C10 = 投资计划!F5 (total dynamic investment).
    Operating years = literal 0.
    """
    _ = params
    return {_nid("C", 10): _num(view, "投资计划!F5")}


# ---------------------------------------------------------------------------
# Step 9: Row 11 — 固定资产净值 (fixed assets, net =
#     original - accumulated depreciation)
# ---------------------------------------------------------------------------

def _row11_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """固定资产净值 = 成本 row 31 (net fixed assets after depreciation).
    Balance D..X (20 cols) ↔ 成本 E..Y, then Y..AB echo X.
    """
    _ = params
    out: dict[str, Scalar] = {}
    # D..X: cost cols E..Y (20 columns of fresh values)
    cost_cols_20 = col_letters("E", 20)  # E..X
    for bc, cc in zip(OP_COLS[:20], cost_cols_20, strict=True):
        out[_nid(bc, 11)] = _num(view, f"成本!{cc}31")
    # X11: 成本!Y31 (column 21)
    x11 = _num(view, "成本!Y31")
    out[_nid("X", 11)] = x11
    # Y11..AB11: echo X11 (last 4 columns stay constant)
    for c in OP_COLS[21:]:  # Y, Z, AA, AB
        out[_nid(c, 11)] = x11
    return out


# ---------------------------------------------------------------------------
# Step 10: Row 5 — 资产总计 (total assets)
# ---------------------------------------------------------------------------

def _row5_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """资产总计 = row6 + row10 + row11 + row12 + row9.
    C5 = C10 only (C6, C11, C12, C9 are blank → 0).
    """
    _ = params
    out: dict[str, Scalar] = {}
    # C column (construction year): only C10 has value
    out[_nid("C", 5)] = _num(view, _nid("C", 10))
    # Operating years
    for c in OP_COLS:
        total = (
            _num(view, _nid(c, 6))
            + _num(view, _nid(c, 10))
            + _num(view, _nid(c, 11))
            + _num(view, _nid(c, 12))
            + _num(view, _nid(c, 9))
        )
        out[_nid(c, 5)] = total
    return out


# ---------------------------------------------------------------------------
# Step 11: Row 15 — 长期借款 (long-term loan balance)
# ---------------------------------------------------------------------------

def _row15_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """长期借款 = 还贷 row 6 (loan repayment schedule balance).
    C15=还贷!D6 (construction), D15=还贷!F6 (yr1), ..., AB15=还贷!AH6 (yr25).
    """
    _ = params
    out: dict[str, Scalar] = {}
    # C (=construction) → 还贷 D
    out[_nid("C", 15)] = _num(view, "还贷!D6")
    # D..AB (25 cols) → 还贷 F..AH (25 cols)
    repay_cols = col_letters("F", 25)
    for bc, rc in zip(OP_COLS, repay_cols, strict=True):
        out[_nid(bc, 15)] = _num(view, f"还贷!{rc}6")
    return out


# ---------------------------------------------------------------------------
# Step 12: Row 16 — 短期借款 (short-term loan)
# ---------------------------------------------------------------------------

def _row16_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """短期借款 = 财务计划 row 22 (short-term borrowing).
    C16=财务计划!D22..AB16=财务计划!AC22.
    """
    _ = params
    finplan_cols = col_letters("D", 26)  # D..AC
    return _echo_row(view, "财务计划", 22, ALL_COLS, finplan_cols, bal_row=16)


# ---------------------------------------------------------------------------
# Step 13: Row 17 — 负债小计 (total liabilities = row14 + row15 + row16)
# ---------------------------------------------------------------------------

def _row17_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """负债小计 = 流动负债 + 长期借款 + 短期借款."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in ALL_COLS:
        out[_nid(c, 17)] = (
            _num(view, _nid(c, 14))
            + _num(view, _nid(c, 15))
            + _num(view, _nid(c, 16))
        )
    return out


# ---------------------------------------------------------------------------
# Step 14: Row 19 — 资本金 (registered capital, cumulative with injections)
# ---------------------------------------------------------------------------

def _row19_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """资本金: C19=投资计划!F12 (construction equity).
    D19 = C19 + 投资计划!G13 (op-year equity injection).
    E19..AB19 = cumulative + 现金流量 row 50 injections.
    """
    _ = params
    out: dict[str, Scalar] = {}
    # C19: construction equity
    c19 = _num(view, "投资计划!F12")
    out[_nid("C", 19)] = c19
    # D19: C19 + 投资计划!G13 (year 1 capital injection from invest plan)
    d19 = c19 + _num(view, "投资计划!G13")
    out[_nid("D", 19)] = d19
    # E19..AB19: cumulative with 现金流量 row 50 (cash capital injections)
    # Balance E..AB (24 cols) ↔ 现金流量 F..AC (24 cols)
    cf_cols = col_letters("F", 24)
    running = d19
    for bc, cfc in zip(OP_COLS[1:], cf_cols, strict=True):
        running += _num(view, f"现金流量!{cfc}50")
        out[_nid(bc, 19)] = running
    return out


# ---------------------------------------------------------------------------
# Step 15: Row 20 — 累计三金 (accumulated surplus reserves)
# ---------------------------------------------------------------------------

def _row20_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """累计三金 = cumulative sum of (损益 row 27 + 损益 row 28).
    Balance D..AB (25 cols) ↔ 损益 G..AE (25 cols).
    """
    _ = params
    out: dict[str, Scalar] = {}
    pl_cols = col_letters("G", 25)  # G..AE
    running = 0.0
    for bc, pc in zip(OP_COLS, pl_cols, strict=True):
        running += _num(view, f"损益!{pc}27") + _num(view, f"损益!{pc}28")
        out[_nid(bc, 20)] = running
    return out


# ---------------------------------------------------------------------------
# Step 16: Row 21 — 累计未分配利润 (accumulated retained earnings)
# ---------------------------------------------------------------------------

def _row21_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """累计未分配利润 = cumulative sum of 损益 row 33.
    Balance D..AB (25 cols) ↔ 损益 G..AE (25 cols).
    """
    _ = params
    out: dict[str, Scalar] = {}
    pl_cols = col_letters("G", 25)  # G..AE
    running = 0.0
    for bc, pc in zip(OP_COLS, pl_cols, strict=True):
        running += _num(view, f"损益!{pc}33")
        out[_nid(bc, 21)] = running
    return out


# ---------------------------------------------------------------------------
# Step 17: Row 18 — 所有者权益 (total equity = SUM row19 + row20 + row21)
# ---------------------------------------------------------------------------

def _row18_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """所有者权益 = 资本金 + 累计三金 + 累计未分配利润."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in ALL_COLS:
        out[_nid(c, 18)] = (
            _num(view, _nid(c, 19))
            + _num(view, _nid(c, 20))
            + _num(view, _nid(c, 21))
        )
    return out


# ---------------------------------------------------------------------------
# Step 18: Row 13 — 负债及所有者权益 (total liabilities + equity)
# ---------------------------------------------------------------------------

def _row13_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """负债及所有者权益 = row17 + row18 (must equal row5 = total assets)."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in ALL_COLS:
        out[_nid(c, 13)] = _num(view, _nid(c, 17)) + _num(view, _nid(c, 18))
    return out


# ---------------------------------------------------------------------------
# Step 19: Row 23 — 资产负债率 (asset-liability ratio = total_liab / total_assets)
# ---------------------------------------------------------------------------

def _row23_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """资产负债率(%) = row17 / row5."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in OP_COLS:
        liab = _num(view, _nid(c, 17))
        assets = _num(view, _nid(c, 5))
        out[_nid(c, 23)] = liab / assets if assets != 0.0 else 0.0
    return out


# ---------------------------------------------------------------------------
# Step 20: Row 25 — balance check (row5 - row13, should be ~0)
# ---------------------------------------------------------------------------

def _row25_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Balance check: row5 (total assets) - row13 (total liab+equity)."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in ALL_COLS:
        out[_nid(c, 25)] = _num(view, _nid(c, 5)) - _num(view, _nid(c, 13))
    return out


# ---------------------------------------------------------------------------
# Step 21: Row 26 — period-over-period diff of row 25 check
# ---------------------------------------------------------------------------

def _row26_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Period diff of the balance check row 25.
    C26 = C6 - C14 (current assets - current liabilities construction year).
    D26 = D25 - C25, E26 = E25 - D25, ..., AB26 = AB25 - AA25.
    """
    _ = params
    out: dict[str, Scalar] = {}
    # C26 = C6 - C14 (both may be blank → 0)
    out[_nid("C", 26)] = _num(view, _nid("C", 6)) - _num(view, _nid("C", 14))
    # D26 = D25 - C25
    out[_nid("D", 26)] = _num(view, _nid("D", 25)) - _num(view, _nid("C", 25))
    # E26..AB26 = current - previous
    for i in range(1, len(OP_COLS)):
        cur = OP_COLS[i]
        prev = OP_COLS[i - 1]
        out[_nid(cur, 26)] = _num(view, _nid(cur, 25)) - _num(view, _nid(prev, 25))
    return out


# ---------------------------------------------------------------------------
# Step 22: Row 28 — maximum asset-liability ratio
# ---------------------------------------------------------------------------

def _row28_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """MAX(D23:AB23) — the peak leverage ratio across all operating years."""
    _ = params
    ratios = [_num(view, _nid(c, 23)) for c in OP_COLS]
    max_ratio = max(ratios) if ratios else 0.0
    return {_nid("D", 28): max_ratio}


# ---------------------------------------------------------------------------
# UNITS registry — schedule-order mapping
# ---------------------------------------------------------------------------

UNITS: dict[Step, StepFn] = {
    ("资产负债", 4): _row4_step,
    ("资产负债", 7): _row7_step,
    ("资产负债", 9): _row9_step,
    ("资产负债", 12): _row12_step,
    ("资产负债", 14): _row14_step,
    ("资产负债", 8): _row8_step,
    ("资产负债", 6): _row6_step,
    ("资产负债", 10): _row10_step,
    ("资产负债", 11): _row11_step,
    ("资产负债", 5): _row5_step,
    ("资产负债", 15): _row15_step,
    ("资产负债", 16): _row16_step,
    ("资产负债", 17): _row17_step,
    ("资产负债", 19): _row19_step,
    ("资产负债", 20): _row20_step,
    ("资产负债", 21): _row21_step,
    ("资产负债", 18): _row18_step,
    ("资产负债", 13): _row13_step,
    ("资产负债", 23): _row23_step,
    ("资产负债", 25): _row25_step,
    ("资产负债", 26): _row26_step,
    ("资产负债", 28): _row28_step,
}
