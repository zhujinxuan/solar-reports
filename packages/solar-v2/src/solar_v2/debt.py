"""DebtService — 借款还本付息计划表 (loan repayment schedule).

Long-term loan: equal-annual-payment (PMT) over loan_years at loan_rate_long.
Working capital loan: constant balance, interest-only.
Short-term loan: balance from 财务计划, interest-only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from xlsx_core.model import Scalar

from solar_v2.cols import col_index, col_name
from solar_v2.params import Params
from solar_v2.pipeline import FineStepFn, ValueView
from solar_v2.schedule import Step

StepFn = Callable[[Params, ValueView], Mapping[str, Scalar]]

SHEET = "还贷"
DEBT_COLS = [
    "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W",
    "X", "Y", "Z", "AA", "AB", "AC",
]  # 26 columns: D..AC
OP_COLS = DEBT_COLS[1:]  # E..AC (25 cols, no D)


def _nid(col: str, row: int) -> str:
    return f"{SHEET}!{col}{row}"


def _num(view: ValueView, node_id: str) -> float:
    """Numeric value of a node; blank/absent = 0.0 (Excel semantics)."""
    v = view.get(node_id)
    return float(v) if isinstance(v, (int, float)) else 0.0


def _pmt(rate: float, nper: int, pv: float) -> float:
    """Excel PMT: periodic payment for a loan.

    PMT = pv * r * (1+r)^n / ((1+r)^n - 1)
    """
    if rate == 0:
        return pv / nper
    factor = (1 + rate) ** nper
    return pv * rate * factor / (factor - 1)


# ── Individual step functions ──────────────────────────────────────────────


def _step_construction_interest(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 8 建设期利息: construction-period loan interest.

    D8 = 投资计划!F7, E8 = 投资计划!G7 (second period is 0).
    """
    _ = params
    d8 = _num(view, "投资计划!F7")
    e8 = _num(view, "投资计划!G7")
    return {_nid("D", 8): d8, _nid("E", 8): e8}


def _step_working_capital_balance(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 13 流动资金年初借款余额: constant carry-forward.

    E13 = 投资计划!G18, then each col = prior col.
    """
    _ = params
    out: dict[str, Scalar] = {}
    val = _num(view, "投资计划!G18")
    for c in OP_COLS:
        out[_nid(c, 13)] = val
    return out


def _step_working_capital_interest(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 16 流动资金付息: balance * 流动资金贷款利率.

    Uses params.working_capital_loan_rate (参数表!C33 = 0.0435).
    """
    _ = view
    rate = params.working_capital_loan_rate
    out: dict[str, Scalar] = {}
    for c in OP_COLS:
        out[_nid(c, 16)] = 450.0 * rate  # balance = 450 constant
    return out


def _step_year_numbers(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 4 年份: echo of 成本 row 4 year numbers."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in DEBT_COLS:
        out[_nid(c, 4)] = _num(view, f"成本!{c}4")
    return out


def _step_pmt(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 35 长期借款等额还本付息额 PMT.

    E35 = -PMT(参数表!C31, 参数表!C32, 投资计划!C15)
    """
    rate = params.loan_rate_long  # 参数表!C31 = 0.0465
    nper = params.loan_years      # 参数表!C32 = 15
    pv = _num(view, "投资计划!C15")
    pmt_val = _pmt(rate, nper, pv)
    return {_nid("E", 35): pmt_val}


def _scc_long_term_loan(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """SCC rows 6,7,10,11,36: 长期借款还本付息 schedule.

    Row 7 (本金): D7 = 投资计划!F16; carry: col_i = prior_row6 - prior_row10.
    Row 6 (年初余额): row7 + row8.
    Row 11 (付息): row6 * loan_rate_long.
    Row 36 (还本): E35 - row11.
    Row 10 (还本): row36.
    """
    rate = params.loan_rate_long
    pmt_val = _num(view, _nid("E", 35))

    d7 = _num(view, "投资计划!F16")
    d8 = _num(view, _nid("D", 8))
    d6 = d7 + d8

    out: dict[str, Scalar] = {
        _nid("D", 7): d7,
        _nid("D", 6): d6,
    }

    prev_balance = d6  # D6
    prev_principal_repay = 0.0  # no repayment in construction

    for i, c in enumerate(OP_COLS):
        # Row 7: principal (outstanding loan balance)
        principal = d6 if i == 0 else prev_balance - prev_principal_repay

        # Row 8: construction interest (zero beyond E)
        interest_constr = 0.0 if c != "E" else _num(view, _nid("E", 8))

        # Row 6: opening balance = principal + construction interest
        balance = principal + interest_constr

        # Row 11: interest payment = balance * rate
        interest_pmt = balance * rate

        # Row 36 / Row 10: principal repayment
        if i < params.loan_years:
            principal_repay = pmt_val - interest_pmt
            out[_nid(c, 36)] = principal_repay
            out[_nid(c, 10)] = principal_repay
        else:
            principal_repay = 0.0
            out[_nid(c, 10)] = 0.0

        out[_nid(c, 7)] = principal
        out[_nid(c, 6)] = balance
        out[_nid(c, 11)] = interest_pmt

        prev_balance = balance
        prev_principal_repay = principal_repay

    return out


def _step_annual_debt_service(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 9 当期还本付息: annual payment (principal + interest).

    E9..S9 = E35 (constant PMT); T9..AC9 = row10 + row11.
    """
    _ = params
    pmt_val = _num(view, _nid("E", 35))
    out: dict[str, Scalar] = {}
    for i, c in enumerate(OP_COLS):
        if i < params.loan_years:
            out[_nid(c, 9)] = pmt_val
        else:
            row10 = _num(view, _nid(c, 10))
            row11 = _num(view, _nid(c, 11))
            out[_nid(c, 9)] = row10 + row11
    return out


def _step_ebit(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 27 息税前利润(EBIT): 成本!col13 + 损益!(col+2)15."""
    _ = params
    out: dict[str, Scalar] = {}
    e_idx = col_index("E")
    for i, c in enumerate(OP_COLS):
        pnl_col = col_name(e_idx + i + 2)  # E->G, F->H, ...
        out[_nid(c, 27)] = (
            _num(view, f"成本!{c}13")
            + _num(view, f"损益!{pnl_col}15")
        )
    return out


def _step_ebit_vat(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 28 息税前利润(含增值税): row27 + 成本!(col+1)51."""
    _ = params
    out: dict[str, Scalar] = {}
    e_idx = col_index("E")
    for i, c in enumerate(OP_COLS):
        row27 = _num(view, _nid(c, 27))
        cost51_col = col_name(e_idx + i + 1)  # E->F, F->G, ...
        out[_nid(c, 28)] = row27 + _num(view, f"成本!{cost51_col}51")
    return out


def _step_icr(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 29 利息备付率(ICR): row28 / 成本!col13.

    AD29 = AVERAGE(F29:AC29). Cols E..X only (20 formula cols).
    """
    _ = params
    out: dict[str, Scalar] = {}
    values: list[float] = []
    for i, c in enumerate(OP_COLS):
        row28 = _num(view, _nid(c, 28))
        cost13 = _num(view, f"成本!{c}13")
        icr = row28 / cost13 if cost13 != 0 else 0.0
        if i < 20:  # E(0)..X(19) = 20 formula cols
            out[_nid(c, 29)] = icr
            if i >= 1:  # F onward for AVERAGE
                values.append(icr)
    out[_nid("AD", 29)] = sum(values) / len(values) if values else 0.0
    return out


def _step_ebitda(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 30 EBITDA: row27 + 成本!col6."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in OP_COLS:
        row27 = _num(view, _nid(c, 27))
        out[_nid(c, 30)] = row27 + _num(view, f"成本!{c}6")
    return out


def _step_ebitda_tax(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 31 EBITDA-tax: row30 + 成本!(col+1)51 - 损益!(col+2)21."""
    _ = params
    out: dict[str, Scalar] = {}
    e_idx = col_index("E")
    for i, c in enumerate(OP_COLS):
        row30 = _num(view, _nid(c, 30))
        cost51_col = col_name(e_idx + i + 1)
        pnl21_col = col_name(e_idx + i + 2)
        out[_nid(c, 31)] = (
            row30
            + _num(view, f"成本!{cost51_col}51")
            - _num(view, f"损益!{pnl21_col}21")
        )
    return out


def _step_dscr(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 32 偿债备付率(DSCR): row31 / (row11 + row10).

    AD32 = AVERAGE(F32:AC32). Cols E..S only (15 formula cols).
    """
    _ = params
    out: dict[str, Scalar] = {}
    values: list[float] = []
    for i, c in enumerate(OP_COLS):
        row31 = _num(view, _nid(c, 31))
        row11 = _num(view, _nid(c, 11))
        row10 = _num(view, _nid(c, 10))
        denom = row11 + row10
        dscr = row31 / denom if denom != 0 else 0.0
        if i < 15:  # E(0)..S(14) = 15 formula cols
            out[_nid(c, 32)] = dscr
            if i >= 1:  # F onward
                values.append(dscr)
    out[_nid("AD", 32)] = sum(values) / len(values) if values else 0.0
    return out


def _step_short_term_balance(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 18 短期借款年初余额: 财务计划!(col-1)22.

    E18 = 财务计划!D22, F18 = 财务计划!E22, ...
    """
    _ = params
    out: dict[str, Scalar] = {}
    d_idx = col_index("D")
    for i, c in enumerate(OP_COLS):
        fin_col = col_name(d_idx + i)  # E->D, F->E, ...
        out[_nid(c, 18)] = _num(view, f"财务计划!{fin_col}22")
    return out


def _step_short_term_principal(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 20 短期借款还本: 财务计划!col28. D..AC aligned."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in DEBT_COLS:
        out[_nid(c, 20)] = _num(view, f"财务计划!{c}28")
    return out


def _step_short_term_interest(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 21 短期借款付息: row20 * 短期贷款利息.

    短期贷款利息 = 参数表!C34 = params.short_term_loan_rate.
    """
    rate = params.short_term_loan_rate
    out: dict[str, Scalar] = {}
    for c in DEBT_COLS:
        row20 = _num(view, _nid(c, 20))
        out[_nid(c, 21)] = row20 * rate
    return out


def _step_total_balance(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 23 借款合计年初余额: row6 + row13 + row18."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in OP_COLS:
        out[_nid(c, 23)] = (
            _num(view, _nid(c, 6))
            + _num(view, _nid(c, 13))
            + _num(view, _nid(c, 18))
        )
    return out


def _step_total_principal(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 25 借款合计还本: row10 + row15 + row20.

    Row 15 (流动资金还本) is blank → 0.
    """
    _ = params
    out: dict[str, Scalar] = {}
    for c in OP_COLS:
        out[_nid(c, 25)] = (
            _num(view, _nid(c, 10))
            + _num(view, _nid(c, 20))
        )
    return out


def _step_total_interest(
    params: Params, view: ValueView,
) -> Mapping[str, Scalar]:
    """Row 26 借款合计付息: row11 + row16 + row21."""
    _ = params
    out: dict[str, Scalar] = {}
    for c in OP_COLS:
        out[_nid(c, 26)] = (
            _num(view, _nid(c, 11))
            + _num(view, _nid(c, 16))
            + _num(view, _nid(c, 21))
        )
    return out


def _fine_short_term_principal(
    params: Params, view: ValueView, col: str,
) -> Mapping[str, Scalar]:
    """Row 20 col 短期借款还本: 财务计划!col28."""
    _ = params
    return {_nid(col, 20): _num(view, f"财务计划!{col}28")}


def _fine_short_term_interest(
    params: Params, view: ValueView, col: str,
) -> Mapping[str, Scalar]:
    """Row 21 col 短期借款付息: row20 * 短期贷款利息."""
    rate = params.short_term_loan_rate
    row20 = _num(view, _nid(col, 20))
    return {_nid(col, 21): row20 * rate}


# ── Registry ────────────────────────────────────────────────────────────────

UNITS: dict[Step, StepFn] = {
    ("还贷", 8): _step_construction_interest,
    ("还贷", 13): _step_working_capital_balance,
    ("还贷", 16): _step_working_capital_interest,
    ("还贷", 4): _step_year_numbers,
    ("还贷", 35): _step_pmt,
    ("还贷", (6, 7, 10, 11, 36)): _scc_long_term_loan,
    ("还贷", 9): _step_annual_debt_service,
    ("还贷", 27): _step_ebit,
    ("还贷", 28): _step_ebit_vat,
    ("还贷", 29): _step_icr,
    ("还贷", 30): _step_ebitda,
    ("还贷", 31): _step_ebitda_tax,
    ("还贷", 32): _step_dscr,
    ("还贷", 18): _step_short_term_balance,
    ("还贷", 23): _step_total_balance,
    ("还贷", 25): _step_total_principal,
    ("还贷", 26): _step_total_interest,
}

UNITS_FINE: dict[tuple[str, int], FineStepFn] = {
    ("还贷", 20): _fine_short_term_principal,
    ("还贷", 21): _fine_short_term_interest,
}
