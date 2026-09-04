#!/usr/bin/env bash
set -euo pipefail
OWNER="${PVE_FAN_GITHUB_OWNER:-xhy200606}"
REPO="${PVE_FAN_GITHUB_REPO:-FanControl_WebUI}"
VISIBILITY="${1:-public}"
[[ "$VISIBILITY" == "public" || "$VISIBILITY" == "private" ]] || { echo "用法: ./scripts/publish-github.sh [public|private]"; exit 2; }
command -v gh >/dev/null 2>&1 || { echo "错误：需要 GitHub CLI (gh)。" >&2; exit 1; }
gh auth status >/dev/null
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -d .git ]]; then
  git init -b main
  git config user.name "${GIT_AUTHOR_NAME:-PVE Fan Control}"
  git config user.email "${GIT_AUTHOR_EMAIL:-pve-fan-control@users.noreply.github.com}"
  git add .
  git commit -m "feat: release PVE Fan Control v$(cat VERSION)"
  git tag -a "v$(cat VERSION)" -m "PVE Fan Control v$(cat VERSION)"
fi
TARGET="${OWNER}/${REPO}"
if gh repo view "$TARGET" >/dev/null 2>&1; then
  git remote remove origin 2>/dev/null || true
  git remote add origin "https://github.com/${TARGET}.git"
  git push -u origin main
  git push origin --tags
else
  gh repo create "$TARGET" "--${VISIBILITY}" --source=. --remote=origin --push
  git push origin --tags
fi
echo "已发布到 GitHub: https://github.com/${TARGET}"
