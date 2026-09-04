from __future__ import annotations

import json
import math
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from .config import ALERTS_PATH, ENHANCED_PATH, atomic_json, default_alerts, default_enhanced, load_json
from .fancontrol import resolve_sysfs_path, write_pwm
from .host import service_action
from .hardware import read_sensor_descriptor, scan_hwmon


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def curve_pwm(temp: float, points: list[dict[str, Any]]) -> int:
    pts = sorted((float(p["temp"]), float(p["pwm"])) for p in points)
    if not pts:
        return 100
    if temp <= pts[0][0]:
        return round(pts[0][1])
    if temp >= pts[-1][0]:
        return round(pts[-1][1])
    for (t1, p1), (t2, p2) in zip(pts, pts[1:]):
        if t1 <= temp <= t2:
            ratio = (temp - t1) / max(0.001, t2 - t1)
            return round(p1 + ratio * (p2 - p1))
    return round(pts[-1][1])


def validate_enhanced(config: dict[str, Any]) -> dict[str, Any]:
    interval = float(config.get("interval", 2.0))
    if not (0.5 <= interval <= 30):
        raise ValueError("Enhanced interval must be between 0.5 and 30 seconds")
    channels = config.get("channels") or []
    cleaned = []
    seen: set[str] = set()
    for channel in channels:
        pwm = str(channel.get("pwm") or "").strip()
        if not pwm or pwm in seen:
            raise ValueError("Each enhanced channel needs a unique PWM")
        seen.add(pwm)
        points = channel.get("points") or []
        if len(points) < 2:
            raise ValueError(f"{pwm}: at least two curve points are required")
        sorted_points = sorted(
            [{"temp": float(p["temp"]), "pwm": int(p["pwm"])} for p in points],
            key=lambda p: p["temp"],
        )
        last_t = -math.inf
        last_p = -1
        for point in sorted_points:
            if not (0 <= point["temp"] <= 120 and 20 <= point["pwm"] <= 100):
                raise ValueError(f"{pwm}: curve point is out of range")
            if point["temp"] <= last_t:
                raise ValueError(f"{pwm}: curve temperatures must increase")
            if point["pwm"] < last_p:
                raise ValueError(f"{pwm}: curve PWM should not decrease as temperature rises")
            last_t, last_p = point["temp"], point["pwm"]
        sources = channel.get("sources") or []
        if not sources:
            raise ValueError(f"{pwm}: at least one temperature source is required")
        hysteresis = float(channel.get("hysteresis", 3.0))
        emergency = float(channel.get("emergency_temp", 82.0))
        if not (0 <= hysteresis <= 15):
            raise ValueError(f"{pwm}: hysteresis must be 0..15°C")
        if not (40 <= emergency <= 120):
            raise ValueError(f"{pwm}: emergency temperature must be 40..120°C")
        cleaned.append({
            "pwm": pwm,
            "label": str(channel.get("label") or pwm),
            "sources": sources,
            "fan_paths": [str(x) for x in (channel.get("fan_paths") or []) if str(x).strip()],
            "points": sorted_points,
            "hysteresis": hysteresis,
            "emergency_temp": emergency,
            "enabled": bool(channel.get("enabled", True)),
        })
    return {
        "enabled": bool(config.get("enabled", False)),
        "interval": interval,
        "channels": cleaned,
        "restore_native_on_disable": bool(config.get("restore_native_on_disable", True)),
    }


class EnhancedController:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._runtime: dict[str, Any] = {
            "running": False,
            "channels": {},
            "last_error": "",
            "last_tick": None,
        }
        self._last_alert_at = 0.0
        self._last_alert_key = ""

    def load_config(self) -> dict[str, Any]:
        raw = load_json(ENHANCED_PATH, default_enhanced())
        try:
            return validate_enhanced(raw)
        except (ValueError, TypeError, KeyError):
            return default_enhanced()

    def save_config(self, config: dict[str, Any]) -> dict[str, Any]:
        clean = validate_enhanced(config)
        atomic_json(ENHANCED_PATH, clean, 0o600)
        return clean

    def alerts(self) -> dict[str, Any]:
        result = default_alerts()
        result.update(load_json(ALERTS_PATH, {}))
        return result

    def save_alerts(self, data: dict[str, Any]) -> dict[str, Any]:
        result = default_alerts()
        result.update({
            "enabled": bool(data.get("enabled", False)),
            "webhook_url": str(data.get("webhook_url", "")).strip(),
            "threshold_temp": max(40.0, min(120.0, float(data.get("threshold_temp", 82)))),
            "cooldown_seconds": max(30, min(86400, int(data.get("cooldown_seconds", 300)))),
        })
        if result["enabled"] and not result["webhook_url"].startswith(("http://", "https://")):
            raise ValueError("Webhook URL must start with http:// or https://")
        atomic_json(ALERTS_PATH, result, 0o600)
        return result

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="pve-fan-enhanced", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        config = self.load_config()
        if config.get("enabled"):
            self._force_all(config, 100)

    def status(self) -> dict[str, Any]:
        config = self.load_config()
        with self._lock:
            runtime = json.loads(json.dumps(self._runtime))
        return {"config": config, "runtime": runtime}

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        config = self.load_config()
        enabled = bool(enabled)
        if enabled:
            active_channels = [c for c in config.get("channels", []) if c.get("enabled", True)]
            if not active_channels:
                raise ValueError("At least one enhanced channel must be configured before enabling")
            for channel in active_channels:
                pwm = resolve_sysfs_path(channel["pwm"])
                if not pwm.exists():
                    raise ValueError(f"PWM path does not exist: {channel['pwm']}")
                if not pwm.is_file():
                    raise ValueError(f"PWM path is invalid: {channel['pwm']}")
            ok, msg = service_action("stop")
            if not ok and "not loaded" not in msg.lower() and "not found" not in msg.lower():
                raise RuntimeError(f"Unable to stop host fancontrol: {msg}")
            config["enabled"] = True
            return self.save_config(config)

        config["enabled"] = False
        config = self.save_config(config)
        self._force_all(config, 100)
        if config.get("restore_native_on_disable"):
            service_action("start")
        return config

    def _force_all(self, config: dict[str, Any], percent: int) -> None:
        for channel in config.get("channels", []):
            if not channel.get("enabled", True):
                continue
            path = resolve_sysfs_path(channel["pwm"])
            try:
                write_pwm(str(path), percent)
            except Exception:
                pass

    def _loop(self) -> None:
        last_effective: dict[str, float] = {}
        while not self._stop.is_set():
            config = self.load_config()
            interval = float(config.get("interval", 2.0))
            runtime_channels: dict[str, Any] = {}
            last_error = ""
            try:
                hardware = scan_hwmon()
                self._alert_monitor(hardware)
                if config.get("enabled"):
                    for channel in config.get("channels", []):
                        if not channel.get("enabled", True):
                            continue
                        result = self._tick_channel(channel, last_effective)
                        runtime_channels[channel["pwm"]] = result
            except Exception as exc:
                last_error = str(exc)
            with self._lock:
                self._runtime = {
                    "running": bool(config.get("enabled")),
                    "channels": runtime_channels,
                    "last_error": last_error,
                    "last_tick": time.time(),
                }
            self._stop.wait(interval)

    def _tick_channel(self, channel: dict[str, Any], last_effective: dict[str, float]) -> dict[str, Any]:
        values: list[float] = []
        unavailable = 0
        for source in channel.get("sources", []):
            value = read_sensor_descriptor(source)
            if value is None:
                unavailable += 1
            else:
                values.append(value)
        pwm_key = channel["pwm"]
        reason = "curve"
        if not values:
            effective = channel["emergency_temp"]
            target = 100
            reason = "sensor-failsafe"
        else:
            raw = max(values)
            previous = last_effective.get(pwm_key, raw)
            hysteresis = float(channel.get("hysteresis", 3.0))
            effective = previous if raw < previous and raw > previous - hysteresis else raw
            last_effective[pwm_key] = effective
            if raw >= float(channel["emergency_temp"]):
                target = 100
                reason = "high-temperature"
            else:
                target = curve_pwm(effective, channel["points"])
        fan_rpms = []
        stalled = False
        for fan_key in channel.get("fan_paths", []):
            path = resolve_sysfs_path(fan_key)
            rpm = _read_int(path)
            if rpm is not None:
                fan_rpms.append(rpm)
                if target >= 30 and rpm == 0:
                    stalled = True
        if stalled:
            target = 100
            reason = "fan-stall"
        pwm_path = resolve_sysfs_path(pwm_key)
        write_pwm(str(pwm_path), int(target))
        if reason in {"sensor-failsafe", "high-temperature", "fan-stall"}:
            self._send_alert(
                reason,
                {
                    "pwm": pwm_key,
                    "temperature": max(values) if values else None,
                    "target_pwm": target,
                    "fan_rpms": fan_rpms,
                    "unavailable_sources": unavailable,
                },
            )
        return {
            "temperature": max(values) if values else None,
            "effective_temperature": effective,
            "target_pwm": target,
            "reason": reason,
            "fan_rpms": fan_rpms,
            "unavailable_sources": unavailable,
        }

    def _alert_monitor(self, hardware: dict[str, Any]) -> None:
        alerts = self.alerts()
        if not alerts.get("enabled"):
            return
        temps = hardware.get("temperatures", [])
        if not temps:
            return
        hottest = max(temps, key=lambda x: float(x.get("celsius", -999)))
        if float(hottest["celsius"]) >= float(alerts["threshold_temp"]):
            self._send_alert("monitor-high-temperature", {"sensor": hottest})

    def _send_alert(self, key: str, payload: dict[str, Any]) -> None:
        alerts = self.alerts()
        if not alerts.get("enabled") or not alerts.get("webhook_url"):
            return
        now = time.time()
        cooldown = int(alerts.get("cooldown_seconds", 300))
        if key == self._last_alert_key and now - self._last_alert_at < cooldown:
            return
        body = json.dumps({
            "event": key,
            "source": "PVE Fan Control",
            "timestamp": int(now),
            "payload": payload,
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            alerts["webhook_url"], data=body,
            headers={"Content-Type": "application/json", "User-Agent": "PVE-Fan-Control/0.2"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read(64)
            self._last_alert_key = key
            self._last_alert_at = now
        except Exception:
            pass


controller = EnhancedController()
