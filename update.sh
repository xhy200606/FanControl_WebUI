#!/usr/bin/env bash
set -euo pipefail
ROLE="${1:-}"
REPO_URL="${PVE_FAN_REPO_URL:-https://github.com/xhy200606/FanControl_WebUI.git}"
INSTALL_DIR="${PVE_FAN_INSTALL_DIR:-/opt/pve-fan-control}"
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then echo "错误：请使用 root 或 sudo 执行。" >&2; exit 1; fi
if [[ "$ROLE" != "agent" && "$ROLE" != "web" ]]; then
  if [[ -f /etc/pve-fan-control/agent.env && ! -f /etc/pve-fan-control/web.env ]]; then ROLE=agent;
  elif [[ -f /etc/pve-fan-control/web.env && ! -f /etc/pve-fan-control/agent.env ]]; then ROLE=web;
  else echo "用法: sudo ./update.sh agent|web"; exit 2; fi
fi
apt-get update; apt-get install -y --no-install-recommends git ca-certificates
if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  rm -rf "$INSTALL_DIR"; git clone "$REPO_URL" "$INSTALL_DIR"
else
  git -C "$INSTALL_DIR" fetch --tags origin
  git -C "$INSTALL_DIR" reset --hard origin/main
fi
exec bash "$INSTALL_DIR/scripts/update-${ROLE}.sh"
