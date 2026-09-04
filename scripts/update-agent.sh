#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib-install.sh"
need_root; install_base_packages; ensure_docker
ENV_FILE=/etc/pve-fan-control/agent.env
[[ -f "$ENV_FILE" ]] || { echo "错误：Agent 尚未安装。" >&2; exit 1; }
install -m 0755 "$INSTALL_DIR/scripts/host-temp-source.py" /usr/local/lib/pve-fan-control/temp_source.py
compose_up "$INSTALL_DIR/deploy/agent" "$ENV_FILE"
echo "Agent 已更新到 $(cat "$INSTALL_DIR/VERSION")。"
