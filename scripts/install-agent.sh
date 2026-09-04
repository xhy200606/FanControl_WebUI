#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-install.sh
source "$SCRIPT_DIR/lib-install.sh"
need_root
install_base_packages
ensure_docker

export DEBIAN_FRONTEND=noninteractive
apt-get install -y --no-install-recommends lm-sensors fancontrol python3 util-linux ipmitool
mkdir -p /etc/pve-fan-control /usr/local/lib/pve-fan-control
install -m 0755 "$INSTALL_DIR/scripts/host-temp-source.py" /usr/local/lib/pve-fan-control/temp_source.py

ENV_FILE=/etc/pve-fan-control/agent.env
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi
PVE_FAN_AGENT_TOKEN="${PVE_FAN_AGENT_TOKEN:-$(random_token)}"
cat > "$ENV_FILE" <<ENV
PVE_FAN_AGENT_TOKEN=${PVE_FAN_AGENT_TOKEN}
ENV
chmod 600 "$ENV_FILE"

compose_up "$INSTALL_DIR/deploy/agent" "$ENV_FILE"
IP="$(host_ipv4)"
cat <<OUT

PVE Fan Control Agent 已安装。
Agent 地址: http://${IP:-PVE-IP}:9488
Agent Token: ${PVE_FAN_AGENT_TOKEN}

下一步：在 LXC 中安装 Web UI，并填写上面的 Agent 地址与 Token。
如果 /etc/fancontrol 尚不存在，请先在 PVE 宿主机执行：
  sensors-detect
  pwmconfig
  systemctl enable --now fancontrol
OUT
