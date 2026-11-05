"""Minimal Shelly device client.

Speaks both protocols shipped by Shelly hardware:
  * Gen1 (ESP8266-era): plain HTTP REST  — GET /status, /relay/0?turn=on, /roller/0?go=open
  * Gen2/Gen3: HTTP RPC — POST /rpc/Switch.Set, /rpc/Cover.GoToPosition, /rpc/Light.Set

Generation is auto-detected with a single cheap probe (GET /shelly): Gen1 firmware
does not report a ``gen`` field, Gen2/3 report 2 and 3. Never trust cached gen hints.

Optional digest auth covers devices with a local password configured.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import requests

try:  # digest auth is only built when requests ships it (it does since 2.11)
    from requests.auth import HTTPDigestAuth
except ImportError:  # pragma: no cover
    HTTPDigestAuth = None


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(value)))


class ShellyClient:
    """One device, one session. All methods return dicts; errors come back as
    ``{"error": "..."}`` instead of raising, so tool handlers never explode."""

    def __init__(self, ip: str, timeout: float = 3.0,
                 auth_user: str = "", auth_password: str = "") -> None:
        self.ip = ip
        self.timeout = timeout
        self.session = requests.Session()
        if auth_password and HTTPDigestAuth is not None:
            self.session.auth = HTTPDigestAuth(auth_user or "admin", auth_password)

    # ------------------------------------------------------------------ http
    def _get(self, path: str, params: Optional[dict] = None) -> Dict[str, Any]:
        try:
            r = self.session.get(f"http://{self.ip}{path}", params=params,
                                 timeout=self.timeout)
            r.raise_for_status()
            return r.json() if r.text.strip() else {}
        except Exception as exc:  # noqa: BLE001 — device offline is normal life
            return {"error": str(exc)}

    def _rpc(self, method: str, params: Optional[dict] = None) -> Dict[str, Any]:
        try:
            r = self.session.post(f"http://{self.ip}/rpc/{method}",
                                  json=params or {}, timeout=self.timeout)
            r.raise_for_status()
            return r.json() if r.text.strip() else {}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    # --------------------------------------------------------------- probing
    def probe(self) -> Dict[str, Any]:
        """Cheap identity probe: gen, model, fw, mac, id. Every generation
        answers GET /shelly with at least gen/model/mac/id."""
        info = self._get("/shelly")
        if "error" in info:
            return {"error": info["error"]}
        return {"gen": int(info.get("gen", 1)),
                "model": info.get("model") or info.get("type") or "",
                "fw": info.get("fw") or info.get("ver") or "",
                "mac": str(info.get("mac") or "").replace(":", "").upper(),
                "id": str(info.get("id") or "")}

    def device_info(self, gen: int) -> Dict[str, str]:
        """Friendly name + MAC as the device reports them over HTTP."""
        if gen == 1:
            settings = self._get("/settings")
            if "error" in settings:
                return {}
            device_cfg = settings.get("device") or {}
            return {"name": str(settings.get("name") or ""),
                    "mac": str(device_cfg.get("mac") or "").replace(":", "").upper()}
        info = self._rpc("Shelly.GetDeviceInfo")
        if "error" in info:
            return {}
        return {"name": str(info.get("name") or ""),
                "mac": str(info.get("mac") or "").replace(":", "").upper()}

    # ---------------------------------------------------------------- status
    def get_status(self, gen: int) -> Dict[str, Any]:
        if gen == 1:
            return self._get("/status")
        return self._rpc("Shelly.GetStatus")

    # ---------------------------------------------------------------- writes
    def set_switch(self, gen: int, index: int, on: str) -> Dict[str, Any]:
        """on: "on" | "off" | "toggle"."""
        if gen == 1:
            return self._get(f"/relay/{index}", params={"turn": on})
        payload: Dict[str, Any] = {"id": index}
        if on == "toggle":
            current = self.get_status(gen).get(f"switch:{index}", {})
            payload["on"] = not bool(current.get("on"))
        else:
            payload["on"] = on == "on"
        return self._rpc("Switch.Set", payload)

    def set_light(self, gen: int, index: int, on: Optional[str] = None,
                  brightness: Optional[int] = None, rgb: Optional[str] = None,
                  white: Optional[int] = None) -> Dict[str, Any]:
        if gen == 1:
            params: Dict[str, Any] = {}
            if on:
                params["turn"] = on
            if brightness is not None:
                params["brightness"] = _clamp(brightness)
            if rgb:
                r_, g_, b_ = _parse_hex_rgb(rgb)
                params["rgb"] = f"{r_},{g_},{b_}"
            return self._get(f"/light/{index}", params=params or None)
        payload: Dict[str, Any] = {"id": index}
        if on:
            payload["on"] = on == "on"
        if brightness is not None:
            payload["brightness"] = _clamp(brightness)
        if rgb:
            payload["rgb"] = rgb if rgb.startswith("#") else f"#{rgb}"
        if white is not None:
            payload["white"] = _clamp(white)
        return self._rpc("Light.Set", payload)

    def set_cover(self, gen: int, index: int, op: Optional[str] = None,
                  position: Optional[int] = None) -> Dict[str, Any]:
        if gen == 1:
            if position is not None:
                return self._get(f"/roller/{index}",
                                 params={"go": "to_pos", "roller_pos": _clamp(position)})
            return self._get(f"/roller/{index}", params={"go": op or "stop"})
        if position is not None:
            return self._rpc("Cover.GoToPosition",
                             {"id": index, "pos": _clamp(position)})
        return self._rpc(f"Cover.{(op or 'stop').capitalize()}", {"id": index})


def _parse_hex_rgb(rgb: str) -> tuple:
    hex_ = rgb.lstrip("#")
    if len(hex_) == 3:
        hex_ = "".join(c * 2 for c in hex_)
    try:
        return int(hex_[0:2], 16), int(hex_[2:4], 16), int(hex_[4:6], 16)
    except (ValueError, IndexError):
        return 255, 255, 255


# ------------------------------------------------------------------ normalize
_COVER_STATE = {"open": "open", "opened": "open", "close": "closed",
                "closed": "closed", "opening": "opening", "closing": "closing",
                "stop": "stop", "stopped": "stop"}

# Hardware codes -> marketing names (only what is certain; raw code otherwise)
MODEL_NAMES = {
    "SHSW-1": "Shelly 1",
    "SHSW-1PM": "Shelly 1PM",
    "SHSW-25": "Shelly 2.5",
    "SHSW-4": "Shelly 4 Pro",
    "SHIX3-1": "Shelly i3",
    "SNSW-001X16EU": "Shelly Plug S",
    "SNSW-102P16EU": "Shelly Plug US",
    "SPSW-104PE16EU": "Shelly 4PM Pro",
    "S3SW-001X8EU": "Shelly 1PM Gen3",
    "S3PL-10112EU": "Shelly Plug Gen3",
    "S3VD-001201": "Shelly Dimmer Gen3",
    "S3SB-002PO12G": "Shelly RGBW Gen3",
}


def friendly_model(code: str) -> str:
    return MODEL_NAMES.get(code, code or "")


def normalize_status(gen: int, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map Gen1 REST and Gen2/3 RPC status payloads onto one common shape:

    {relays:[{index,on,apower?,atotal?}], lights:[{index,on,brightness?,rgb?}],
     covers:[{index,state,position?,apower?}], meters:[{index,power?,energy?,voltage?}],
     sensors:{temperature?,humidity?,battery?}}
    """
    out: Dict[str, Any] = {"relays": [], "lights": [], "covers": [],
                           "meters": [], "sensors": {}}
    if not isinstance(raw, dict) or "error" in raw:
        return out

    if gen == 1:
        for i, r in enumerate(raw.get("relays") or []):
            item = {"index": i, "on": bool(r.get("ison"))}
            if "apower" in r:
                item["apower"] = r["apower"]
            if "aenergy" in r and isinstance(r["aenergy"], dict):
                item["atotal"] = r["aenergy"].get("total")
            out["relays"].append(item)
        for i, l in enumerate(raw.get("lights") or []):
            item = {"index": i, "on": bool(l.get("ison"))}
            if l.get("brightness") is not None:
                item["brightness"] = l["brightness"]
            if l.get("rgb"):
                item["rgb"] = l["rgb"]
            out["lights"].append(item)
        for i, c in enumerate(raw.get("rollers") or []):
            out["covers"].append({
                "index": i,
                "state": _COVER_STATE.get(str(c.get("state", "")), str(c.get("state", "?"))),
                "position": c.get("current_pos"),
            })
        for i, m in enumerate(raw.get("meters") or []):
            out["meters"].append({"index": i, "power": m.get("power", m.get("apower")),
                                  "energy": m.get("energy", m.get("total"))})
        for key, label in (("temperature", "temperature"), ("humidity", "humidity"),
                           ("battery", "battery"), ("illuminance", "illuminance")):
            if isinstance(raw.get(key), (int, float)):
                out["sensors"][label] = raw[key]
        return out

    for key, comp in raw.items():
        if not isinstance(comp, dict):
            continue
        kind, _, idx = key.partition(":")
        try:
            index = int(idx)
        except ValueError:
            index = 0
        if kind == "switch":
            item = {"index": index, "on": bool(comp.get("on", comp.get("output")))}
            if comp.get("apower") is not None:
                item["apower"] = comp["apower"]
            if comp.get("atotal") is not None:
                item["atotal"] = comp["atotal"]
            out["relays"].append(item)
        elif kind in ("light", "dimmer"):
            item = {"index": index, "on": bool(comp.get("on"))}
            if comp.get("brightness") is not None:
                item["brightness"] = comp["brightness"]
            if comp.get("rgb"):
                item["rgb"] = comp["rgb"]
            out["lights"].append(item)
        elif kind == "cover":
            out["covers"].append({
                "index": index,
                "state": _COVER_STATE.get(str(comp.get("state", "")),
                                          str(comp.get("state", "?"))),
                "position": comp.get("position", comp.get("current_pos")),
                "apower": comp.get("apower"),
            })
        elif kind in ("pm", "em"):
            out["meters"].append({
                "index": index,
                "power": comp.get("apower", comp.get("a_total")),
                "energy": comp.get("atotal", comp.get("a_total")),
                "voltage": comp.get("voltage"),
            })
        elif kind == "temperature" and comp.get("tC") is not None:
            out["sensors"]["temperature"] = comp["tC"]
        elif kind == "humidity" and comp.get("rh") is not None:
            out["sensors"]["humidity"] = comp["rh"]
        elif kind == "battery":
            out["sensors"]["battery"] = comp.get("value")
    return out


def classify_kind(status: Dict[str, Any], model: str = "") -> str:
    """Component-driven device kind; model string only breaks ties."""
    kinds = set()
    if status.get("relays"):
        kinds.add("relay")
    if status.get("lights"):
        model_l = (model or "").lower()
        kinds.add("rgbw" if ("rgbw" in model_l or "color" in model_l) else "dimmer")
    if status.get("covers"):
        kinds.add("cover")
    if status.get("meters") and not status.get("relays"):
        kinds.add("meter")
    if status.get("sensors") and len(kinds) == 0:
        kinds.add("sensor")
    if not kinds:
        return "unknown"
    return next(iter(kinds)) if len(kinds) == 1 else "mixed"
