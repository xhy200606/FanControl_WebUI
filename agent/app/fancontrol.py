from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from .config import BACKUP_DIR, FANCONTROL_PATH, SOURCES_DIR, SOURCE_WRAPPER_DIR, atomic_json, ensure_dirs
from .hardware import find_sensor, scan_hwmon, sensor_descriptor
from .host import service_action, service_state

PAIR_VARS = {
    "FCTEMPS", "FCFANS", "MINTEMP", "MAXTEMP", "MINSTART", "MINSTOP",
    "MINPWM", "MAXPWM", "AVERAGE"
}


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_pairs(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in text.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        result[key] = value
    return result


def load_fancontrol() -> dict[str, Any]:
    if not FANCONTROL_PATH.exists():
        return {"exists": False, "path": "/etc/fancontrol", "interval": 10, "channels": [], "raw": {}}
    raw: dict[str, str] = {}
    for line in FANCONTROL_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        raw[key.strip()] = value.strip()
    maps = {name: parse_pairs(raw.get(name, "")) for name in PAIR_VARS}
    keys: set[str] = set()
    for mapping in maps.values():
        keys.update(mapping.keys())
    channels = []
    for pwm in sorted(keys):
        if not re.search(r"/pwm\d+$", pwm) and not re.fullmatch(r"hwmon\d+(/device)?/pwm\d+", pwm):
            continue
        def val(name: str, default: str | None = None) -> str | None:
            return maps[name].get(pwm, default)
        channels.append({
            "pwm": pwm,
            "temp": val("FCTEMPS"),
            "fan": val("FCFANS"),
            "mintemp": _safe_int(val("MINTEMP"), 40),
            "maxtemp": _safe_int(val("MAXTEMP"), 75),
            "minstart": _safe_int(val("MINSTART"), 120),
            "minstop": _safe_int(val("MINSTOP"), 90),
            "minpwm": _safe_int(val("MINPWM"), 90),
            "maxpwm": _safe_int(val("MAXPWM"), 255),
            "average": _safe_int(val("AVERAGE"), 1),
            "source_kind": "command" if str(val("FCTEMPS") or "").startswith("!") else "hwmon",
        })
    return {
        "exists": True,
        "path": "/etc/fancontrol",
        "interval": _safe_int(raw.get("INTERVAL"), 10),
        "channels": channels,
        "raw": raw,
    }


def _serialize(raw: dict[str, str]) -> str:
    ordered = [
        "INTERVAL", "DEVPATH", "DEVNAME", "FCTEMPS", "FCFANS", "MINTEMP",
        "MAXTEMP", "MINSTART", "MINSTOP", "MINPWM", "MAXPWM", "AVERAGE"
    ]
    lines = ["# Managed by PVE Fan Control. Backup is created before each write."]
    seen: set[str] = set()
    for key in ordered:
        if key in raw:
            lines.append(f"{key}={raw[key]}")
            seen.add(key)
    for key, value in raw.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def _backup_and_write(raw: dict[str, str]) -> Path:
    ensure_dirs()
    if not FANCONTROL_PATH.exists():
        raise FileNotFoundError("/etc/fancontrol does not exist; run pwmconfig first")
    backup = BACKUP_DIR / f"fancontrol.{time.strftime('%Y%m%d-%H%M%S')}.bak"
    shutil.copy2(FANCONTROL_PATH, backup)
    tmp = FANCONTROL_PATH.with_suffix(".pve-fan.tmp")
    tmp.write_text(_serialize(raw), encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, FANCONTROL_PATH)
    return backup


def update_channel(pwm_key: str, settings: dict[str, Any], interval: int) -> Path:
    config = load_fancontrol()
    if not config["exists"]:
        raise FileNotFoundError("/etc/fancontrol does not exist; run pwmconfig first")
    if pwm_key not in {c["pwm"] for c in config["channels"]}:
        raise ValueError("Unknown fancontrol channel")
    mintemp = int(settings["mintemp"]); maxtemp = int(settings["maxtemp"])
    minstart = int(settings["minstart"]); minstop = int(settings["minstop"])
    minpwm = int(settings["minpwm"]); maxpwm = int(settings["maxpwm"])
    average = int(settings.get("average", 1)); interval = int(interval)
    if not (0 <= mintemp < maxtemp <= 120):
        raise ValueError("Temperature range is invalid")
    if not (0 <= minstop <= minstart <= 255):
        raise ValueError("MINSTOP/MINSTART are invalid")
    if not (0 <= minpwm <= maxpwm <= 255):
        raise ValueError("MINPWM/MAXPWM are invalid")
    if not (1 <= average <= 60 and 1 <= interval <= 60):
        raise ValueError("Interval/average is invalid")
    raw = dict(config["raw"])
    raw["INTERVAL"] = str(interval)
    for var, value in {
        "MINTEMP": mintemp, "MAXTEMP": maxtemp, "MINSTART": minstart,
        "MINSTOP": minstop, "MINPWM": minpwm, "MAXPWM": maxpwm, "AVERAGE": average,
    }.items():
        pairs = parse_pairs(raw.get(var, ""))
        pairs[pwm_key] = str(value)
        raw[var] = " ".join(f"{k}={v}" for k, v in pairs.items())
    return _backup_and_write(raw)


def _source_name(pwm_key: str) -> str:
    return "source-" + hashlib.sha256(pwm_key.encode("utf-8")).hexdigest()[:16]


def native_source_spec(pwm_key: str) -> dict[str, Any] | None:
    name = _source_name(pwm_key)
    path = SOURCES_DIR / f"{name}.json"
    if not path.exists():
        return None
    from .config import load_json
    return load_json(path, None)


def set_native_sources(pwm_key: str, sensor_ids: list[str], failsafe_temp: float = 100.0) -> dict[str, Any]:
    config = load_fancontrol()
    if pwm_key not in {c["pwm"] for c in config.get("channels", [])}:
        raise ValueError("Unknown fancontrol channel")
    if not sensor_ids:
        raise ValueError("At least one temperature source is required")
    hardware = scan_hwmon()
    sources = []
    missing = []
    for sensor_id in sensor_ids:
        sensor = find_sensor(sensor_id, hardware)
        if sensor is None:
            missing.append(sensor_id)
            continue
        sources.append(sensor_descriptor(sensor))
    if missing:
        raise ValueError("Unknown sensor: " + ", ".join(missing))
    failsafe_temp = max(60.0, min(120.0, float(failsafe_temp)))
    ensure_dirs()
    name = _source_name(pwm_key)
    spec = {
        "version": 1,
        "strategy": "max",
        "pwm": pwm_key,
        "sources": sources,
        "failsafe_temp": failsafe_temp,
    }
    spec_path = SOURCES_DIR / f"{name}.json"
    atomic_json(spec_path, spec, 0o600)
    wrapper_host = f"/usr/local/lib/pve-fan-control/sources/{name}"
    wrapper = SOURCE_WRAPPER_DIR / name
    wrapper.write_text(
        "#!/bin/sh\n"
        f"exec /usr/bin/python3 /usr/local/lib/pve-fan-control/temp_source.py /etc/pve-fan-control/sources/{name}.json\n",
        encoding="utf-8",
    )
    os.chmod(wrapper, 0o755)
    raw = dict(config["raw"])
    pairs = parse_pairs(raw.get("FCTEMPS", ""))
    pairs[pwm_key] = "!" + wrapper_host
    raw["FCTEMPS"] = " ".join(f"{k}={v}" for k, v in pairs.items())
    backup = _backup_and_write(raw)
    ok, message = service_action("restart")
    if not ok:
        raise RuntimeError(f"Configuration saved but fancontrol restart failed: {message}")
    return {"backup": str(backup).replace("/host", ""), "source": spec, "command": "!" + wrapper_host}


def resolve_sysfs_path(key: str) -> Path:
    """Resolve fancontrol-style relative paths after hwmon class/device moves."""
    if key.startswith("/"):
        return Path(key)
    base = Path("/sys/class/hwmon") / key
    if base.exists():
        return base
    if "/device/" in key:
        fallback = Path("/sys/class/hwmon") / key.replace("/device/", "/", 1)
        if fallback.exists():
            return fallback
    return base


def _validate_pwm_path(path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or not str(candidate).startswith("/sys/class/hwmon/"):
        raise ValueError("PWM path must be under /sys/class/hwmon")
    if not re.fullmatch(r"pwm\d+", candidate.name):
        raise ValueError("Invalid PWM file")
    if not candidate.exists():
        raise ValueError("PWM file does not exist")
    return candidate


def write_pwm(path: str, percent: int) -> dict[str, Any]:
    percent = max(20, min(100, int(percent)))
    pwm = _validate_pwm_path(path)
    value = round(percent / 100 * 255)
    enable = pwm.with_name(pwm.name + "_enable")
    if enable.exists() and os.access(enable, os.W_OK):
        try:
            enable.write_text("1", encoding="ascii")
        except OSError:
            pass
    pwm.write_text(str(value), encoding="ascii")
    return {"path": str(pwm), "percent": percent, "value": value}


def set_manual_pwm(path: str, percent: int, stop_native: bool = True) -> dict[str, Any]:
    before = service_state()
    if stop_native and before == "active":
        ok, msg = service_action("stop")
        if not ok:
            raise RuntimeError(f"Could not stop fancontrol: {msg}")
    result = write_pwm(path, percent)
    result["fancontrol_was"] = before
    return result
