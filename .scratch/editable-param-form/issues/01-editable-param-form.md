# Editable model parameters wired to the v2 engine

Status: resolved
Type: task

## Problem

The parameter panel on the compute tab was read-only (`readonly` hardcoded on all
7 inputs, legend "当前模型参数（只读参考）"), and the frontend only posted
`{version: "v2"}` — user edits could never influence computation, even though the
backend v2 engine already accepted per-request `ModelInputs` overrides via
`POST /api/domains/compute {inputs}`.

## Answer

Frontend-only fix in commit `156c1fa`:

- `apps/server/static/index.html`: dropped `readonly` from all 7 inputs.
- 标杆上网电价 maps to the `ModelInputs` field **`base_tariff`** —
  `feed_in_tariff` is *derived* (`base_tariff + subsidy_per_kwh`), not an input.
- `apps/server/static/app.js`: `collectParamInputs()` gathers finite numeric
  field values into the POST body `{version, inputs}`; any form `input` event
  invalidates the memoized `computePromise`/`computed` cache.
- `apps/server/static/styles.css`: removed the dead `input[readonly]` rule.

Verification: capacity 15→30 MW and hours 1145→2000 scaled
`pnl:power_generation` 15908.34 → 55575.0, matching the physical ratio
(30·2000)/(15·1145) = 3.4930 to 4 dp. Gates: ty ✓, ruff ✓, pytest 165 passed.

## Comments

- 2026-09-26: Resolved and deployed to the SWAS VPS (see
  `.scratch/swas-vps-deploy/issues/01-deploy-solar-report-service.md`).
