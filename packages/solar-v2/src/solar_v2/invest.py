"""InvestmentPlanning — 投资计划与资金筹措表 (construction-period table).

Column layout: C=合计 D,E=建设期年1,2 F,G=运营期年1,2 H=累计. Auxiliary block
rows 23-32 (cols B/C/F/G/I-L) computes the annual split, loan and construction
interest. Cross-sheet reads go through the ValueView (node ids), never cached.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from xlsx_core.model import Scalar

from solar_v2.params import Params
from solar_v2.pipeline import ValueView
from solar_v2.schedule import Step

StepFn = Callable[[Params, ValueView], Mapping[str, Scalar]]

SHEET = "投资计划"
PERIOD_COLS = ["D", "E", "F", "G"]  # construction 1-2, operation 1-2


def _nid(col: str, row: int) -> str:
    return f"{SHEET}!{col}{row}"


def _num(view: ValueView, node_id: str) -> float:
    """Numeric value of a node; blank/absent = 0.0 (Excel semantics)."""
    v = view.get(node_id)
    return float(v) if isinstance(v, (int, float)) else 0.0


def _f(v: Scalar) -> float:
    """Coerce a computed Scalar to float; non-numeric = 0.0."""
    return float(v) if isinstance(v, (int, float)) else 0.0


def _static_ratio_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 3 静态投资完成比例: named cells aa/ab/ac = J28/K28/L28 literals."""
    _ = params
    return {
        _nid("D", 3): _num(view, _nid("J", 28)),
        _nid("E", 3): _num(view, _nid("K", 28)),
        _nid("F", 3): _num(view, _nid("L", 28)),
    }


def _working_capital_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Rows 8/13/18 流动资金 block (SCC: C8 feeds C13/C18, D8 sums them)."""
    _ = view
    total = params.working_capital_total
    c13 = total * 0.0  # C13 = C8*0% — equity share of working capital
    c18 = total * 1.0  # C18 = C8*100% — loan share
    g13, g18 = c13, c18
    out: dict[str, Scalar] = {
        _nid("C", 8): total,
        _nid("C", 13): c13,
        _nid("G", 13): g13,
        _nid("C", 18): c18,
        _nid("G", 18): g18,
    }
    for col in PERIOD_COLS:
        r13 = {_nid("G", 13): g13}.get(_nid(col, 13), 0.0)
        r18 = {_nid("G", 18): g18}.get(_nid(col, 18), 0.0)
        out[_nid(col, 8)] = r13 + r18
    out[_nid("H", 8)] = sum(_f(out[_nid(c, 8)]) for c in PERIOD_COLS)
    out[_nid("H", 13)] = g13
    out[_nid("H", 18)] = g18
    return out


def _short_term_loan_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 19 其他短期贷款: only the cumulative cell H19."""
    _ = params, view
    return {_nid("H", 19): 0.0}


def _interest_rate_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 26: B26 静态投资 (echo of 参数表!C15), J26 construction interest rate."""
    _ = params
    return {
        _nid("B", 26): _num(view, "参数表!C15"),
        _nid("J", 26): _num(view, "参数表!C31") * (_num(view, "参数表!C35") / 12),
    }


def _annual_static_split_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 29 年度静态投资: B26 split by J28/K28/L28; B29 = total."""
    _ = params
    static_total = _num(view, _nid("B", 26))
    r29 = {
        "C": static_total * _num(view, _nid("J", 28)),
        "F": static_total * _num(view, _nid("K", 28)),
        "G": static_total * _num(view, _nid("L", 28)),
    }
    out: dict[str, Scalar] = {_nid("B", 29): sum(r29.values())}
    for col, v in r29.items():
        out[_nid(col, 29)] = v
    return out


def _loan_balance_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 28: B28 贷款 = B26 - B27."""
    _ = params
    return {_nid("B", 28): _num(view, _nid("B", 26)) - _num(view, _nid("B", 27))}


def _aux_block_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Rows 24,27,30-32 辅助测算表 (SCC): equity split, loan, construction interest.

    Defined names: i=J26, b=J27, aa/ab/ac=J28/K28/L28, cc=J29, j=J30.
    Rows 28/29 are separate steps (no mutual dependency after range expansion).
    """
    rate = _num(view, _nid("J", 26))  # i
    equity_ratio = params.equity_ratio  # b -> J27
    aa = _num(view, _nid("J", 28))
    ab = _num(view, _nid("K", 28))
    ac = _num(view, _nid("L", 28))
    cc = _num(view, _nid("C", 8))  # J29 = C8 working capital
    static_total = _num(view, _nid("B", 26))  # j -> J30 = B26

    # J31 动态投资: closed-form split formula from the workbook
    growth = aa * (1 + rate) ** 2 + ab * (1 + rate) + ac
    dynamic_total = (
        static_total * (2 + rate) * growth + 2 * cc
    ) / (equity_ratio * (2 + rate) * growth + 2 * (1 - equity_ratio)) - cc
    j32 = dynamic_total + cc  # J32 总投资
    b27 = j32 * equity_ratio  # 资本金

    # annual split rows 30-32 across C(yr1), F(yr2), G(yr3)
    split = {"C": aa, "F": ab, "G": ac}
    r29 = {c: _num(view, _nid(c, 29)) for c in split}
    r30 = {c: b27 * split[c] for c in split}
    r31 = {c: r29[c] - r30[c] for c in split}
    r32 = {
        "C": r31["C"] / 2 * rate,
        "F": 0.0,
        "G": 0.0,
    }
    r32["F"] = (r31["F"] / 2 + r32["C"] + r31["C"]) * rate
    # G32 = (G31/2 + SUM(C31:F32)) * rate; SUM(C31:F32) = C31+F31+C32+F32
    r32["G"] = (r31["G"] / 2 + r31["C"] + r31["F"] + r32["C"] + r32["F"]) * rate

    out: dict[str, Scalar] = {
        _nid("J", 27): equity_ratio,
        _nid("J", 29): cc,
        _nid("J", 30): static_total,
        _nid("J", 31): dynamic_total,
        _nid("J", 32): j32,
        _nid("B", 24): j32,
        _nid("B", 27): b27,
        _nid("B", 30): sum(r30.values()),
        _nid("B", 31): sum(r31.values()),
        _nid("B", 32): sum(r32.values()),
    }
    for col in ("C", "F", "G"):
        out[_nid(col, 30)] = r30[col]
        out[_nid(col, 31)] = r31[col]
        out[_nid(col, 32)] = r32[col]
    return out


def _construction_interest_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 7 建设期利息: echoes of the aux-block annual interest row 32."""
    _ = params
    c32, f32, g32 = (
        _num(view, _nid("C", 32)),
        _num(view, _nid("F", 32)),
        _num(view, _nid("G", 32)),
    )
    b32 = _num(view, _nid("B", 32))
    return {
        _nid("C", 7): b32,
        _nid("D", 7): c32,
        _nid("E", 7): f32,
        _nid("F", 7): g32,
        _nid("H", 7): c32 + f32 + g32,
    }


def _equity_for_construction_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 12 自有资金用于建设投资: C12 = B27, split by row-3 ratios."""
    _ = params
    c12 = _num(view, _nid("B", 27))
    f3, g3 = _num(view, _nid("F", 3)), _num(view, _nid("G", 3))
    f12, g12 = c12 * f3, c12 * g3
    return {
        _nid("C", 12): c12,
        _nid("F", 12): f12,
        _nid("G", 12): g12,
        _nid("H", 12): f12 + g12,  # D12/E12 are literal 0
    }


def _other_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 20 其他: G20 = G7, H20 = SUM(D20:G20)."""
    _ = params
    g7 = _num(view, _nid("G", 7))
    return {_nid("G", 20): g7, _nid("H", 20): g7}


def _dynamic_investment_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 25: B25 动态投资 = J31."""
    _ = params
    return {_nid("B", 25): _num(view, _nid("J", 31))}


def _construction_investment_step(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    """Row 6 建设投资: C6 = 指标汇总!H6, split by row-3 ratios; G6 = 成本!D54."""
    _ = params
    c6 = _num(view, "指标汇总!H6")
    d6 = c6 * _num(view, _nid("D", 3))
    e6 = c6 * _num(view, _nid("E", 3))
    f6 = c6 * _num(view, _nid("F", 3))
    g6 = _num(view, "成本!D54")
    return {
        _nid("C", 6): c6,
        _nid("D", 6): d6,
        _nid("E", 6): e6,
        _nid("F", 6): f6,
        _nid("G", 6): g6,
        _nid("H", 6): d6 + e6 + f6 + g6,
    }


def _total_investment_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 5 总投资: per-period sum of rows 6-8."""
    _ = params
    c5 = sum(_num(view, _nid("C", r)) for r in (6, 7, 8))
    out: dict[str, Scalar] = {_nid("C", 5): c5}
    for col in PERIOD_COLS:
        out[_nid(col, 5)] = sum(_num(view, _nid(col, r)) for r in (6, 7, 8))
    out[_nid("H", 5)] = sum(_f(out[_nid(c, 5)]) for c in PERIOD_COLS)
    return out


def _dynamic_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 9 动态投资: C9 = C6 + C7."""
    _ = params
    return {_nid("C", 9): _num(view, _nid("C", 6)) + _num(view, _nid("C", 7))}


def _equity_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 11 自有资金: rows 12+13 per period; I11 = C11/C5."""
    _ = params
    out: dict[str, Scalar] = {}
    for col in ["C", *PERIOD_COLS]:
        out[_nid(col, 11)] = _num(view, _nid(col, 12)) + _num(view, _nid(col, 13))
    out[_nid("H", 11)] = sum(_f(out[_nid(c, 11)]) for c in PERIOD_COLS)
    c5 = _num(view, _nid("C", 5))
    out[_nid("I", 11)] = _f(out[_nid("C", 11)]) / c5
    return out


def _equity_ratio_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 4 资本金使用比例: per-period row 11 / C11."""
    _ = params
    c11 = _num(view, _nid("C", 11))
    out: dict[str, Scalar] = {}
    for col in PERIOD_COLS:
        out[_nid(col, 4)] = _num(view, _nid(col, 11)) / c11
    out[_nid("H", 4)] = sum(_f(out[_nid(c, 4)]) for c in PERIOD_COLS)
    return out


def _loan_principal_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 16 长期借款本金: echoes of annual loan row 31; G16 = G6-G12."""
    _ = params
    return {
        _nid("D", 16): _num(view, _nid("C", 31)),
        _nid("E", 16): _num(view, _nid("F", 31)),
        _nid("F", 16): _num(view, _nid("G", 31)),
        _nid("G", 16): _num(view, _nid("G", 6)) - _num(view, _nid("G", 12)),
    }


def _long_term_loan_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Rows 15/17 长期借款(本金+利息) block (SCC)."""
    _ = params
    d17 = _num(view, _nid("C", 32))
    e17 = _num(view, _nid("F", 32))
    f17 = _num(view, _nid("G", 32))
    d16, e16, f16 = (
        _num(view, _nid("D", 16)),
        _num(view, _nid("E", 16)),
        _num(view, _nid("F", 16)),
    )
    e7, g7, g16 = (
        _num(view, _nid("E", 7)),
        _num(view, _nid("G", 7)),
        _num(view, _nid("G", 16)),
    )
    d15 = d16 + d17
    e15 = e7 + e16
    f15 = f16 + f17
    g15 = g7 + g16
    g17 = g15 - g16
    h15 = d15 + e15 + f15 + g15
    return {
        _nid("D", 15): d15,
        _nid("E", 15): e15,
        _nid("F", 15): f15,
        _nid("G", 15): g15,
        _nid("H", 15): h15,
        _nid("C", 15): f15,
        _nid("D", 17): d17,
        _nid("E", 17): e17,
        _nid("F", 17): f17,
        _nid("G", 17): g17,
    }


def _loan_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 14 借款: per-period sums of rows 15-19 (F14 = F15+F18 per workbook)."""
    _ = params
    out: dict[str, Scalar] = {}
    out[_nid("C", 14)] = sum(_num(view, _nid("C", r)) for r in range(15, 20))
    for col in ("D", "E", "G"):
        out[_nid(col, 14)] = sum(_num(view, _nid(col, r)) for r in range(15, 20))
    out[_nid("F", 14)] = _num(view, _nid("F", 15)) + _num(view, _nid("F", 18))
    out[_nid("H", 14)] = sum(_f(out[_nid(c, 14)]) for c in PERIOD_COLS)
    return out


def _funding_step(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 10 资金筹措: per-period row 11 + row 14; H10 += D17."""
    _ = params
    out: dict[str, Scalar] = {}
    for col in ["C", *PERIOD_COLS]:
        out[_nid(col, 10)] = _num(view, _nid(col, 11)) + _num(view, _nid(col, 14))
    out[_nid("H", 10)] = sum(_f(out[_nid(c, 10)]) for c in PERIOD_COLS) + _num(
        view, _nid("D", 17)
    )
    return out


UNITS: dict[Step, StepFn] = {
    ("投资计划", 3): _static_ratio_step,
    ("投资计划", (8, 13, 18)): _working_capital_step,
    ("投资计划", 19): _short_term_loan_step,
    ("投资计划", 26): _interest_rate_step,
    ("投资计划", 29): _annual_static_split_step,
    ("投资计划", 28): _loan_balance_step,
    ("投资计划", (24, 27, 30, 31, 32)): _aux_block_step,
    ("投资计划", 7): _construction_interest_step,
    ("投资计划", 12): _equity_for_construction_step,
    ("投资计划", 20): _other_step,
    ("投资计划", 25): _dynamic_investment_step,
    ("投资计划", 6): _construction_investment_step,
    ("投资计划", 5): _total_investment_step,
    ("投资计划", 9): _dynamic_step,
    ("投资计划", 11): _equity_step,
    ("投资计划", 4): _equity_ratio_step,
    ("投资计划", 16): _loan_principal_step,
    ("投资计划", (15, 17)): _long_term_loan_step,
    ("投资计划", 14): _loan_step,
    ("投资计划", 10): _funding_step,
}



# ── Domain calculation schema ─────────────────────────────────────

from solar_v2.schema import DomainSchema, ItemSchema  # noqa: E402

SCHEMA = DomainSchema(
    key="invest",
    sheet="投资计划",
    label="投资计划与资金筹措表 (Invest)",
    depends_on=("params",),
    items=(
        ItemSchema(
            key="static_investment_ratio",
            label="静态投资完成比例",
            unit="%",
            formula="params:epc_contract_price split ratios (row 3) — per-period allocation",
            inputs=(),
            rows=(3,),
        ),
        ItemSchema(
            key="equity_ratio_schedule",
            label="资本金使用比例",
            unit="%",
            formula="per-period equity / total equity per construction period",
            inputs=("equity_capital",),
            rows=(4,),
        ),
        ItemSchema(
            key="total_investment",
            label="总投资",
            unit="万元",
            formula="construction_investment + construction_interest + working_capital",
            inputs=("construction_investment", "construction_interest", "working_capital"),
            rows=(5,),
        ),
        ItemSchema(
            key="construction_investment",
            label="建设投资",
            unit="万元",
            formula="static investment + land costs (cost:deductible_vat + cost:land_rent_original); per-period from static_investment_ratio",
            inputs=("params:static_investment", "cost:deductible_vat", "cost:land_rent_original"),
            rows=(6,),
        ),
        ItemSchema(
            key="construction_interest",
            label="建设期利息",
            unit="万元",
            formula="annual interest from aux block, echo of row 32 per construction period",
            inputs=("annual_interest", "annual_loan"),
            rows=(7,),
        ),
        ItemSchema(
            key="working_capital",
            label="流动资金",
            unit="万元",
            formula="params:working_capital_total split across periods",
            inputs=("params:working_capital_total",),
            rows=(8,),
        ),
        ItemSchema(
            key="dynamic_investment",
            label="动态投资",
            unit="万元",
            formula="construction_investment + construction_interest (per period)",
            inputs=("construction_investment", "construction_interest"),
            rows=(9,),
        ),
        ItemSchema(
            key="funding_sources",
            label="资金筹措",
            unit="万元",
            formula="equity_capital + total_loan per period",
            inputs=("equity_capital", "total_loan"),
            rows=(10,),
        ),
        ItemSchema(
            key="equity_capital",
            label="自有资金（资本金）",
            unit="万元",
            formula="equity_for_construction + equity_for_working_capital per period",
            inputs=("equity_for_construction", "equity_for_working_capital"),
            rows=(11,),
        ),
        ItemSchema(
            key="equity_for_construction",
            label="自有资金用于建设投资",
            unit="万元",
            formula="equity_ratio × static_investment_ratio over construction periods",
            inputs=("params:equity_ratio", "static_investment_ratio"),
            rows=(12,),
        ),
        ItemSchema(
            key="equity_for_working_capital",
            label="自有资金用于流动资金",
            unit="万元",
            formula="working_capital × equity_ratio",
            inputs=("working_capital", "params:equity_ratio"),
            rows=(13,),
        ),
        ItemSchema(
            key="total_loan",
            label="借款",
            unit="万元",
            formula="long_term_loan + working_capital_loan + short_term_loan + other_funding per period",
            inputs=("long_term_loan", "working_capital_loan", "short_term_loan"),
            rows=(14,),
        ),
        ItemSchema(
            key="long_term_loan",
            label="长期借款（含利息）",
            unit="万元",
            formula="long_term_loan_principal + long_term_loan_interest per period",
            inputs=("long_term_loan_principal", "long_term_loan_interest"),
            rows=(15,),
        ),
        ItemSchema(
            key="long_term_loan_principal",
            label="长期借款本金",
            unit="万元",
            formula="annual loan split per construction period; G16 = construction_investment − equity_for_construction",
            inputs=("annual_loan", "construction_investment", "equity_for_construction"),
            rows=(16,),
        ),
        ItemSchema(
            key="long_term_loan_interest",
            label="长期借款利息",
            unit="万元",
            formula="construction_interest block (per period)",
            inputs=("construction_interest",),
            rows=(17,),
        ),
        ItemSchema(
            key="working_capital_loan",
            label="流动资金借款",
            unit="万元",
            formula="working_capital × (1 − equity_ratio)",
            inputs=("working_capital", "params:equity_ratio"),
            rows=(18,),
        ),
        ItemSchema(
            key="short_term_loan",
            label="其他短期贷款",
            unit="万元",
            formula="0 (all periods)",
            inputs=(),
            rows=(19,),
        ),
        ItemSchema(
            key="other_funding",
            label="其他",
            unit="万元",
            formula="echo of construction_interest per final period",
            inputs=("construction_interest",),
            rows=(20,),
        ),
        ItemSchema(
            key="aux_total_investment",
            label="辅助表：总投资",
            unit="万元",
            formula="total_investment B column echo (辅助测算表)",
            inputs=("total_investment",),
            rows=(24,),
        ),
        ItemSchema(
            key="aux_dynamic_investment",
            label="辅助表：动态投资",
            unit="万元",
            formula="dynamic_investment echo from aux block",
            inputs=("dynamic_investment",),
            rows=(25,),
        ),
        ItemSchema(
            key="aux_static_investment",
            label="辅助表：静态投资",
            unit="万元",
            formula="static investment + loan interest rate (aux block)",
            inputs=("params:loan_rate_long",),
            rows=(26,),
        ),
        ItemSchema(
            key="aux_equity",
            label="辅助表：资本金",
            unit="万元",
            formula="equity_capital split per period (aux block)",
            inputs=("equity_capital",),
            rows=(27,),
        ),
        ItemSchema(
            key="aux_loan_balance",
            label="辅助表：贷款",
            unit="万元",
            formula="static_investment − equity_capital (aux block)",
            inputs=("aux_static_investment", "aux_equity"),
            rows=(28,),
        ),
        ItemSchema(
            key="annual_static_split",
            label="年度静态投资",
            unit="万元",
            formula="aux_static_investment × static_investment_ratio per period",
            inputs=("aux_static_investment", "static_investment_ratio"),
            rows=(29,),
        ),
        ItemSchema(
            key="annual_equity",
            label="年度资本金",
            unit="万元",
            formula="aux_equity × static_investment_ratio per period",
            inputs=("aux_equity", "static_investment_ratio"),
            rows=(30,),
        ),
        ItemSchema(
            key="annual_loan",
            label="年度贷款",
            unit="万元",
            formula="annual_static_split − annual_equity per period",
            inputs=("annual_static_split", "annual_equity"),
            rows=(31,),
        ),
        ItemSchema(
            key="annual_interest",
            label="年度利息",
            unit="万元",
            formula="cumulative loan × loan_rate_long (construction interest)",
            inputs=("annual_loan", "params:loan_rate_long"),
            rows=(32,),
        ),
    ),
)
