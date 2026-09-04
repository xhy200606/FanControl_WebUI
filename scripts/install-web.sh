#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-install.sh
source "$SCRIPT_DIR/lib-install.sh"
need_root
install_base_packages

if command -v systemd-detect-virt >/dev/null 2>&1 && [[ "$(systemd-detect-virt 2>/dev/null || true)" == "lxc" ]]; then
  if [[ ! -e /dev/fuse ]] && ! grep -qE '(^|,)nesting(=1)?(,|$)' /proc/1/environ 2>/dev/null; then
    echo "提示：Docker 位于 LXC 中时，建议在 PVE 为该 CT 启用 nesting=1,keyctl=1。"
  fi
fi
ensure_docker

ENV_FILE=/etc/pve-fan-control/web.env
mkdir -p /etc/pve-fan-control
OLD_AGENT_URL=""; OLD_AGENT_TOKEN=""; OLD_WEB_TOKEN=""; OLD_PORT=""
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  OLD_AGENT_URL="${PVE_FAN_AGENT_URL:-}"; OLD_AGENT_TOKEN="${PVE_FAN_AGENT_TOKEN:-}"; OLD_WEB_TOKEN="${PVE_FAN_WEB_TOKEN:-}"; OLD_PORT="${PVE_FAN_WEB_PORT:-}"
fi

AGENT_URL="${PVE_FAN_AGENT_URL:-${OLD_AGENT_URL}}"
AGENT_TOKEN="${PVE_FAN_AGENT_TOKEN:-${OLD_AGENT_TOKEN}}"
WEB_TOKEN="${PVE_FAN_WEB_TOKEN:-${OLD_WEB_TOKEN:-$(random_token)}}"
WEB_PORT="${PVE_FAN_WEB_PORT:-${OLD_PORT:-9487}}"

if [[ -z "$AGENT_URL" ]]; then
  read -r -p "请输入 Agent 地址（例如 http://192.168.1.10:9488）: " AGENT_URL
fi
if [[ -z "$AGENT_TOKEN" ]]; then
  read -r -s -p "请输入 Agent Token: " AGENT_TOKEN; echo
fi
AGENT_URL="${AGENT_URL%/}"
if [[ ! "$AGENT_URL" =~ ^https?:// ]]; then
  echo "错误：Agent 地址必须以 http:// 或 https:// 开头。" >&2; exit 1
fi

cat > "$ENV_FILE" <<ENV
PVE_FAN_WEB_TOKEN=${WEB_TOKEN}
PVE_FAN_WEB_PORT=${WEB_PORT}
PVE_FAN_AGENT_URL=${AGENT_URL}
PVE_FAN_AGENT_TOKEN=${AGENT_TOKEN}
PVE_FAN_HISTORY_INTERVAL=5
PVE_FAN_HISTORY_RETENTION_HOURS=48
ENV
chmod 600 "$ENV_FILE"
compose_up "$INSTALL_DIR/deploy/web" "$ENV_FILE"
IP="$(host_ipv4)"
cat <<OUT

PVE Fan Control Web UI 已安装。
访问地址: http://${IP:-LXC-IP}:${WEB_PORT}
Web UI Token: ${WEB_TOKEN}
Agent: ${AGENT_URL}
OUT
