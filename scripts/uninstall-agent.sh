#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib-install.sh"
need_root; ensure_docker
ENV_FILE=/etc/pve-fan-control/agent.env
[[ -f "$ENV_FILE" ]] && compose_down "$INSTALL_DIR/deploy/agent" "$ENV_FILE"
# Keep the host temperature adapter because /etc/fancontrol may still reference
# generated !command wrappers after the Agent container is removed.
echo "Agent 容器已卸载。温度适配器、/etc/pve-fan-control 配置与备份已保留，以保证现有 fancontrol !command 继续可用。"
