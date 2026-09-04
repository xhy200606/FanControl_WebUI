from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
from typing import Any

HOST_NSENTER = os.getenv("PVE_FAN_HOST_NSENTER", "1") not in {"0", "false", "False"}


def host_exec(argv: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    cmd = list(argv)
    if HOST_NSENTER and shutil.which("nsenter"):
        cmd = ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--"] + cmd
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def service_state() -> str:
    try:
        proc = host_exec(["systemctl", "is-active", "fancontrol"], timeout=3)
        value = proc.stdout.strip()
        return value or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def service_action(action: str) -> tuple[bool, str]:
    if action not in {"start", "stop", "restart"}:
        return False, "unsupported action"
    try:
        proc = host_exec(["systemctl", action, "fancontrol"], timeout=15)
        msg = (proc.stdout + proc.stderr).strip()
        return proc.returncode == 0, msg
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def nvidia_scan() -> list[dict[str, Any]]:
    try:
        proc = host_exec(
            ["nvidia-smi", "--query-gpu=index,uuid,name,temperature.gpu", "--format=csv,noheader,nounits"],
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    rows: list[dict[str, Any]] = []
    for row in csv.reader(io.StringIO(proc.stdout)):
        if len(row) < 4:
            continue
        try:
            idx = int(row[0].strip())
            temp = float(row[3].strip())
        except ValueError:
            continue
        name = row[2].strip()
        uuid = row[1].strip()
        rows.append({
            "id": f"nvidia:{uuid or idx}",
            "kind": "nvidia",
            "chip": "nvidia",
            "label": f"GPU {idx} · {name}",
            "celsius": temp,
            "gpu_index": idx,
            "gpu_uuid": uuid,
            "path": None,
        })
    return rows


def ipmi_sensors() -> dict[str, Any]:
    try:
        proc = host_exec(["ipmitool", "sensor"], timeout=8)
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": False,
            "state": "error",
            "message": "IPMI 检测执行失败",
            "error": str(exc),
            "sensors": [],
        }
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        lowered = detail.lower()
        absent_markers = (
            "could not open device at /dev/ipmi0",
            "could not open device",
            "no such file or directory",
            "ipmi device not found",
            "unable to open ipmi device",
        )
        if any(marker in lowered for marker in absent_markers):
            return {
                "available": False,
                "state": "not_detected",
                "message": "未检测到本地 BMC/IPMI 设备（不影响 hwmon/fancontrol）",
                "error": "",
                "sensors": [],
            }
        return {
            "available": False,
            "state": "error",
            "message": "IPMI 命令执行异常",
            "error": detail,
            "sensors": [],
        }
    sensors: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 4:
            continue
        name, reading, units, status = cols[:4]
        if reading.lower() in {"na", "n/a", "disabled", ""}:
            continue
        sensors.append({"name": name, "reading": reading, "units": units, "status": status})
    return {
        "available": True,
        "state": "available",
        "message": f"已检测到 {len(sensors)} 个 IPMI 传感器项目",
        "error": "",
        "sensors": sensors,
    }
