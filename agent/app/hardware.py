from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .host import host_exec, nvidia_scan

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


def _direct_scan() -> dict[str, Any]:
    temperatures: list[dict[str, Any]] = []
    fans: list[dict[str, Any]] = []
    pwms: list[dict[str, Any]] = []
    devices: list[str] = []
    if HWMON_ROOT.exists():
        for hwmon in sorted(HWMON_ROOT.glob("hwmon*")):
            chip = _read(hwmon / "name") or hwmon.name
            devices.append(chip)
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
    return {"temperatures": temperatures, "fans": fans, "pwms": pwms, "devices": devices, "source": "container-sysfs"}


def _host_scan() -> dict[str, Any] | None:
    # Docker's own /sys view can omit hwmon entries on some hosts. Ask PID 1's
    # mount namespace directly so Agent sees what the PVE host actually sees.
    code = r'''
import glob,json,os,re
T=[];F=[];P=[];D=[]
def rd(p):
    try:
        with open(p,'r',encoding='utf-8',errors='replace') as f:return f.read().strip()
    except OSError:return None
def iv(p):
    try:return int(rd(p))
    except (TypeError,ValueError):return None
for h in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
    chip=rd(os.path.join(h,'name')) or os.path.basename(h);D.append(chip)
    for item in sorted(glob.glob(os.path.join(h,'temp*_input'))):
        m=re.fullmatch(r'temp(\d+)_input',os.path.basename(item))
        if not m:continue
        i=m.group(1);v=iv(item)
        if v is None:continue
        label=rd(os.path.join(h,f'temp{i}_label')) or f'Temp {i}'
        T.append({'id':f'hwmon:{chip}:{label}:temp{i}','kind':'hwmon','chip':chip,'label':label,'index':int(i),'celsius':round(v/1000,1),'path':item})
    for item in sorted(glob.glob(os.path.join(h,'fan*_input'))):
        m=re.fullmatch(r'fan(\d+)_input',os.path.basename(item))
        if not m:continue
        i=m.group(1);v=iv(item)
        if v is None:continue
        label=rd(os.path.join(h,f'fan{i}_label')) or f'Fan {i}'
        F.append({'id':f'hwmon:{chip}:{label}:fan{i}','chip':chip,'label':label,'index':int(i),'rpm':v,'path':item})
    for item in sorted(glob.glob(os.path.join(h,'pwm[0-9]*'))):
        if not re.fullmatch(r'pwm\d+',os.path.basename(item)):continue
        v=iv(item)
        if v is None:continue
        en=item+'_enable'
        P.append({'id':f'hwmon:{chip}:{os.path.basename(item)}','chip':chip,'label':os.path.basename(item).upper(),'value':v,'percent':round(max(0,min(255,v))/255*100),'path':item,'enable_path':en if os.path.exists(en) else None,'enable_value':iv(en) if os.path.exists(en) else None,'writable':os.access(item,os.W_OK)})
print(json.dumps({'temperatures':T,'fans':F,'pwms':P,'devices':D,'source':'host-nsenter'}))
'''
    try:
        proc = host_exec(["python3", "-c", code], timeout=6)
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _diagnostic_message(data: dict[str, Any]) -> str:
    devices = data.get("devices") or []
    pwms = data.get("pwms") or []
    writable = [p for p in pwms if p.get("writable")]
    if not devices:
        return "宿主机未发现 hwmon 设备。请运行 sensors-detect，并确认主板传感器驱动已加载。"
    if not pwms:
        return "宿主机已发现 hwmon，但内核没有暴露 pwmN 控制通道。请检查主板 Super I/O 驱动（如 nct6775/it87）并运行 pwmconfig。"
    if not writable:
        return "检测到 PWM 通道，但当前不可写。请检查驱动控制模式与权限。"
    return f"检测到 {len(pwms)} 个 PWM 通道，其中 {len(writable)} 个可写。"


def scan_hwmon() -> dict[str, Any]:
    data = _host_scan() or _direct_scan()
    temperatures = list(data.get("temperatures") or [])
    fans = list(data.get("fans") or [])
    pwms = list(data.get("pwms") or [])
    gpu = nvidia_scan()
    temperatures.extend(gpu)
    diagnostics = {
        "scan_source": data.get("source", "unknown"),
        "hwmon_root": "/sys/class/hwmon",
        "hwmon_devices": data.get("devices") or [],
        "native_temperature_count": len([x for x in temperatures if x.get("kind") == "hwmon"]),
        "nvidia_count": len(gpu),
        "fan_count": len(fans),
        "pwm_count": len(pwms),
        "writable_pwm_count": len([x for x in pwms if x.get("writable")]),
    }
    diagnostics["message"] = _diagnostic_message(data)
    return {"temperatures": temperatures, "fans": fans, "pwms": pwms, "diagnostics": diagnostics}


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


def _host_read_int(path: str) -> int | None:
    try:
        proc = host_exec(["cat", path], timeout=2)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


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
    path_text = str(source.get("path") or "")
    path = Path(path_text)
    raw = _int(path) if path.exists() else None
    if raw is None and path_text.startswith("/sys/class/hwmon/"):
        raw = _host_read_int(path_text)
    if raw is not None:
        return raw / 1000.0
    chip = source.get("chip")
    label = source.get("label")
    idx = source.get("index")
    current = scan_hwmon().get("temperatures", [])
    for sensor in current:
        if sensor.get("kind") != "hwmon":
            continue
        if sensor.get("chip") == chip and sensor.get("label") == label and (idx is None or sensor.get("index") == idx):
            return float(sensor["celsius"])
    return None
