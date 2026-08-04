"""engine — compute_model(inputs) -> ModelResults.

Explicit typed dataflow (see packages/solar-v2/DOMAIN.md §Engine dataflow):
params → cost statics → invest → debt base → pnl core → cost core →
mutual solve → assemble cost/pnl/debt → finplan → cashflow → balance →
pnl valuation-aux → params back-edges → valuation.

Zero file I/O in the compute path. The engine never touches dag files,
workbooks, parsers, or evaluators.
"""

from __future__ import annotations

import polars as pl

from solar_v2.axis import YearAxis
from solar_v2.domains import (
    balance,
    cashflow,
    cost,
    debt,
    finplan,
    invest,
    params,
    pnl,
    valuation,
)
from solar_v2.inputs import ModelInputs
from solar_v2.mutual import MutualSolution, solve
from solar_v2.results import ModelResults


def _invest_at(invest_plan: invest.InvestResult, column: str, period: str) -> float:
    """One invest frame value at a named construction period."""
    periods = invest_plan.frame["period"].to_list()
    if period not in periods:
        return 0.0
    return float(invest_plan.frame[column].to_list()[periods.index(period)])


def _coupled_26(solution: MutualSolution, key: str) -> pl.Series:
    """Coupled key as a 26-value series (construction year 0.0 + 25 op years)."""
    return pl.Series(
        key, [0.0, *[getattr(s, key) for s in solution.steps]], dtype=pl.Float64
    )


def _op_as_26(name: str, series: pl.Series) -> pl.Series:
    """Prepend a construction-year 0.0 to a 25-value operating-year series."""
    return pl.Series(name, [0.0, *series.to_list()], dtype=pl.Float64)


def compute_model(inputs: ModelInputs | None = None) -> ModelResults:
    """Run the full solar economic-evaluation model.

    Args:
        inputs: model parameters; defaults to the workbook-derived defaults.

    Returns:
        Typed per-domain results (year-keyed polars frames + scalars).
    """
    if inputs is None:
        inputs = ModelInputs()

    axis = YearAxis.of(inputs.construction_year, inputs.operating_years)

    params_core = params.compute_core(inputs, axis)
    cost_statics = cost.compute_statics(params_core, inputs)
    invest_plan = invest.compute_invest_plan(params_core, cost_statics)
    debt_base = debt.compute_base(
        inputs,
        axis,
        invest_frame=invest_plan.frame,
        invest_working_capital_loan_total=invest_plan.scalars.working_capital_loan_total,
        invest_long_term_loan_total=invest_plan.scalars.long_term_loan_total,
        invest_construction_interest_oper1=_invest_at(
            invest_plan, "construction_interest", "oper1"
        ),
    )
    pnl_core = pnl.compute_core(params_core, cost_statics)
    cost_core = cost.compute_core(
        params_core, inputs, cost_statics, invest_plan, debt_base, pnl_core
    )

    solution = solve(params_core, invest_plan, debt_base, cost_core, pnl_core)

    cost_result = cost.assemble(cost_core, solution)
    pnl_result = pnl.assemble(pnl_core, solution)
    debt_result = debt.assemble(
        debt_base,
        short_term_principal=_coupled_26(solution, "short_term_principal"),
        short_term_interest=_coupled_26(solution, "short_term_interest"),
        short_term_borrowing=pl.Series(
            "short_term_borrowing",
            [s.short_term_borrowing for s in solution.steps],
            dtype=pl.Float64,
        ),
        cost_interest_expense=_op_as_26(
            "interest_expense", cost_result.frame["interest_expense"]
        ),
        cost_depreciation=_op_as_26("depreciation", cost_result.frame["depreciation"]),
        cost_deferred_vat_amortization=_op_as_26(
            "deferred_vat_amortization", cost_result.frame["deferred_vat_amortization"]
        ),
        pnl_total_profit=_op_as_26("total_profit", pnl_result.frame["total_profit"]),
        pnl_income_tax=_op_as_26("income_tax", pnl_result.frame["income_tax"]),
    )
    finplan_result = finplan.compute_finplan(
        params_core, invest_plan, debt_result, cost_result, pnl_result, solution
    )
    cashflow_result = cashflow.compute_cashflow(
        params_core,
        invest_plan,
        debt_result,
        cost_result,
        pnl_result,
        finplan_result,
        solution,
    )
    balance_result = balance.compute_balance(
        params_core,
        invest_plan,
        debt_result,
        cost_result,
        pnl_result,
        finplan_result,
        cashflow_result,
    )
    pnl_result = pnl.compute_valuation_aux(
        pnl_result, balance_result, cost_result, params_core
    )
    params_final = params.compute_backedges(params_core, pnl_result, cost_result)
    valuation_result = valuation.compute_valuation(
        params_final,
        invest_plan,
        debt_result,
        cost_result,
        pnl_result,
        cashflow_result,
        finplan_result,
        balance_result,
    )

    return ModelResults(
        inputs=inputs,
        params=params_final,
        invest=invest_plan,
        debt=debt_result,
        cost=cost_result,
        pnl=pnl_result,
        cashflow=cashflow_result,
        finplan=finplan_result,
        balance=balance_result,
        valuation=valuation_result,
    )
