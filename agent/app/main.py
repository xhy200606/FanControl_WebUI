from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import __version__
from .config import get_agent_token
from .enhanced import controller
from .fancontrol import (
    load_fancontrol,
    native_source_spec,
    set_manual_pwm,
    set_native_sources,
    update_channel,
)
from .hardware import find_sensor, scan_hwmon, sensor_descriptor
from .host import ipmi_sensors, service_action, service_state
from .metrics import render_metrics

TOKEN = get_agent_token()


@asynccontextmanager
async def lifespan(app: FastAPI):
    controller.start()
    yield
    controller.stop()


app = FastAPI(title="PVE Fan Agent", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)


def require_token(
    authorization: Annotated[str | None, Header()] = None,
    x_pve_fan_token: Annotated[str | None, Header()] = None,
) -> None:
    candidate = x_pve_fan_token
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
    if not candidate or not hmac.compare_digest(candidate, TOKEN):
        raise HTTPException(status_code=401, detail="Invalid agent token")


class ManualPWM(BaseModel):
    path: str
    percent: int = Field(ge=20, le=100)


class ChannelSettings(BaseModel):
    pwm: str
    mintemp: int = Field(ge=0, le=119)
    maxtemp: int = Field(ge=1, le=120)
    minstart: int = Field(ge=0, le=255)
    minstop: int = Field(ge=0, le=255)
    minpwm: int = Field(ge=0, le=255)
    maxpwm: int = Field(ge=0, le=255)
    average: int = Field(default=1, ge=1, le=60)
    interval: int = Field(default=10, ge=1, le=60)


class ServiceAction(BaseModel):
    action: str


class NativeSources(BaseModel):
    pwm: str
    sensor_ids: list[str]
    failsafe_temp: float = Field(default=100, ge=60, le=120)


class CurvePoint(BaseModel):
    temp: float = Field(ge=0, le=120)
    pwm: int = Field(ge=20, le=100)


class EnhancedChannel(BaseModel):
    pwm: str
    label: str | None = None
    sensor_ids: list[str]
    points: list[CurvePoint]
    hysteresis: float = Field(default=3.0, ge=0, le=15)
    emergency_temp: float = Field(default=82, ge=40, le=120)
    enabled: bool = True
    fan_paths: list[str] | None = None


class EnhancedConfig(BaseModel):
    enabled: bool = False
    interval: float = Field(default=2.0, ge=0.5, le=30)
    restore_native_on_disable: bool = True
    channels: list[EnhancedChannel]


class EnabledPayload(BaseModel):
    enabled: bool


class AlertsConfig(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    threshold_temp: float = Field(default=82, ge=40, le=120)
    cooldown_seconds: int = Field(default=300, ge=30, le=86400)


def build_overview() -> dict[str, Any]:
    hardware = scan_hwmon()
    fc = load_fancontrol()
    for channel in fc.get("channels", []):
        channel["source_spec"] = native_source_spec(channel["pwm"])
    return {
        "version": __version__,
        "service": service_state(),
        "hardware": hardware,
        "fancontrol": fc,
        "enhanced": controller.status(),
        "alerts": controller.alerts(),
    }


@app.get("/api/health", dependencies=[Depends(require_token)])
def health():
    return {"ok": True, "version": __version__, "role": "agent"}


@app.get("/api/overview", dependencies=[Depends(require_token)])
def overview():
    return build_overview()


@app.get("/api/ipmi", dependencies=[Depends(require_token)])
def ipmi():
    return ipmi_sensors()


@app.post("/api/manual", dependencies=[Depends(require_token)])
def manual(payload: ManualPWM):
    try:
        if controller.load_config().get("enabled"):
            controller.set_enabled(False)
        return {"ok": True, "result": set_manual_pwm(payload.path, payload.percent)}
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/fancontrol/channel", dependencies=[Depends(require_token)])
def fancontrol_channel(payload: ChannelSettings):
    try:
        if controller.load_config().get("enabled"):
            raise ValueError("Disable enhanced control before editing native fancontrol")
        backup = update_channel(payload.pwm, payload.model_dump(), payload.interval)
        ok, message = service_action("restart")
        if not ok:
            raise RuntimeError(f"Configuration saved, but fancontrol restart failed: {message}")
        return {"ok": True, "backup": str(backup).replace("/host", "")}
    except (ValueError, RuntimeError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/fancontrol/source", dependencies=[Depends(require_token)])
def fancontrol_source(payload: NativeSources):
    try:
        if controller.load_config().get("enabled"):
            raise ValueError("Disable enhanced control before editing native fancontrol")
        return {"ok": True, **set_native_sources(payload.pwm, payload.sensor_ids, payload.failsafe_temp)}
    except (ValueError, RuntimeError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/service", dependencies=[Depends(require_token)])
def service(payload: ServiceAction):
    if controller.load_config().get("enabled") and payload.action in {"start", "restart"}:
        raise HTTPException(status_code=400, detail="Enhanced control is active; host fancontrol must stay stopped")
    ok, message = service_action(payload.action)
    if not ok:
        raise HTTPException(status_code=400, detail=message or "systemctl failed")
    return {"ok": True, "state": service_state(), "message": message}


@app.post("/api/enhanced/config", dependencies=[Depends(require_token)])
def enhanced_config(payload: EnhancedConfig):
    try:
        hardware = scan_hwmon()
        fc = load_fancontrol()
        native = {c["pwm"]: c for c in fc.get("channels", [])}
        channels = []
        for item in payload.channels:
            sources = []
            for sensor_id in item.sensor_ids:
                sensor = find_sensor(sensor_id, hardware)
                if sensor is None:
                    raise ValueError(f"Unknown sensor: {sensor_id}")
                sources.append(sensor_descriptor(sensor))
            fan_paths = list(item.fan_paths or [])
            if not fan_paths and item.pwm in native and native[item.pwm].get("fan"):
                fan_paths = str(native[item.pwm]["fan"]).split("+")
            channels.append({
                "pwm": item.pwm,
                "label": item.label or item.pwm,
                "sources": sources,
                "points": [p.model_dump() for p in item.points],
                "hysteresis": item.hysteresis,
                "emergency_temp": item.emergency_temp,
                "enabled": item.enabled,
                "fan_paths": fan_paths,
            })
        current = controller.load_config()
        clean = controller.save_config({
            "enabled": current.get("enabled", False),
            "interval": payload.interval,
            "channels": channels,
            "restore_native_on_disable": payload.restore_native_on_disable,
        })
        return {"ok": True, "config": clean}
    except (ValueError, TypeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/enhanced/enable", dependencies=[Depends(require_token)])
def enhanced_enable(payload: EnabledPayload):
    try:
        return {"ok": True, "config": controller.set_enabled(payload.enabled)}
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/alerts", dependencies=[Depends(require_token)])
def alerts_get():
    return controller.alerts()


@app.post("/api/alerts", dependencies=[Depends(require_token)])
def alerts_set(payload: AlertsConfig):
    try:
        return {"ok": True, "config": controller.save_alerts(payload.model_dump())}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/metrics", response_class=PlainTextResponse, dependencies=[Depends(require_token)])
def metrics():
    return render_metrics(build_overview())
