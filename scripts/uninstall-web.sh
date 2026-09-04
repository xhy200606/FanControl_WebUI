#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib-install.sh"
need_root; ensure_docker
ENV_FILE=/etc/pve-fan-control/web.env
[[ -f "$ENV_FILE" ]] && compose_down "$INSTALL_DIR/deploy/web" "$ENV_FILE"
echo "Web UI 已卸载。历史数据卷默认保留。"
