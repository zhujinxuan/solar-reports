"""Perturbation tests — build ModelInputs in code, verify downstream effects.

Invariants from test_properties are re-run on every perturbed result.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import polars as pl
from solar_v2.engine import compute_model
from solar_v2.inputs import ModelInputs

# ── Invariant checkers (same as test_properties, relaxed where needed) ──


def _check_balance_sheet_identity(result):
    b = result.balance.frame
    ta = b["total_assets"].to_list()
    tle = b["total_liabilities_equity"].to_list()
    for i, (a, e) in enumerate(zip(ta, tle, strict=True)):
        assert math.isclose(a, e, abs_tol=1e-6), (
            f"Balance sheet imbalance at year index {i}"
        )


def _check_cumulative_surplus(result):
    fp = result.finplan.frame
    cs = fp["cumulative_surplus"].to_list()
    ncf = fp["net_cash_flow"].to_list()
    assert math.isclose(cs[0], ncf[0], abs_tol=1e-6)
    for i in range(1, len(cs)):
        assert math.isclose(cs[i], cs[i - 1] + ncf[i], abs_tol=1e-6)


def _check_cumulative_surplus_check(result):
    """cumulative_surplus_check[t] == net_cash_flow[t] for op years (t>=1)."""
    fp = result.finplan.frame
    csc = fp["cumulative_surplus_check"].to_list()
    ncf = fp["net_cash_flow"].to_list()
    assert abs(csc[0]) < 1e-6, f"csc[0]={csc[0]}"
    for i in range(1, len(csc)):
        assert math.isclose(csc[i], ncf[i], abs_tol=1e-6)


def _check_debt_amortized(result):
    """Long-term loan fully amortized by loan_years."""
    balance = result.debt.frame["long_term_loan_principal_repay"].to_list()
    loan_years = result.inputs.loan_years
    final_balance = balance[loan_years + 1]
    assert abs(final_balance) < 1e-3, (
        f"Loan balance after {loan_years} years: {final_balance}"
    )


def _check_cum_profit_recurrence(result):
    p = result.pnl.frame
    cp = p["cum_profit"].to_list()
    tp = p["total_profit"].to_list()
    te = p["tax_echo"].to_list()
    lcf = p["loss_carry_forward"].to_list()
    expected_0 = tp[0] - te[0] + lcf[0]
    assert math.isclose(cp[0], expected_0, abs_tol=2e-3)
    for i in range(1, len(cp)):
        expected = cp[i - 1] + tp[i] - te[i] + lcf[i]
        assert math.isclose(cp[i], expected, abs_tol=2e-3)


def _check_revenue_decomposition(result):
    p = result.pnl.frame
    sr = p["sales_revenue"].to_list()
    pg = p["power_generation"].to_list()
    ope = p["on_grid_price_excl_vat"].to_list()
    for _i, (r, g, price) in enumerate(zip(sr, pg, ope, strict=True)):
        assert math.isclose(r, g * price, abs_tol=1e-6)


def _check_all_invariants(result):
    """Run all property invariants on a result."""
    _check_balance_sheet_identity(result)
    _check_cumulative_surplus(result)
    _check_cumulative_surplus_check(result)
    _check_debt_amortized(result)
    _check_cum_profit_recurrence(result)
    _check_revenue_decomposition(result)


# ── Helpers ────────────────────────────────────────────────────────────


def _series_equal(a: pl.Series, b: pl.Series, rel_tol: float = 1e-6) -> bool:
    """Element-wise relative-tolerance equality."""
    al = a.to_list()
    bl = b.to_list()
    if len(al) != len(bl):
        return False
    for x, y in zip(al, bl, strict=True):
        if abs(y) > 1e-9:
            if abs(x - y) / abs(y) > rel_tol:
                return False
        elif abs(x - y) > 1e-9:
            return False
    return True


def _changed_domains(default_result, perturbed_result) -> int:
    """Count how many domain frames differ (at rel_tol=1e-6)."""
    domains = [
        ("params", default_result.params.frame),
        ("invest", default_result.invest.frame),
        ("debt", default_result.debt.frame),
        ("cost", default_result.cost.frame),
        ("pnl", default_result.pnl.frame),
        ("cashflow", default_result.cashflow.frame),
        ("finplan", default_result.finplan.frame),
        ("balance", default_result.balance.frame),
    ]
    changed = 0
    for name, def_frame in domains:
        pert_frame = getattr(perturbed_result, name).frame
        for col in def_frame.columns:
            if col in ("year", "period"):
                continue
            if not _series_equal(def_frame[col], pert_frame[col]):
                changed += 1
                break
    return changed


def _to_toml(data: dict) -> str:
    """Convert a flat dict to TOML text. Handles str, int, float, bool, tuple."""
    lines = []
    for key, val in data.items():
        if isinstance(val, bool):
            lines.append(f'{key} = {"true" if val else "false"}')
        elif isinstance(val, str):
            escaped = val.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        elif isinstance(val, (int, float)):
            lines.append(f"{key} = {val}")
        elif isinstance(val, (tuple, list)):
            items = ", ".join(str(float(v) if isinstance(v, int) else v) for v in val)
            lines.append(f"{key} = [{items}]")
    return "\n".join(lines)


# ── Tests ──────────────────────────────────────────────────────────────


def test_capacity_plus_10_pct(model_results):
    """+10% installed_capacity_mw: power_generation and sales_revenue scale
    x1.1 every year; equity_irr changes; invariants hold."""
    perturbed_inputs = ModelInputs(installed_capacity_mw=16.5)
    result = compute_model(perturbed_inputs)

    # Power generation scales x1.1
    default_pg = model_results.pnl.frame["power_generation"]
    perturbed_pg = result.pnl.frame["power_generation"]
    assert _series_equal(perturbed_pg / 1.1, default_pg), (
        "power_generation must scale x1.1 every year"
    )

    # Sales revenue scales x1.1
    default_sr = model_results.pnl.frame["sales_revenue"]
    perturbed_sr = result.pnl.frame["sales_revenue"]
    assert _series_equal(perturbed_sr / 1.1, default_sr), (
        "sales_revenue must scale x1.1 every year"
    )

    # Equity IRR changes
    assert not math.isclose(
        result.equity_irr, model_results.equity_irr, abs_tol=1e-8,
    ), "equity_irr must change when installed_capacity_mw changes"

    # All invariants still hold
    _check_all_invariants(result)


def test_loan_rate_plus_1pp(model_results):
    """+1pp loan_rate_long: debt service changes; invariants hold."""
    perturbed_inputs = ModelInputs(loan_rate_long=0.0465 + 0.01)
    result = compute_model(perturbed_inputs)

    # At least 3 downstream domains changed
    changed = _changed_domains(model_results, result)
    assert changed >= 3, (
        f"Expected >=3 domains to change with +1pp loan rate, got {changed}"
    )

    # All invariants still hold
    _check_all_invariants(result)


def test_toml_round_trip():
    """Write temp TOML with +10% capacity; from_toml == code-built inputs."""
    inputs = ModelInputs(installed_capacity_mw=16.5)
    data = inputs.model_dump()
    toml_text = _to_toml(data)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".toml", delete=False, encoding="utf-8"
    ) as f:
        f.write(toml_text)
        tmp_path = Path(f.name)

    try:
        loaded = ModelInputs.from_toml(tmp_path)
        assert loaded.model_dump() == inputs.model_dump(), (
            "TOML round-trip mismatch"
        )
    finally:
        tmp_path.unlink(missing_ok=True)
