#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib-install.sh"
need_root; install_base_packages; ensure_docker
ENV_FILE=/etc/pve-fan-control/web.env
[[ -f "$ENV_FILE" ]] || { echo "错误：Web UI 尚未安装。" >&2; exit 1; }
compose_up "$INSTALL_DIR/deploy/web" "$ENV_FILE"
echo "Web UI 已更新到 $(cat "$INSTALL_DIR/VERSION")。"
