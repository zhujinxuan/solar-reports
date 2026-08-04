"""CashFlow — 现金流量表 (project/equity/investor cash flow statements).

Three sections:
  - 项目投资现金流量表 (rows 4-33): project cash flow (pre-tax/post-tax)
  - 资本金财务现金流量表 (rows 40-69): equity cash flow
  - 投资方财务现金流量表 (rows 80-98): investor cash flow
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
    from solar_v2.domains.finplan import FinPlanResult
    from solar_v2.domains.invest import InvestResult
    from solar_v2.domains.params import ParamsCore
    from solar_v2.domains.pnl import PnLResult
    from solar_v2.mutual import MutualSolution

# ═══════════════════════════════════════════════════════════════════════════════
# Domain calculation schema
# ═══════════════════════════════════════════════════════════════════════════════

SCHEMA = DomainSchema(
    key="cashflow",
    sheet="现金流量",
    label="现金流量表 (CashFlow)",
    depends_on=(
        "params",
        "invest",
        "debt",
        "cost",
        "pnl",
        "finplan",
        "mutual",
    ),
    items=(
        # ── Project cash flow ──
        ItemSchema(
            key="project_year_labels",
            label="项目现金流量：年份",
            unit="-",
            formula="cost year labels echoed; D=construction year, E..AC=1..25",
            inputs=("params:construction_year",),
            rows=(4,),
            kind="series",
        ),
        ItemSchema(
            key="project_cash_inflow",
            label="项目现金流量：现金流入",
            unit="万元",
            formula=(
                "project_power_sales + project_vat_refund + project_vat_output "
                "+ project_salvage_recovery + project_wc_recovery per year"
            ),
            inputs=(
                "project_power_sales",
                "project_vat_refund",
                "project_vat_output",
                "project_salvage_recovery",
                "project_wc_recovery",
            ),
            rows=(5,),
            kind="series",
        ),
        ItemSchema(
            key="project_power_sales",
            label="项目现金流量：发电销售收入",
            unit="万元",
            formula="pnl:sales_revenue − finplan:subsidy_shortfall per year",
            inputs=("pnl:sales_revenue", "finplan:subsidy_shortfall"),
            rows=(6,),
            kind="series",
        ),
        ItemSchema(
            key="project_vat_refund",
            label="项目现金流量：增值税即征即退补贴",
            unit="万元",
            formula="pnl:vat_refund per year",
            inputs=("pnl:vat_refund",),
            rows=(7,),
            kind="series",
        ),
        ItemSchema(
            key="project_vat_output",
            label="项目现金流量：增值税销项税额",
            unit="万元",
            formula="pnl:output_vat per year",
            inputs=("pnl:output_vat",),
            rows=(8,),
            kind="series",
        ),
        ItemSchema(
            key="project_salvage_recovery",
            label="项目现金流量：回收固定资产余值",
            unit="万元",
            formula="salvage value at Y (20yr) or AC (25yr) per operating_years",
            inputs=("cost:fixed_asset_net_value", "params:operating_years"),
            rows=(9,),
            kind="series",
        ),
        ItemSchema(
            key="project_wc_recovery",
            label="项目现金流量：回收流动资金",
            unit="万元",
            formula="working capital recovery at end of operating period",
            inputs=("invest:working_capital",),
            rows=(10,),
            kind="series",
        ),
        ItemSchema(
            key="project_row11",
            label="项目现金流量：合计行11",
            unit="万元",
            formula="row total (0)",
            inputs=(),
            rows=(11,),
            kind="series",
        ),
        ItemSchema(
            key="project_cash_outflow",
            label="项目现金流量：现金流出",
            unit="万元",
            formula=(
                "SUM of rows 13-19 per year (fixed_asset_invest, wc, vat_payable, "
                "land_rent, op_cost, sales_tax, adjusted_income_tax)"
            ),
            inputs=(
                "project_fixed_asset_invest",
                "project_working_capital",
                "project_vat_payable",
                "project_land_rent",
                "project_operating_cost",
                "project_sales_tax",
                "project_adjusted_income_tax",
            ),
            rows=(12,),
            kind="series",
        ),
        ItemSchema(
            key="project_fixed_asset_invest",
            label="项目现金流量：固定资产投资",
            unit="万元",
            formula="invest:construction_investment at construction periods F, G",
            inputs=("invest:construction_investment",),
            rows=(13,),
            kind="series",
        ),
        ItemSchema(
            key="project_working_capital",
            label="项目现金流量：流动资金",
            unit="万元",
            formula=(
                "invest:working_capital per period mapped via "
                "_invest_col_for_row14 irregularity"
            ),
            inputs=("invest:working_capital",),
            rows=(14,),
            kind="series",
        ),
        ItemSchema(
            key="project_vat_payable",
            label="项目现金流量：应交增值税金",
            unit="万元",
            formula="pnl:vat_payable per year",
            inputs=("pnl:vat_payable",),
            rows=(15,),
            kind="series",
        ),
        ItemSchema(
            key="project_land_rent",
            label="项目现金流量：土地租金",
            unit="万元",
            formula="finplan:large_rent_payment per year",
            inputs=("finplan:large_rent_payment",),
            rows=(16,),
            kind="series",
        ),
        ItemSchema(
            key="project_operating_cost",
            label="项目现金流量：经营成本",
            unit="万元",
            formula="cost:operating_cost per year",
            inputs=("cost:operating_cost",),
            rows=(17,),
            kind="series",
        ),
        ItemSchema(
            key="project_sales_tax",
            label="项目现金流量：销售税金附加",
            unit="万元",
            formula="pnl:vat_surcharge_total per year",
            inputs=("pnl:vat_surcharge_total",),
            rows=(18,),
            kind="series",
        ),
        ItemSchema(
            key="project_adjusted_income_tax",
            label="项目现金流量：调整所得税",
            unit="万元",
            formula="project_ebit × income_tax_rate (first 3 formula years halved)",
            inputs=("project_ebit", "params:income_tax_rate"),
            rows=(19,),
            kind="series",
        ),
        ItemSchema(
            key="project_ebit",
            label="项目现金流量：息税前利润",
            unit="万元",
            formula="pnl:total_profit + cost:interest_expense per year",
            inputs=("pnl:total_profit", "cost:interest_expense"),
            rows=(20,),
            kind="series",
        ),
        ItemSchema(
            key="project_row21",
            label="项目现金流量：合计行21",
            unit="万元",
            formula="row total (0)",
            inputs=(),
            rows=(21,),
            kind="series",
        ),
        ItemSchema(
            key="project_net_cf",
            label="项目现金流量：净现金流量",
            unit="万元",
            formula="project_cash_inflow − project_cash_outflow per year",
            inputs=("project_cash_inflow", "project_cash_outflow"),
            rows=(22,),
            kind="series",
        ),
        ItemSchema(
            key="project_cum_net_cf",
            label="项目现金流量：累计净现金流量",
            unit="万元",
            formula="cumulative sum of project_net_cf",
            inputs=("project_net_cf",),
            rows=(23,),
            kind="series",
        ),
        ItemSchema(
            key="project_payback",
            label="项目现金流量：投资回收期(税后)",
            unit="年",
            formula="linear interpolation when cum_net_cf crosses zero",
            inputs=("project_net_cf", "project_cum_net_cf"),
            rows=(24,),
            kind="series",
        ),
        ItemSchema(
            key="project_pre_tax_net_cf",
            label="项目现金流量：税前净现金流量",
            unit="万元",
            formula="project_net_cf + project_adjusted_income_tax per year",
            inputs=("project_net_cf", "project_adjusted_income_tax"),
            rows=(25,),
            kind="series",
        ),
        ItemSchema(
            key="project_cum_pre_tax_cf",
            label="项目现金流量：累计税前净现金流量",
            unit="万元",
            formula="cumulative sum of project_pre_tax_net_cf",
            inputs=("project_pre_tax_net_cf",),
            rows=(26,),
            kind="series",
        ),
        ItemSchema(
            key="project_payback_pre_tax",
            label="项目现金流量：投资回收期(税前)",
            unit="年",
            formula="linear interpolation when cum_pre_tax_cf crosses zero",
            inputs=("project_pre_tax_net_cf", "project_cum_pre_tax_cf"),
            rows=(27,),
            kind="series",
        ),
        ItemSchema(
            key="project_irr",
            label="项目现金流量：项目投资IRR",
            unit="%",
            formula="IRR of project_net_cf (after/pre-tax) × 100",
            inputs=("project_net_cf", "project_pre_tax_net_cf"),
            rows=(29,),
            kind="scalar",
        ),
        ItemSchema(
            key="project_npv",
            label="项目现金流量：项目投资NPV",
            unit="万元",
            formula="NPV(5%, project_net_cf) after/pre-tax",
            inputs=("project_net_cf", "project_pre_tax_net_cf"),
            rows=(30,),
            kind="scalar",
        ),
        ItemSchema(
            key="project_payback_period",
            label="项目现金流量：投资回收期(汇总)",
            unit="年",
            formula="project_payback and project_payback_pre_tax aggregate values",
            inputs=("project_payback", "project_payback_pre_tax"),
            rows=(31,),
            kind="scalar",
        ),
        ItemSchema(
            key="project_20yr_irr",
            label="项目现金流量：项目投资IRR(20年)",
            unit="%",
            formula="IRR of first 20 years of project_net_cf × 100",
            inputs=("project_net_cf", "project_pre_tax_net_cf"),
            rows=(33,),
            kind="scalar",
        ),
        # ── Equity cash flow ──
        ItemSchema(
            key="equity_year_labels",
            label="资本金现金流量：年份",
            unit="-",
            formula="project_year_labels echoed per year",
            inputs=("project_year_labels",),
            rows=(40,),
            kind="series",
        ),
        ItemSchema(
            key="equity_cash_inflow",
            label="资本金现金流量：现金流入",
            unit="万元",
            formula=(
                "equity_power_sales + equity_vat_refund + equity_vat_output "
                "+ equity_salvage_recovery + equity_wc_recovery per year"
            ),
            inputs=(
                "equity_power_sales",
                "equity_vat_refund",
                "equity_vat_output",
                "equity_salvage_recovery",
                "equity_wc_recovery",
            ),
            rows=(42,),
            kind="series",
        ),
        ItemSchema(
            key="equity_power_sales",
            label="资本金现金流量：发电销售收入",
            unit="万元",
            formula="project_power_sales echoed per year",
            inputs=("project_power_sales",),
            rows=(43,),
            kind="series",
        ),
        ItemSchema(
            key="equity_vat_refund",
            label="资本金现金流量：增值税即征即退补贴",
            unit="万元",
            formula="pnl:vat_refund per year",
            inputs=("pnl:vat_refund",),
            rows=(44,),
            kind="series",
        ),
        ItemSchema(
            key="equity_vat_output",
            label="资本金现金流量：增值税销项税额",
            unit="万元",
            formula="pnl:output_vat per year",
            inputs=("pnl:output_vat",),
            rows=(45,),
            kind="series",
        ),
        ItemSchema(
            key="equity_salvage_recovery",
            label="资本金现金流量：回收固定资产余值",
            unit="万元",
            formula=(
                "F46 = project_salvage_recovery at op yr 1; "
                "Y/AC salvage per operating_years"
            ),
            inputs=("project_salvage_recovery", "cost:fixed_asset_net_value"),
            rows=(46,),
            kind="series",
        ),
        ItemSchema(
            key="equity_wc_recovery",
            label="资本金现金流量：回收流动资金",
            unit="万元",
            formula="0 (always zero)",
            inputs=(),
            rows=(47,),
            kind="series",
        ),
        ItemSchema(
            key="equity_row48",
            label="资本金现金流量：合计行48",
            unit="万元",
            formula="row total (0)",
            inputs=(),
            rows=(48,),
            kind="series",
        ),
        ItemSchema(
            key="equity_cash_outflow",
            label="资本金现金流量：现金流出",
            unit="万元",
            formula=(
                "SUM of rows 50-58 per year (capital, principal, interest, "
                "operating_cost, land_rent, vat_payable, sales_tax, income_tax, "
                "long_term_rent)"
            ),
            inputs=(
                "equity_capital_invest",
                "equity_loan_principal_repay",
                "equity_loan_interest",
                "equity_operating_cost",
                "equity_land_rent",
                "equity_vat_payable",
                "equity_sales_tax",
                "equity_income_tax",
                "equity_long_term_rent",
            ),
            rows=(49,),
            kind="series",
        ),
        ItemSchema(
            key="equity_capital_invest",
            label="资本金现金流量：资本金投入",
            unit="万元",
            formula="invest:equity_capital at construction periods F, G",
            inputs=("invest:equity_capital",),
            rows=(50,),
            kind="series",
        ),
        ItemSchema(
            key="equity_loan_principal_repay",
            label="资本金现金流量：借款本金偿还",
            unit="万元",
            formula=(
                "E..W: debt:total_principal − finplan:short_term_borrowing "
                "+ finplan:short_term_repayment; "
                "X..AC: debt:total_principal − debt:short_term_balance "
                "+ debt:short_term_principal"
            ),
            inputs=(
                "debt:total_principal",
                "debt:short_term_balance",
                "debt:short_term_principal",
                "finplan:short_term_borrowing",
                "finplan:short_term_repayment",
            ),
            rows=(51,),
            kind="series",
        ),
        ItemSchema(
            key="equity_loan_interest",
            label="资本金现金流量：借款利息支付",
            unit="万元",
            formula="cost:interest_expense per year",
            inputs=("cost:interest_expense",),
            rows=(52,),
            kind="series",
        ),
        ItemSchema(
            key="equity_operating_cost",
            label="资本金现金流量：经营成本",
            unit="万元",
            formula="cost:operating_cost per year",
            inputs=("cost:operating_cost",),
            rows=(53,),
            kind="series",
        ),
        ItemSchema(
            key="equity_land_rent",
            label="资本金现金流量：土地租金",
            unit="万元",
            formula="project_land_rent echoed per year",
            inputs=("project_land_rent",),
            rows=(54,),
            kind="series",
        ),
        ItemSchema(
            key="equity_vat_payable",
            label="资本金现金流量：应交增值税",
            unit="万元",
            formula="pnl:vat_payable per year",
            inputs=("pnl:vat_payable",),
            rows=(55,),
            kind="series",
        ),
        ItemSchema(
            key="equity_sales_tax",
            label="资本金现金流量：销售税金附加",
            unit="万元",
            formula="pnl:vat_surcharge_total per year",
            inputs=("pnl:vat_surcharge_total",),
            rows=(56,),
            kind="series",
        ),
        ItemSchema(
            key="equity_income_tax",
            label="资本金现金流量：所得税",
            unit="万元",
            formula="mutual:equity_income_tax per year (coupled)",
            inputs=("pnl:income_tax",),
            rows=(57,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="equity_long_term_rent",
            label="资本金现金流量：长期待摊租金",
            unit="万元",
            formula="project_fixed_asset_invest at E echoed (E58 only)",
            inputs=("project_fixed_asset_invest",),
            rows=(58,),
            kind="series",
        ),
        ItemSchema(
            key="equity_net_cf",
            label="资本金现金流量：净现金流量",
            unit="万元",
            formula="equity_cash_inflow − equity_cash_outflow per year",
            inputs=("equity_cash_inflow", "equity_cash_outflow"),
            rows=(59,),
            kind="series",
        ),
        ItemSchema(
            key="equity_cum_cf",
            label="资本金现金流量：累计净现金流量",
            unit="万元",
            formula="cumulative sum of equity_net_cf",
            inputs=("equity_net_cf",),
            rows=(60,),
            kind="series",
        ),
        ItemSchema(
            key="equity_irr",
            label="资本金现金流量：资本金IRR",
            unit="%",
            formula="IRR of equity_net_cf × 100",
            inputs=("equity_net_cf",),
            rows=(61,),
            kind="scalar",
        ),
        ItemSchema(
            key="equity_npv",
            label="资本金现金流量：资本金NPV",
            unit="万元",
            formula="NPV(8%, equity_net_cf)",
            inputs=("equity_net_cf",),
            rows=(62,),
            kind="scalar",
        ),
        ItemSchema(
            key="equity_20yr_irr",
            label="资本金现金流量：资本金IRR(20年)",
            unit="%",
            formula="IRR of first 21 points (D..Y) of equity_net_cf × 100",
            inputs=("equity_net_cf",),
            rows=(64,),
            kind="scalar",
        ),
        ItemSchema(
            key="equity_adjustment",
            label="资本金现金流量：工程收益调整",
            unit="万元",
            formula=(
                "(epc_cost_price + provisional_sum / 1.09 × (1 − 0.09×0.1)) "
                "× (1 − mgmt_allocation_ratio)"
            ),
            inputs=(
                "params:epc_cost_price",
                "params:provisional_sum",
                "params:mgmt_allocation_ratio",
            ),
            rows=(67,),
            kind="scalar",
        ),
        ItemSchema(
            key="equity_adjusted_cf",
            label="资本金现金流量：调整后净现金流",
            unit="万元",
            formula="equity_adjustment + equity_net_cf per year",
            inputs=("equity_adjustment", "equity_net_cf"),
            rows=(68,),
            kind="series",
        ),
        ItemSchema(
            key="equity_adjusted_irr",
            label="资本金现金流量：调整后IRR",
            unit="%",
            formula="IRR of equity_adjusted_cf",
            inputs=("equity_adjusted_cf",),
            rows=(69,),
            kind="scalar",
        ),
        # ── Investor cash flow ──
        ItemSchema(
            key="investor_year_labels",
            label="投资方现金流量：年份",
            unit="-",
            formula="equity_year_labels echoed per year",
            inputs=("equity_year_labels",),
            rows=(83,),
            kind="series",
        ),
        ItemSchema(
            key="investor_cash_inflow",
            label="投资方现金流量：现金流入",
            unit="万元",
            formula="investor_profit_distribution + investor_asset_disposal per year",
            inputs=("investor_profit_distribution", "investor_asset_disposal"),
            rows=(84,),
            kind="series",
        ),
        ItemSchema(
            key="investor_profit_distribution",
            label="投资方现金流量：利润分配",
            unit="万元",
            formula="pnl:dividend per year",
            inputs=("pnl:dividend",),
            rows=(85,),
            kind="series",
        ),
        ItemSchema(
            key="investor_asset_disposal",
            label="投资方现金流量：资产处置收益分配",
            unit="万元",
            formula="SUM(investor_salvage + investor_surplus_fund) at end period",
            inputs=("investor_salvage", "investor_surplus_fund"),
            rows=(86,),
            kind="series",
        ),
        ItemSchema(
            key="investor_salvage",
            label="投资方现金流量：回收固定资产和无形资产余值",
            unit="万元",
            formula="project_salvage_recovery at AC echoed",
            inputs=("project_salvage_recovery",),
            rows=(87,),
            kind="series",
        ),
        ItemSchema(
            key="investor_surplus_fund",
            label="投资方现金流量：回收累计盈余资金",
            unit="万元",
            formula="finplan:cumulative_surplus at final operating year",
            inputs=("finplan:cumulative_surplus",),
            rows=(88,),
            kind="series",
        ),
        ItemSchema(
            key="investor_cash_outflow",
            label="投资方现金流量：现金流出",
            unit="万元",
            formula=(
                "investor_construction_equity + investor_own_wc per year"
            ),
            inputs=("investor_construction_equity", "investor_own_wc"),
            rows=(91,),
            kind="series",
        ),
        ItemSchema(
            key="investor_construction_equity",
            label="投资方现金流量：建设投资资本金",
            unit="万元",
            formula="equity_capital_invest at D echoed (D92 = D50)",
            inputs=("equity_capital_invest",),
            rows=(92,),
            kind="series",
        ),
        ItemSchema(
            key="investor_own_wc",
            label="投资方现金流量：自有流动资金",
            unit="万元",
            formula="invest:equity_for_working_capital at period G echoed",
            inputs=("invest:equity_for_working_capital",),
            rows=(93,),
            kind="series",
        ),
        ItemSchema(
            key="investor_net_cf",
            label="投资方现金流量：净现金流量",
            unit="万元",
            formula="investor_cash_inflow − investor_cash_outflow per year",
            inputs=("investor_cash_inflow", "investor_cash_outflow"),
            rows=(94,),
            kind="series",
        ),
        ItemSchema(
            key="investor_cum_cf",
            label="投资方现金流量：累计净现金流",
            unit="万元",
            formula="cumulative sum of investor_net_cf",
            inputs=("investor_net_cf",),
            rows=(95,),
            kind="series",
        ),
        ItemSchema(
            key="investor_irr",
            label="投资方现金流量：投资方IRR",
            unit="%",
            formula="IRR of investor_net_cf",
            inputs=("investor_net_cf",),
            rows=(97,),
            kind="scalar",
        ),
        ItemSchema(
            key="investor_npv",
            label="投资方现金流量：投资方NPV",
            unit="万元",
            formula="NPV(8%, investor_net_cf)",
            inputs=("investor_net_cf",),
            rows=(98,),
            kind="scalar",
        ),
    ),
)


# ═══════════════════════════════════════════════════════════════════════════════
# Result types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CashFlowScalars:
    """Scalar outputs of the cash flow analysis."""

    project_irr_after_tax: float
    project_irr_pre_tax: float
    project_npv_after_tax: float
    project_npv_pre_tax: float
    project_20yr_irr_after_tax: float
    project_20yr_irr_pre_tax: float
    project_payback_after_tax: float
    project_payback_pre_tax: float
    equity_irr: float
    equity_npv: float
    equity_20yr_irr: float
    equity_adjustment: float
    equity_adjusted_irr: float
    investor_irr: float
    investor_npv: float


@dataclass(frozen=True)
class CashFlowResult:
    """Project/equity/investor cash flow analysis result."""

    years: tuple[int, ...]
    frame: pl.DataFrame
    scalars: CashFlowScalars


# ═══════════════════════════════════════════════════════════════════════════════
# Numeric helpers (IRR / NPV / payback)
# ═══════════════════════════════════════════════════════════════════════════════


def _npv(rate: float, cashflows: list[float]) -> float:
    """Net present value: Σ CF_t / (1+r)^(t+1), t starting from 0.

    This is the Excel NPV convention (cashflows[0] discounted by 1 period).
    """
    return sum(cf / ((1.0 + rate) ** (t + 1)) for t, cf in enumerate(cashflows))


def _npv_deriv(rate: float, cashflows: list[float]) -> float:
    """Derivative of _npv w.r.t. rate: Σ -(t+1)·CF_t / (1+r)^(t+2)."""
    s = 0.0
    for t, cf in enumerate(cashflows):
        s -= (t + 1) * cf / ((1.0 + rate) ** (t + 2))
    return s


def _irr(
    cashflows: list[float], guess: float = 0.1, max_iter: int = 100
) -> float:
    """Internal rate of return: bisection + Newton-Raphson hybrid.

    Returns 0.0 when no sign change is found or all cashflows are zero.
    """
    if len(cashflows) < 2 or all(cf == 0.0 for cf in cashflows):
        return 0.0

    # Find bounds with sign change. The NPV has a singularity at rate=-1,
    # so the lower bound stays strictly above it.
    lo, hi = -0.9999, 10.0
    for _ in range(100):
        npv_lo = _npv(lo, cashflows)
        npv_hi = _npv(hi, cashflows)
        if npv_lo * npv_hi <= 0:
            break
        lo = max(lo - 0.5, -0.9999)
        hi += 1.0
        if lo == -0.9999 and npv_lo * _npv(hi, cashflows) > 0 and hi > 1e6:
            return 0.0
    else:
        return 0.0

    # Ensure lo has negative NPV and hi has positive NPV
    if _npv(lo, cashflows) > 0:
        lo, hi = hi, lo

    r = guess
    for _ in range(max_iter):
        if r <= -1.0:
            r = (lo + hi) / 2.0
            if r <= -1.0:
                return 0.0
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


def _payback_series(
    net_cf: pl.Series,
    cum_cf: pl.Series,
    axis: YearAxis,
) -> pl.Series:
    """Compute payback periods via linear interpolation at zero-crossing.

    For each year where prior cumulative is negative and current cumulative is
    positive, the payback is (year_index - prior_cum / net_cf). All other years
    are 0. The series length is 26 (construction year + 25 operating years),
    matching the D..AC column range. Construction year (index 0) is always 0.
    """
    n = len(net_cf)
    result = [0.0] * n
    for i in range(1, n):
        prev_cum = cum_cf[i - 1]
        curr_cum = cum_cf[i]
        if prev_cum < 0.0 and curr_cum > 0.0:
            # Year index: i-1 is the prior period (0 = construction year,
            # 1 = op year 1, ...).  The payback year label uses the prior
            # period's year index.
            year_label = float(i - 1)
            result[i] = year_label - prev_cum / net_cf[i]
    return pl.Series("payback", result, dtype=pl.Float64)


def _compute_salvage(params: ParamsCore, invest: InvestResult) -> float:
    """Compute salvage = D29 × salvage_ratio.

    D29 = invest.scalars.fixed_asset_original (which equals
    invest dynamic_total − deductible_vat − land_rent_original_oper1).
    """
    d29 = invest.scalars.fixed_asset_original
    dep_years = int(params.depreciation_years)
    load_sum = sum(params.load_rate[1 : dep_years + 1])
    salvage_ratio = 1.0 - params.depreciation_rate * load_sum
    return d29 * salvage_ratio


# ═══════════════════════════════════════════════════════════════════════════════
# Project cash flow compute functions
# ═══════════════════════════════════════════════════════════════════════════════


def compute_project_year_labels(axis: YearAxis) -> pl.Series:
    """Row 4: D = cost year label, E..AC = operating year indices 1..25.

    Ported exactly: construction year column shows 1 (not the calendar year).
    """
    labels = [1.0] + [float(i) for i in range(1, axis.operating_years + 1)]
    return pl.Series("project_year_labels", labels, dtype=pl.Float64)

def compute_project_power_sales(
    pnl: PnLResult, finplan: FinPlanResult
) -> pl.Series:
    """Row 6: pnl:sales_revenue − finplan:subsidy_shortfall per operating year.

    Construction year (index 0) is 0. PnL frame has 25 operating-year rows;
    finplan frame has 26 rows (construction year + 25 operating years).
    We use finplan[1:] to skip the construction year row.
    """
    sales = pnl.frame["sales_revenue"].to_list()
    shortfall = finplan.frame["subsidy_shortfall"].to_list()
    values = [0.0]
    values.extend(s - ss for s, ss in zip(sales, shortfall[1:], strict=True))
    return pl.Series("project_power_sales", values, dtype=pl.Float64)

def compute_project_vat_refund(pnl: PnLResult) -> pl.Series:
    """Row 7: pnl:vat_refund per operating year. Construction year = 0."""
    refund = pnl.frame["vat_refund"].to_list()
    return pl.Series(
        "project_vat_refund", [0.0, *refund], dtype=pl.Float64
    )


def compute_project_vat_output(pnl: PnLResult) -> pl.Series:
    """Row 8: pnl:output_vat per operating year. Construction year = 0."""
    output_vat = pnl.frame["output_vat"].to_list()
    return pl.Series(
        "project_vat_output", [0.0, *output_vat], dtype=pl.Float64
    )


def compute_project_salvage_recovery(
    params: ParamsCore, invest: InvestResult, axis: YearAxis
) -> pl.Series:
    """Row 9: salvage value at Y (20yr) or AC (25yr). All other years 0."""
    salvage = _compute_salvage(params, invest)
    n = axis.operating_years + 1
    values = [0.0] * n
    if axis.operating_years == 20:
        values[20] = salvage
    elif axis.operating_years == 25:
        values[25] = salvage
    return pl.Series("project_salvage_recovery", values, dtype=pl.Float64)

def compute_project_wc_recovery(
    params: ParamsCore, axis: YearAxis
) -> pl.Series:
    """Row 10: working capital recovery at Y/AC depending on operating_years.

    Recovery value = params.working_capital_total.
    """
    wc_total = params.working_capital_total
    n = axis.operating_years + 1
    values = [0.0] * n
    if axis.operating_years == 20:
        values[20] = wc_total
    elif axis.operating_years == 25:
        values[25] = wc_total
    return pl.Series("project_wc_recovery", values, dtype=pl.Float64)


def compute_project_row11(axis: YearAxis) -> pl.Series:
    """Row 11: all zeros (blank label row)."""
    return pl.Series(
        "project_row11",
        [0.0] * (axis.operating_years + 1),
        dtype=pl.Float64,
    )


def compute_project_fixed_asset_invest(
    invest: InvestResult, axis: YearAxis
) -> pl.Series:
    """Row 13: invest construction_investment at period oper1/oper2.

    Period oper1 (F, index 2) → D (construction year),
    period oper2 (G, index 3) → E (operating year 1). All other years are 0.
    """
    ci = invest.frame["construction_investment"].to_list()
    n = axis.operating_years + 1
    values = [0.0] * n
    if len(ci) > 2:
        values[0] = float(ci[2])  # D13
    if len(ci) > 3:
        values[1] = float(ci[3])  # E13
    return pl.Series("project_fixed_asset_invest", values, dtype=pl.Float64)


def compute_project_working_capital(
    invest: InvestResult, axis: YearAxis
) -> pl.Series:
    """Row 14: invest working_capital mapped via _invest_col_for_row14.

    Irregularity: the mapping D→H, E→I, F→J, G→I, H→J, I+→+2.
    In practice, only the construction year (D, mapped to invest H = cumulative)
    has a non-zero value; all other years map to non-existent invest columns and
    resolve to 0.

    The cumulative working capital total is available as
    invest.scalars.working_capital_total.
    """
    d14 = invest.scalars.working_capital_total
    n = axis.operating_years + 1
    values = [0.0] * n
    values[0] = d14
    return pl.Series("project_working_capital", values, dtype=pl.Float64)


def compute_project_vat_payable(pnl: PnLResult) -> pl.Series:
    """Row 15: pnl:vat_payable per operating year. Construction year = 0."""
    vp = pnl.frame["vat_payable"].to_list()
    return pl.Series(
        "project_vat_payable", [0.0, *vp], dtype=pl.Float64
    )


def compute_project_land_rent(finplan: FinPlanResult) -> pl.Series:
    """Row 16: finplan:large_rent_payment per operating year. D=0.

    FinPlan frame has 26 rows; construction year (index 0) is already 0,
    but we emit our own 0 for cashflow consistency.
    """
    rent = finplan.frame["large_rent_payment"].to_list()
    return pl.Series("project_land_rent", [0.0, *rent[1:]], dtype=pl.Float64)


def compute_project_operating_cost(cost: CostResult) -> pl.Series:
    """Row 17: cost:operating_cost per operating year. D=0.

    Cost frame holds the 25 operating years, aligned with the project section.
    """
    oc = cost.frame["operating_cost"].to_list()
    return pl.Series("project_operating_cost", [0.0, *oc], dtype=pl.Float64)


def compute_project_sales_tax(pnl: PnLResult) -> pl.Series:
    """Row 18: pnl:vat_surcharge_total per operating year. D=0."""
    st = pnl.frame["vat_surcharge_total"].to_list()
    return pl.Series(
        "project_sales_tax", [0.0, *st], dtype=pl.Float64
    )


def compute_project_ebit(pnl: PnLResult, cost: CostResult) -> pl.Series:
    """Row 20: pnl:total_profit + cost:interest_expense per operating year.

    PnL and cost frames both hold the 25 operating years, aligned.
    Construction year = 0.
    """
    tp = pnl.frame["total_profit"].to_list()
    ie = cost.frame["interest_expense"].to_list()
    values = [0.0]
    values.extend(p + i for p, i in zip(tp, ie, strict=True))
    return pl.Series("project_ebit", values, dtype=pl.Float64)


def compute_project_adjusted_income_tax(
    params: ParamsCore,
    project_ebit: pl.Series,
) -> pl.Series:
    """Row 19: project_ebit × income_tax_rate; first 3 formula years halved.

    Construction year (D) = 0. Operating years 1-3 (E..G) = 0 (literal).
    Operating years 4-6 (H..J) = ebit × rate × 0.5.
    Operating years 7-25 (K..AC) = ebit × rate.
    """
    tax_rate = params.income_tax_rate
    ebit_vals = project_ebit.to_list()
    n = len(ebit_vals)
    values = [0.0] * n
    # D (index 0) = 0 already; E,F,G (indices 1,2,3) = 0 (literal)
    # Formula cols H..AC start at index 4 (op year 4)
    for i in range(4, n):
        factor = 0.5 if i < 7 else 1.0  # H=idx4, I=idx5, J=idx6 halved
        values[i] = ebit_vals[i] * tax_rate * factor
    return pl.Series("project_adjusted_income_tax", values, dtype=pl.Float64)


def compute_project_row21(axis: YearAxis) -> pl.Series:
    """Row 21: all zeros."""
    return pl.Series(
        "project_row21",
        [0.0] * (axis.operating_years + 1),
        dtype=pl.Float64,
    )


def compute_project_cash_inflow(
    project_power_sales: pl.Series,
    project_vat_refund: pl.Series,
    project_vat_output: pl.Series,
    project_salvage_recovery: pl.Series,
    project_wc_recovery: pl.Series,
) -> pl.Series:
    """Row 5: sum of rows 6-10 per year."""
    vals = (
        project_power_sales.to_list()[i]
        + project_vat_refund.to_list()[i]
        + project_vat_output.to_list()[i]
        + project_salvage_recovery.to_list()[i]
        + project_wc_recovery.to_list()[i]
        for i in range(len(project_power_sales))
    )
    return pl.Series("project_cash_inflow", list(vals), dtype=pl.Float64)


def compute_project_cash_outflow(
    project_fixed_asset_invest: pl.Series,
    project_working_capital: pl.Series,
    project_vat_payable: pl.Series,
    project_land_rent: pl.Series,
    project_operating_cost: pl.Series,
    project_sales_tax: pl.Series,
    project_adjusted_income_tax: pl.Series,
) -> pl.Series:
    """Row 12: sum of rows 13-19 per year."""
    n = len(project_fixed_asset_invest)
    result = [0.0] * n
    fai = project_fixed_asset_invest.to_list()
    wc = project_working_capital.to_list()
    vp = project_vat_payable.to_list()
    lr = project_land_rent.to_list()
    oc = project_operating_cost.to_list()
    st = project_sales_tax.to_list()
    ait = project_adjusted_income_tax.to_list()
    for i in range(n):
        result[i] = fai[i] + wc[i] + vp[i] + lr[i] + oc[i] + st[i] + ait[i]
    return pl.Series("project_cash_outflow", result, dtype=pl.Float64)


def compute_project_net_cf(
    project_cash_inflow: pl.Series,
    project_cash_outflow: pl.Series,
) -> pl.Series:
    """Row 22: cash_inflow − cash_outflow per year."""
    inflow = project_cash_inflow.to_list()
    outflow = project_cash_outflow.to_list()
    return pl.Series(
        "project_net_cf",
        [inflow[i] - outflow[i] for i in range(len(inflow))],
        dtype=pl.Float64,
    )


def compute_project_cum_net_cf(
    project_net_cf: pl.Series,
) -> pl.Series:
    """Row 23: cumulative sum of project_net_cf."""
    vals = project_net_cf.to_list()
    cum = 0.0
    result = []
    for v in vals:
        cum += v
        result.append(cum)
    return pl.Series("project_cum_net_cf", result, dtype=pl.Float64)


def compute_project_payback(
    axis: YearAxis,
    project_net_cf: pl.Series,
    project_cum_net_cf: pl.Series,
) -> pl.Series:
    """Row 24: payback period interpolation at zero-crossing."""
    return _payback_series(project_net_cf, project_cum_net_cf, axis)


def compute_project_pre_tax_net_cf(
    project_net_cf: pl.Series,
    project_adjusted_income_tax: pl.Series,
) -> pl.Series:
    """Row 25: project_net_cf + project_adjusted_income_tax."""
    ncf = project_net_cf.to_list()
    ait = project_adjusted_income_tax.to_list()
    return pl.Series(
        "project_pre_tax_net_cf",
        [ncf[i] + ait[i] for i in range(len(ncf))],
        dtype=pl.Float64,
    )


def compute_project_cum_pre_tax_cf(
    project_pre_tax_net_cf: pl.Series,
) -> pl.Series:
    """Row 26: cumulative sum of project_pre_tax_net_cf."""
    vals = project_pre_tax_net_cf.to_list()
    cum = 0.0
    result = []
    for v in vals:
        cum += v
        result.append(cum)
    return pl.Series("project_cum_pre_tax_cf", result, dtype=pl.Float64)


def compute_project_payback_pre_tax(
    axis: YearAxis,
    project_pre_tax_net_cf: pl.Series,
    project_cum_pre_tax_cf: pl.Series,
) -> pl.Series:
    """Row 27: payback period interpolation at zero-crossing (pre-tax)."""
    return _payback_series(
        project_pre_tax_net_cf, project_cum_pre_tax_cf, axis
    )


def compute_project_irr(
    project_net_cf: pl.Series,
    project_pre_tax_net_cf: pl.Series,
) -> dict[str, float]:
    """Row 29: IRR of project_net_cf (×100) and project_pre_tax_net_cf (×100).

    Both use the full D..AC range (construction year + 25 operating years).
    """
    cf_after = project_net_cf.to_list()
    cf_pre = project_pre_tax_net_cf.to_list()
    return {
        "project_irr_after_tax": _irr(cf_after) * 100.0,
        "project_irr_pre_tax": _irr(cf_pre) * 100.0,
    }


def compute_project_npv(
    project_net_cf: pl.Series,
    project_pre_tax_net_cf: pl.Series,
) -> dict[str, float]:
    """Row 30: NPV(5%) of project_net_cf after-tax and pre-tax."""
    cf_after = project_net_cf.to_list()
    cf_pre = project_pre_tax_net_cf.to_list()
    return {
        "project_npv_after_tax": _npv(0.05, cf_after),
        "project_npv_pre_tax": _npv(0.05, cf_pre),
    }


def compute_project_payback_period(
    project_payback: pl.Series,
    project_payback_pre_tax: pl.Series,
) -> dict[str, float]:
    """Row 31: aggregated payback values (sum of positive year fractions)."""
    pb_vals = project_payback.to_list()
    pb_pre_vals = project_payback_pre_tax.to_list()
    return {
        "project_payback_after_tax": sum(v for v in pb_vals if v > 0),
        "project_payback_pre_tax": sum(v for v in pb_pre_vals if v > 0),
    }


def compute_project_20yr_irr(
    project_net_cf: pl.Series,
    project_pre_tax_net_cf: pl.Series,
) -> dict[str, float]:
    """Row 33: IRR of first 20 years (D..X, 21 data points) × 100."""
    cf_after = project_net_cf.to_list()[:21]  # D..X
    cf_pre = project_pre_tax_net_cf.to_list()[:21]
    return {
        "project_20yr_irr_after_tax": _irr(cf_after) * 100.0,
        "project_20yr_irr_pre_tax": _irr(cf_pre) * 100.0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Equity cash flow compute functions
# ═══════════════════════════════════════════════════════════════════════════════


def compute_equity_year_labels(
    project_year_labels: pl.Series,
) -> pl.Series:
    """Row 40: echo of project_year_labels."""
    return pl.Series(
        "equity_year_labels",
        project_year_labels.to_list(),
        dtype=pl.Float64,
    )


def compute_equity_power_sales(
    project_power_sales: pl.Series,
) -> pl.Series:
    """Row 43: echo of project_power_sales."""
    return pl.Series(
        "equity_power_sales",
        project_power_sales.to_list(),
        dtype=pl.Float64,
    )


def compute_equity_vat_refund(pnl: PnLResult) -> pl.Series:
    """Row 44: pnl:vat_refund per operating year. D=0."""
    refund = pnl.frame["vat_refund"].to_list()
    return pl.Series(
        "equity_vat_refund", [0.0, *refund], dtype=pl.Float64
    )


def compute_equity_vat_output(pnl: PnLResult) -> pl.Series:
    """Row 45: pnl:output_vat per operating year. D=0."""
    ov = pnl.frame["output_vat"].to_list()
    return pl.Series(
        "equity_vat_output", [0.0, *ov], dtype=pl.Float64
    )


def compute_equity_salvage_recovery(
    params: ParamsCore,
    invest: InvestResult,
    axis: YearAxis,
    project_salvage_recovery: pl.Series,
) -> pl.Series:
    """Row 46: salvage at F (op year 1) from project row 9, and Y/AC end.

    Old code: F46 = F9, Y46/AC46 = salvage at end of operating period.
    """
    psr = project_salvage_recovery.to_list()
    salvage = _compute_salvage(params, invest)
    n = len(psr)
    values = [0.0] * n
    if len(psr) > 1:
        values[1] = float(psr[1])  # F46 = F9
    if axis.operating_years == 20:
        values[20] = salvage  # Y46
    elif axis.operating_years == 25:
        values[25] = salvage  # AC46
    return pl.Series("equity_salvage_recovery", values, dtype=pl.Float64)


def compute_equity_wc_recovery(axis: YearAxis) -> pl.Series:
    """Row 47: all zeros (AD47 = 0)."""
    return pl.Series(
        "equity_wc_recovery",
        [0.0] * (axis.operating_years + 1),
        dtype=pl.Float64,
    )


def compute_equity_row48(axis: YearAxis) -> pl.Series:
    """Row 48: all zeros."""
    return pl.Series(
        "equity_row48",
        [0.0] * (axis.operating_years + 1),
        dtype=pl.Float64,
    )


def compute_equity_cash_inflow(
    equity_power_sales: pl.Series,
    equity_vat_refund: pl.Series,
    equity_vat_output: pl.Series,
    equity_salvage_recovery: pl.Series,
    equity_wc_recovery: pl.Series,
) -> pl.Series:
    """Row 42: sum of rows 43-47 per year."""
    eps = equity_power_sales.to_list()
    evr = equity_vat_refund.to_list()
    evo = equity_vat_output.to_list()
    esr = equity_salvage_recovery.to_list()
    ewr = equity_wc_recovery.to_list()
    n = len(eps)
    return pl.Series(
        "equity_cash_inflow",
        [eps[i] + evr[i] + evo[i] + esr[i] + ewr[i] for i in range(n)],
        dtype=pl.Float64,
    )


def compute_equity_capital_invest(
    invest: InvestResult, axis: YearAxis
) -> pl.Series:
    """Row 50: invest equity_capital at period oper1 (idx 2), oper2 (idx 3).

    Period oper1 → D (construction year), period oper2 → E (operating year 1).
    """
    ec = invest.frame["equity_capital"].to_list()
    n = axis.operating_years + 1
    values = [0.0] * n
    if len(ec) > 2:
        values[0] = float(ec[2])  # D50
    if len(ec) > 3:
        values[1] = float(ec[3])  # E50
    return pl.Series("equity_capital_invest", values, dtype=pl.Float64)


def compute_equity_loan_principal_repay(
    debt: DebtResult,
    finplan: FinPlanResult,
    axis: YearAxis,
) -> pl.Series:
    """Row 51: loan principal repayment, two-part formula.

    E..W (op years 1-19): debt row 10 − finplan row 22 + finplan row 28.
    X..AC (op years 20-25): debt row 10 − debt row 18 + debt row 20.

    Ported exactly: the old formula uses debt long_term_loan_interest_payment
    (row 10), NOT total_principal (row 25). At late years the finplan /
    debt short-term columns compensate so the result still equals the
    principal repayment flow.
    Construction year (D) = 0.
    """
    r10 = debt.frame["long_term_loan_interest_payment"].to_list()
    stb_fp = finplan.frame["short_term_borrowing"].to_list()
    str_fp = finplan.frame["short_term_repayment"].to_list()
    stb_d = debt.frame["short_term_balance"].to_list()
    stp_d = debt.frame["short_term_principal"].to_list()

    n = axis.operating_years + 1  # 26
    values = [0.0] * n
    # Operating years 1-19 (indices 1..19): E..W pattern
    for i in range(1, min(20, n)):
        values[i] = r10[i] - stb_fp[i] + str_fp[i]
    # Operating years 20-25 (indices 20..25): X..AC pattern
    for i in range(20, n):
        values[i] = r10[i] - stb_d[i] + stp_d[i]
    return pl.Series("equity_loan_principal_repay", values, dtype=pl.Float64)


def compute_equity_loan_interest(cost: CostResult) -> pl.Series:
    """Row 52: cost:interest_expense per operating year. D=0."""
    ie = cost.frame["interest_expense"].to_list()
    return pl.Series(
        "equity_loan_interest", [0.0, *ie], dtype=pl.Float64
    )


def compute_equity_operating_cost(cost: CostResult) -> pl.Series:
    """Row 53: cost:operating_cost per operating year. D=0."""
    oc = cost.frame["operating_cost"].to_list()
    return pl.Series(
        "equity_operating_cost", [0.0, *oc], dtype=pl.Float64
    )


def compute_equity_land_rent(
    project_land_rent: pl.Series,
) -> pl.Series:
    """Row 54: echo of project_land_rent."""
    return pl.Series(
        "equity_land_rent",
        project_land_rent.to_list(),
        dtype=pl.Float64,
    )


def compute_equity_vat_payable(pnl: PnLResult) -> pl.Series:
    """Row 55: pnl:vat_payable per operating year. D=0."""
    vp = pnl.frame["vat_payable"].to_list()
    return pl.Series(
        "equity_vat_payable", [0.0, *vp], dtype=pl.Float64
    )


def compute_equity_sales_tax(pnl: PnLResult) -> pl.Series:
    """Row 56: pnl:vat_surcharge_total per operating year. D=0."""
    st = pnl.frame["vat_surcharge_total"].to_list()
    return pl.Series(
        "equity_sales_tax", [0.0, *st], dtype=pl.Float64
    )


def compute_equity_long_term_rent(
    project_fixed_asset_invest: pl.Series, axis: YearAxis
) -> pl.Series:
    """Row 58: E58 = E13 (project_fixed_asset_invest at op year 1)."""
    pfai = project_fixed_asset_invest.to_list()
    n = axis.operating_years + 1
    values = [0.0] * n
    if len(pfai) > 1:
        values[1] = pfai[1]  # E58 = E13
    return pl.Series("equity_long_term_rent", values, dtype=pl.Float64)


def compute_equity_cash_outflow(
    equity_capital_invest: pl.Series,
    equity_loan_principal_repay: pl.Series,
    equity_loan_interest: pl.Series,
    equity_operating_cost: pl.Series,
    equity_land_rent: pl.Series,
    equity_vat_payable: pl.Series,
    equity_sales_tax: pl.Series,
    equity_income_tax: pl.Series,
    equity_long_term_rent: pl.Series,
) -> pl.Series:
    """Row 49: sum of rows 50-58 per year."""
    eci = equity_capital_invest.to_list()
    elpr = equity_loan_principal_repay.to_list()
    eli = equity_loan_interest.to_list()
    eoc = equity_operating_cost.to_list()
    elr = equity_land_rent.to_list()
    evp = equity_vat_payable.to_list()
    est = equity_sales_tax.to_list()
    eit = equity_income_tax.to_list()
    eltr = equity_long_term_rent.to_list()
    n = len(eci)
    return pl.Series(
        "equity_cash_outflow",
        [
            eci[i] + elpr[i] + eli[i] + eoc[i] + elr[i] + evp[i]
            + est[i] + eit[i] + eltr[i]
            for i in range(n)
        ],
        dtype=pl.Float64,
    )


def compute_equity_net_cf(
    equity_cash_inflow: pl.Series,
    equity_cash_outflow: pl.Series,
) -> pl.Series:
    """Row 59: equity_cash_inflow − equity_cash_outflow."""
    inflow = equity_cash_inflow.to_list()
    outflow = equity_cash_outflow.to_list()
    return pl.Series(
        "equity_net_cf",
        [inflow[i] - outflow[i] for i in range(len(inflow))],
        dtype=pl.Float64,
    )


def compute_equity_cum_cf(
    equity_net_cf: pl.Series,
) -> pl.Series:
    """Row 60: cumulative sum of equity_net_cf."""
    vals = equity_net_cf.to_list()
    cum = 0.0
    result = []
    for v in vals:
        cum += v
        result.append(cum)
    return pl.Series("equity_cum_cf", result, dtype=pl.Float64)


def compute_equity_irr(
    equity_net_cf: pl.Series,
) -> float:
    """Row 61: IRR of equity_net_cf (full D..AC, 26 points)."""
    cf = equity_net_cf.to_list()
    return _irr(cf)


def compute_equity_npv(
    equity_net_cf: pl.Series,
) -> float:
    """Row 62: NPV(8%) of equity_net_cf."""
    cf = equity_net_cf.to_list()
    return _npv(0.08, cf)


def compute_equity_20yr_irr(
    equity_net_cf: pl.Series,
) -> float:
    """Row 64: IRR of first 21 points (D..Y) of equity_net_cf × 100."""
    cf = equity_net_cf.to_list()[:22]  # D..Y = 22 points (yr0..yr21)
    return _irr(cf) * 100.0


def compute_equity_adjustment(params: ParamsCore) -> float:
    """Row 67: (project_income + provisional/1.09×(1−0.09×0.1)) × (1−sale_tax).

    Workbook convention: the provisional sum enters VAT-discounted at 9%
    with a 10% surcharge relief, and the total is taxed at the equity-sale
    rate.  Ported exactly from the old formula.
    """
    income = params.inputs.project_income
    provisional = params.inputs.provisional_sum
    sale_tax = params.inputs.equity_sale_tax_rate
    return (income + provisional / 1.09 * (1.0 - 0.09 * 0.1)) * (1.0 - sale_tax)



def compute_equity_adjusted_cf(
    equity_adjustment: float,
    equity_net_cf: pl.Series,
) -> pl.Series:
    """Row 68: equity_adjustment + equity_net_cf per year.

    Only D67 has a formula value (the adjustment scalar); E67..AC67 are
    blank → 0. So only the construction year (index 0) gets the adjustment.
    """
    encf = equity_net_cf.to_list()
    result = list(encf)
    result[0] = encf[0] + equity_adjustment
    return pl.Series("equity_adjusted_cf", result, dtype=pl.Float64)


def compute_equity_adjusted_irr(
    equity_adjusted_cf: pl.Series,
) -> float:
    """Row 69: IRR of equity_adjusted_cf (full D..AC)."""
    cf = equity_adjusted_cf.to_list()
    return _irr(cf)


# ═══════════════════════════════════════════════════════════════════════════════


def compute_investor_year_labels(
    equity_year_labels: pl.Series,
) -> pl.Series:
    """Row 83: echo of equity_year_labels."""
    return pl.Series(
        "investor_year_labels",
        equity_year_labels.to_list(),
        dtype=pl.Float64,
    )


def compute_investor_profit_distribution(pnl: PnLResult) -> pl.Series:
    """Row 85: pnl:dividend per operating year. D=0."""
    div = pnl.frame["dividend"].to_list()
    return pl.Series(
        "investor_profit_distribution", [0.0, *div], dtype=pl.Float64
    )


def compute_investor_salvage(
    project_salvage_recovery: pl.Series, axis: YearAxis
) -> pl.Series:
    """Row 87: project_salvage_recovery at AC echoed (AC87 = AC9)."""
    psr = project_salvage_recovery.to_list()
    n = axis.operating_years + 1
    values = [0.0] * n
    # AC is the last index
    if axis.operating_years == 25 and n > 25:
        values[25] = float(psr[25])
    return pl.Series("investor_salvage", values, dtype=pl.Float64)


def compute_investor_surplus_fund(
    finplan: FinPlanResult, axis: YearAxis
) -> pl.Series:
    """Row 88: finplan cumulative_surplus at final operating year.

    Only the final year has a value; all other years are zero.
    """
    cs = finplan.frame["cumulative_surplus"].to_list()
    n = axis.operating_years + 1
    values = [0.0] * n
    if len(cs) > 0:
        # Last operating year = index 25 (for 25-year case, AC col)
        values[-1] = float(cs[-1])
    return pl.Series("investor_surplus_fund", values, dtype=pl.Float64)


def compute_investor_asset_disposal(
    investor_salvage: pl.Series,
    investor_surplus_fund: pl.Series,
) -> pl.Series:
    """Row 86: investor_salvage + investor_surplus_fund per year.

    F..AC only (no E, no D). Old code starts from col F (index 2).
    """
    inv_salv = investor_salvage.to_list()
    inv_sf = investor_surplus_fund.to_list()
    n = len(inv_salv)
    values = [0.0] * n
    for i in range(n):
        values[i] = inv_salv[i] + inv_sf[i]
    return pl.Series("investor_asset_disposal", values, dtype=pl.Float64)


def compute_investor_cash_inflow(
    investor_profit_distribution: pl.Series,
    investor_asset_disposal: pl.Series,
) -> pl.Series:
    """Row 84: investor_profit_distribution + investor_asset_disposal."""
    ipd = investor_profit_distribution.to_list()
    iad = investor_asset_disposal.to_list()
    n = len(ipd)
    return pl.Series(
        "investor_cash_inflow",
        [ipd[i] + iad[i] for i in range(n)],
        dtype=pl.Float64,
    )


def compute_investor_construction_equity(
    equity_capital_invest: pl.Series, axis: YearAxis
) -> pl.Series:
    """Row 92: D92 = D50 (equity_capital_invest at construction year)."""
    eci = equity_capital_invest.to_list()
    n = axis.operating_years + 1
    values = [0.0] * n
    if len(eci) > 0:
        values[0] = eci[0]  # D92 = D50
    return pl.Series("investor_construction_equity", values, dtype=pl.Float64)


def compute_investor_own_wc(
    invest: InvestResult, axis: YearAxis
) -> pl.Series:
    """Row 93: invest equity_for_working_capital at period oper2 (idx 3)."""
    efwc = invest.frame["equity_for_working_capital"].to_list()
    n = axis.operating_years + 1
    values = [0.0] * n
    if len(efwc) > 3:
        values[1] = float(efwc[3])  # E93
    return pl.Series("investor_own_wc", values, dtype=pl.Float64)


def compute_investor_cash_outflow(
    investor_construction_equity: pl.Series,
    investor_own_wc: pl.Series,
) -> pl.Series:
    """Row 91: investor_construction_equity + investor_own_wc."""
    ice = investor_construction_equity.to_list()
    iow = investor_own_wc.to_list()
    n = len(ice)
    return pl.Series(
        "investor_cash_outflow",
        [ice[i] + iow[i] for i in range(n)],
        dtype=pl.Float64,
    )


def compute_investor_net_cf(
    investor_cash_inflow: pl.Series,
    investor_cash_outflow: pl.Series,
) -> pl.Series:
    """Row 94: investor_cash_inflow − investor_cash_outflow."""
    inflow = investor_cash_inflow.to_list()
    outflow = investor_cash_outflow.to_list()
    return pl.Series(
        "investor_net_cf",
        [inflow[i] - outflow[i] for i in range(len(inflow))],
        dtype=pl.Float64,
    )


def compute_investor_cum_cf(
    investor_net_cf: pl.Series,
) -> pl.Series:
    """Row 95: cumulative sum of investor_net_cf."""
    vals = investor_net_cf.to_list()
    cum = 0.0
    result = []
    for v in vals:
        cum += v
        result.append(cum)
    return pl.Series("investor_cum_cf", result, dtype=pl.Float64)


def compute_investor_irr(
    investor_net_cf: pl.Series,
) -> float:
    """Row 97: IRR of investor_net_cf (full D..AC)."""
    cf = investor_net_cf.to_list()
    return _irr(cf)


def compute_investor_npv(
    investor_net_cf: pl.Series,
) -> float:
    """Row 98: NPV(8%) of investor_net_cf."""
    cf = investor_net_cf.to_list()
    return _npv(0.08, cf)


# ═══════════════════════════════════════════════════════════════════════════════
# Main assembler
# ═══════════════════════════════════════════════════════════════════════════════


def compute_cashflow(
    params: ParamsCore,
    invest: InvestResult,
    debt: DebtResult,
    cost: CostResult,
    pnl: PnLResult,
    finplan: FinPlanResult,
    solution: MutualSolution,
) -> CashFlowResult:
    """Compute all cash flow items and assemble the result.

    The mutual solution provides the coupled equity_income_tax series.
    All other items are computed by dedicated compute_ functions, called in
    intra-domain dependency order (project → equity → investor).
    """
    axis = YearAxis(
        construction_year=params.construction_year,
        operating_years=params.operating_years,
    )
    years = axis.all_years

    # ── Project section ──
    pyl = compute_project_year_labels(axis)
    pps = compute_project_power_sales(pnl, finplan)
    pvr = compute_project_vat_refund(pnl)
    pvo = compute_project_vat_output(pnl)
    psr = compute_project_salvage_recovery(params, invest, axis)
    pwr = compute_project_wc_recovery(params, axis)
    pr11 = compute_project_row11(axis)
    pci = compute_project_cash_inflow(pps, pvr, pvo, psr, pwr)

    pfai = compute_project_fixed_asset_invest(invest, axis)
    pwc = compute_project_working_capital(invest, axis)
    pvp = compute_project_vat_payable(pnl)
    plr = compute_project_land_rent(finplan)
    poc = compute_project_operating_cost(cost)
    pst = compute_project_sales_tax(pnl)
    pebit = compute_project_ebit(pnl, cost)
    pait = compute_project_adjusted_income_tax(params, pebit)
    pr21 = compute_project_row21(axis)
    pco = compute_project_cash_outflow(pfai, pwc, pvp, plr, poc, pst, pait)

    pncf = compute_project_net_cf(pci, pco)
    pcncf = compute_project_cum_net_cf(pncf)
    ppb = compute_project_payback(axis, pncf, pcncf)

    pptncf = compute_project_pre_tax_net_cf(pncf, pait)
    pcptcf = compute_project_cum_pre_tax_cf(pptncf)
    ppbpt = compute_project_payback_pre_tax(axis, pptncf, pcptcf)

    # ── Project scalars ──
    pirr = compute_project_irr(pncf, pptncf)
    pnpv = compute_project_npv(pncf, pptncf)
    ppbp = compute_project_payback_period(ppb, ppbpt)
    p20irr = compute_project_20yr_irr(pncf, pptncf)

    # ── Equity section ──
    eyl = compute_equity_year_labels(pyl)
    eps_ = compute_equity_power_sales(pps)
    evr_ = compute_equity_vat_refund(pnl)
    evo_ = compute_equity_vat_output(pnl)
    esr_ = compute_equity_salvage_recovery(params, invest, axis, psr)
    ewr_ = compute_equity_wc_recovery(axis)
    er48 = compute_equity_row48(axis)
    eci_ = compute_equity_cash_inflow(eps_, evr_, evo_, esr_, ewr_)

    ecap = compute_equity_capital_invest(invest, axis)
    elpr = compute_equity_loan_principal_repay(debt, finplan, axis)
    eli = compute_equity_loan_interest(cost)
    eoc = compute_equity_operating_cost(cost)
    elr_ = compute_equity_land_rent(plr)
    evp_ = compute_equity_vat_payable(pnl)
    est_ = compute_equity_sales_tax(pnl)
    # Coupled: equity_income_tax from mutual solution
    eit_vals = [0.0, *list(solution.equity_income_tax)]
    eit = pl.Series("equity_income_tax", eit_vals, dtype=pl.Float64)
    eltr = compute_equity_long_term_rent(pfai, axis)
    eco = compute_equity_cash_outflow(
        ecap, elpr, eli, eoc, elr_, evp_, est_, eit, eltr
    )

    encf = compute_equity_net_cf(eci_, eco)
    eccf = compute_equity_cum_cf(encf)

    # ── Equity scalars ──
    eq_irr = compute_equity_irr(encf)
    eq_npv = compute_equity_npv(encf)
    eq_20irr = compute_equity_20yr_irr(encf)
    eq_adj = compute_equity_adjustment(params)
    eacf = compute_equity_adjusted_cf(eq_adj, encf)
    eq_adj_irr = compute_equity_adjusted_irr(eacf)

    # ── Investor section ──
    iyl = compute_investor_year_labels(eyl)
    ipd = compute_investor_profit_distribution(pnl)
    isal = compute_investor_salvage(psr, axis)
    isf = compute_investor_surplus_fund(finplan, axis)
    iad = compute_investor_asset_disposal(isal, isf)
    ici = compute_investor_cash_inflow(ipd, iad)

    ice = compute_investor_construction_equity(ecap, axis)
    iow = compute_investor_own_wc(invest, axis)
    ico = compute_investor_cash_outflow(ice, iow)

    incf = compute_investor_net_cf(ici, ico)
    iccf = compute_investor_cum_cf(incf)

    # ── Investor scalars ──
    inv_irr = compute_investor_irr(incf)
    inv_npv = compute_investor_npv(incf)

    # ── Assemble frame ──
    frame = pl.DataFrame(
        {
            "year": list(years),
            # Project section
            "project_year_labels": pyl,
            "project_cash_inflow": pci,
            "project_power_sales": pps,
            "project_vat_refund": pvr,
            "project_vat_output": pvo,
            "project_salvage_recovery": psr,
            "project_wc_recovery": pwr,
            "project_row11": pr11,
            "project_cash_outflow": pco,
            "project_fixed_asset_invest": pfai,
            "project_working_capital": pwc,
            "project_vat_payable": pvp,
            "project_land_rent": plr,
            "project_operating_cost": poc,
            "project_sales_tax": pst,
            "project_adjusted_income_tax": pait,
            "project_ebit": pebit,
            "project_row21": pr21,
            "project_net_cf": pncf,
            "project_cum_net_cf": pcncf,
            "project_payback": ppb,
            "project_pre_tax_net_cf": pptncf,
            "project_cum_pre_tax_cf": pcptcf,
            "project_payback_pre_tax": ppbpt,
            # Equity section
            "equity_year_labels": eyl,
            "equity_cash_inflow": eci_,
            "equity_power_sales": eps_,
            "equity_vat_refund": evr_,
            "equity_vat_output": evo_,
            "equity_salvage_recovery": esr_,
            "equity_wc_recovery": ewr_,
            "equity_row48": er48,
            "equity_cash_outflow": eco,
            "equity_capital_invest": ecap,
            "equity_loan_principal_repay": elpr,
            "equity_loan_interest": eli,
            "equity_operating_cost": eoc,
            "equity_land_rent": elr_,
            "equity_vat_payable": evp_,
            "equity_sales_tax": est_,
            "equity_income_tax": eit,
            "equity_long_term_rent": eltr,
            "equity_net_cf": encf,
            "equity_cum_cf": eccf,
            "equity_adjusted_cf": eacf,
            # Investor section
            "investor_year_labels": iyl,
            "investor_cash_inflow": ici,
            "investor_profit_distribution": ipd,
            "investor_asset_disposal": iad,
            "investor_salvage": isal,
            "investor_surplus_fund": isf,
            "investor_cash_outflow": ico,
            "investor_construction_equity": ice,
            "investor_own_wc": iow,
            "investor_net_cf": incf,
            "investor_cum_cf": iccf,
        }
    )

    scalars = CashFlowScalars(
        project_irr_after_tax=pirr["project_irr_after_tax"],
        project_irr_pre_tax=pirr["project_irr_pre_tax"],
        project_npv_after_tax=pnpv["project_npv_after_tax"],
        project_npv_pre_tax=pnpv["project_npv_pre_tax"],
        project_20yr_irr_after_tax=p20irr["project_20yr_irr_after_tax"],
        project_20yr_irr_pre_tax=p20irr["project_20yr_irr_pre_tax"],
        project_payback_after_tax=ppbp["project_payback_after_tax"],
        project_payback_pre_tax=ppbp["project_payback_pre_tax"],
        equity_irr=eq_irr,
        equity_npv=eq_npv,
        equity_20yr_irr=eq_20irr,
        equity_adjustment=eq_adj,
        equity_adjusted_irr=eq_adj_irr,
        investor_irr=inv_irr,
        investor_npv=inv_npv,
    )

    return CashFlowResult(years=years, frame=frame, scalars=scalars)
