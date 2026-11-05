"""Dashboard REST API for Shelly Direct — mounted at /api/plugins/shelly-direct/.

Sync handlers on purpose: the Shelly client is blocking requests I/O and
FastAPI runs sync endpoints on its threadpool, keeping the dashboard loop free.
Shares the durable inventory file with the agent-side tool.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import APIRouter  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from shelly_core import actions, inventory  # noqa: E402
from shelly_core.actions import merged_cfg  # noqa: E402

router = APIRouter()

PLUGIN_ID = "shelly-direct"
VERSION = "1.0.0"


def _settings() -> dict:
    """Read plugin settings straight from config.yaml (the dashboard process
    has no PluginContext). Secrets stay in the environment / secret store."""
    settings: dict = {}
    try:
        import yaml
        cfg_path = Path(os.environ.get("HERMES_HOME",
                                       Path.home() / ".hermes")) / "config.yaml"
        data = yaml.safe_load(cfg_path.read_text()) or {}
        entry = (data.get("plugins", {}).get("entries", {})
                 .get(PLUGIN_ID, {}).get("settings", {})) or {}
        for key in ("timeout_ms", "verify_writes", "extra_hosts", "auth_user"):
            if entry.get(key) not in (None, ""):
                settings[key] = entry[key]
    except Exception:  # noqa: BLE001 — defaults are fine
        pass
    try:
        from agent.secret_scope import get_secret
        secret = get_secret("SHELLY_DIRECT_AUTH_PASSWORD")
        if secret:
            settings["auth_password"] = secret
    except Exception:  # noqa: BLE001
        pass
    return settings


class ActionBody(BaseModel):
    mac: str
    action: str  # on | off | toggle | set | cover
    channel: int = 0
    brightness: Optional[int] = None
    rgb: Optional[str] = None
    white: Optional[int] = None
    position: Optional[int] = None
    op: Optional[str] = None


@router.get("/health")
def health():
    return {"ok": True, "version": VERSION}


class DiscoverBody(BaseModel):
    subnet: Optional[str] = None


@router.post("/discover")
def discover(body: DiscoverBody | None = None):
    return actions.act_discover(merged_cfg(_settings()),
                                subnet=(body.subnet if body else "") or "")


@router.get("/devices")
def devices():
    return actions.act_list(merged_cfg(_settings()))


@router.get("/device/{mac}")
def device_status(mac: str):
    return actions.act_status(mac.upper(), merged_cfg(_settings()))


@router.post("/action")
def action(body: ActionBody):
    cfg = merged_cfg(_settings())
    if body.action in ("on", "off", "toggle"):
        return actions.act_switch(body.mac.upper(), body.action, body.channel, cfg)
    if body.action == "set":
        return actions.act_set(body.mac.upper(), body.channel, body.brightness,
                               body.rgb, body.white, cfg)
    if body.action == "cover":
        return actions.act_cover(body.mac.upper(), body.op, body.position,
                                 body.channel, cfg)
    return {"ok": False, "error": f"unsupported action '{body.action}'"}


@router.get("/settings")
def settings():
    cfg = merged_cfg(_settings())
    return {"ok": True, "settings": {
        "verify_writes": bool(cfg["verify_writes"]),
        "extra_hosts": cfg["extra_hosts"],
        "auth_configured": bool(cfg["auth_password"]),
    }}
