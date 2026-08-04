#!/usr/bin/env bash
# Deploy or update solar-server on a yum-based Linux VPS (Rocky/Alma/CentOS Stream).
#
# First-time setup:
#   sudo dnf install -y git
#   sudo git clone <repo-url> /opt/solar-server
#   cd /opt/solar-server
#   sudo bash deploy/update.sh
#
# Updates:
#   cd /opt/solar-server && sudo git pull && sudo bash deploy/update.sh
#
# Optional, for /verify engine path 1.1:
#   sudo dnf install -y libreoffice-calc
#
# Public access: reverse-proxy 127.0.0.1:8000 with Caddy (dnf copr enable
# @caddy/caddy && dnf install caddy) or nginx (EPEL; then also
# sudo setsebool -P httpd_can_network_connect 1 for SELinux).

set -euo pipefail

APP_DIR="/opt/solar-server"
SERVICE_USER="solar"
DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"

[[ -f "$APP_DIR/pyproject.toml" ]] || {
    echo "Expected the repo checkout at $APP_DIR" >&2
    exit 1
}

# 1. uv — installs its own Python 3.13; yum repos don't ship it.
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
fi

# 2. Service user.
id "$SERVICE_USER" &>/dev/null || useradd -r -m -s /sbin/nologin "$SERVICE_USER"

# 3. Dependencies from uv.lock. Never reuse a Windows .venv — its wheels
#    are platform-specific; this rebuilds for Linux.
cd "$APP_DIR"
uv sync --frozen --no-dev

# 4. Env file — created once from the template, never overwritten.
if [[ ! -f "$APP_DIR/env" ]]; then
    cp "$DEPLOY_DIR/env.template" "$APP_DIR/env"
    echo "Created $APP_DIR/env from template — review it (esp. the recalc engine)."
fi

# 5. Ownership before the service starts.
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

# 6. systemd unit.
install -m 0644 "$DEPLOY_DIR/solar-server.service" /etc/systemd/system/solar-server.service
systemctl daemon-reload
systemctl enable solar-server
systemctl restart solar-server

# 7. Smoke test.
for _ in $(seq 1 15); do
    if curl -fsS http://127.0.0.1:8000/health; then
        echo
        echo "Deployed. Service: systemctl status solar-server / journalctl -u solar-server -f"
        exit 0
    fi
    sleep 1
done
echo "Service did not answer on :8000 — check: journalctl -u solar-server -n 50" >&2
exit 1
