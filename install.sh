#!/usr/bin/env bash
set -euo pipefail
ROLE="${1:-}"
REPO_URL="${PVE_FAN_REPO_URL:-https://github.com/xhy200606/FanControl_WebUI.git}"
INSTALL_DIR="${PVE_FAN_INSTALL_DIR:-/opt/pve-fan-control}"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then echo "错误：请使用 root 或 sudo 执行。" >&2; exit 1; fi
if [[ "$ROLE" != "agent" && "$ROLE" != "web" ]]; then
  echo "用法: sudo ./install.sh agent   # PVE 宿主机"
  echo "      sudo ./install.sh web     # LXC 容器"
  exit 2
fi

# curl | bash / bash -s 模式下 BASH_SOURCE[0] 可能不存在。
# 只有脚本作为真实文件执行时，才尝试从当前源码目录安装。
SOURCE_ROOT=""
ENTRY_SOURCE="${BASH_SOURCE[0]-}"
if [[ -n "$ENTRY_SOURCE" && -f "$ENTRY_SOURCE" ]]; then
  HERE="$(cd "$(dirname "$ENTRY_SOURCE")" 2>/dev/null && pwd || true)"
  if [[ -n "$HERE" && -f "$HERE/VERSION" && -d "$HERE/scripts" ]]; then
    SOURCE_ROOT="$HERE"
  fi
fi

apt-get update
apt-get install -y --no-install-recommends git ca-certificates
mkdir -p "$(dirname "$INSTALL_DIR")"
if [[ -n "$SOURCE_ROOT" ]]; then
  if [[ "$(readlink -f "$SOURCE_ROOT")" != "$(readlink -f "$INSTALL_DIR" 2>/dev/null || true)" ]]; then
    rm -rf "$INSTALL_DIR"; mkdir -p "$INSTALL_DIR"; cp -a "$SOURCE_ROOT/." "$INSTALL_DIR/"
  fi
elif [[ -d "$INSTALL_DIR/.git" ]]; then
  git -C "$INSTALL_DIR" fetch --tags origin
  git -C "$INSTALL_DIR" reset --hard origin/main
else
  rm -rf "$INSTALL_DIR"
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

# curl | bash 会占用 stdin；Web 安装需要交互输入 Agent URL/Token。
# 有控制终端时把子安装器 stdin 恢复到 /dev/tty。
if [[ -r /dev/tty ]]; then
  exec bash "$INSTALL_DIR/scripts/install-${ROLE}.sh" </dev/tty
else
  exec bash "$INSTALL_DIR/scripts/install-${ROLE}.sh"
fi
