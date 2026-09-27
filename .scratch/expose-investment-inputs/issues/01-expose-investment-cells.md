# 01 · Expose 总投资 component cells as inputs (v2 + serving)

Status: resolved
Type: task

## Target

- `packages/solar-v2/src/solar_v2/inputs.py` — new `working_capital_per_kw` field
- `packages/solar-v2/src/solar_v2/domains/params.py` — `from_inputs` uses the field
- `packages/solar-v2/DOMAIN.md` — givens list updated
- `apps/server/static/index.html`, `apps/server/static/app.js` — investment input
  fieldset + read-only derived strip
- `apps/server/tests/test_domains.py` — behavioral override test
- `apps/cli/config.example.toml` — document the new key

## Change

Per `.scratch/expose-investment-inputs/spec.md` (contract + acceptance).

## Comments

## Answer

Implemented 2026-09-27. `working_capital_per_kw=30.0` added to ModelInputs
(+ `_FLOAT_FIELDS`); `DerivedParams.from_inputs` and debt.py's frozen 450.0
working-capital-interest constant both migrated (clean cutover, no leftover
magic numbers). Serving UI: 投资参数 fieldset with 8 absolute-万元 inputs +
read-only derived strip （静态投资/建设期利息/流动资金/总投资/单位千瓦投资）
filled after each compute. CLI config.example.toml documents the key.

Verification: ruff + ty clean; pytest 152 passed; CLI golden
`solar-cli verify --skip-engine` path 1.2 CLEAN (5059/5059, 0 diffs);
override test rate 35 → 流动资金 525; browser e2e strip fill confirmed.
Journal: 2026-09-27 · expose-investment-inputs.
