"""Domain invariants on compute_model() results.

Every invariant MUST hold on the default benchmark inputs.
"""

from __future__ import annotations

import math

# ── (a) Balance-sheet identity ──────────────────────────────────────────


def test_balance_sheet_identity(model_results):
    """total_assets == total_liabilities_equity every year."""
    b = model_results.balance.frame
    ta = b["total_assets"].to_list()
    tle = b["total_liabilities_equity"].to_list()
    for i, (a, e) in enumerate(zip(ta, tle, strict=True)):
        assert math.isclose(a, e, abs_tol=1e-6), (
            f"Balance sheet imbalance at year index {i}: "
            f"total_assets={a}, total_liabilities_equity={e}"
        )


def test_balance_check_zero(model_results):
    """balance_check ≈ 0 every year (atol=1e-6)."""
    bc = model_results.balance.frame["balance_check"].to_list()
    for i, v in enumerate(bc):
        assert abs(v) < 1e-6, f"balance_check[{i}] = {v}, expected ~0"


# ── (b) Cash conservation ───────────────────────────────────────────────


def test_cumulative_surplus_recurrence(model_results):
    """cumulative_surplus[t] == cumulative_surplus[t-1] + net_cash_flow[t]."""
    fp = model_results.finplan.frame
    cs = fp["cumulative_surplus"].to_list()
    ncf = fp["net_cash_flow"].to_list()

    # Construction year (index 0): cumulative_surplus = net_cash_flow
    assert math.isclose(cs[0], ncf[0], abs_tol=1e-6), (
        f"Construction year: cumulative_surplus={cs[0]}, net_cash_flow={ncf[0]}"
    )
    for i in range(1, len(cs)):
        expected = cs[i - 1] + ncf[i]
        assert math.isclose(cs[i], expected, abs_tol=1e-6), (
            f"Year {i}: cumulative_surplus={cs[i]}, "
            f"expected={cs[i-1]}+{ncf[i]}={expected}"
        )


def test_cumulative_surplus_check_equals_net_cf(model_results):
    """cumulative_surplus_check[t] == net_cash_flow[t] for all op years (t>=1).

    cumulative_surplus_check (row 42) is an audit row that independently
    computes operating_net_cf + invest_finance_net_cf - short_term_repayment,
    which must equal net_cash_flow by the mutual-block identity.
    """
    fp = model_results.finplan.frame
    csc = fp["cumulative_surplus_check"].to_list()
    ncf = fp["net_cash_flow"].to_list()
    # Year 0 (construction): both should be 0
    assert abs(csc[0]) < 1e-6, f"cumulative_surplus_check[0] = {csc[0]}"
    for i in range(1, len(csc)):
        assert math.isclose(csc[i], ncf[i], abs_tol=1e-6), (
            f"Year {i}: cumulative_surplus_check={csc[i]}, "
            f"net_cash_flow={ncf[i]}"
        )


# ── (c) Debt schedule consistency ───────────────────────────────────────

def test_debt_long_term_loan_amortized(model_results):
    """Long-term loan fully amortized: balance at loan_years ≈ 0."""
    debt_frame = model_results.debt.frame
    balance = debt_frame["long_term_loan_principal_repay"].to_list()
    loan_years = model_results.inputs.loan_years  # 15

    # Balance at start of construction year should be 0
    # (the loan is drawn in construction period, not before)
    # After loan_years of operating, the balance should be ~0
    final_balance = balance[loan_years + 1]  # +1 for construction year
    assert abs(final_balance) < 1e-3, (
        f"Long-term loan balance after {loan_years} years: {final_balance}"
    )


def test_surplus_carry_diffs(model_results):
    """Consecutive cumulative_surplus diffs == net_cash_flow."""
    fp = model_results.finplan.frame
    cs = fp["cumulative_surplus"].to_list()
    ncf = fp["net_cash_flow"].to_list()
    for i in range(1, len(cs)):
        diff = cs[i] - cs[i - 1]
        assert math.isclose(diff, ncf[i], abs_tol=1e-6), (
            f"Year {i}: cumulative_surplus diff={diff}, "
            f"net_cash_flow={ncf[i]}"
        )


# ── (e) PnL cum_profit recurrence ───────────────────────────────────────


def test_cum_profit_recurrence(model_results):
    """cum_profit[t] == cum_profit[t-1] + total_profit[t] - tax_echo[t]
    + loss_carry_forward[t].

    For operating year 1 (index 0 in pnl.frame): cum_profit[0] == expected.
    Uses abs_tol=2e-3 to account for floating-point in the loss_carry_forward
    chain (rounded to 0.001 precision in workbook semantics).
    """
    p = model_results.pnl.frame
    cp = p["cum_profit"].to_list()
    tp = p["total_profit"].to_list()
    te = p["tax_echo"].to_list()
    lcf = p["loss_carry_forward"].to_list()

    expected_0 = tp[0] - te[0] + lcf[0]
    assert math.isclose(cp[0], expected_0, abs_tol=2e-3), (
        f"PnL year 0: cum_profit={cp[0]}, expected={expected_0}"
    )

    for i in range(1, len(cp)):
        expected = cp[i - 1] + tp[i] - te[i] + lcf[i]
        assert math.isclose(cp[i], expected, abs_tol=2e-3), (
            f"PnL year {i}: cum_profit={cp[i]}, "
            f"expected={cp[i-1]}+{tp[i]}-{te[i]}+{lcf[i]}={expected}"
        )



# ── (f) Revenue decomposition ───────────────────────────────────────────


def test_revenue_decomposition(model_results):
    """sales_revenue == power_generation × on_grid_price_excl_vat."""
    p = model_results.pnl.frame
    sr = p["sales_revenue"].to_list()
    pg = p["power_generation"].to_list()
    ope = p["on_grid_price_excl_vat"].to_list()
    for i, (r, g, price) in enumerate(zip(sr, pg, ope, strict=True)):
        expected = g * price
        assert math.isclose(r, expected, abs_tol=1e-6), (
            f"PnL year {i}: sales_revenue={r}, "
            f"power_generation × price={g}×{price}={expected}"
        )
