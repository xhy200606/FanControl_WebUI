from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .host import nvidia_scan

HWMON_ROOT = Path(os.getenv("PVE_FAN_HWMON_ROOT", "/sys/class/hwmon"))


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _int(path: Path) -> int | None:
    value = _read(path)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _label(hwmon: Path, stem: str, fallback: str) -> str:
    return _read(hwmon / f"{stem}_label") or fallback


def scan_hwmon() -> dict[str, Any]:
    temperatures: list[dict[str, Any]] = []
    fans: list[dict[str, Any]] = []
    pwms: list[dict[str, Any]] = []
    if HWMON_ROOT.exists():
        for hwmon in sorted(HWMON_ROOT.glob("hwmon*")):
            chip = _read(hwmon / "name") or hwmon.name
            for item in sorted(hwmon.glob("temp*_input")):
                match = re.fullmatch(r"temp(\d+)_input", item.name)
                if not match:
                    continue
                idx = match.group(1)
                raw = _int(item)
                if raw is None:
                    continue
                label = _label(hwmon, f"temp{idx}", f"Temp {idx}")
                temperatures.append({
                    "id": f"hwmon:{chip}:{label}:temp{idx}",
                    "kind": "hwmon",
                    "chip": chip,
                    "label": label,
                    "index": int(idx),
                    "celsius": round(raw / 1000.0, 1),
                    "path": str(item),
                })
            for item in sorted(hwmon.glob("fan*_input")):
                match = re.fullmatch(r"fan(\d+)_input", item.name)
                if not match:
                    continue
                idx = match.group(1)
                rpm = _int(item)
                if rpm is None:
                    continue
                label = _label(hwmon, f"fan{idx}", f"Fan {idx}")
                fans.append({
                    "id": f"hwmon:{chip}:{label}:fan{idx}",
                    "chip": chip,
                    "label": label,
                    "index": int(idx),
                    "rpm": rpm,
                    "path": str(item),
                })
            for item in sorted(hwmon.glob("pwm[0-9]*")):
                if not re.fullmatch(r"pwm\d+", item.name):
                    continue
                value = _int(item)
                if value is None:
                    continue
                enable = item.with_name(item.name + "_enable")
                pwms.append({
                    "id": f"hwmon:{chip}:{item.name}",
                    "chip": chip,
                    "label": item.name.upper(),
                    "value": value,
                    "percent": round(max(0, min(255, value)) / 255 * 100),
                    "path": str(item),
                    "enable_path": str(enable) if enable.exists() else None,
                    "enable_value": _int(enable) if enable.exists() else None,
                    "writable": os.access(item, os.W_OK),
                })
    temperatures.extend(nvidia_scan())
    return {"temperatures": temperatures, "fans": fans, "pwms": pwms}


def sensor_descriptor(sensor: dict[str, Any]) -> dict[str, Any]:
    if sensor.get("kind") == "nvidia":
        return {
            "kind": "nvidia",
            "gpu_index": sensor.get("gpu_index"),
            "gpu_uuid": sensor.get("gpu_uuid"),
            "label": sensor.get("label"),
        }
    return {
        "kind": "hwmon",
        "chip": sensor.get("chip"),
        "label": sensor.get("label"),
        "index": sensor.get("index"),
        "path": sensor.get("path"),
    }


def find_sensor(sensor_id: str, hardware: dict[str, Any] | None = None) -> dict[str, Any] | None:
    hw = hardware or scan_hwmon()
    return next((x for x in hw["temperatures"] if x.get("id") == sensor_id), None)


def read_sensor_descriptor(source: dict[str, Any]) -> float | None:
    kind = source.get("kind")
    if kind == "nvidia":
        current = nvidia_scan()
        uuid = source.get("gpu_uuid")
        idx = source.get("gpu_index")
        for gpu in current:
            if uuid and gpu.get("gpu_uuid") == uuid:
                return float(gpu["celsius"])
            if uuid is None and gpu.get("gpu_index") == idx:
                return float(gpu["celsius"])
        return None
    path = Path(str(source.get("path") or ""))
    raw = _int(path) if path.exists() else None
    if raw is not None:
        return raw / 1000.0
    chip = source.get("chip")
    label = source.get("label")
    idx = source.get("index")
    if HWMON_ROOT.exists():
        for hwmon in HWMON_ROOT.glob("hwmon*"):
            if (_read(hwmon / "name") or hwmon.name) != chip:
                continue
            candidates = [hwmon / f"temp{idx}_input"] if idx else list(hwmon.glob("temp*_input"))
            for candidate in candidates:
                match = re.fullmatch(r"temp(\d+)_input", candidate.name)
                if not match:
                    continue
                ci = match.group(1)
                if _label(hwmon, f"temp{ci}", f"Temp {ci}") != label:
                    continue
                raw = _int(candidate)
                if raw is not None:
                    return raw / 1000.0
    return None
