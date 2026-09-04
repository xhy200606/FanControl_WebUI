#!/usr/bin/env python3
"""Temperature adapter for lm-sensors fancontrol !command sources.

Prints one integer in millidegrees Celsius. On any total source failure it
prints the configured failsafe temperature so fancontrol moves to maximum PWM.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HWMON = Path("/sys/class/hwmon")


def text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def intval(path: Path) -> int | None:
    value = text(path)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def hwmon_value(source: dict) -> int | None:
    path = Path(str(source.get("path") or ""))
    raw = intval(path) if path.exists() else None
    if raw is not None:
        return raw
    chip = source.get("chip")
    label = source.get("label")
    index = source.get("index")
    if not HWMON.exists():
        return None
    for hw in HWMON.glob("hwmon*"):
        if (text(hw / "name") or hw.name) != chip:
            continue
        candidates = [hw / f"temp{index}_input"] if index else list(hw.glob("temp*_input"))
        for candidate in candidates:
            m = re.fullmatch(r"temp(\d+)_input", candidate.name)
            if not m:
                continue
            idx = m.group(1)
            current_label = text(hw / f"temp{idx}_label") or f"Temp {idx}"
            if label and current_label != label:
                continue
            raw = intval(candidate)
            if raw is not None:
                return raw
    return None


def nvidia_value(source: dict) -> int | None:
    selector = source.get("gpu_uuid") or source.get("gpu_index")
    if selector is None:
        return None
    try:
        proc = subprocess.run(
            ["nvidia-smi", "-i", str(selector), "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    first = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
    try:
        return round(float(first) * 1000)
    except ValueError:
        return None


def main() -> int:
    if len(sys.argv) != 2:
        print(100000)
        return 0
    try:
        config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except Exception:
        print(100000)
        return 0
    values: list[int] = []
    for source in config.get("sources", []):
        value = nvidia_value(source) if source.get("kind") == "nvidia" else hwmon_value(source)
        if value is not None and 0 <= value <= 150000:
            values.append(value)
    if values:
        print(max(values))
    else:
        failsafe = float(config.get("failsafe_temp", 100.0))
        print(round(max(60.0, min(120.0, failsafe)) * 1000))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
