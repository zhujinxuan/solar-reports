"""FinancingPlan — 财务计划现金流量表 (sources & uses of funds).


Fine steps (per-column, 14 rows): 5,11,15,17,18,22,24,28,30,31,33,34,40,41
Coarse steps (remaining): 4,6,7,8,10,12,13,14,16,19,20,21,25,26,27,32,36,38,39,42

Column layout: D=construction, E..AC=25 operating years.
Cross-sheet column offsets (from 财务计划 col to other sheet col):
  损益:      +2  (E->G)
  参数表:    -1  (E->D)
  投资计划:  +2  (D->F, E->G)
  现金流量/成本/还贷: 0
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from xlsx_core.model import ErrorValue, Scalar

from solar_v2.cols import col_index, col_letters, col_name
from solar_v2.params import Params
from solar_v2.pipeline import FineStepFn, ValueView
from solar_v2.schedule import Step

StepFn = Callable[[Params, ValueView], Mapping[str, Scalar]]

SHEET = "财务计划"
ALL_YR_COLS = ["D", *col_letters("E", 25)]
OP_COLS = col_letters("E", 25)
TOTAL_COL = "AD"


def _nid(col: str, row: int) -> str:
    return f"{SHEET}!{col}{row}"


def _num(view: ValueView, node_id: str) -> float:
    v = view.get(node_id)
    return float(v) if isinstance(v, (int, float)) else 0.0


def _xcol(col: str, offset: int) -> str:
    return col_name(col_index(col) + offset)


def _prev_col(col: str) -> str | None:
    idx = col_index(col)
    return col_name(idx - 1) if idx > 0 else None


# ---- coarse steps ----

def _row4_year_labels(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    _ = params
    return {_nid(c, 4): _num(view, f"成本!{c}4") for c in ALL_YR_COLS}


def _row6_op_inflow(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    _ = params
    out = {_nid("D", 6): 0.0}
    for c in OP_COLS:
        out[_nid(c, 6)] = (
            _num(view, _nid(c, 7)) + _num(view, _nid(c, 8))
            + _num(view, _nid(c, 9)) - _num(view, _nid(c, 10))
        )
    return out


def _row7_sales_revenue(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    _ = params
    return {
        _nid(c, 7): (
            _num(view, f"损益!{_xcol(c,2)}8") + _num(view, f"损益!{_xcol(c,2)}12")
        )
        for c in OP_COLS
    }


def _row8_vat(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    _ = params
    out = {_nid(c, 8): _num(view, f"损益!{_xcol(c,2)}37") for c in OP_COLS}
    out[_nid(TOTAL_COL, 8)] = sum(
        _num(view, f"损益!{_xcol(c,2)}37") for c in OP_COLS
    )
    return out


def _row10_subsidy_shortfall(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    _ = params
    tariff = _num(view, "参数表!C11")
    out: dict[str, Scalar] = {}
    for c in OP_COLS:
        pc = _xcol(c, -1)
        xc = _xcol(c, 2)
        out[_nid(c, 10)] = (
            (1.0 - _num(view, f"参数表!{pc}13"))
            * tariff
            * _num(view, f"损益!{xc}47")
        )
    return out


def _row12_operating_cost(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    _ = params
    out = {_nid(c, 12): _num(view, f"现金流量!{c}53") for c in OP_COLS}
    out[_nid(TOTAL_COL, 12)] = sum(
        _num(view, f"现金流量!{c}53") for c in OP_COLS
    )
    return out


def _row13_city_tax(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    _ = params
    out = {_nid(c, 13): _num(view, f"现金流量!{c}56") for c in OP_COLS}
    out[_nid(TOTAL_COL, 13)] = sum(
        _num(view, f"现金流量!{c}56") for c in OP_COLS
    )
    return out


def _row14_large_rent(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    _ = params
    out = {_nid(c, 14): _num(view, f"参数表!{_xcol(c,-1)}68") for c in OP_COLS}
    out[_nid(TOTAL_COL, 14)] = sum(
        _num(view, f"参数表!{_xcol(c,-1)}68") for c in OP_COLS
    )
    return out


def _row16_vat_payable(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    _ = params
    out = {_nid(c, 16): _num(view, f"现金流量!{c}55") for c in OP_COLS}
    out[_nid(TOTAL_COL, 16)] = sum(
        _num(view, f"现金流量!{c}55") for c in OP_COLS
    )
    return out


def _row19_equity(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    _ = params
    return {
        _nid("D", 19): _num(view, f"投资计划!{_xcol('D',2)}11"),
        _nid("E", 19): _num(view, f"投资计划!{_xcol('E',2)}11"),
    }


def _row20_construction_loan(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    _ = params
    return {_nid("D", 20): _num(view, "还贷!D6")}


def _row21_wc_loan(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    _ = params
    return {_nid("E", 21): _num(view, f"投资计划!{_xcol('E',2)}18")}


def _row25_construction_investment(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    _ = params
    return {
        _nid("D", 25): _num(view, f"投资计划!{_xcol('D',2)}10"),
        _nid("E", 25): _num(view, f"投资计划!{_xcol('E',2)}15"),
    }


def _row26_working_capital(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    _ = params
    return {_nid("E", 26): _num(view, f"投资计划!{_xcol('E',2)}8")}


def _row27_lt_loan_repay(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    _ = params
    out = {_nid(c, 27): _num(view, f"还贷!{c}10") for c in OP_COLS}
    out[_nid(TOTAL_COL, 27)] = sum(_num(view, f"还贷!{c}10") for c in OP_COLS)
    return out


def _row32_other_outflow(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    _ = params, view
    out = {_nid(c, 32): 0.0 for c in ALL_YR_COLS}
    out[_nid(TOTAL_COL, 32)] = 0.0
    return out


def _row36_errors(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    _ = params
    out: dict[str, Scalar] = {_nid("D", 36): 0.0}
    out[_nid("E", 36)] = 0.0
    for i in range(2, len(ALL_YR_COLS)):
        curr_col = ALL_YR_COLS[i]
        prev_col = ALL_YR_COLS[i - 1]
        two_back_col = ALL_YR_COLS[i - 2]
        prev_repay = _num(view, _nid(prev_col, 28))
        curr_repay = _num(view, _nid(curr_col, 28))
        if prev_repay + curr_repay == 0 or curr_repay > 0:
            out[_nid(curr_col, 36)] = 0.0
        else:
            two_back_repay = _num(view, _nid(two_back_col, 28))
            if two_back_repay == 0:
                out[_nid(curr_col, 36)] = ErrorValue(error="#DIV/0!")
            else:
                out[_nid(curr_col, 36)] = (
                    _num(view, _nid(two_back_col, 4))
                    + prev_repay / two_back_repay
                )
    out[_nid(TOTAL_COL, 36)] = ErrorValue(error="#REF!")
    return out


def _row38_outflow_excl_dist(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    _ = params
    out: dict[str, Scalar] = {}
    for c in OP_COLS:
        s = sum(_num(view, _nid(c, r)) for r in [25, 26, 27, 28, 29, 30])
        if c == "E":
            out[_nid(c, 38)] = s - _num(view, _nid(c, 18))
        else:
            out[_nid(c, 38)] = s
    return out


def _row39_net_cf_excl_dist(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    _ = params
    return {
        _nid(c, 39): _num(view, _nid(c, 5)) - _num(view, _nid(c, 38))
        for c in OP_COLS
    }


def _row42_cumulative_surplus(
    params: Params, view: ValueView
) -> Mapping[str, Scalar]:
    _ = params
    return {
        _nid(c, 42): (
            _num(view, _nid(c, 5))
            + _num(view, _nid(c, 17))
            - _num(view, _nid(c, 28))
        )
        for c in OP_COLS
    }


# ---- fine steps (per-column) ----

def _fine_row5(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    return {_nid(col, 5): _num(view, _nid(col, 6)) - _num(view, _nid(col, 11))}


def _fine_row11(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    if col in OP_COLS:
        val = sum(_num(view, _nid(col, r)) for r in [12, 13, 14, 15, 16])
    elif col == "D":
        val = 0.0
    else:  # AD
        val = (
            _num(view, _nid(TOTAL_COL, 12))
            + _num(view, _nid(TOTAL_COL, 13))
            + _num(view, _nid(TOTAL_COL, 15))
            + _num(view, _nid(TOTAL_COL, 16))
        )
    return {_nid(col, 11): val}


def _fine_row15(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    if col in OP_COLS:
        val = _num(view, f"现金流量!{col}57")
    else:
        val = sum(_num(view, f"现金流量!{c}57") for c in OP_COLS)
    return {_nid(col, 15): val}


def _fine_row17(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    if col == "AD":
        # AD18 = AD19+AD20+AD21+AD22+AD23 (workbook formula, not per-year sum)
        ad18 = sum(_num(view, _nid("AD", r)) for r in [19, 20, 21, 22, 23])
        ad24 = sum(_num(view, _nid(c, 24)) for c in ALL_YR_COLS)
        return {_nid("AD", 17): ad18 - ad24}
    return {
        _nid(col, 17): _num(view, _nid(col, 18)) - _num(view, _nid(col, 24))
    }


def _fine_row18(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    if col == "AD":
        # AD18 = AD19+AD20+AD21+AD22+AD23
        ad18 = sum(_num(view, _nid("AD", r)) for r in [19, 20, 21, 22, 23])
        return {_nid("AD", 18): ad18}
    return {
        _nid(col, 18): sum(_num(view, _nid(col, r)) for r in [19, 20, 21, 22, 23])
    }


def _fine_row22(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    if col == "C":
        vals = [_num(view, _nid(c, 22)) for c in OP_COLS[1:]]
        return {_nid("C", 22): max(vals) if vals else 0.0}
    op_net = _num(view, _nid(col, 5))
    inv_outflow = _num(view, _nid(col, 24))
    st_repay = _num(view, _nid(col, 28))
    equity = _num(view, _nid(col, 19))
    constr_loan = _num(view, _nid(col, 20))
    wc_loan = _num(view, _nid(col, 21))
    deficit = op_net - inv_outflow - st_repay
    if deficit < 0:
        pc = _prev_col(col)
        prior_cs = _num(view, _nid(pc, 34)) if pc else 0.0
        avail = (
            prior_cs - inv_outflow - st_repay
            + equity + constr_loan + wc_loan + op_net
        )
        if avail >= 0:
            val: Scalar = 0.0
        else:
            val = (
                -prior_cs - op_net - equity
                - constr_loan - wc_loan + inv_outflow + st_repay
            )
    else:
        val = 0.0
    return {_nid(col, 22): val}


def _fine_row24(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    if col == "AD":
        return {_nid("AD", 24): sum(_num(view, _nid(c, 24)) for c in ALL_YR_COLS)}
    return {
        _nid(col, 24): sum(
            _num(view, _nid(col, r)) for r in [25, 26, 27, 30, 31, 32]
        )
    }


def _fine_row28(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    pc = _prev_col(col)
    return {_nid(col, 28): _num(view, _nid(pc, 22)) if pc else 0.0}


def _fine_row30(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    if col in OP_COLS:
        val = _num(view, f"成本!{col}13")
    else:
        val = sum(_num(view, f"成本!{c}13") for c in OP_COLS)
    return {_nid(col, 30): val}


def _fine_row31(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    if col in OP_COLS:
        val = _num(view, _nid(col, 41))
    else:
        val = sum(_num(view, _nid(c, 41)) for c in OP_COLS[1:])
    return {_nid(col, 31): val}


def _fine_row33(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    if col == "AD":
        return {
            _nid("AD", 33): sum(
                _num(view, _nid(c, 33)) for c in OP_COLS[1:]
            )
        }
    return {
        _nid(col, 33): (
            _num(view, _nid(col, 5))
            + _num(view, _nid(col, 17))
            - _num(view, _nid(col, 28))
        )
    }


def _fine_row34(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    if col == "AD":
        return {
            _nid("AD", 34): sum(
                _num(view, _nid(c, 34)) for c in OP_COLS[1:]
            )
        }
    pc = _prev_col(col)
    prior = _num(view, _nid(pc, 34)) if pc else 0.0
    net = _num(view, _nid(col, 33))
    return {_nid(col, 34): prior + net}


def _fine_row40(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    ratio = params.dividend_ratio
    xc = _xcol(col, 2)
    return {_nid(col, 40): _num(view, f"损益!{xc}29") * ratio}


def _fine_row41(params: Params, view: ValueView, col: str) -> Mapping[str, Scalar]:
    _ = params
    return {_nid(col, 41): _num(view, _nid(col, 40))}


# ---- registries ----

UNITS: dict[Step, StepFn] = {
    ("财务计划", 4): _row4_year_labels,
    ("财务计划", 7): _row7_sales_revenue,
    ("财务计划", 8): _row8_vat,
    ("财务计划", 10): _row10_subsidy_shortfall,
    ("财务计划", 6): _row6_op_inflow,
    ("财务计划", 13): _row13_city_tax,
    ("财务计划", 14): _row14_large_rent,
    ("财务计划", 16): _row16_vat_payable,
    ("财务计划", 21): _row21_wc_loan,
    ("财务计划", 26): _row26_working_capital,
    ("财务计划", 32): _row32_other_outflow,
    ("财务计划", 12): _row12_operating_cost,
    ("财务计划", 19): _row19_equity,
    ("财务计划", 20): _row20_construction_loan,
    ("财务计划", 25): _row25_construction_investment,
    ("财务计划", 27): _row27_lt_loan_repay,
    ("财务计划", 36): _row36_errors,
    ("财务计划", 38): _row38_outflow_excl_dist,
    ("财务计划", 39): _row39_net_cf_excl_dist,
    ("财务计划", 42): _row42_cumulative_surplus,
}

UNITS_FINE: dict[tuple[str, int], FineStepFn] = {
    ("财务计划", 5): _fine_row5,
    ("财务计划", 11): _fine_row11,
    ("财务计划", 15): _fine_row15,
    ("财务计划", 17): _fine_row17,
    ("财务计划", 18): _fine_row18,
    ("财务计划", 22): _fine_row22,
    ("财务计划", 24): _fine_row24,
    ("财务计划", 28): _fine_row28,
    ("财务计划", 30): _fine_row30,
    ("财务计划", 31): _fine_row31,
    ("财务计划", 33): _fine_row33,
    ("财务计划", 34): _fine_row34,
    ("财务计划", 40): _fine_row40,
    ("财务计划", 41): _fine_row41,
}



# ── Domain calculation schema ─────────────────────────────────────

from solar_v2.schema import DomainSchema, ItemSchema  # noqa: E402

SCHEMA = DomainSchema(
    key="finplan",
    sheet="财务计划",
    label="财务计划现金流量表 (FinPlan)",
    depends_on=("params", "pnl", "cost", "invest", "debt"),
    items=(
        ItemSchema(
            key="year_labels",
            label="运营年度",
            unit="-",
            formula="成本 row 4 echoed per year",
            inputs=("cost:year_labels",),
            rows=(4,),
        ),
        ItemSchema(
            key="operating_net_cf",
            label="经营活动净现金流量",
            unit="万元",
            formula="operating_inflow − operating_outflow per year",
            inputs=("operating_inflow", "operating_outflow"),
            rows=(5,),
        ),
        ItemSchema(
            key="operating_inflow",
            label="经营活动：现金流入",
            unit="万元",
            formula="sales_revenue + vat + subsidy_shortfall",
            inputs=("sales_revenue", "vat_refund_inflow", "subsidy_shortfall"),
            rows=(6,),
        ),
        ItemSchema(
            key="sales_revenue",
            label="经营活动：销售收入",
            unit="万元",
            formula="pnl:sales_revenue per year",
            inputs=("pnl:sales_revenue",),
            rows=(7,),
        ),
        ItemSchema(
            key="vat_refund_inflow",
            label="经营活动：增值税退税",
            unit="万元",
            formula="pnl:vat_refund per year",
            inputs=("pnl:vat_refund",),
            rows=(8,),
        ),
        ItemSchema(
            key="subsidy_shortfall",
            label="经营活动：补贴未到位资金",
            unit="万元",
            formula="(pnl:guaranteed_sales − pnl:power_generation × subsidy_arrival) × subsidy_per_kwh per year",
            inputs=("pnl:guaranteed_sales", "pnl:power_generation", "params:subsidy_per_kwh"),
            rows=(10,),
        ),
        ItemSchema(
            key="operating_outflow",
            label="经营活动：现金流出",
            unit="万元",
            formula="SUM of rows 12-16 per year",
            inputs=("operating_cost_outflow", "city_tax", "large_rent_payment", "income_tax_outflow", "vat_payable_outflow"),
            rows=(11,),
        ),
        ItemSchema(
            key="operating_cost_outflow",
            label="经营活动：经营成本",
            unit="万元",
            formula="cost:operating_cost per year",
            inputs=("cost:operating_cost",),
            rows=(12,),
        ),
        ItemSchema(
            key="city_tax",
            label="经营活动：城建税及教育附加",
            unit="万元",
            formula="pnl:vat_surcharge_total per year",
            inputs=("pnl:vat_surcharge_total",),
            rows=(13,),
        ),
        ItemSchema(
            key="large_rent_payment",
            label="经营活动：大额租金",
            unit="万元",
            formula="params:land_rent_payment per year (lump-sum)",
            inputs=("params:first_year_land_rent", "params:rent_payment_freq"),
            rows=(14,),
        ),
        ItemSchema(
            key="income_tax_outflow",
            label="经营活动：所得税",
            unit="万元",
            formula="pnl:income_tax per year",
            inputs=("pnl:income_tax",),
            rows=(15,),
        ),
        ItemSchema(
            key="vat_payable_outflow",
            label="经营活动：应缴增值税",
            unit="万元",
            formula="pnl:vat_payable per year",
            inputs=("pnl:vat_payable",),
            rows=(16,),
        ),
        ItemSchema(
            key="invest_finance_net_cf",
            label="投资、筹资活动净现金流量",
            unit="万元",
            formula="invest_inflow − invest_outflow per year",
            inputs=("invest_inflow", "invest_outflow"),
            rows=(17,),
        ),
        ItemSchema(
            key="invest_inflow",
            label="投筹资：现金流入",
            unit="万元",
            formula="SUM(equity, construction_loan, wc_loan, short_term_borrowing) per year",
            inputs=("equity_injection", "construction_loan", "wc_loan", "short_term_borrowing"),
            rows=(18,),
        ),
        ItemSchema(
            key="equity_injection",
            label="投筹资：项目资本金投入",
            unit="万元",
            formula="invest:equity_capital per construction period",
            inputs=("invest:equity_capital",),
            rows=(19,),
        ),
        ItemSchema(
            key="construction_loan",
            label="投筹资：建设投资借款",
            unit="万元",
            formula="debt:long_term_loan_balance initial (D20 = 还贷!D6)",
            inputs=("debt:long_term_loan_balance",),
            rows=(20,),
        ),
        ItemSchema(
            key="wc_loan",
            label="投筹资：流动资金借款",
            unit="万元",
            formula="invest:working_capital_loan per period",
            inputs=("invest:working_capital_loan",),
            rows=(21,),
        ),
        ItemSchema(
            key="short_term_borrowing",
            label="投筹资：短期借款",
            unit="万元",
            formula="cumulative cash shortfall bridge loan per year",
            inputs=(),
            rows=(22,),
        ),
        ItemSchema(
            key="invest_outflow",
            label="投筹资：现金流出",
            unit="万元",
            formula="SUM of rows 25-28+30-32 per year",
            inputs=("construction_investment_outflow", "working_capital_outflow", "lt_loan_repay", "short_term_repayment", "interest_outflow", "profit_distribution"),
            rows=(24,),
        ),
        ItemSchema(
            key="construction_investment_outflow",
            label="投筹资：建设投资",
            unit="万元",
            formula="invest:construction_investment per construction period",
            inputs=("invest:construction_investment",),
            rows=(25,),
        ),
        ItemSchema(
            key="working_capital_outflow",
            label="投筹资：流动资金",
            unit="万元",
            formula="invest:working_capital per period",
            inputs=("invest:working_capital",),
            rows=(26,),
        ),
        ItemSchema(
            key="lt_loan_repay",
            label="投筹资：长期借款本金偿还",
            unit="万元",
            formula="debt:long_term_loan_principal_repay per year",
            inputs=("debt:long_term_loan_principal_repay",),
            rows=(27,),
        ),
        ItemSchema(
            key="short_term_repayment",
            label="投筹资：短期借款本金偿还",
            unit="万元",
            formula="prior year short_term_borrowing repaid per year",
            inputs=("short_term_borrowing",),
            rows=(28,),
        ),
        ItemSchema(
            key="interest_outflow",
            label="投筹资：各种利息支出",
            unit="万元",
            formula="cost:interest_expense per year",
            inputs=("cost:interest_expense",),
            rows=(30,),
        ),
        ItemSchema(
            key="profit_distribution",
            label="投筹资：各投资方利润分配",
            unit="万元",
            formula="pnl:distributable_profit × dividend_ratio per year",
            inputs=("pnl:distributable_profit", "params:dividend_ratio"),
            rows=(31,),
        ),
        ItemSchema(
            key="other_outflow",
            label="投筹资：其他流出",
            unit="万元",
            formula="0 (all years)",
            inputs=(),
            rows=(32,),
        ),
        ItemSchema(
            key="net_cash_flow",
            label="净现金流量",
            unit="万元",
            formula="operating_net_cf + invest_finance_net_cf per year",
            inputs=("operating_net_cf", "invest_finance_net_cf"),
            rows=(33,),
        ),
        ItemSchema(
            key="cumulative_surplus",
            label="累计盈余资金",
            unit="万元",
            formula="cumulative sum of net_cash_flow per year",
            inputs=("net_cash_flow",),
            rows=(34,),
        ),
        ItemSchema(
            key="error_checks",
            label="错误检查行",
            unit="-",
            formula="#REF! error cells (dead IF branches)",
            inputs=(),
            rows=(36,),
        ),
        ItemSchema(
            key="outflow_excl_distribution",
            label="不含利润分配的流出",
            unit="万元",
            formula="invest_outflow − profit_distribution per year",
            inputs=("invest_outflow", "profit_distribution"),
            rows=(38,),
        ),
        ItemSchema(
            key="net_cf_excl_distribution",
            label="净现金流（不含利润分配）",
            unit="万元",
            formula="cash_inflow − outflow_excl_distribution per year (operating + invest inflows − excl-dist outflows)",
            inputs=("operating_inflow", "invest_inflow", "outflow_excl_distribution"),
            rows=(39,),
        ),
        ItemSchema(
            key="distributable_profit_pool",
            label="可分配利润",
            unit="万元",
            formula="pnl:distributable_profit per year (echo from 损益 row 29)",
            inputs=("pnl:distributable_profit",),
            rows=(40,),
        ),
        ItemSchema(
            key="actual_distribution",
            label="实际分配利润",
            unit="万元",
            formula="profit_distribution per year (echo)",
            inputs=("profit_distribution",),
            rows=(41,),
        ),
        ItemSchema(
            key="cumulative_surplus_check",
            label="累计盈余资金(审计)",
            unit="万元",
            formula="recomputed cumulative surplus for audit",
            inputs=("cumulative_surplus",),
            rows=(42,),
        ),
    ),
)
