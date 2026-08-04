"""Cost — 总成本费用估算表 (operating cost + depreciation/amortization).

The cost sheet has three sections:
- Top section (rows 4-22): year labels, depreciation echo, repair, salary,
  insurance, material, land tax, land-rent echo, interest, other, operating cost,
  total operating cost.
- Depreciation section (rows 26-31): fixed-asset original, annual depreciation,
  net-value carry chain.
- Deferred sections (rows 48-57): deferred VAT amortization + net, land-rent
  original + amortization + net.

Year alignment note
-------------------
All frames are keyed by operating calendar year (the 25-year operating period).
The old sheet uses column shifts (E..AC vs F..AD) to avoid construction-year
blanks; those are Excel layout artifacts with NO semantic year offset. Every
item key maps to the operating year it belongs to.
The land-rent-net carry chain starts with the construction-year land-rent
payment as the initial prior-net. It then carries forward:
net_t = prior_net - amort_t + original_t.

The deferred-VAT carry chain starts with deferred_original (D50 = D28) as the
initial prior-net. Year 1 amortization = pnl.sales_revenue[0] * vat_rate,
subsequent years: min(prior_net, pnl.sales_revenue[t] * vat_rate).

Stage-order flag
----------------
compute_core takes pnl_core: PnLCore because deferred-VAT amortization reads
pnl.sales_revenue. Engine stage 6 (cost_core) MUST run AFTER pnl_core (stage 7
in the original numbering). The lead should reorder: run pnl_core first, then
cost_core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from solar_v2.axis import YearAxis
from solar_v2.schema import DomainSchema, ItemSchema

if TYPE_CHECKING:
    from solar_v2.domains.debt import DebtBase
    from solar_v2.domains.invest import InvestResult
    from solar_v2.domains.params import ParamsCore
    from solar_v2.domains.pnl import PnLCore
    from solar_v2.inputs import ModelInputs
    from solar_v2.mutual import MutualSolution


# ── Result types ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CostStatics:
    """Scalars computable from params alone (needed by invest before cost_core).

    These are produced by ``compute_statics`` at engine stage 3.
    """

    deductible_vat: float  # 待抵扣固定资产进项税额 (D28)
    deferred_original: float  # 递延资产原值 (D50, = D28)
    land_rent_originals: tuple[float, ...]  # row 55 长期待摊费用原值 (25 values)
    land_rent_initial: float  # first land_rent_payment (construction year)
    construction_land_rent: float  # always 0.0


@dataclass(frozen=True)
class CostScalars:
    """Scalar values from the cost domain."""

    fixed_asset_original: float  # 固定资产原值 (D29)
    deductible_vat: float  # 待抵扣固定资产进项税额 (D28)
    deferred_original: float  # 递延资产原值 (D50)
    # Final-year (26th column) tails of the shifted land-rent schedule:
    land_rent_original_final: float = 0.0  # 末年长期待摊费用原值(第26列)
    land_rent_amortization_final: float = 0.0  # 末年长期待摊费用摊销(第26列)
    land_rent_net_final: float = 0.0  # 末年长期待摊费用净值(第26列)
    # Static label scalars (row 19, 20) — AD columns are 0.0
    fixed_cost_label: float = 0.0  # 固定成本标签
    variable_cost_label: float = 0.0  # 可变成本标签


@dataclass(frozen=True)
class CostCore:
    """Non-coupled cost items: frame + scalars, before mutual solution."""

    years: tuple[int, ...]
    frame: pl.DataFrame
    scalars: CostScalars


@dataclass(frozen=True)
class CostResult:
    """Full cost result: frame with coupled columns merged, plus scalars."""

    years: tuple[int, ...]
    frame: pl.DataFrame
    scalars: CostScalars


# ── statics ───────────────────────────────────────────────────────────────


def compute_statics(
    params_core: ParamsCore,
    inputs: ModelInputs,
) -> CostStatics:
    """Compute cost scalars from params alone (stage 3, before invest).

    params_core: ParamsCore from domains.params — must have:
      - frame with columns "land_rent_payment", "land_rent_amortization"
      - derived: deductible_vat_construction
    """
    frame: pl.DataFrame = params_core.frame  # type: ignore[attr-defined]
    deductible = float(params_core.derived.deductible_vat_construction)  # type: ignore[attr-defined]

    # Land-rent originals in the cost sheet (row 55, E..AC):
    #   E55 (op yr 1) = params payment for construction year
    #   F55 (op yr 2) = params payment for year 2021
    #   ...
    # This is a one-year shift: cost-sheet original[i] = params_payment[i]
    # (where i=0 is the construction year, i=24 is year 24 of op).
    # We take payments[0..24] = 25 values.
    payments = frame["land_rent_payment"].to_list()  # 26 values
    land_rent_originals = tuple(float(payments[i]) for i in range(25))

    return CostStatics(
        deductible_vat=deductible,
        deferred_original=deductible,
        land_rent_originals=land_rent_originals,
        land_rent_initial=float(payments[0]),
        construction_land_rent=0.0,  # D54 — always zero
    )


# ── Item compute functions (one per non-coupled schema key) ───────────────
#
# Each function name matches the item key: compute_<key>.
# Series items return pl.Series (Float64 or Int64); scalar items return float.


# -- Year label items -------------------------------------------------------


def compute_year_labels(n: int) -> pl.Series:
    """Row 4: year labels (1..25)."""
    return pl.Series("year_labels", list(range(1, n + 1)), dtype=pl.Int64)


def compute_depreciation_year_labels(n: int) -> pl.Series:
    """Row 26: depreciation section year labels (1..25)."""
    return pl.Series("depreciation_year_labels", list(range(1, n + 1)), dtype=pl.Int64)


def compute_deferred_vat_year_labels(n: int) -> pl.Series:
    """Row 48: deferred-VAT section year labels — first two both 1, then 2..24."""
    return pl.Series("deferred_vat_year_labels", [1, 1, *range(2, n)], dtype=pl.Int64)


# -- Constant-rate items ----------------------------------------------------


def compute_salary_cost(
    staff_count: float,
    avg_salary: float,
    welfare_rate: float,
    n: int,
) -> pl.Series:
    """Row 8: 工资及福利等 — staff_count × avg_salary × (1 + welfare_rate), constant."""
    val = staff_count * avg_salary * (1.0 + welfare_rate)
    return pl.Series("salary_cost", [val] * n, dtype=pl.Float64)


def compute_material_cost(
    material_cost_rate: float,
    installed_capacity_mw: float,
    n: int,
) -> pl.Series:
    """Row 10: 材料费 — material_cost_rate × installed_capacity_mw, constant."""
    val = material_cost_rate * installed_capacity_mw
    return pl.Series("material_cost", [val] * n, dtype=pl.Float64)


def compute_land_tax_cost(land_use_tax: float, n: int) -> pl.Series:
    """Row 11: 城镇土地使用税 — land_use_tax per year, constant."""
    return pl.Series("land_tax_cost", [land_use_tax] * n, dtype=pl.Float64)


def compute_surplus_interest(n: int) -> pl.Series:
    """Row 17: 盈余资金利息收入 — 0, all years."""
    return pl.Series("surplus_interest", [0.0] * n, dtype=pl.Float64)


def compute_other_cost(
    other_cost_rate: float,
    installed_capacity_mw: float,
    n: int,
) -> pl.Series:
    """Row 18: 其他费用 — other_cost_rate × installed_capacity_mw, constant."""
    val = other_cost_rate * installed_capacity_mw
    return pl.Series("other_cost", [val] * n, dtype=pl.Float64)


# -- Echo items (pass-through from upstream) --------------------------------


def compute_depreciation_echo(depreciation: pl.Series) -> pl.Series:
    """Row 6: 折旧费 echo — same as depreciation (row 30)."""
    return depreciation.alias("depreciation_echo")


def compute_land_rent_echo(land_rent_amortization: pl.Series) -> pl.Series:
    """Row 12: 长期待摊费用（摊销回显）— same-year echo of row 56."""
    return land_rent_amortization.alias("land_rent_echo")


def compute_long_term_loan_interest(
    lt_interest: tuple[float, ...],
) -> pl.Series:
    """Row 14: 长期贷款利息 — echo from debt_base."""
    return pl.Series("long_term_loan_interest", list(lt_interest), dtype=pl.Float64)


def compute_working_capital_loan_interest(
    wc_interest: tuple[float, ...],
) -> pl.Series:
    """Row 15: 流动资金贷款利息 — echo from debt_base."""
    return pl.Series(
        "working_capital_loan_interest", list(wc_interest), dtype=pl.Float64
    )


def compute_land_rent_original(
    statics_originals: tuple[float, ...],
) -> pl.Series:
    """Row 55: 长期待摊费用原值 — from statics (pre-shifted param payments)."""
    return pl.Series("land_rent_original", list(statics_originals), dtype=pl.Float64)


def compute_land_rent_amortization(
    params_amort: tuple[float, ...],
) -> pl.Series:
    """Row 56: 长期待摊费用摊销 — shifted from params land_rent_amortization."""
    return pl.Series("land_rent_amortization", list(params_amort), dtype=pl.Float64)


# -- Scalar echo items ------------------------------------------------------


def compute_deductible_vat(deductible: float) -> float:
    """Row 28: 待抵扣固定资产进项税额 (D28 only)."""
    return deductible


def compute_fixed_asset_original(fa_orig: float) -> float:
    """Row 29: 固定资产原值 — pre-computed by invest."""
    return fa_orig


def compute_deferred_original(deferred: float) -> float:
    """Row 50: 递延资产原值 — = D28."""
    return deferred


# -- Carry-chain / rate-based items -----------------------------------------


def compute_depreciation(
    fixed_asset_original: float,
    load_rates: tuple[float, ...],
    dep_rate: float,
    dep_years: int,
    n: int,
) -> pl.Series:
    """Row 30: 当期折旧费 — D29 × dep_rate × load_rate, 20-year cutoff."""
    vals = [
        fixed_asset_original * dep_rate * load_rates[i]
        if dep_years - (i + 1) >= 0
        else 0.0
        for i in range(n)
    ]
    return pl.Series("depreciation", vals, dtype=pl.Float64)


def compute_fixed_asset_net_value(
    fixed_asset_original: float,
    depreciation: pl.Series,
) -> pl.Series:
    """Row 31: 固定资产净值 — carry chain: prev_net − depreciation."""
    prev = fixed_asset_original
    vals = []
    for v in depreciation.to_list():
        net = prev - float(v)
        vals.append(net)
        prev = net
    return pl.Series("fixed_asset_net_value", vals, dtype=pl.Float64)


def compute_insurance_cost(
    fixed_asset_net_value: pl.Series,
    insurance_rate: float,
) -> pl.Series:
    """Row 9: 保险费 — fixed_asset_net_value × insurance_rate per year."""
    vals = [float(nv) * insurance_rate for nv in fixed_asset_net_value.to_list()]
    return pl.Series("insurance_cost", vals, dtype=pl.Float64)


def compute_repair_cost(
    fixed_asset_original: float,
    repair_rates: tuple[float, ...],
) -> pl.Series:
    """Row 7: 修理费 — fixed_asset_original × repair_rate per year."""
    vals = [fixed_asset_original * rr for rr in repair_rates]
    return pl.Series("repair_cost", vals, dtype=pl.Float64)


def compute_deferred_vat_amortization(
    deferred_original: float,
    sales_revenue: tuple[float, ...],
    vat_rate: float,
    n: int,
) -> pl.Series:
    """Row 51: 递延资产摊销(进项税额) — carry chain from deferred_original.

    Year 1: pnl.sales_revenue[0] × vat_rate.
    Year t: min(prior_net, pnl.sales_revenue[t] × vat_rate).
    """
    amort_vals = []
    prev = deferred_original
    for i in range(n):
        vat_from_pnl = sales_revenue[i] * vat_rate
        amort = vat_from_pnl if i == 0 else min(prev, vat_from_pnl)
        amort_vals.append(amort)
        prev -= amort
    return pl.Series("deferred_vat_amortization", amort_vals, dtype=pl.Float64)


def compute_deferred_vat_net(
    deferred_original: float,
    deferred_vat_amortization: pl.Series,
) -> pl.Series:
    """Row 52: 递延资产净值(进项税额) — carry chain from deferred_original."""
    prev = deferred_original
    vals = []
    for amort in deferred_vat_amortization.to_list():
        prev -= float(amort)
        vals.append(prev)
    return pl.Series("deferred_vat_net", vals, dtype=pl.Float64)


def compute_land_rent_net(
    land_rent_original: pl.Series,
    land_rent_amortization: pl.Series,
    n: int,
) -> pl.Series:
    """Row 57: 长期待摊费用净值 — carry chain: prev + original − amort.

    Initial prior = 0.0. Amort at year i uses amort[i-1] (i≥1), else 0.
    """
    prev = 0.0
    vals = []
    amort_list = land_rent_amortization.to_list()
    orig_list = land_rent_original.to_list()
    for i in range(n):
        net_amort = float(amort_list[i - 1]) if i > 0 else 0.0
        net_val = prev - net_amort + float(orig_list[i])
        vals.append(net_val)
        prev = net_val
    return pl.Series("land_rent_net", vals, dtype=pl.Float64)


def compute_operating_cost(
    repair_cost: pl.Series,
    salary_cost: pl.Series,
    insurance_cost: pl.Series,
    material_cost: pl.Series,
    land_tax_cost: pl.Series,
    other_cost: pl.Series,
    n: int,
) -> pl.Series:
    """Row 22: 经营成本 — sum of non-interest cost rows."""
    vals = [
        float(repair_cost[i]) + float(salary_cost[i]) + float(insurance_cost[i])
        + float(material_cost[i]) + float(land_tax_cost[i]) + float(other_cost[i])
        for i in range(n)
    ]
    return pl.Series("operating_cost", vals, dtype=pl.Float64)


# ── Orchestrator: compute_core ────────────────────────────────────────────


def compute_core(
    params_core: ParamsCore,
    inputs: ModelInputs,
    statics: CostStatics,
    invest: InvestResult,
    debt_base: DebtBase,
    pnl_core: PnLCore,
) -> CostCore:
    """Compute non-coupled cost items (stage 6).

    Calls the compute_<key> functions in dependency order and assembles
    the CostCore result.
    """
    axis: YearAxis = params_core.axis  # type: ignore[attr-defined]
    years = axis.years
    n = len(years)
    params_frame: pl.DataFrame = params_core.frame  # type: ignore[attr-defined]
    debt_frame: pl.DataFrame = debt_base.frame  # type: ignore[attr-defined]
    pnl_frame: pl.DataFrame = pnl_core.frame  # type: ignore[attr-defined]

    # Extract operating-year slices from upstream frames
    op_mask = [y > axis.construction_year for y in params_frame["year"].to_list()]
    repair_rates = tuple(
        float(v)
        for v in params_frame.filter(pl.Series(op_mask))["repair_rate_series"].to_list()
    )
    load_rates = tuple(
        float(v)
        for v in params_frame.filter(pl.Series(op_mask))["load_rate"].to_list()
    )
    # Land-rent amortization: cost row 56 (F..AD) = params amorts[1..25]
    all_amorts = params_frame["land_rent_amortization"].to_list()
    land_rent_amort = tuple(float(all_amorts[i + 1]) for i in range(n))

    # Debt: extract operating years
    debt_op_mask = [
        y > axis.construction_year for y in debt_frame["year"].to_list()
    ]
    lt_interest = tuple(
        float(v)
        for v in debt_frame.filter(pl.Series(debt_op_mask))[
            "long_term_interest_total"
        ].to_list()
    )
    wc_interest = tuple(
        float(v)
        for v in debt_frame.filter(pl.Series(debt_op_mask))[
            "working_capital_interest"
        ].to_list()
    )

    # PnL: sales_revenue (operating-year keyed, 25 values)
    sales_revenue = tuple(float(v) for v in pnl_frame["sales_revenue"].to_list())

    # Scalars from upstream
    fixed_asset_original_val = float(invest.scalars.fixed_asset_original)  # type: ignore[attr-defined]
    dep_rate = params_core.derived.depreciation_rate  # type: ignore[attr-defined]
    dep_years = int(inputs.depreciation_years)

    # ── Call compute_ functions in dependency order ─────────────────────

    # Year labels
    year_labels_s = compute_year_labels(n)
    dep_year_labels_s = compute_depreciation_year_labels(n)
    def_vat_year_labels_s = compute_deferred_vat_year_labels(n)

    # Depreciation + net value (needed by insurance and repair)
    depreciation_s = compute_depreciation(
        fixed_asset_original_val, load_rates, dep_rate, dep_years, n
    )
    net_value_s = compute_fixed_asset_net_value(
        fixed_asset_original_val, depreciation_s
    )

    # Rate-based items
    insurance_cost_s = compute_insurance_cost(net_value_s, inputs.insurance_rate)
    repair_cost_s = compute_repair_cost(fixed_asset_original_val, repair_rates)

    # Constant-rate items
    salary_cost_s = compute_salary_cost(
        inputs.staff_count, inputs.avg_salary, inputs.welfare_rate, n
    )
    material_cost_s = compute_material_cost(
        inputs.material_cost_rate, params_core.derived.installed_capacity_mw, n  # type: ignore[attr-defined]
    )
    land_tax_cost_s = compute_land_tax_cost(
        params_core.derived.land_use_tax, n  # type: ignore[attr-defined]
    )
    surplus_interest_s = compute_surplus_interest(n)
    other_cost_s = compute_other_cost(
        inputs.other_cost_rate, params_core.derived.installed_capacity_mw, n  # type: ignore[attr-defined]
    )

    # Echo items
    depreciation_echo_s = compute_depreciation_echo(depreciation_s)
    land_rent_echo_s = compute_land_rent_echo(
        compute_land_rent_amortization(land_rent_amort)
    )
    lt_loan_interest_s = compute_long_term_loan_interest(lt_interest)
    wc_loan_interest_s = compute_working_capital_loan_interest(wc_interest)

    # Land-rent block
    lr_original_s = compute_land_rent_original(statics.land_rent_originals)
    lr_amort_s = compute_land_rent_amortization(land_rent_amort)
    lr_net_s = compute_land_rent_net(lr_original_s, lr_amort_s, n)

    # Deferred VAT block
    deferred_amt_s = compute_deferred_vat_amortization(
        statics.deferred_original, sales_revenue, inputs.vat_rate, n
    )
    deferred_net_s = compute_deferred_vat_net(
        statics.deferred_original, deferred_amt_s
    )

    # Operating cost (sum of non-interest items)
    operating_cost_s = compute_operating_cost(
        repair_cost_s, salary_cost_s, insurance_cost_s,
        material_cost_s, land_tax_cost_s, other_cost_s, n,
    )

    # Final-year tails of the shifted land-rent schedule
    all_payments = params_frame["land_rent_payment"].to_list()
    land_rent_original_final = float(all_payments[25])
    land_rent_amortization_final = float(all_amorts[25])
    lr_net_list = lr_net_s.to_list()
    land_rent_net_final = (
        lr_net_list[-1] - land_rent_amortization_final + land_rent_original_final
    )

    # ── Build frame ──────────────────────────────────────────────────────

    frame = pl.DataFrame(
        {
            "year": list(years),
            "year_labels": year_labels_s,
            "depreciation_year_labels": dep_year_labels_s,
            "deferred_vat_year_labels": def_vat_year_labels_s,
            "depreciation_echo": depreciation_echo_s,
            "repair_cost": repair_cost_s,
            "salary_cost": salary_cost_s,
            "insurance_cost": insurance_cost_s,
            "material_cost": material_cost_s,
            "land_tax_cost": land_tax_cost_s,
            "land_rent_echo": land_rent_echo_s,
            "long_term_loan_interest": lt_loan_interest_s,
            "working_capital_loan_interest": wc_loan_interest_s,
            "surplus_interest": surplus_interest_s,
            "other_cost": other_cost_s,
            "operating_cost": operating_cost_s,
            "depreciation": depreciation_s,
            "fixed_asset_net_value": net_value_s,
            "deferred_vat_amortization": deferred_amt_s,
            "deferred_vat_net": deferred_net_s,
            "land_rent_original": lr_original_s,
            "land_rent_amortization": lr_amort_s,
            "land_rent_net": lr_net_s,
        },
        schema_overrides={
            "year": pl.Int64,
            "year_labels": pl.Int64,
            "depreciation_year_labels": pl.Int64,
            "deferred_vat_year_labels": pl.Int64,
            "depreciation_echo": pl.Float64,
            "repair_cost": pl.Float64,
            "salary_cost": pl.Float64,
            "insurance_cost": pl.Float64,
            "material_cost": pl.Float64,
            "land_tax_cost": pl.Float64,
            "land_rent_echo": pl.Float64,
            "long_term_loan_interest": pl.Float64,
            "working_capital_loan_interest": pl.Float64,
            "surplus_interest": pl.Float64,
            "other_cost": pl.Float64,
            "operating_cost": pl.Float64,
            "depreciation": pl.Float64,
            "fixed_asset_net_value": pl.Float64,
            "deferred_vat_amortization": pl.Float64,
            "deferred_vat_net": pl.Float64,
            "land_rent_original": pl.Float64,
            "land_rent_amortization": pl.Float64,
            "land_rent_net": pl.Float64,
        },
    )

    return CostCore(
        years=years,
        frame=frame,
        scalars=CostScalars(
            fixed_asset_original=fixed_asset_original_val,
            deductible_vat=statics.deductible_vat,
            deferred_original=statics.deferred_original,
            land_rent_original_final=land_rent_original_final,
            land_rent_amortization_final=land_rent_amortization_final,
            land_rent_net_final=land_rent_net_final,
        ),
    )


# ── assemble ──────────────────────────────────────────────────────────────


def assemble(core: CostCore, solution: MutualSolution) -> CostResult:
    """Merge coupled columns from the mutual solution into the cost frame.

    solution: MutualSolution with fields:
      - short_term_loan_interest: tuple[float, ...]  (25 values)
      - interest_expense: tuple[float, ...]          (25 values)
      - total_operating_cost: tuple[float, ...]      (25 values)
    """

    st_interest = tuple(float(v) for v in solution.short_term_loan_interest)  # type: ignore[attr-defined]
    int_expense = tuple(float(v) for v in solution.interest_expense)  # type: ignore[attr-defined]
    total_op_cost = tuple(float(v) for v in solution.total_operating_cost)  # type: ignore[attr-defined]

    frame = core.frame.with_columns(
        pl.Series("short_term_loan_interest", list(st_interest), dtype=pl.Float64),
        pl.Series("interest_expense", list(int_expense), dtype=pl.Float64),
        pl.Series("total_operating_cost", list(total_op_cost), dtype=pl.Float64),
    )

    return CostResult(
        years=core.years,
        frame=frame,
        scalars=core.scalars,
    )


# ── SCHEMA ────────────────────────────────────────────────────────────────

SCHEMA = DomainSchema(
    key="cost",
    sheet="成本",
    label="总成本费用估算表 (Cost)",
    depends_on=("params", "invest", "debt", "pnl", "mutual"),
    items=(
        ItemSchema(
            key="year_labels",
            label="运营年度",
            unit="-",
            formula="year numbers 1..25 for operating years",
            inputs=("params:years",),
            rows=(4,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="depreciation_year_labels",
            label="折旧区年份",
            unit="-",
            formula="year numbers 1..25 for the depreciation section",
            inputs=("params:years",),
            rows=(26,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="deferred_vat_year_labels",
            label="递延资产区年份",
            unit="-",
            formula="first two years both 1, then 2..24 (shifted section)",
            inputs=("params:years",),
            rows=(48,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="depreciation_echo",
            label="折旧费",
            unit="万元",
            formula="depreciation echoed to top section (row 6 = row 30 per year)",
            inputs=("depreciation",),
            rows=(6,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="repair_cost",
            label="修理费",
            unit="万元",
            formula="fixed_asset_original × repair_rate per year",
            inputs=("fixed_asset_original", "params:repair_rate"),
            rows=(7,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="salary_cost",
            label="工资及福利等",
            unit="万元",
            formula="staff_count × avg_salary × (1 + welfare_rate), constant per year",
            inputs=(
                "params:staff_count",
                "params:avg_salary",
                "params:welfare_rate",
            ),
            rows=(8,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="insurance_cost",
            label="保险费",
            unit="万元",
            formula="fixed_asset_net_value × insurance_rate per year",
            inputs=("fixed_asset_net_value", "params:insurance_rate"),
            rows=(9,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="material_cost",
            label="材料费",
            unit="万元",
            formula="material_cost_rate × installed_capacity_mw, constant per year",
            inputs=("params:material_cost_rate", "params:installed_capacity_mw"),
            rows=(10,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="land_tax_cost",
            label="城镇土地使用税",
            unit="万元",
            formula="land_use_tax per year (constant)",
            inputs=("params:land_use_tax",),
            rows=(11,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="land_rent_echo",
            label="长期待摊费用（摊销回显）",
            unit="万元",
            formula=(
                "land_rent_amortization echoed to top section "
                "(same year; old Excel column offset E12=F56 is a layout artifact)"
            ),
            inputs=("land_rent_amortization",),
            rows=(12,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="interest_expense",
            label="利息支出",
            unit="万元",
            formula=(
                "long_term_loan_interest + working_capital_loan_interest "
                "+ short_term_loan_interest"
            ),
            inputs=(
                "long_term_loan_interest",
                "working_capital_loan_interest",
                "short_term_loan_interest",
            ),
            rows=(13,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="long_term_loan_interest",
            label="长期贷款利息",
            unit="万元",
            formula="debt:long_term_interest_total per year",
            inputs=("debt:long_term_interest_total",),
            rows=(14,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="working_capital_loan_interest",
            label="流动资金贷款利息",
            unit="万元",
            formula="debt:working_capital_interest per year",
            inputs=("debt:working_capital_interest",),
            rows=(15,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="short_term_loan_interest",
            label="短期借款利息",
            unit="万元",
            formula="debt:short_term_interest per year (mutual-block coupled)",
            inputs=("debt:short_term_interest",),
            rows=(16,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="surplus_interest",
            label="盈余资金利息收入",
            unit="万元",
            formula="0 (all years)",
            inputs=(),
            rows=(17,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="other_cost",
            label="其他费用",
            unit="万元",
            formula="other_cost_rate × installed_capacity_mw, constant per year",
            inputs=("params:other_cost_rate", "params:installed_capacity_mw"),
            rows=(18,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="total_operating_cost",
            label="总成本费用",
            unit="万元",
            formula=(
                "depreciation_echo + repair_cost + salary_cost + insurance_cost "
                "+ material_cost + land_tax_cost + land_rent_echo "
                "+ interest_expense + other_cost"
            ),
            inputs=(
                "depreciation_echo",
                "repair_cost",
                "salary_cost",
                "insurance_cost",
                "material_cost",
                "land_tax_cost",
                "land_rent_echo",
                "interest_expense",
                "other_cost",
            ),
            rows=(21,),
            kind="series",
            coupled=True,
        ),
        ItemSchema(
            key="operating_cost",
            label="经营成本",
            unit="万元",
            formula=(
                "repair_cost + salary_cost + insurance_cost + material_cost "
                "+ land_tax_cost + other_cost"
            ),
            inputs=(
                "repair_cost",
                "salary_cost",
                "insurance_cost",
                "material_cost",
                "land_tax_cost",
                "other_cost",
            ),
            rows=(22,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="deductible_vat",
            label="待抵扣固定资产进项税额",
            unit="万元",
            formula="params:deductible_vat_construction (D28 only)",
            inputs=("params:deductible_vat_construction",),
            rows=(28,),
            kind="scalar",
            coupled=False,
        ),
        ItemSchema(
            key="fixed_asset_original",
            label="固定资产原值",
            unit="万元",
            formula=(
                "invest:dynamic_investment − deductible_vat − land_rent_initial"
            ),
            inputs=(
                "deductible_vat",
                "land_rent_initial",
            ),
            rows=(29,),
            kind="scalar",
            coupled=False,
        ),
        ItemSchema(
            key="depreciation",
            label="当期折旧费",
            unit="万元",
            formula=(
                "fixed_asset_original × (1 − salvage_rate) / depreciation_years "
                "× load_rate; 20-year cutoff (years 21-25 = 0)"
            ),
            inputs=(
                "fixed_asset_original",
                "params:salvage_rate",
                "params:depreciation_years",
            ),
            rows=(30,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="fixed_asset_net_value",
            label="固定资产净值",
            unit="万元",
            formula="prior net value − depreciation (carry chain from D29)",
            inputs=("fixed_asset_original", "depreciation"),
            rows=(31,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="deferred_original",
            label="递延资产原值",
            unit="万元",
            formula="deductible_vat echoed (D50 = D28)",
            inputs=("deductible_vat",),
            rows=(50,),
            kind="scalar",
            coupled=False,
        ),
        ItemSchema(
            key="deferred_vat_amortization",
            label="递延资产摊销(进项税额)",
            unit="万元",
            formula=(
                "year 1: pnl.sales_revenue × vat_rate; "
                "year t: min(prior_net, pnl.sales_revenue × vat_rate)"
            ),
            inputs=("deferred_original", "pnl:sales_revenue", "params:vat_rate"),
            rows=(51,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="deferred_vat_net",
            label="递延资产净值(进项税额)",
            unit="万元",
            formula="prior net − amortization per year (carry chain from D50)",
            inputs=("deferred_vat_amortization",),
            rows=(52,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="land_rent_original",
            label="长期待摊费用原值",
            unit="万元",
            formula="params:land_rent_payment per operating year",
            inputs=("params:land_rent_payment",),
            rows=(55,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="land_rent_amortization",
            label="长期待摊费用摊销",
            unit="万元",
            formula="params:land_rent_amortization per operating year",
            inputs=("params:land_rent_amortization",),
            rows=(56,),
            kind="series",
            coupled=False,
        ),
        ItemSchema(
            key="land_rent_net",
            label="长期待摊费用净值",
            unit="万元",
            formula=(
                "prior net + original − amortization per year "
                "(carry chain; initial prior = construction-year land_rent_payment)"
            ),
            inputs=("land_rent_original", "land_rent_amortization"),
            rows=(57,),
            kind="series",
            coupled=False,
        ),
    ),
)
