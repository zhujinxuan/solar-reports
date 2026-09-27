"""DebtService — 借款还本付息计划表 (loan repayment schedule).

Long-term loan: equal-annual-payment (PMT) over loan_years at loan_rate_long.
Working capital loan: constant balance, interest-only.
Short-term loan: balance from 财务计划 via mutual block solution.

Dataflow:
  compute_base(params_core, invest) -> DebtBase
  assemble(base, solution, cost_core, pnl_core) -> DebtResult
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from solar_v2.axis import YearAxis
from solar_v2.schema import DomainSchema, ItemSchema

if TYPE_CHECKING:
    from solar_v2.inputs import ModelInputs


# ── PMT (standard annuity formula) ──────────────────────────────────────


def _pmt(rate: float, nper: int, pv: float) -> float:
    """Excel PMT: periodic payment for a loan.

    PMT = pv * r * (1+r)^n / ((1+r)^n - 1)
    """
    if rate == 0.0:
        return pv / nper
    factor = (1 + rate) ** nper
    return pv * rate * factor / (factor - 1.0)


# ── Result types ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DebtScalars:
    """Scalar items for the debt domain."""

    pmt: float = 0.0
    icr_average: float = 0.0
    dscr_average: float = 0.0


@dataclass(frozen=True)
class DebtBase:
    """Non-coupled debt items computable from params + invest alone."""

    years: tuple[int, ...]
    frame: pl.DataFrame
    scalars: DebtScalars


@dataclass(frozen=True)
class DebtResult:
    """Full debt result including coupled and ratio columns."""

    years: tuple[int, ...]
    frame: pl.DataFrame
    scalars: DebtScalars


# ── Item compute functions (one per non-coupled schema key) ─────────────


def compute_pmt(
    loan_rate_long: float,
    loan_years: int,
    invest_long_term_loan_total: float,
) -> float:
    """Row 35: PMT(loan_rate_long, loan_years, long_term_loan_total)."""
    return _pmt(loan_rate_long, loan_years, invest_long_term_loan_total)


def compute_year_numbers(n: int) -> pl.Series:
    """Row 4: year numbers — D=1, E=1, F=2, ..., AC=25 (26 values)."""
    return pl.Series(
        "year_numbers",
        [1.0, 1.0] + [float(i) for i in range(2, n + 1)],
        dtype=pl.Float64,
    )


def compute_construction_interest(
    invest_construction_interest_oper1: float,
    n: int,
) -> pl.Series:
    """Row 8: D = invest carry-in, E..AC = 0 (26 values)."""
    return pl.Series(
        "construction_interest",
        [invest_construction_interest_oper1] + [0.0] * n,
        dtype=pl.Float64,
    )


def compute_working_capital_balance(
    invest_working_capital_loan_total: float,
    n: int,
) -> pl.Series:
    """Row 13: D=0, then constant wc_loan_total (26 values)."""
    return pl.Series(
        "working_capital_balance",
        [0.0] + [invest_working_capital_loan_total] * n,
        dtype=pl.Float64,
    )


def compute_working_capital_interest(
    invest_working_capital_loan_total: float,
    wc_rate: float,
    n: int,
) -> pl.Series:
    """Row 16: D=0, then working_capital_balance × wc_rate (26 values)."""
    return pl.Series(
        "working_capital_interest",
        [0.0] + [invest_working_capital_loan_total * wc_rate] * n,
        dtype=pl.Float64,
    )


def compute_long_term_loan_balance(
    d6: float,
    balances: list[float],
) -> pl.Series:
    """Row 6: D=d6, then carry chain (26 values)."""
    return pl.Series(
        "long_term_loan_balance",
        [d6, *balances],
        dtype=pl.Float64,
    )


def compute_long_term_loan_principal_repay(
    d7: float,
    principals: list[float],
) -> pl.Series:
    """Row 7: D=d7, then carry chain (26 values)."""
    return pl.Series(
        "long_term_loan_principal_repay",
        [d7, *principals],
        dtype=pl.Float64,
    )


def compute_long_term_loan_interest_payment(
    principal_repays: list[float],
) -> pl.Series:
    """Row 10: D=0, then principal repay portion of PMT (26 values)."""
    return pl.Series(
        "long_term_loan_interest_payment",
        [0.0, *principal_repays],
        dtype=pl.Float64,
    )


def compute_long_term_interest_total(
    interests: list[float],
) -> pl.Series:
    """Row 11: D=0, then interest = balance × rate (26 values)."""
    return pl.Series(
        "long_term_interest_total",
        [0.0, *interests],
        dtype=pl.Float64,
    )


def compute_annual_debt_service(
    pmt_val: float,
    loan_years: int,
    principal_repays: list[float],
    interests: list[float],
    n: int,
) -> pl.Series:
    """Row 9: D=0, PMT during loan term else principal+interest (26 values)."""
    vals = [
        pmt_val if i < loan_years else principal_repays[i] + interests[i]
        for i in range(n)
    ]
    return pl.Series("annual_debt_service", [0.0, *vals], dtype=pl.Float64)


def compute_pmt_residual(
    principal_repays: list[float],
) -> pl.Series:
    """Row 36: same as row 10 (26 values)."""
    return pl.Series("pmt_residual", [0.0, *principal_repays], dtype=pl.Float64)


def compute_short_term_balance(
    short_term_borrowing: pl.Series,
) -> pl.Series:
    """Row 18: D=0, E=0, F=b[0], G=b[1], ..., AC=b[23] (26 values)."""
    borrow_list = short_term_borrowing.to_list()
    result = [0.0, 0.0, *borrow_list[:-1]]
    return pl.Series("short_term_balance", result, dtype=pl.Float64)


def compute_total_balance(
    lt_balance: pl.Series,
    wc_balance: pl.Series,
    st_balance: pl.Series,
) -> pl.Series:
    """Row 23: row6 + row13 + row18."""
    return (lt_balance + wc_balance + st_balance).alias("total_balance")


def compute_total_principal(
    lt_principal_repay: pl.Series,
    short_term_principal: pl.Series,
) -> pl.Series:
    """Row 25: row10 + row20."""
    return (lt_principal_repay + short_term_principal).alias("total_principal")


def compute_total_interest(
    lt_interest: pl.Series,
    wc_interest: pl.Series,
    short_term_interest: pl.Series,
) -> pl.Series:
    """Row 26: row11 + row16 + row21."""
    return (lt_interest + wc_interest + short_term_interest).alias("total_interest")


def compute_ebit(
    cost_interest_expense: pl.Series,
    pnl_total_profit: pl.Series,
) -> pl.Series:
    """Row 27: cost:interest_expense + pnl:total_profit."""
    return (cost_interest_expense + pnl_total_profit).alias("ebit")


def compute_ebit_vat(
    ebit: pl.Series,
    cost_deferred_vat_amortization: pl.Series,
) -> pl.Series:
    """Row 28: ebit + cost:deferred_vat_amortization."""
    return (ebit + cost_deferred_vat_amortization).alias("ebit_vat")


def compute_icr(
    ebit_vat: pl.Series,
    cost_interest_expense: pl.Series,
) -> pl.Series:
    """Row 29: ebit_vat / cost:interest_expense."""
    vals = []
    for i in range(len(ebit_vat)):
        denom = cost_interest_expense[i]
        vals.append(0.0 if denom == 0.0 else float(ebit_vat[i]) / float(denom))
    return pl.Series("icr", vals, dtype=pl.Float64)


def compute_ebitda(
    ebit: pl.Series,
    cost_depreciation: pl.Series,
) -> pl.Series:
    """Row 30: ebit + cost:depreciation."""
    return (ebit + cost_depreciation).alias("ebitda")


def compute_ebitda_tax(
    ebitda: pl.Series,
    cost_deferred_vat_amortization: pl.Series,
    pnl_income_tax: pl.Series,
) -> pl.Series:
    """Row 31: ebitda + cost:deferred_vat_amortization - pnl:income_tax."""
    return (ebitda + cost_deferred_vat_amortization - pnl_income_tax).alias(
        "ebitda_tax"
    )


def compute_dscr(
    ebitda_tax: pl.Series,
    lt_principal_repay: pl.Series,
    lt_interest: pl.Series,
) -> pl.Series:
    """Row 32: ebitda_tax / (principal_repay + interest)."""
    vals = []
    for i in range(len(ebitda_tax)):
        denom = float(lt_principal_repay[i]) + float(lt_interest[i])
        vals.append(0.0 if denom == 0.0 else float(ebitda_tax[i]) / denom)
    return pl.Series("dscr", vals, dtype=pl.Float64)


# ── Orchestrator: compute_base ──────────────────────────────────────────


def compute_base(
    inputs: ModelInputs,
    axis: YearAxis,
    *,
    invest_frame: pl.DataFrame,
    invest_working_capital_loan_total: float,
    invest_long_term_loan_total: float,
    invest_construction_interest_oper1: float,
) -> DebtBase:
    """Compute non-coupled debt items from params and invest."""
    n = axis.operating_years
    all_years = axis.all_years

    rate = inputs.loan_rate_long
    loan_years = inputs.loan_years
    wc_rate = inputs.working_capital_loan_rate

    pmt_val = compute_pmt(rate, loan_years, invest_long_term_loan_total)

    invest_principal_oper1 = (
        invest_frame.filter(pl.col("period") == "oper1")["long_term_loan_principal"]
        .item()
    )
    d7 = invest_principal_oper1
    d6 = d7 + invest_construction_interest_oper1

    # Long-term loan carry loop
    balances: list[float] = []
    principals: list[float] = []
    principal_repays: list[float] = []
    interests: list[float] = []
    residuals: list[float] = []

    prev_balance = d6
    prev_principal_repay = 0.0

    for i in range(n):
        principal = d6 if i == 0 else prev_balance - prev_principal_repay
        balance = principal
        interest = balance * rate
        principal_repay = pmt_val - interest if i < loan_years else 0.0

        balances.append(balance)
        principals.append(principal)
        interests.append(interest)
        principal_repays.append(principal_repay)
        residuals.append(principal_repay)

        prev_balance = balance
        prev_principal_repay = principal_repay

    # Build frame via compute_ functions
    frame = pl.DataFrame(
        {
            "year": pl.Series("year", list(all_years), dtype=pl.Int64),
            "year_numbers": compute_year_numbers(n),
            "long_term_loan_balance": compute_long_term_loan_balance(d6, balances),
            "long_term_loan_principal_repay": compute_long_term_loan_principal_repay(
                d7, principals
            ),
            "construction_interest": compute_construction_interest(
                invest_construction_interest_oper1, n
            ),
            "annual_debt_service": compute_annual_debt_service(
                pmt_val, loan_years, principal_repays, interests, n
            ),
            "long_term_loan_interest_payment": compute_long_term_loan_interest_payment(
                principal_repays
            ),
            "long_term_interest_total": compute_long_term_interest_total(interests),
            "working_capital_balance": compute_working_capital_balance(
                invest_working_capital_loan_total, n
            ),
            "working_capital_interest": compute_working_capital_interest(
                invest_working_capital_loan_total, wc_rate, n
            ),
            "pmt_residual": compute_pmt_residual(residuals),
        },
        schema_overrides={
            "year": pl.Int64,
            "year_numbers": pl.Float64,
            "long_term_loan_balance": pl.Float64,
            "long_term_loan_principal_repay": pl.Float64,
            "construction_interest": pl.Float64,
            "annual_debt_service": pl.Float64,
            "long_term_loan_interest_payment": pl.Float64,
            "long_term_interest_total": pl.Float64,
            "working_capital_balance": pl.Float64,
            "working_capital_interest": pl.Float64,
            "pmt_residual": pl.Float64,
        },
    )

    return DebtBase(
        years=all_years,
        frame=frame,
        scalars=DebtScalars(pmt=pmt_val),
    )


# ── assemble ────────────────────────────────────────────────────────────


def assemble(
    base: DebtBase,
    *,
    short_term_principal: pl.Series,
    short_term_interest: pl.Series,
    short_term_borrowing: pl.Series,
    cost_interest_expense: pl.Series,
    cost_depreciation: pl.Series,
    cost_deferred_vat_amortization: pl.Series,
    pnl_total_profit: pl.Series,
    pnl_income_tax: pl.Series,
) -> DebtResult:
    """Assemble full DebtResult from base + coupled + ratio columns."""
    frame = base.frame

    # Coupled items (from mutual solution)
    frame = frame.with_columns(
        short_term_principal.alias("short_term_principal"),
        short_term_interest.alias("short_term_interest"),
    )

    # Ratio items
    st_balance = compute_short_term_balance(short_term_borrowing)
    lt_balance = frame["long_term_loan_balance"]
    wc_balance = frame["working_capital_balance"]
    lt_principal_repay = frame["long_term_loan_interest_payment"]
    lt_interest = frame["long_term_interest_total"]
    wc_interest = frame["working_capital_interest"]

    ebit_s = compute_ebit(cost_interest_expense, pnl_total_profit)
    ebit_vat_s = compute_ebit_vat(ebit_s, cost_deferred_vat_amortization)
    ebitda_s = compute_ebitda(ebit_s, cost_depreciation)
    ebitda_tax_s = compute_ebitda_tax(
        ebitda_s, cost_deferred_vat_amortization, pnl_income_tax
    )

    frame = frame.with_columns(
        st_balance.alias("short_term_balance"),
        compute_total_balance(lt_balance, wc_balance, st_balance).alias(
            "total_balance"
        ),
        compute_total_principal(lt_principal_repay, short_term_principal).alias(
            "total_principal"
        ),
        compute_total_interest(lt_interest, wc_interest, short_term_interest).alias(
            "total_interest"
        ),
        ebit_s.alias("ebit"),
        ebit_vat_s.alias("ebit_vat"),
        compute_icr(ebit_vat_s, cost_interest_expense).alias("icr"),
        ebitda_s.alias("ebitda"),
        ebitda_tax_s.alias("ebitda_tax"),
        compute_dscr(ebitda_tax_s, lt_principal_repay, lt_interest).alias("dscr"),
    )

    icr_vals = frame["icr"].to_list()[2:21]
    dscr_vals = frame["dscr"].to_list()[2:16]
    scalars = DebtScalars(
        pmt=base.scalars.pmt,
        icr_average=sum(icr_vals) / len(icr_vals) if icr_vals else 0.0,
        dscr_average=sum(dscr_vals) / len(dscr_vals) if dscr_vals else 0.0,
    )

    return DebtResult(
        years=base.years,
        frame=frame,
        scalars=scalars,
    )


# ── SCHEMA ───────────────────────────────────────────────────────────────


SCHEMA = DomainSchema(
    key="debt",
    sheet="还贷",
    label="借款还本付息计划表 (Debt)",
    depends_on=("params", "invest", "cost", "pnl", "finplan"),
    items=(
        ItemSchema(
            key="year_numbers",
            label="运营年份",
            unit="-",
            formula="1..25 echoed year labels (D=1, E=1, F=2, ..., AC=25)",
            inputs=(),
            rows=(4,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="long_term_loan_balance",
            label="长期借款年初余额",
            unit="万元",
            formula="principal + construction_interest carry-forward",
            inputs=("long_term_loan_principal_repay", "construction_interest"),
            rows=(6,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="long_term_loan_principal_repay",
            label="长期借款还本",
            unit="万元",
            formula="outstanding principal at year start (carry chain from invest)",
            inputs=("invest:long_term_loan_principal",),
            rows=(7,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="construction_interest",
            label="建设期利息",
            unit="万元",
            formula="invest construction_interest carried into operating year 1",
            inputs=("invest:construction_interest",),
            rows=(8,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="annual_debt_service",
            label="当期还本付息",
            unit="万元",
            formula="PMT during loan term; principal_repay + interest after",
            inputs=("long_term_loan_interest_payment", "long_term_interest_total"),
            rows=(9,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="long_term_loan_interest_payment",
            label="长期借款付息",
            unit="万元",
            formula="principal repayment portion of PMT (pmt − interest)",
            inputs=("pmt", "long_term_loan_balance"),
            rows=(10,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="long_term_interest_total",
            label="长期借款付息合计",
            unit="万元",
            formula="interest payment = balance × loan_rate_long",
            inputs=("long_term_loan_balance", "params:loan_rate_long"),
            rows=(11,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="working_capital_balance",
            label="流动资金年初借款余额",
            unit="万元",
            formula="constant = invest:working_capital_loan_total per year",
            inputs=("invest:working_capital_loan",),
            rows=(13,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="working_capital_interest",
            label="流动资金付息",
            unit="万元",
            formula="working_capital_balance × working_capital_loan_rate",
            inputs=("working_capital_balance", "params:working_capital_loan_rate"),
            rows=(16,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="pmt",
            label="长期借款等额还本付息额",
            unit="万元",
            formula="PMT(loan_rate_long, loan_years, long_term_loan_total)",
            inputs=("params:loan_rate_long", "params:loan_years",
                    "invest:long_term_loan"),
            rows=(35,),
            kind="scalar",
            coupled=False,
        ),
        ItemSchema(
            key="pmt_residual",
            label="长期借款期末余额(SCC)",
            unit="万元",
            formula="balance − principal repayment carry-forward (SCC row 36)",
            inputs=("long_term_loan_balance", "long_term_loan_interest_payment"),
            rows=(36,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="short_term_principal",
            label="短期借款还本",
            unit="万元",
            formula="finplan short_term_repayment echoed (mutual block)",
            inputs=("finplan:short_term_repayment",),
            rows=(20,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="short_term_interest",
            label="短期借款付息",
            unit="万元",
            formula="short_term_principal × short_term_loan_rate (mutual block)",
            inputs=("short_term_principal", "params:short_term_loan_rate"),
            rows=(21,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="short_term_balance",
            label="短期借款年初余额",
            unit="万元",
            formula="lagged short_term_borrowing from finplan via solution",
            inputs=("finplan:short_term_borrowing",),
            rows=(18,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="total_balance",
            label="借款合计年初余额",
            unit="万元",
            formula="long_term + working_capital + short_term",
            inputs=("long_term_loan_balance", "working_capital_balance",
                    "short_term_balance"),
            rows=(23,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="total_principal",
            label="借款合计还本",
            unit="万元",
            formula="long_term_loan_interest_payment + short_term_principal",
            inputs=("long_term_loan_interest_payment", "short_term_principal"),
            rows=(25,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="total_interest",
            label="借款合计付息",
            unit="万元",
            formula="long_term + working_capital + short_term",
            inputs=("long_term_interest_total", "working_capital_interest",
                    "short_term_interest"),
            rows=(26,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="ebit",
            label="息税前利润(EBIT)",
            unit="万元",
            formula="cost:interest_expense + pnl:total_profit",
            inputs=("cost:interest_expense", "pnl:total_profit"),
            rows=(27,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="ebit_vat",
            label="息税前利润(含增值税)",
            unit="万元",
            formula="ebit + cost:deferred_vat_amortization",
            inputs=("ebit", "cost:deferred_vat_amortization"),
            rows=(28,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="icr",
            label="利息备付率(ICR)",
            unit="倍",
            formula="ebit_vat / cost:interest_expense (E..X, 20 cols; AD avg F..X)",
            inputs=("ebit_vat", "cost:interest_expense"),
            rows=(29,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="ebitda",
            label="EBITDA",
            unit="万元",
            formula="ebit + cost:depreciation",
            inputs=("ebit", "cost:depreciation"),
            rows=(30,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="ebitda_tax",
            label="EBITDA-所得税",
            unit="万元",
            formula="ebitda + cost:deferred_vat_amortization − pnl:income_tax",
            inputs=("ebitda", "cost:deferred_vat_amortization", "pnl:income_tax"),
            rows=(31,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="dscr",
            label="偿债备付率(DSCR)",
            unit="倍",
            formula="ebitda_tax / (principal_repay + interest) (E..S, 15 cols)",
            inputs=("ebitda_tax", "long_term_loan_interest_payment",
                    "long_term_interest_total"),
            rows=(32,),
            kind="series",
            coupled=False,
        ),
    ),
)
