# expose-investment-inputs — spec

## Background

总投资 in the source workbook is **not a function of 装机容量**: 建设投资
components (`参数表!C16` 建安, `C17` 设备, `C18` 其他, `C22` 预备费) are absolute
万元 literals; only 土地租金 (`C68`, via 占地面积 `C61=C2×…`) and 流动资金
(`C29=C2×30`) scale with capacity. v2 and the dag faithfully reproduce this, so
raising `installed_capacity_mw` in the serving app leaves 总投资 nearly unchanged
while revenue scales — IRR explodes (15→30→60 万kW: equity IRR 9.6%→57.1%→152.6%,
总投资 +1.3%/+4.0%). See JOURNAL 2026-09-27 · capacity-vs-investment-diagnosis.

Decision (user, 2026-09-27): expose the 总投资 calculation cells as explicit
inputs — **multiple component cells, not one 总投资 cell** — because the engine
consumes the components separately (per-component VAT rates → 进项税抵扣, EPC
单价, 建设期利息 on 建设投资 only, 折旧基数). No auto-scaling of costs with
capacity; the tripwire is a read-only 单位千瓦投资 display next to capacity.

## Scope

1. **v2 (`packages/solar-v2`)**: lift the hardcoded `30` (流动资金标准, 元/kW,
   inline in workbook formula `参数表!C29=C2*30`) out of
   `domains/params.py:from_inputs` (`working_capital_total = cap * 30`) into a
   new `ModelInputs` field `working_capital_per_kw: float = 30.0`. All other
   investment cells already exist as ModelInputs fields.
2. **Serving (`apps/server`)**: expose the investment input cells in the UI form
   and add a read-only derived display (静态投资 / 建设期利息 / 流动资金 /
   总投资 / 单位千瓦投资) that refreshes after each compute.
3. **CLI (`apps/cli`)**: `config.example.toml` documents the new input.

## Contract

- New field: `working_capital_per_kw: float = 30.0`, unit 元/kW,
  description 铺底流动资金标准（流动资金总额 = 装机容量 × 标准）.
- UI input names = ModelInputs field names (form posts straight to
  `/api/domains/compute` inputs): `construction_cost`, `equipment_cost`,
  `other_cost_base`, `farmland_occupation_tax`, `contingency`, `land_per_mw`,
  `land_rent_per_mu`, `working_capital_per_kw`.
- Derived display bindings (computed result items):
  `params:static_investment`, `params:unit_static_investment`,
  `params:working_capital_total`, `invest:construction_interest` (sum),
  `invest:total_investment` (sum).

## Acceptance

- Defaults unchanged ⇒ golden diff stays empty:
  `uv run pytest packages/solar-v2` (incl. test_golden_benchmark) green and
  `solar-cli verify --skip-engine` (path 1.2, v2 vs v1) clean.
- `working_capital_per_kw` override observable: rate 35 → 流动资金 = 15×35 = 525.
- UI shows the 8 investment inputs and the derived strip; manual browser check.
- Gates: `uv run ty check`, `uv run ruff check`, `uv run pytest` clean.
