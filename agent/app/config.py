from __future__ import annotations

import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

HOST_ETC = Path(os.getenv("PVE_FAN_HOST_ETC", "/host/etc"))
HOST_LIB = Path(os.getenv("PVE_FAN_HOST_LIB", "/host/usr/local/lib/pve-fan-control"))
STATE_DIR = HOST_ETC / "pve-fan-control"
FANCONTROL_PATH = HOST_ETC / "fancontrol"
BACKUP_DIR = STATE_DIR / "backups"
SOURCES_DIR = STATE_DIR / "sources"
SOURCE_WRAPPER_DIR = HOST_LIB / "sources"
ENHANCED_PATH = STATE_DIR / "enhanced.json"
ALERTS_PATH = STATE_DIR / "alerts.json"


def ensure_dirs() -> None:
    for path in (STATE_DIR, BACKUP_DIR, SOURCES_DIR, SOURCE_WRAPPER_DIR):
        path.mkdir(parents=True, exist_ok=True)


def get_agent_token() -> str:
    token = os.getenv("PVE_FAN_AGENT_TOKEN", "").strip()
    if token:
        return token
    ensure_dirs()
    token_path = STATE_DIR / "agent-token"
    if token_path.exists():
        saved = token_path.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    token = secrets.token_urlsafe(36)
    token_path.write_text(token + "\n", encoding="utf-8")
    os.chmod(token_path, 0o600)
    return token


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def atomic_json(path: Path, data: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def default_enhanced() -> dict[str, Any]:
    return {
        "enabled": False,
        "interval": 2.0,
        "channels": [],
        "restore_native_on_disable": True,
    }


def default_alerts() -> dict[str, Any]:
    return {
        "enabled": False,
        "webhook_url": "",
        "threshold_temp": 82.0,
        "cooldown_seconds": 300,
    }
