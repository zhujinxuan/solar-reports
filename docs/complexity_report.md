# solar-v2 Complexity & Compression Report

Understanding = compression (MDL / Schmidhuber). Node count alone is
gameable by chunking; the robust signatures are total description length,
reuse structure (fan-out), and bounded per-unit complexity.

## 1. Minimum Description Length

- Engine compute-logic AST nodes (no docstrings): **21331**
  across **352** named compute functions.
- DAG formula/error cells: **5059**, total expression
  tokens: **31858**.
- **MDL ratio (engine AST / dag tokens) = 0.670**
  — the typed engine describes the same computation more tersely than the
  raw cell formulas. Re-chunking logic cannot move this ratio.
- One named function per 14.4 cells.

## 2. Reuse structure (anti-translation signature)

- Item dependency graph: 362 items, 423 edges.
- **Mean fan-out over producing items = 1.967**
  (cell-by-cell translation ≈ 1.0; high reuse = distilled concepts).
- Hubs with fan-out ≥ 3: **54**;
  ≥ 5: **16**; max fan-out = 8.
- Top reused items: pnl:total_profit(8), pnl:output_vat(7), finplan:short_term_repayment(7), cost:interest_expense(7), invest:working_capital(7), debt:long_term_loan_balance(6), cashflow:equity_net_cf(6), cashflow:project_net_cf(6), cost:fixed_asset_net_value(5), cashflow:project_pre_tax_net_cf(5)
- Longest dependency chain (DAG depth) = 33.

## 3. Cyclomatic complexity per compute function

- Median **1.0**, mean 1.63, max **14**.
- Branchy functions (CC ≥ 8): 4
  - CC=14  mutual.py:step_year
  - CC=10  invest.py:_compute_intermediates
  - CC=9  cost.py:compute_core
  - CC=8  finplan.py:compute_finplan

## 4. Halstead vocabulary

- Distinct operators n1=397, operands n2=1111,
  vocabulary = 1508, volume V = 87033.

## Gate bounds (tests/test_complexity.py)

- mdl_ratio_vs_tokens < 1.0  (now 0.670)
- mean_fanout_producers ≥ 1.5  (now 1.967)
- hubs_fanout_ge3 ≥ 30  (now 54)
- cc_max ≤ 20  (now 14)
- cc_median ≤ 2  (now 1.0)
- total_items ≤ 380  (now 362)
