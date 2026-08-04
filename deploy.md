# deploy.md — solar-server on a yum-based Aliyun VPS

## Architecture

```
browser ── http(s)://<vps-ip>:13005/solar-server/… ──▶ Caddy (public edge)
                                                          │ reverse_proxy, paths as-is
                                                          ▼
                                    uvicorn 127.0.0.1:14905 (systemd: solar-server)
                                    FastAPI mounted under /solar-server
                                    (static UI + /api/* + /health + /compute + /verify)
```

- **Public port** (13005) belongs to Caddy; **internal port** (14905, default)
  belongs to uvicorn and is configurable.
- The **path prefix is owned by the app** (`SOLAR_URL_PREFIX`), so the proxy
  forwards paths unchanged — no rewriting, and the same app also works when
  exposed directly without a proxy.

## 1. First-time install

```bash
sudo dnf install -y git curl
sudo git clone <repo-url> /opt/solar-server
cd /opt/solar-server
sudo bash deploy/update.sh
```

`update.sh` installs uv (which installs Python 3.13 — yum repos don't ship it),
builds deps from `uv.lock`, creates the `solar` service user, installs +
enables the systemd unit, and smoke-tests `/health`.

## 2. Configuration — `/opt/solar-server/env`

Created once from `deploy/env.template`; `update.sh` never overwrites it.
The systemd unit ships defaults (`Environment=`), the env file overrides them.

| Key | Default | Meaning |
|---|---|---|
| `SOLAR_HOST` | `127.0.0.1` | `0.0.0.0` exposes uvicorn directly (skip the proxy) |
| `SOLAR_PORT` | `14905` | uvicorn listen port (internal when behind a proxy) |
| `SOLAR_URL_PREFIX` | *(unset)* | path prefix the app mounts under, e.g. `/solar-server` |
| `XLSX_*` | see template | **all optional** for frontend-only use (the UI only hits
  zero-file-I/O v2 endpoints); only `/compute/v1`, `flat` and `/verify` need dag/workbook/engine keys |

For this deployment the env file needs exactly one uncommented line:

```ini
SOLAR_URL_PREFIX=/solar-server
```

## 3. Public access via Caddy (ip:13005/solar-server)

```bash
sudo dnf copr enable @caddy/caddy
sudo dnf install -y caddy
sudo tee /etc/caddy/Caddyfile <<'EOF'
https://<VPS_IP>:13005 {
    tls internal

    # solar-server owns its /solar-server prefix — pass paths as-is
    handle /solar-server* {
        reverse_proxy 127.0.0.1:14905
    }

    # add other services the same way, one block each:
    # handle /other-service* {
    #     reverse_proxy 127.0.0.1:OTHER_PORT
    # }

    handle {
        abort
    }
}
EOF
sudo systemctl enable --now caddy
```

Then open `https://<VPS_IP>:13005/solar-server/` (one-time browser warning —
see §4a to trust the cert permanently). One public port, many services,
routed by first path segment. Use `handle`, **not** `handle_path`: the latter
strips the prefix, but solar-server is mounted under it and needs the full
path (services that assume root instead would want `handle_path`). The final
catch-all `handle { abort }` closes every other path; each service stays
bound to 127.0.0.1 on its own internal port.

### Aliyun access rules

1. **Security group** (this is the one people forget): Aliyun console → ECS →
   instance → Security Groups → Inbound → add rule: TCP, port `13005`,
   source `0.0.0.0/0`.
2. **OS firewall** (only if firewalld is enabled — check
   `systemctl is-active firewalld`):
   ```bash
   sudo firewall-cmd --permanent --add-port=13005/tcp && sudo firewall-cmd --reload
   ```

## 4. HTTPS with an IP-only VPS — the honest picture

**Let's Encrypt does not issue certificates for bare IP addresses.** With no
domain there is no free *trusted* certificate. Realistic options:

### 4a. Caddy self-signed (`tls internal`) — recommended for personal use

```
https://<VPS_IP>:13005 {
    tls internal
    reverse_proxy 127.0.0.1:14905
}
```

Caddy generates and auto-renews its own CA. The browser shows a one-time
warning ("Advanced → Proceed"). To remove the warning on your own devices,
install Caddy's local root CA once:

```powershell
# on your Windows machine:
ssh user@<VPS_IP> "sudo cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt" > caddy-root.crt
```

Double-click `caddy-root.crt` → Install Certificate → **Local Machine** →
"Place all certificates in the following store" → **Trusted Root
Certification Authorities**. After that `https://<VPS_IP>:13005/solar-server/`
shows a green lock (Caddy's internal cert carries the IP as SAN).
Note: `tls internal` needs no port 80 at all — there is no ACME challenge.

### 4b. Add a domain later

Point an A record at the VPS IP and change the site address to the domain —
Caddy obtains Let's Encrypt certs automatically. **Mainland-China reality:**
this ECS region requires ICP filing (备案) before any domain can serve
80/443 — a real-name-registered domain plus filing through the Aliyun ICP
portal, typically 1–3 weeks; Aliyun intercepts unfiled sites on 80/443.
A bare IP on a non-standard port (like 13005) is the practical route until
you choose to file, and this setup needs no change when you do: add the
domain site block, swap `tls internal` for automatic LE.

### 4c. Paid IP certificate

Commercial CAs (ZeroSSL, SSL.com, GoGetSSL…) sell certificates for public IPs.
This is the only way to get a *trusted* cert for a bare IP; rarely worth it
for a personal tool.

## 5. Without Caddy (direct exposure, HTTP only)

`/opt/solar-server/env`:

```ini
SOLAR_HOST=0.0.0.0
SOLAR_PORT=13005
SOLAR_URL_PREFIX=/solar-server
```

`sudo systemctl restart solar-server`, open the same security-group port, and
browse `http://<VPS_IP>:13005/solar-server/`. One fewer daemon; no TLS.

## 6. Updates

```bash
cd /opt/solar-server && sudo git pull && sudo bash deploy/update.sh
```

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| Browser timeout, curl on VPS works | Aliyun security group rule for 13005; firewalld |
| 502 from Caddy | `systemctl status solar-server`; is `SOLAR_PORT` == the proxy target? |
| Service crash loop | `journalctl -u solar-server -n 50` |
| Caddy won't start | `journalctl -u caddy -n 50`; Caddyfile syntax (`sudo caddy validate --config /etc/caddy/Caddyfile`) |
| nginx instead of Caddy | `sudo setsebool -P httpd_can_network_connect 1` (SELinux) |
