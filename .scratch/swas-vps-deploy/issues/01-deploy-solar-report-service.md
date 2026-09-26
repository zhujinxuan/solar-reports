# Deploy solar-report service to Aliyun SWAS VPS (port 19111, prefix /solar-report)

Status: resolved
Type: task

## Problem

Serve the solar-server FastAPI app publicly as the current report at
`:19111/solar-report/` on the Aliyun SWAS (轻量应用服务器) VPS, running under
`uv` as the unprivileged `appuser` (per `deploy.md` roles — no sudo in repo
tooling).

## Answer

Deployed 2026-09-26.

Pre-deploy findings: nothing on 19111; old uvicorn served unprefixed on a
loopback-only port from an outdated checkout; the pre-existing Caddy edge
proxied to a dead backend (502) — unrelated to this path.

Steps: `git pull --ff-only` + `uv sync --frozen --no-dev`; rewrote `env`
(`SOLAR_HOST=0.0.0.0`, `SOLAR_PORT=19111`, `SOLAR_URL_PREFIX=/solar-report`,
`XLSX_DAG_PATH=<checkout>/dag/solar.dag.yaml`); restarted via
`setsid nohup bash deploy/run.sh > server.log 2>&1 &` (direct uvicorn exposure,
no proxy).

Verification: `/solar-report/health` → 200; UI and `/api/schema` → 200; POST
with `{installed_capacity_mw: 30, first_year_full_hours: 2000}` returns
`pnl:power_generation = 55575.0`, matching the local reference run.

Ops notes: public reachability requires a TCP 19111 rule in the SWAS console
firewall (OS firewall inactive). Remote exec for deploy/verify uses the
SWAS-OPEN `RunCommand` API (plaintext shell, Base64-encoded output).

## Comments

- 2026-09-26: Code at `156c1fa`. Editable-form update deployed via `git pull`
  (static-only, no restart needed).
