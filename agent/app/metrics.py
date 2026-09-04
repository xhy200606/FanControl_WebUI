from __future__ import annotations

import re
from typing import Any


def _esc(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", value)


def render_metrics(overview: dict[str, Any]) -> str:
    lines = [
        "# HELP pve_fan_temperature_celsius Hardware temperature.",
        "# TYPE pve_fan_temperature_celsius gauge",
    ]
    for sensor in overview.get("hardware", {}).get("temperatures", []):
        labels = f'kind="{_esc(sensor.get("kind"))}",chip="{_esc(sensor.get("chip"))}",sensor="{_esc(sensor.get("label"))}"'
        lines.append(f"pve_fan_temperature_celsius{{{labels}}} {float(sensor.get('celsius', 0))}")
    lines += [
        "# HELP pve_fan_rpm Fan speed in RPM.",
        "# TYPE pve_fan_rpm gauge",
    ]
    for fan in overview.get("hardware", {}).get("fans", []):
        labels = f'chip="{_esc(fan.get("chip"))}",fan="{_esc(fan.get("label"))}"'
        lines.append(f"pve_fan_rpm{{{labels}}} {int(fan.get('rpm', 0))}")
    lines += [
        "# HELP pve_fan_pwm_percent PWM duty in percent.",
        "# TYPE pve_fan_pwm_percent gauge",
    ]
    for pwm in overview.get("hardware", {}).get("pwms", []):
        labels = f'chip="{_esc(pwm.get("chip"))}",pwm="{_esc(pwm.get("label"))}"'
        lines.append(f"pve_fan_pwm_percent{{{labels}}} {int(pwm.get('percent', 0))}")
    lines += [
        "# HELP pve_fan_native_service_up Whether host fancontrol is active.",
        "# TYPE pve_fan_native_service_up gauge",
        f"pve_fan_native_service_up {1 if overview.get('service') == 'active' else 0}",
        "# HELP pve_fan_enhanced_enabled Whether enhanced controller is enabled.",
        "# TYPE pve_fan_enhanced_enabled gauge",
        f"pve_fan_enhanced_enabled {1 if overview.get('enhanced', {}).get('config', {}).get('enabled') else 0}",
    ]
    return "\n".join(lines) + "\n"
