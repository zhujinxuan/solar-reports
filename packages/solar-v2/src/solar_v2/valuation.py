"""ValuationAndKPI — 估值结果 (equity valuation) + 指标汇总 (KPI summary).

Covers both sheets in one module: 471 formula cells (估值结果) + 81 formula
cells (指标汇总). Includes IRR/NPV/payback utility functions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from xlsx_core.model import Scalar

from solar_v2.cols import col_letters
from solar_v2.params import Params
from solar_v2.pipeline import ValueView
from solar_v2.schedule import Step

StepFn = Callable[[Params, ValueView], Mapping[str, Scalar]]

VAL = "估值结果"
KPI = "指标汇总"

# ---------------------------------------------------------------------------
# Column ranges
# ---------------------------------------------------------------------------
VAL_25 = col_letters("B", 25)  # B..Z  — 25-year axis (income approach)
VAL_20 = col_letters("B", 20)  # B..U  — 20-year axis (market approach)
CF_25 = col_letters("E", 25)  # E..AC — 现金流量 25 years
BS_25 = col_letters("D", 25)  # D..AB — 资产负债 25 years
CF_20 = col_letters("E", 20)  # E..X  — 现金流量 20 years
COST_20 = col_letters("E", 20)  # E..X  — 成本 20 years

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nid(sheet: str, col: str, row: int) -> str:
    return f"{sheet}!{col}{row}"


def _num(view: ValueView, node_id: str) -> float:
    v = view.get(node_id)
    return float(v) if isinstance(v, (int, float)) else 0.0


def _f(v: Scalar) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


# ---------------------------------------------------------------------------
# IRR / NPV / Payback utilities
# ---------------------------------------------------------------------------


def _npv_at(rate: float, cashflows: list[float]) -> float:
    """NPV of cash flows at rate r, t=0 aligned."""
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cashflows))


def npv(rate: float, cashflows: list[float]) -> float:
    """Net present value of a series of cash flows."""
    return _npv_at(rate, cashflows)


def irr(
    cashflows: list[float],
    guess: float = 0.1,
    tol: float = 1e-10,
    max_iter: int = 200,
) -> float:
    """Internal rate of return: Newton-Raphson with bisection fallback."""
    if (
        not cashflows
        or all(c <= 0 for c in cashflows)
        or all(c >= 0 for c in cashflows)
    ):
        return 0.0

    # Newton-Raphson
    r = guess
    for _ in range(max_iter):
        fv = 0.0
        dv = 0.0
        for t, cf in enumerate(cashflows):
            d = (1.0 + r) ** t
            fv += cf / d
            if t > 0:
                dv -= t * cf / (d * (1.0 + r))
        if abs(fv) < tol:
            return r
        if dv == 0.0:
            break
        r_next = r - fv / dv
        if r_next <= -1.0:
            r_next = -0.999
        if abs(r_next - r) < tol:
            return r_next
        r = r_next

    # Bisection fallback
    lo, hi = -0.999, 10.0
    flo = _npv_at(lo, cashflows)
    fhi = _npv_at(hi, cashflows)
    if flo * fhi > 0:
        return 0.0
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        fmid = _npv_at(mid, cashflows)
        if abs(fmid) < tol:
            return mid
        if flo * fmid < 0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return (lo + hi) / 2.0


def payback(cumulative: list[float]) -> float:
    """Payback period by linear interpolation of cumulative cash flows."""
    for i in range(len(cumulative)):
        if cumulative[i] >= 0:
            if i == 0:
                return 0.0
            prev = cumulative[i - 1]
            curr = cumulative[i]
            if curr == prev:
                return float(i)
            return (i - 1) + abs(prev) / (curr - prev)
    return float(len(cumulative))


# ===========================================================================
# 估值结果 steps
# ===========================================================================


def _val_benchmark_rate(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 1: B1 = 基准内部收益率 = 参数表!C71."""
    _ = view
    return {_nid(VAL, "B", 1): params.buyer_benchmark_rate}


def _val_net_cashflow(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 5: net cash flow echoes from 现金流量!E59:AC59."""
    _ = params
    return {
        _nid(VAL, vc, 5): _num(view, _nid("现金流量", cc, 59))
        for vc, cc in zip(VAL_25, CF_25, strict=False)
    }


def _val_terminal_value(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 6: 终值 = row5 * (1+rate)^(25-year)."""
    r = params.buyer_benchmark_rate
    out: dict[str, Scalar] = {}
    for i, vc in enumerate(VAL_25):
        year = i + 1
        cf = _num(view, _nid(VAL, vc, 5))
        out[_nid(VAL, vc, 6)] = cf * (1.0 + r) ** (25 - year)
    return out


def _val_sale_price_inc(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 7: 卖出价格 = SUM(trailing row6) / (1+rate)^exponent (income approach)."""
    r = params.buyer_benchmark_rate
    out: dict[str, Scalar] = {}
    for i, vc in enumerate(VAL_25):
        year = i + 1
        trailing = sum(_num(view, _nid(VAL, vc2, 6)) for vc2 in VAL_25[i:])
        exp = 25.0 if year == 1 else float(25 - year)
        out[_nid(VAL, vc, 7)] = trailing / (1.0 + r) ** exp
    return out


def _val_full_equity_price(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 8: 100%股权卖出价格 = echo row 7."""
    _ = params
    return {_nid(VAL, vc, 8): _num(view, _nid(VAL, vc, 7)) for vc in VAL_25}


def _val_capital(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 14: 资本金 = 资产负债!D19:AB19."""
    _ = params
    return {
        _nid(VAL, vc, 14): _num(view, _nid("资产负债", bc, 19))
        for vc, bc in zip(VAL_25, BS_25, strict=False)
    }


def _val_income_tax(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 9: 所得税 = MAX((B8-B14)*C72, 0)."""
    tax = params.equity_sale_tax_rate
    out: dict[str, Scalar] = {}
    for vc in VAL_25:
        val = (_num(view, _nid(VAL, vc, 8)) - _num(view, _nid(VAL, vc, 14))) * tax
        out[_nid(VAL, vc, 9)] = max(val, 0.0)
    return out


def _val_undistributed_profit(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 15: 累计未分配利润 = 资产负债!D20:AB20."""
    _ = params
    return {
        _nid(VAL, vc, 15): _num(view, _nid("资产负债", bc, 20))
        for vc, bc in zip(VAL_25, BS_25, strict=False)
    }


def _val_premium_rate(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 12: 溢价率 = (B7+B15)/B14-1."""
    _ = params
    out: dict[str, Scalar] = {}
    for vc in VAL_25:
        denom = _num(view, _nid(VAL, vc, 14))
        out[_nid(VAL, vc, 12)] = (
            _num(view, _nid(VAL, vc, 7)) + _num(view, _nid(VAL, vc, 15))
        ) / denom - 1.0
    return out


def _val_equity_plus_profit(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 16: 股权+利润分配 = B7+B15."""
    _ = params
    return {
        _nid(VAL, vc, 16): _num(view, _nid(VAL, vc, 7)) + _num(view, _nid(VAL, vc, 15))
        for vc in VAL_25
    }


def _val_stamp_duty(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 10: 印花税 = B16 * 0.05%."""
    _ = params
    return {_nid(VAL, vc, 10): _num(view, _nid(VAL, vc, 16)) * 0.0005 for vc in VAL_25}


def _val_after_tax_return(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 11: 税后收益 = B8-B9-B10."""
    _ = params
    out: dict[str, Scalar] = {}
    for vc in VAL_25:
        out[_nid(VAL, vc, 11)] = (
            _num(view, _nid(VAL, vc, 8))
            - _num(view, _nid(VAL, vc, 9))
            - _num(view, _nid(VAL, vc, 10))
        )
    return out


def _val_premium_rate2(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 17: 溢价率 = B16/B14-1 (20-year axis)."""
    _ = params
    out: dict[str, Scalar] = {}
    for vc in VAL_20:
        denom = _num(view, _nid(VAL, vc, 14))
        out[_nid(VAL, vc, 17)] = _num(view, _nid(VAL, vc, 16)) / denom - 1.0
    return out


# --- Market value method (rows 20-24) ---


def _val_capex(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 20: 资本性支出 = 成本!E31:X31."""
    _ = params
    return {
        _nid(VAL, vc, 20): _num(view, _nid("成本", cc, 31))
        for vc, cc in zip(VAL_20, COST_20, strict=False)
    }


def _val_fcf_in(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 21: 息税前利润-调整所得税+折旧摊销
    = 现金流量!E20 - 现金流量!E19 + 成本!E6."""
    _ = params
    out: dict[str, Scalar] = {}
    for vc, cc in zip(VAL_20, CF_20, strict=False):
        ebit_less_tax = _num(view, _nid("现金流量", cc, 20)) - _num(
            view, _nid("现金流量", cc, 19)
        )
        dep = _num(view, _nid("成本", cc, 6))
        out[_nid(VAL, vc, 21)] = ebit_less_tax + dep
    return out


def _val_fcf_out(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 22: 净现金流量 = echo row 21 (same formula for C:U)."""
    _ = params
    # B22 = B21 (echo); C22:U22 same formula as C21:U21
    out: dict[str, Scalar] = {_nid(VAL, "B", 22): _num(view, _nid(VAL, "B", 21))}
    for vc, cc in zip(VAL_20[1:], CF_20[1:], strict=False):
        ebit_less_tax = _num(view, _nid("现金流量", cc, 20)) - _num(
            view, _nid("现金流量", cc, 19)
        )
        dep = _num(view, _nid("成本", cc, 6))
        out[_nid(VAL, vc, 22)] = ebit_less_tax + dep
    return out


def _val_fcf_terminal(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 23: 终值 = B22*(1+rate)^(20-year)."""
    r = params.buyer_benchmark_rate
    out: dict[str, Scalar] = {}
    for i, vc in enumerate(VAL_20):
        year = i + 1
        cf = _num(view, _nid(VAL, vc, 22))
        out[_nid(VAL, vc, 23)] = cf * (1.0 + r) ** (20 - year)
    return out


def _val_fcf_sale_price(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 24: 卖出价格 = SUM(trailing row23) / (1+rate)^(20-year) (market approach)."""
    r = params.buyer_benchmark_rate
    out: dict[str, Scalar] = {}
    for i, vc in enumerate(VAL_20):
        year = i + 1
        trailing = sum(_num(view, _nid(VAL, vc2, 23)) for vc2 in VAL_20[i:])
        exp = float(20 - year)
        out[_nid(VAL, vc, 24)] = trailing / (1.0 + r) ** exp
    return out


def _val_owners_equity(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 26: 所有者权益 = 资产负债!D18:AB18."""
    _ = params
    return {
        _nid(VAL, vc, 26): _num(view, _nid("资产负债", bc, 18))
        for vc, bc in zip(VAL_25, BS_25, strict=False)
    }


def _val_net_profit(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 27: B27:Z27 = B11-B14."""
    _ = params
    out: dict[str, Scalar] = {}
    for vc in VAL_25:
        out[_nid(VAL, vc, 27)] = _num(view, _nid(VAL, vc, 11)) - _num(
            view, _nid(VAL, vc, 14)
        )
    return out


def _val_discounted_cf(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 28: discounted net cash flows at benchmark rate.
    B28=B5; C28=C5/(1+B1)^(C4-B4); ... Z28=Z5/(1+B1)^(Z4-B4)."""
    r = _num(view, _nid(VAL, "B", 1))
    out: dict[str, Scalar] = {_nid(VAL, "B", 28): _num(view, _nid(VAL, "B", 5))}
    for i, vc in enumerate(VAL_25):
        if i == 0:
            continue
        year = i + 1
        out[_nid(VAL, vc, 28)] = _num(view, _nid(VAL, vc, 5)) / (1.0 + r) ** (year - 1)
    return out


# ===========================================================================
# 指标汇总 steps
# ===========================================================================


def _kpi_row5(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 5: D5=装机容量=参数表!C2, H5=年发电量=参数表!C2*参数表!C7."""
    c2 = params.installed_capacity_mw
    c7 = _num(view, "参数表!C7")
    return {_nid(KPI, "D", 5): c2, _nid(KPI, "H", 5): c2 * c7}


def _kpi_row6(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 6: D6=单位千瓦投资(静态)=参数表!C23, H6=静态投资=参数表!C15."""
    _ = params
    return {
        _nid(KPI, "D", 6): _num(view, "参数表!C23"),
        _nid(KPI, "H", 6): _num(view, "参数表!C15"),
    }


def _kpi_row7(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 7: D7=资本金比例=参数表!C30*100, H7=动态投资=投资计划!C9."""
    _ = params
    return {
        _nid(KPI, "D", 7): params.equity_ratio * 100.0,
        _nid(KPI, "H", 7): _num(view, "投资计划!C9"),
    }


def _kpi_row8(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 8: D8=含税上网电价=参数表!C8."""
    _ = view
    return {_nid(KPI, "D", 8): params.feed_in_tariff}


def _kpi_row9(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 9: D9=年发电小时数=参数表!C7, H9=项目投资IRR(税前)=现金流量!L29."""
    _ = params
    return {
        _nid(KPI, "D", 9): _num(view, "参数表!C7"),
        _nid(KPI, "H", 9): _num(view, "现金流量!L29"),
    }


def _kpi_row10(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 10: D10=H7/H5, H10=资本金IRR(税后)=现金流量!H61*100."""
    _ = params
    h7 = _num(view, _nid(KPI, "H", 7))
    h5 = _num(view, _nid(KPI, "H", 5))
    return {
        _nid(KPI, "D", 10): h7 / h5,
        _nid(KPI, "H", 10): _num(view, "现金流量!H61") * 100.0,
    }


def _kpi_row11(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 11: H11=考虑工程收益的资本金IRR=现金流量!D69*100."""
    _ = params
    return {_nid(KPI, "H", 11): _num(view, "现金流量!D69") * 100.0}


def _kpi_row12(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 12: D12=年均经营成本=成本!AD22/25."""
    _ = params
    return {_nid(KPI, "D", 12): _num(view, "成本!AD22") / 25.0}


def _kpi_row15(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 15: H15=贷款还贷年限=参数表!C32."""
    return {_nid(KPI, "H", 15): float(params.loan_years)}


def _kpi_row21(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 21: D21=装机容量=参数表!C2 (defined name: 装机容量)."""
    _ = view
    return {_nid(KPI, "D", 21): params.installed_capacity_mw}


def _kpi_row22(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 22: D22=年发电量=H5, H22=项目投资回收期=现金流量!I31."""
    _ = params
    return {
        _nid(KPI, "D", 22): _num(view, _nid(KPI, "H", 5)),
        _nid(KPI, "H", 22): _num(view, "现金流量!I31"),
    }


def _kpi_row23(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 23: D23=总投资=投资计划!C5, H23=项目投资IRR(税前)=现金流量!L29."""
    _ = params
    return {
        _nid(KPI, "D", 23): _num(view, "投资计划!C5"),
        _nid(KPI, "H", 23): _num(view, "现金流量!L29"),
    }


def _kpi_row24(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 24: D24=建设期利息=投资计划!H7, H24=项目投资NPV(税前)=现金流量!L30."""
    _ = params
    return {
        _nid(KPI, "D", 24): _num(view, "投资计划!H7"),
        _nid(KPI, "H", 24): _num(view, "现金流量!L30"),
    }


def _kpi_row25(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 25: D25=流动资金=投资计划!C8."""
    _ = params
    return {_nid(KPI, "D", 25): _num(view, "投资计划!C8")}


def _kpi_row26(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 26: H26=项目投资IRR(税后)=现金流量!I29."""
    _ = params
    return {_nid(KPI, "H", 26): _num(view, "现金流量!I29")}


def _kpi_row28(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 28: D28=上网电价(含增值税)=参数表!C8, H28=投资方IRR=现金流量!H97*100."""
    _ = params
    return {
        _nid(KPI, "D", 28): params.feed_in_tariff,
        _nid(KPI, "H", 28): _num(view, "现金流量!H97") * 100.0,
    }


def _kpi_row27(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 27: D27=D28/(1+增值税率), H27=资本金IRR=现金流量!H61*100."""
    vat_rate = params.vat_rate
    return {
        _nid(KPI, "D", 27): _num(view, _nid(KPI, "D", 28)) / (1.0 + vat_rate),
        _nid(KPI, "H", 27): _num(view, "现金流量!H61") * 100.0,
    }


def _kpi_row30(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 30: D30=发电销售收入总额=损益!AF8, H30=项目投资NPV=现金流量!I30."""
    _ = params
    return {
        _nid(KPI, "D", 30): _num(view, "损益!AF8"),
        _nid(KPI, "H", 30): _num(view, "现金流量!I30"),
    }


def _kpi_row31(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 31: D31=总成本费用总额=成本!AD21, H31=资本金NPV(ic=8%)=现金流量!H62."""
    _ = params
    return {
        _nid(KPI, "D", 31): _num(view, "成本!AD21"),
        _nid(KPI, "H", 31): _num(view, "现金流量!H62"),
    }


def _kpi_row32(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 32: D32=销售税金附加总额=损益!AF9, H32=投资方NPV(ic=8%)=现金流量!H98."""
    _ = params
    return {
        _nid(KPI, "D", 32): _num(view, "损益!AF9"),
        _nid(KPI, "H", 32): _num(view, "现金流量!H98"),
    }


def _kpi_row33(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 33: D33=发电利润总额=损益!AF15, H33=D10."""
    _ = params
    return {
        _nid(KPI, "D", 33): _num(view, "损益!AF15"),
        _nid(KPI, "H", 33): _num(view, _nid(KPI, "D", 10)),
    }


def _kpi_row34(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 34: D34=年均经营成本=成本!AD22/25, H34=投资利润率=D33/总投资/25*100."""
    _ = params
    total_invest = _num(view, _nid(KPI, "D", 23))
    return {
        _nid(KPI, "D", 34): _num(view, "成本!AD22") / 25.0,
        _nid(KPI, "H", 34): _num(view, _nid(KPI, "D", 33))
        / total_invest
        / 25.0
        * 100.0,
    }


def _kpi_row36(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 36: D36=D34/装机容量, H36=资本金净利润率=损益!AF26/25/投资计划!C11*100."""
    cap = params.installed_capacity_mw
    d34 = _num(view, _nid(KPI, "D", 34))
    return {
        _nid(KPI, "D", 36): d34 / cap,
        _nid(KPI, "H", 36): (
            _num(view, "损益!AF26") / 25.0 / _num(view, "投资计划!C11") * 100.0
        ),
    }


def _kpi_row38(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 38: D38=年发电小时数=参数表!C7, H38=最大资产负债率=资产负债!D28*100."""
    _ = params
    return {
        _nid(KPI, "D", 38): _num(view, "参数表!C7"),
        _nid(KPI, "H", 38): _num(view, "资产负债!D28") * 100.0,
    }


def _kpi_row13(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 13: D13=D12/年发电量, H13=H38."""
    d12 = _num(view, _nid(KPI, "D", 12))
    nfd = _num(view, _nid(KPI, "D", 22))  # 年发电量 = D22
    return {
        _nid(KPI, "D", 13): d12 / nfd,
        _nid(KPI, "H", 13): _num(view, _nid(KPI, "H", 38)),
    }


def _kpi_row39(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 39: D39=D23/D22, H39=最大累计亏损额=MIN(0,损益!AF16)."""
    _ = params
    return {
        _nid(KPI, "D", 39): _num(view, _nid(KPI, "D", 23))
        / _num(view, _nid(KPI, "D", 22)),
        _nid(KPI, "H", 39): min(0.0, _num(view, "损益!AF16")),
    }


def _kpi_row40(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 40: D40=单位千瓦投资(静态)=参数表!C23, H40=累计最大短期借款=财务计划!C22."""
    _ = params
    return {
        _nid(KPI, "D", 40): _num(view, "参数表!C23"),
        _nid(KPI, "H", 40): _num(view, "财务计划!C22"),
    }


def _kpi_row14(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 14: D14=D12/装机容量, H14=H40."""
    d12 = _num(view, _nid(KPI, "D", 12))
    cap = params.installed_capacity_mw
    return {
        _nid(KPI, "D", 14): d12 / cap,
        _nid(KPI, "H", 14): _num(view, _nid(KPI, "H", 40)),
    }


def _kpi_row41(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 41: D41=资本金比例=参数表!C30*100, H41=长期借款还贷年限=参数表!C32."""
    return {
        _nid(KPI, "D", 41): params.equity_ratio * 100.0,
        _nid(KPI, "H", 41): float(params.loan_years),
    }


def _kpi_row42(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 42: H42=全部贷款还贷年限=参数表!C32."""
    return {_nid(KPI, "H", 42): float(params.loan_years)}


def _kpi_row43(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 43: D43=资本金出资额=投资计划!B27, H43=利息备付率(平均)=还贷!AD29."""
    _ = params
    return {
        _nid(KPI, "D", 43): _num(view, "投资计划!B27"),
        _nid(KPI, "H", 43): _num(view, "还贷!AD29"),
    }


def _kpi_row44(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 44: D44=电站转让净利润=估值结果!B11-B14, H44=偿债备付率=还贷!AD32."""
    _ = params
    return {
        _nid(KPI, "D", 44): _num(view, _nid(VAL, "B", 11))
        - _num(view, _nid(VAL, "B", 14)),
        _nid(KPI, "H", 44): _num(view, "还贷!AD32"),
    }


def _kpi_row45(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 45: D45=工程收益, H45=总投资收益率(ROI)=现金流量!AD20/25/总投资."""
    epc = params.epc_contract_price  # C73
    epc_cost = params.epc_cost_price  # C74
    cap = params.installed_capacity_mw  # C2
    mgmt = params.mgmt_allocation_ratio  # C75
    tax = params.equity_sale_tax_rate  # C72

    # ((C73-C74)*C2 - C73*C2/(1+12%)*C75 - ((C73-C74)*C2/(1+12%)*12%*1.12)) * (1-C72)
    d45 = (
        cap
        * ((epc - epc_cost) - epc / 1.12 * mgmt - (epc - epc_cost) / 1.12 * 0.12 * 1.12)
        * (1.0 - tax)
    )

    total_invest = _num(view, _nid(KPI, "D", 23))
    return {
        _nid(KPI, "D", 45): d45,
        _nid(KPI, "H", 45): _num(view, "现金流量!AD20") / 25.0 / total_invest,
    }


def _kpi_row46(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 46: D46=D44+D45."""
    _ = params
    return {
        _nid(KPI, "D", 46): _num(view, _nid(KPI, "D", 44))
        + _num(view, _nid(KPI, "D", 45))
    }


def _kpi_row51(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 51: D51=固定资产折旧=成本!AD6+成本!AD12, H51=所得税金额=损益!AF21."""
    _ = params
    return {
        _nid(KPI, "D", 51): _num(view, "成本!AD6") + _num(view, "成本!AD12"),
        _nid(KPI, "H", 51): _num(view, "损益!AF21"),
    }


def _kpi_scc_50_52(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """SCC rows (50,52):
    D50=成本!AD8; D52=现金流量!AD55+现金流量!AD56;
    G50=C52(literal), H50=D52, I50=E52(literal);
    H52=H50+H51."""
    _ = params
    d50 = _num(view, "成本!AD8")
    d52 = _num(view, "现金流量!AD55") + _num(view, "现金流量!AD56")
    # G50, I50 are literals in the actual cells (text labels), but they're formula cells
    # in the DAG. G50=C52 (echoes the literal text), I50=E52 (echoes unit literal).
    g50 = "生产税（增值税、增值税附加税等）金额"
    i50 = "万元"
    h51 = _num(view, _nid(KPI, "H", 51))
    return {
        _nid(KPI, "D", 50): d50,
        _nid(KPI, "G", 50): g50,
        _nid(KPI, "H", 50): d52,
        _nid(KPI, "I", 50): i50,
        _nid(KPI, "D", 52): d52,
        _nid(KPI, "H", 52): d52 + h51,
    }


def _kpi_row35(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 35: D35=D34/年发电量, H35=(D52+损益!AF21)/25/总投资*100."""
    d34 = _num(view, _nid(KPI, "D", 34))
    nfd = _num(view, _nid(KPI, "D", 22))
    d52 = _num(view, _nid(KPI, "D", 52))
    total_invest = _num(view, _nid(KPI, "D", 23))
    return {
        _nid(KPI, "D", 35): d34 / nfd,
        _nid(KPI, "H", 35): (d52 + _num(view, "损益!AF21"))
        / 25.0
        / total_invest
        * 100.0,
    }


def _kpi_row53(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 53: D53=利润总额=损益!AF15."""
    _ = params
    return {_nid(KPI, "D", 53): _num(view, "损益!AF15")}


def _kpi_row54(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 54: D54=利息=成本!AD13, H54=H53*年发电量/1000000."""
    _ = params
    nfd = _num(view, _nid(KPI, "D", 22))
    return {
        _nid(KPI, "D", 54): _num(view, "成本!AD13"),
        _nid(KPI, "H", 54): 306.9 * nfd / 1000000.0,
    }


def _kpi_row55(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 55: D55=D53+D52+D51+D50+D54, H55=H54*2.7."""
    d53 = _num(view, _nid(KPI, "D", 53))
    d52 = _num(view, _nid(KPI, "D", 52))
    d51 = _num(view, _nid(KPI, "D", 51))
    d50 = _num(view, _nid(KPI, "D", 50))
    d54 = _num(view, _nid(KPI, "D", 54))
    h54 = _num(view, _nid(KPI, "H", 54))
    return {
        _nid(KPI, "D", 55): d53 + d52 + d51 + d50 + d54,
        _nid(KPI, "H", 55): h54 * 2.7,
    }


def _kpi_row56(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 56: D56=总投资*0.95, H56=115152/111000."""
    total_invest = _num(view, _nid(KPI, "D", 23))
    return {
        _nid(KPI, "D", 56): total_invest * 0.95,
        _nid(KPI, "H", 56): 115152.0 / 111000.0,
    }


def _kpi_row57(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 57: H57=H55/H56."""
    return {
        _nid(KPI, "H", 57): _num(view, _nid(KPI, "H", 55))
        / _num(view, _nid(KPI, "H", 56))
    }


def _kpi_row58(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 58: D58=D56*D57."""
    return {_nid(KPI, "D", 58): _num(view, _nid(KPI, "D", 56)) * 0.3}


def _kpi_row60(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 60: D60=D58+D55+D59 (D59=4392 literal)."""
    return {
        _nid(KPI, "D", 60): _num(view, _nid(KPI, "D", 58))
        + _num(view, _nid(KPI, "D", 55))
        + 4392.0
    }


def _kpi_row64(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 64: D64=全投资IRR(税前,20年)=现金流量!L33."""
    _ = params
    return {_nid(KPI, "D", 64): _num(view, "现金流量!L33")}


def _kpi_row65(params: Params, view: ValueView) -> Mapping[str, Scalar]:
    """Row 65: D65=资本金IRR(税后,20年)=现金流量!H64."""
    _ = params
    return {_nid(KPI, "D", 65): _num(view, "现金流量!H64")}


# ===========================================================================
# UNITS registry
# ===========================================================================

UNITS: dict[Step, StepFn] = {
    # --- 估值结果 ---
    (VAL, 1): _val_benchmark_rate,
    (VAL, 5): _val_net_cashflow,
    (VAL, 6): _val_terminal_value,
    (VAL, 7): _val_sale_price_inc,
    (VAL, 8): _val_full_equity_price,
    (VAL, 14): _val_capital,
    (VAL, 9): _val_income_tax,
    (VAL, 15): _val_undistributed_profit,
    (VAL, 12): _val_premium_rate,
    (VAL, 16): _val_equity_plus_profit,
    (VAL, 10): _val_stamp_duty,
    (VAL, 11): _val_after_tax_return,
    (VAL, 17): _val_premium_rate2,
    (VAL, 20): _val_capex,
    (VAL, 21): _val_fcf_in,
    (VAL, 22): _val_fcf_out,
    (VAL, 23): _val_fcf_terminal,
    (VAL, 24): _val_fcf_sale_price,
    (VAL, 26): _val_owners_equity,
    (VAL, 27): _val_net_profit,
    (VAL, 28): _val_discounted_cf,
    # --- 指标汇总 ---
    (KPI, 5): _kpi_row5,
    (KPI, 6): _kpi_row6,
    (KPI, 7): _kpi_row7,
    (KPI, 8): _kpi_row8,
    (KPI, 9): _kpi_row9,
    (KPI, 10): _kpi_row10,
    (KPI, 11): _kpi_row11,
    (KPI, 12): _kpi_row12,
    (KPI, 15): _kpi_row15,
    (KPI, 21): _kpi_row21,
    (KPI, 22): _kpi_row22,
    (KPI, 23): _kpi_row23,
    (KPI, 24): _kpi_row24,
    (KPI, 25): _kpi_row25,
    (KPI, 26): _kpi_row26,
    (KPI, 28): _kpi_row28,
    (KPI, 27): _kpi_row27,
    (KPI, 30): _kpi_row30,
    (KPI, 31): _kpi_row31,
    (KPI, 32): _kpi_row32,
    (KPI, 33): _kpi_row33,
    (KPI, 34): _kpi_row34,
    (KPI, 36): _kpi_row36,
    (KPI, 38): _kpi_row38,
    (KPI, 13): _kpi_row13,
    (KPI, 39): _kpi_row39,
    (KPI, 40): _kpi_row40,
    (KPI, 14): _kpi_row14,
    (KPI, 41): _kpi_row41,
    (KPI, 42): _kpi_row42,
    (KPI, 43): _kpi_row43,
    (KPI, 44): _kpi_row44,
    (KPI, 45): _kpi_row45,
    (KPI, 46): _kpi_row46,
    (KPI, 51): _kpi_row51,
    (KPI, (50, 52)): _kpi_scc_50_52,
    (KPI, 35): _kpi_row35,
    (KPI, 53): _kpi_row53,
    (KPI, 54): _kpi_row54,
    (KPI, 55): _kpi_row55,
    (KPI, 56): _kpi_row56,
    (KPI, 57): _kpi_row57,
    (KPI, 58): _kpi_row58,
    (KPI, 60): _kpi_row60,
    (KPI, 64): _kpi_row64,
    (KPI, 65): _kpi_row65,
}
