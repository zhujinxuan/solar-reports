# deploy.md — solar-server on an Aliyun VPS (yum-based)

## Roles — who does what

| Role | Account | Owns |
|---|---|---|
| **appuser** | `appuser` | checkout `/home/appuser/solar-price-servec`, `.venv`, `env`, starting/stopping the service with `uv run` |
| **admin** | root/admin | Caddy (`/etc/caddy/Caddyfile`), Aliyun security group, firewalld |

**Nothing in this repo needs sudo.** Every app-side command runs as `appuser`;
admin-side config lives outside the repo — this file documents it, it does not
script it. Caddy talks to the app only over `127.0.0.1:14905`, so neither side
touches the other's files.

## Architecture

```
browser ── https://<vps-ip>:13005/solar-server/… ──▶ Caddy (admin-owned edge)
                                                        │ handle /solar-server*
                                                        │ (paths as-is)
                                                        ▼
                       uv run uvicorn 127.0.0.1:14905  (runs as appuser)
                       FastAPI mounted under /solar-server
```

## 1. First-time install (appuser — no sudo)

```bash
git clone <repo-url> ~/solar-price-servec
cd ~/solar-price-servec
uv sync --frozen --no-dev     # uv is already installed; brings its own Python 3.13
bash deploy/run.sh            # first run creates ./env from the template and exits
```

Uncomment this one line in `./env`:

```ini
SOLAR_URL_PREFIX=/solar-server
```

Then start for real:

```bash
bash deploy/run.sh                                   # foreground (Ctrl+C stops)
# or background:
nohup bash deploy/run.sh > server.log 2>&1 &
```

Verify: `curl http://127.0.0.1:14905/solar-server/health`
Stop (background mode): `pkill -f 'uvicorn solar_server.main:app'`

## 2. Configuration — `./env` (sourced by deploy/run.sh)

| Key | Default | Meaning |
|---|---|---|
| `SOLAR_HOST` | `127.0.0.1` | `0.0.0.0` exposes uvicorn directly (skip the proxy) |
| `SOLAR_PORT` | `14905` | uvicorn port (internal while behind Caddy) |
| `SOLAR_URL_PREFIX` | *(unset)* | path prefix the app mounts under, e.g. `/solar-server` |
| `XLSX_*` | see template | **all optional** for frontend-only use — the UI only hits
  zero-file-I/O v2 endpoints; dag/workbook/engine keys matter only for
  `/compute/v1`, `flat` and `/verify` |

## 3. Edge (admin) — Caddy path routing on 13005

One public port, many services, routed by first path segment. solar-server is
mounted under its prefix, so paths pass through unchanged (`handle`, **not**
`handle_path` — the latter strips the prefix; root-assuming services want
that one instead). The catch-all closes every other path.

`/etc/caddy/Caddyfile` (admin-owned):

```
https://<VPS_IP>:13005 {
    tls internal

    handle /solar-server* {
        reverse_proxy 127.0.0.1:14905
    }

    # other services, one block each:
    # handle /other-service* {
    #     reverse_proxy 127.0.0.1:OTHER_PORT
    # }

    handle {
        abort
    }
}
```

Then `systemctl reload caddy` (admin). Each service stays bound to
`127.0.0.1` on its own internal port; only 13005 is public.

### Aliyun access rules (admin console)

1. **Security group**: ECS → instance → Security Groups → Inbound → add
   TCP `13005`, source `0.0.0.0/0`. No 80/443 needed (`tls internal` has no
   ACME challenge).
2. **OS firewall** (only if `systemctl is-active firewalld`):
   `firewall-cmd --permanent --add-port=13005/tcp && firewall-cmd --reload`.

## 4. HTTPS with an IP-only VPS — the honest picture

**Let's Encrypt does not issue certificates for bare IP addresses.** With no
domain there is no free *trusted* certificate.

### 4a. Caddy self-signed (`tls internal`) — the choice here

Already in the Caddyfile above. The browser shows a one-time warning
("Advanced → Proceed"). To get a green lock on your own Windows machine,
trust Caddy's local root CA once:

```powershell
ssh user@<VPS_IP> "sudo cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt" > caddy-root.crt
```

Double-click `caddy-root.crt` → Install Certificate → **Local Machine** →
"Place all certificates in the following store" → **Trusted Root
Certification Authorities**. Caddy's internal cert carries the IP as SAN, so
`https://<VPS_IP>:13005/solar-server/` then shows fully trusted.

### 4b. Add a domain later

Point an A record at the VPS IP, change the site address to the domain, drop
`tls internal` — Caddy obtains Let's Encrypt certs automatically.
**Mainland-China reality:** this ECS region requires ICP filing (备案) before
any domain can serve 80/443 — a real-name-registered domain plus filing
through the Aliyun ICP portal, typically 1–3 weeks; Aliyun intercepts
unfiled sites on 80/443. A bare IP on a non-standard port (13005) is the
practical route until then.

### 4c. Paid IP certificate

Commercial CAs (ZeroSSL, SSL.com, GoGetSSL…) sell certificates for public
IPs — the only *trusted* option for a bare IP; rarely worth it for a
personal tool.

## 5. Updates (appuser — no sudo)

```bash
cd ~/solar-price-servec
git pull
uv sync --frozen --no-dev
pkill -f 'uvicorn solar_server.main:app' || true
nohup bash deploy/run.sh > server.log 2>&1 &
```

## 6. Optional: survive reboots (systemd user unit)

Everything below is appuser-side **except one** lingering command only an
admin can type once (`loginctl enable-linger appuser`) — without it the user
service dies at logout. If you'd rather skip that, use the `nohup` flow and
re-start after reboots.

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/solar-server.service <<'EOF'
[Unit]
Description=solar-server (uv run)
After=network-online.target

[Service]
WorkingDirectory=/home/appuser/solar-price-servec
ExecStart=/usr/bin/env bash deploy/run.sh
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now solar-server
```

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| Browser timeout, curl on VPS works | Aliyun security group rule for 13005; firewalld |
| 502 from Caddy | is the app up? `curl 127.0.0.1:14905/solar-server/health`; `server.log` |
| `uv: command not found` (cron/new shell) | uv lives in `~/.local/bin` — check `PATH` |
| App 404s under the prefix | `SOLAR_URL_PREFIX=/solar-server` uncommented in `./env`? process restarted after? |
| Caddy won't start | `journalctl -u caddy -n 50`; `caddy validate --config /etc/caddy/Caddyfile` (admin) |
