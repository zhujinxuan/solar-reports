# DOMAIN.md — solar-v2 (v2-rebuild, settled 2026-07-26)

solar-v2 is the **standalone distilled domain engine**: the solar economic-evaluation
model as human-readable software. It embodies the model; it does NOT translate the DAG.

## Hard boundaries (goal SHALL-NOTs)

- NO imports of `xlsx_core`, `solar_v1`, `yaml`, or any dag/xlsx/extraction artifact —
  in `src/solar_v2/` anywhere (code, comments, docstrings, strings).
- NO cell addresses in `src/solar_v2/`: the regex `![A-Z]+\d+` (e.g. `损益!G8`,
  `参数表!C20`) must match NOTHING, including Chinese docstrings. Refer to concepts
  in prose ("参数表 建设周期月数"), never cells. Cell identity lives ONLY in
  `src/v2_benchmark/`.
- NO formula parsing/evaluation, NO global value-view/dict, NO per-cell compute
  functions. Cross-domain data flows through typed frozen dataclasses with named
  fields ONLY.
- polars for year-series. Frozen `@dataclass(frozen=True)` results; frozen pydantic
  for `ModelInputs`. No `Any`, no naked `dict`.

## Package layout

```
src/solar_v2/
  __init__.py           # empty
  inputs.py             # ModelInputs (frozen pydantic) + from_toml
  schema.py             # ItemSchema / DomainSchema / all_domains  (engine-owned)
  axis.py               # YearAxis (construction_year, operating years, n)
  domains/
    __init__.py
    params.py           # ProjectParameters: DerivedParams + 参数表 items + land-rent schedule
    invest.py           # InvestmentPlanning (投资计划)
    debt.py             # DebtService (还贷)
    cost.py             # Cost (成本)
    pnl.py              # PnL (损益)
    cashflow.py         # CashFlow (现金流量)
    finplan.py          # FinancialPlan (财务计划)
    balance.py          # BalanceSheet (资产负债)
    valuation.py        # Valuation (估值结果 + 指标汇总)
  mutual.py             # the year-interleaved mutual block solver
  engine.py             # compute_model(inputs) -> ModelResults  (staged dataflow)
  results.py            # ModelResults + headline scalars
src/v2_benchmark/        # SEPARATE import root; engine NEVER imports it
  __init__.py
  layout.py             # per-sheet cell-layout tables (THE only cell knowledge)
  projection.py         # ModelResults -> {node_id: value}
  compare.py            # diff vs benchmark, node-localized report
tests/                   # golden / properties / perturbation / structure / independence
```

## Year axis convention

`YearAxis`: `construction_year: int` (2020), `operating_years: int` (25),
`years: tuple[int, ...]` = the 25 operating calendar years (2021..2045),
`all_years` = construction year + operating years (26).

Every domain frame is a `pl.DataFrame` with a `year: Int64` column holding calendar
years, one row per year of that domain's natural axis (operating 25 for most;
construction year included only where the domain genuinely has construction-period
values). Column order in a frame: `year` first, then item keys in schema order.
Frames hold ONLY real year values — aggregate/total columns are NOT in frames
(they are projection-side reductions declared in `v2_benchmark/layout.py`).
Non-year axes (投资计划's 4 construction-period columns, 估值结果's dual 20/25-year
axes) get their own keyed frame (e.g. `period` column) on the result dataclass.

## Result type convention (every domain)

```python
@dataclass(frozen=True)
class PnLResult:                       # one per domain, defined in its module
    years: tuple[int, ...]
    frame: pl.DataFrame                # one column per year-series item key
    scalars: PnLScalars                # frozen dataclass, one field per scalar item key

@dataclass(frozen=True)
class PnLScalars: ...
```

Downstream domains read upstream values ONLY via these typed objects
(`cost.frame["total_operating_cost"]`, `debt.scalars.pmt`). No string-keyed bags.

## Item-computer convention (G7 — mechanically checked)

Each module declares `SCHEMA: DomainSchema` (from `solar_v2.schema`). ItemSchema
gains: `kind: "series" | "scalar"` and `coupled: bool` (default False).

- Non-coupled item key `foo` in domain module `m` ⇒ module `m` defines EXACTLY ONE
  function `compute_foo(...) -> pl.Series` (kind="series", length = domain axis)
  or `-> float | int | str | bool` (kind="scalar"). The structural test finds
  computers by name; a key with zero or two computers fails.
- Coupled items (`coupled=True`, the mutual block) are computed by
  `solar_v2.mutual.step_year`; their keys correspond 1:1 to fields of
  `mutual.YearSlice`. No module may define `compute_<key>` for a coupled key.
- No engine function returns one year of one series (a "single cell"); per-year
  work happens only inside `mutual.step_year`, which returns the whole `YearSlice`
  (~31 values across 5 domains) for one year.
- Cross-domain dependency extraction: `inspect.get_type_hints` on every
  `compute_*`/`step_year`/assemble function in module `m`; parameter annotation
  types map to domains via the type registry (each domain result type → its domain
  key; `ModelInputs`/`DerivedParams`/`YearAxis` → "params"). The set of FOREIGN
  domains referenced must equal `m.SCHEMA.depends_on`.

## Engine dataflow (stages — engine.py orchestrates, in this order)

1. `axis = YearAxis.from_inputs(inputs)`
2. `params_core = domains.params.compute_core(inputs, axis)` — DerivedParams
   (constant-folded scalars), year echoes, repair-rate echo, land-rent schedule.
3. `cost_statics = domains.cost.compute_statics(params_core)` — cost scalars
   computable from params alone (待抵扣进项税, 递延资产原值, land-rent-fed 原值
   values) needed by 投资计划.
4. `invest = domains.invest.compute_invest_plan(params_core, cost_statics)` —
   construction schedule, aux block (closed-form), funding plan.
5. `debt_base = domains.debt.compute_base(params_core, invest)` — long-term PMT
   schedule, working-capital loan, non-coupled rows.
6. `cost_core = domains.cost.compute_core(params_core, invest, debt_base)` —
   non-coupled cost items (depreciation, O&M, deferred VAT, land-rent amort).
7. `pnl_core = domains.pnl.compute_core(params_core, cost_statics)` — revenue,
   VAT/surcharge block, non-coupled PnL items.
8. `solution = mutual.solve(params_core, invest, debt_base, cost_core, pnl_core)`
   — per-year loop over the 25 operating years (see below).
9. Assemble full domain results merging coupled columns:
   `debt = debt.assemble(debt_base, solution)`,
   `cost = cost.assemble(cost_core, solution)`,
   `pnl = pnl.assemble(pnl_core, solution)`,
   `finplan = finplan.compute_finplan(params_core, invest, debt, cost, pnl, solution)`,
   `cashflow = cashflow.compute_cashflow(params_core, invest, debt, cost, pnl, finplan, solution)`.
10. `balance = balance.compute_balance(...)` (all upstream results).
11. `pnl = pnl.compute_valuation_aux(pnl, balance, cost)` — 估值口径 adjusted
    profit reads the balance sheet (genuine back-edge, computed here).
12. `params = params.compute_backedges(params_core, pnl, cost)` — 年发电小时数,
    首年运维费费率 (genuine back-edges from PnL/cost).
13. `valuation = valuation.compute_valuation(params, ..., balance, cashflow, cost, pnl)`.

**Echo-through-origin rule**: when the workbook mirrors a value across sheets
(e.g. 财务计划 reads 现金流量 rows that merely echo 成本/损益 items), the engine
reads the ORIGIN domain result, never the mirror. Document the origin in the
item's formula text.

## Mutual block (the year-interleaved recurrence)

The workbook's only cross-domain cycle is a SEQUENTIAL year recurrence, closed by
short-term borrowing. Carry into year t (as `YearCarry`, frozen):
`prior_short_term_borrowing: float`, `prior_cum_profit: float`,
`prior_cumulative_surplus: float` (all 0.0 before the first operating year).

`step_year(t, params, debt_base, cost_core, pnl_core, invest, carry) -> YearSlice`
computes, IN THIS ORDER (feed-forward within the year):

1. 财务计划 short_term_repayment(t) = carry.prior_short_term_borrowing
2. 还贷 short_term_principal(t) = short_term_repayment(t);
   还贷 short_term_interest(t) = principal × short_term_loan_rate
3. 成本 short_term_loan_interest(t) = 还贷 short_term_interest(t);
   成本 interest_expense(t) = long_term + working_capital + short_term + surplus(0);
   成本 total_operating_cost(t) = Σ non-interest cost rows + interest_expense
4. 损益 total_cost(t) = 成本 total_operating_cost(t);
   total_profit(t) = revenue − vat_surcharge − total_cost + vat_refund;
   loss_compensation(t) (reads carry.prior_cum_profit);
   income_tax(t) = (total_profit − loss_comp) × tax_rate_schedule(t);
   loss(t); tax_echo(t) = income_tax(t);
   loss_carry_forward(t) (fires only from operating year 6);
   cum_profit(t) = total_profit − tax_echo + loss_carry_forward + carry.prior_cum_profit;
   net_profit(t); surplus_reserve(t); distributable_profit(t)
5. 现金流量 equity_income_tax(t) = 损益 income_tax(t)
6. 财务计划 income_tax_outflow(t) = equity_income_tax(t);
   operating_outflow(t); operating_net_cf(t);
   interest_outflow(t) = 成本 interest_expense(t);
   distributable_profit_pool(t) = 损益 distributable_profit(t) × dividend_ratio;
   actual_distribution(t) = pool(t); profit_distribution(t) = pool(t);
   invest_outflow(t); invest_inflow(t);
   short_term_borrowing(t) = deficit bridge =
   max(0, −carry.prior_cumulative_surplus − operating_net_cf(t) − equity_injection(t)
          − construction_loan(t) − wc_loan(t) + invest_outflow(t) + short_term_repayment(t))
   invest_finance_net_cf(t); net_cash_flow(t) = operating + invest_finance − short_term_repayment(t);
   cumulative_surplus(t) = carry.prior_cumulative_surplus + net_cash_flow(t)

`YearSlice` has one named float field per coupled item key (exactly the schema
keys marked coupled across debt/cost/pnl/cashflow/finplan). `solve` returns
`MutualSolution` (frozen) holding one tuple per coupled key in year order, which
the domain `assemble` functions turn into frame columns.

## ModelInputs (inputs.py — frozen pydantic, Chinese `description` per field)

Givens with workbook defaults (names are the contract — do not rename):
`installed_capacity_mw=15.0, construction_year=2020, operating_years=25,
construction_months=6, first_year_full_hours=1145.0, guaranteed_hours=1100.0,
base_tariff=0.401, market_tariff=0.39, subsidy_per_kwh=0.0,
construction_cost=10046.37, equipment_cost=40042.42, survey_design_fee=600.0,
contingency=631.8, other_cost_base=2281.33, farmland_occupation_tax=3000.0,
land_use_fee=180.0, vat_rate_construction=0.13, vat_rate_equipment=0.13,
vat_rate_survey=0.06, equity_ratio=0.2, loan_rate_long=0.0465, loan_years=15,
working_capital_loan_rate=0.0435, short_term_loan_rate=0.0435, vat_rate=0.13,
vat_exempt_year=2020, city_maintenance_tax_rate=0.05,
education_surcharge_rate=0.05, income_tax_rate=0.25,
western_dev_preferential=False, western_dev_tax_rate=0.15,
land_use_tax_rate=0.0, land_taxed_area=0.0, surplus_reserve_ratio=0.1,
depreciation_years=20, salvage_rate=0.05, staff_count=8, avg_salary=9.0,
welfare_rate=0.5, other_cost_rate=25.0, material_cost_rate=10.0,
insurance_rate=0.0005, land_per_mw=11.623, land_rent_per_mu=600.0,
rent_escalation_freq=3, rent_escalation_rate=0.05, rent_payment_freq=2,
dividend_ratio=0.8, buyer_benchmark_rate=0.085, equity_sale_tax_rate=0.15,
epc_cost_price=3200.0, mgmt_allocation_ratio=0.0, project_income=300.0,
provisional_sum=3000.0`
Series givens: `degradation_factor` (26: 0, 0.975, 0.97, …, 0.855),
`load_rate` (26: 0, 0.95, then 1.0), `repair_rate_series` (25:
0.002×3, 0.004×5, 0.006×6, 0.01×11 — verify against old params/cost code).
Aux investment ratios: `aux_static_ratio_build1=0.0, aux_static_ratio_build2=0.0,
aux_static_ratio_operate=1.0`.
Derived scalars (unit_static_investment, deductible_vat, land_area, …) are NOT
inputs — they live in `DerivedParams`. `ModelInputs.from_toml(path)` (tomllib)
validates keys and constructs; unknown keys raise.

## Error-cell policy

- 财务计划 error-check row: a live domain concept with error states. FinPlanResult
  carries `error_checks: tuple[ErrorCheck, ...]` where
  `ErrorCheck(year: int, value: float | None, error: str | None)` — value when the
  check is finite, error string (e.g. `#DIV/0!`) where the workbook semantics
  divide by zero. Port the IF-chain faithfully from the old finplan code.
- 损益 construction-year label cells are deleted-reference artifacts with NO domain
  meaning: declared as static errors in `v2_benchmark/layout.py` (documented),
  not computed by the engine.

## Old-code usage during the build (transitional)

The old pipeline modules (`params.py`, `pipeline.py`, `schedule.py`, per-sheet
modules, `api.py`) remain in the tree ONLY as the logic source and numeric oracle
while slices are built. Slice builders: port logic from them (never import them),
and verify numerically against `solar_v2.api.compute()` output per sheet-row
(write scratch scripts under your own tmp paths, do not commit them). They are
DELETED at integration, together with the old tests, `scripts/gen_*.py`, and the
annotated dag artifact.
