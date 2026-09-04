#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${PVE_FAN_REPO_URL:-https://github.com/xhy200606/FanControl_WebUI.git}"
INSTALL_DIR="${PVE_FAN_INSTALL_DIR:-/opt/pve-fan-control}"

need_root() {
  if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    echo "错误：请使用 root 或 sudo 执行。" >&2
    exit 1
  fi
}

install_base_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl git openssl
}

ensure_docker() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    :
  else
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    if ! apt-get install -y docker.io; then
      echo "错误：无法从系统软件源安装 Docker。" >&2
      exit 1
    fi
    systemctl enable --now docker
  fi

  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y docker-compose-v2 2>/dev/null || \
      apt-get install -y docker-compose-plugin 2>/dev/null || \
      apt-get install -y docker-compose
    if docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose); else COMPOSE=(docker-compose); fi
  fi
}

sync_repo() {
  local source_root="${1:-}"
  mkdir -p "$(dirname "$INSTALL_DIR")"
  if [[ -n "$source_root" && -f "$source_root/VERSION" ]]; then
    if [[ "$(readlink -f "$source_root")" != "$(readlink -f "$INSTALL_DIR" 2>/dev/null || true)" ]]; then
      rm -rf "$INSTALL_DIR"
      mkdir -p "$INSTALL_DIR"
      cp -a "$source_root/." "$INSTALL_DIR/"
    fi
    return
  fi
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" fetch --tags origin
    git -C "$INSTALL_DIR" reset --hard origin/main
  else
    rm -rf "$INSTALL_DIR"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
  fi
}

compose_up() {
  local project_dir="$1" env_file="$2"
  (cd "$project_dir" && "${COMPOSE[@]}" --env-file "$env_file" build --pull && "${COMPOSE[@]}" --env-file "$env_file" up -d --remove-orphans)
}

compose_down() {
  local project_dir="$1" env_file="$2"
  if [[ -d "$project_dir" ]]; then
    (cd "$project_dir" && "${COMPOSE[@]}" --env-file "$env_file" down --remove-orphans) || true
  fi
}

random_token() { openssl rand -hex 32; }

host_ipv4() {
  hostname -I 2>/dev/null | awk '{print $1}'
}
