"""Action handlers shared by the agent tool and the dashboard API.

Every handler returns a plain dict (the tool layer json.dumps it; the FastAPI
layer returns it directly). Nothing here raises: device offline, ambiguous
name, unsupported verb — all come back as ``{"ok": false, "error": "..."}``.

Write commands follow verify-after-write: read the state back, retry once on
mismatch (flaky IoT Wi-Fi is normal life), report the actual state.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from . import discovery, inventory
from .client import ShellyClient, classify_kind, normalize_status

DEFAULT_CFG = {
    "timeout_ms": 3000,
    "verify_writes": True,
    "extra_hosts": [],
    "auth_user": "",
    "auth_password": "",
}


def merged_cfg(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CFG)
    for key in cfg:
        if settings and settings.get(key) not in (None, ""):
            cfg[key] = settings[key]
    cfg["timeout"] = max(0.5, int(cfg["timeout_ms"]) / 1000.0)
    return cfg


def _client(dev: Dict[str, Any], cfg: Dict[str, Any]) -> ShellyClient:
    return ShellyClient(dev["ip"], timeout=cfg["timeout"],
                        auth_user=cfg["auth_user"],
                        auth_password=cfg["auth_password"])


def _refresh_inventory(cfg: Dict[str, Any],
                       subnet: str = "") -> Dict[str, Dict[str, Any]]:
    found = discovery.discover(
        timeout_s=min(2.0, cfg["timeout"]),
        extra_hosts=cfg["extra_hosts"], http_timeout=cfg["timeout"],
        auth_user=cfg["auth_user"], auth_password=cfg["auth_password"],
        subnet=subnet)
    inv = inventory.load()
    for hit in found:
        hit.setdefault("online", True)
    inv = inventory.upsert(inv, found)
    known_ips = {h["ip"] for h in found}
    for record in inv.values():
        if record.get("ip") and record["ip"] not in known_ips:
            record["online"] = False
    inventory.save(inv)
    return inv


def _resolve_or_discover(query: str,
                         cfg: Dict[str, Any]) -> tuple:
    """Resolve against cache; on a miss run one live discovery and retry —
    first-run UX: 'turn on the office light' works right after install."""
    inv = inventory.load()
    dev, cands = inventory.resolve(inv, query)
    if dev is None:
        inv = _refresh_inventory(cfg)
        dev, cands = inventory.resolve(inv, query)
    return dev, cands


def _fetch_status(dev: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    client = _client(dev, cfg)
    info = client.probe()
    if "error" in info:
        return {"error": f"device unreachable at {dev.get('ip')} "
                         f"(battery models may be asleep)"}
    gen = info["gen"]
    raw = client.get_status(gen)
    if "error" in raw:
        return {"error": raw["error"]}
    status = normalize_status(gen, raw)
    channels = ([{"index": r["index"], "type": "relay"} for r in status["relays"]]
                + [{"index": l["index"], "type": "light"} for l in status["lights"]]
                + [{"index": c["index"], "type": "cover"} for c in status["covers"]])
    dev["gen"] = gen
    dev["kind"] = classify_kind(status, dev.get("model", ""))
    dev["channels"] = channels
    dev["online"] = True
    return {"gen": gen, "status": status}


# ------------------------------------------------------------------- actions
def act_discover(cfg: Dict[str, Any], subnet: str = "") -> Dict[str, Any]:
    inv = _refresh_inventory(cfg, subnet=subnet)
    devices = [inventory.public_view(d) for d in inv.values()]
    return {"ok": True, "count": len(devices), "devices": devices}


def act_list(cfg: Dict[str, Any]) -> Dict[str, Any]:
    devices = [inventory.public_view(d) for d in inventory.load().values()]
    devices.sort(key=lambda d: (d.get("name") or d.get("id") or d.get("mac", "")).lower())
    return {"ok": True, "count": len(devices), "devices": devices}


def act_status(device: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    dev, cands = _resolve_or_discover(device, cfg)
    if dev is None:
        hint = ("ambiguous, candidates: "
                + ", ".join(d.get("name") or d.get("id", "?") for d in cands[:8])
                if cands else f"no device matches '{device}'")
        return {"ok": False, "error": hint}
    result = _fetch_status(dev, cfg)
    if "error" in result:
        dev["online"] = False
        inventory.save(inventory.load() | {dev.get("mac") or f"ip:{dev['ip']}": dev})
        return {"ok": False, "error": result["error"], "device": inventory.public_view(dev)}
    inventory.save(inventory.load() | {dev.get("mac") or f"ip:{dev['ip']}": dev})
    return {"ok": True, "device": inventory.public_view(dev), "status": result["status"]}


def _write_with_verify(dev, cfg, write_fn, readback_fn, want) -> Dict[str, Any]:
    """write_fn() sends the command; readback_fn() returns the observed value
    to compare against ``want`` (None disables verification)."""
    client = _client(dev, cfg)
    gen = dev.get("gen", 1)
    result = write_fn(client, gen)
    ok = "error" not in result
    verified: Optional[bool] = None
    retried = False
    if ok and cfg["verify_writes"] and want is not None:
        time.sleep(0.25)
        observed = readback_fn(client, gen)
        if observed != want:
            retried = True
            write_fn(client, gen)
            time.sleep(0.25)
            observed = readback_fn(client, gen)
        verified = observed == want
    return {"ok": ok, "verified": verified, "retried": retried,
            "error": result.get("error")}


def act_switch(device: str, action: str, channel: int,
               cfg: Dict[str, Any]) -> Dict[str, Any]:
    dev, cands = _resolve_or_discover(device, cfg)
    if dev is None:
        return {"ok": False, "error": f"no device matches '{device}'"
                    + (f" (candidates: {', '.join(d.get('name','?') for d in cands[:5])})"
                       if cands else "")}
    info = _fetch_status(dev, cfg)
    if "error" in info:
        return {"ok": False, "error": info["error"]}
    gen = info["gen"]

    def write(client, g):
        return client.set_switch(g, channel, action)

    def readback(client, g):
        status = normalize_status(g, client.get_status(g))
        for relay in status["relays"]:
            if relay["index"] == channel:
                return relay["on"]
        return None

    want = {"on": True, "off": False}.get(action)
    result = _write_with_verify(dev, cfg, write, readback, want)
    final = _fetch_status(dev, cfg)
    result["state"] = final.get("status") if "error" not in final else None
    result["device"] = inventory.public_view(dev)
    inventory.save(inventory.load() | {dev.get("mac") or f"ip:{dev['ip']}": dev})
    return result


def act_set(device: str, channel: int, brightness: Optional[int],
            rgb: Optional[str], white: Optional[int],
            cfg: Dict[str, Any]) -> Dict[str, Any]:
    if brightness is None and rgb is None and white is None:
        return {"ok": False, "error": "set needs brightness, rgb or white"}
    dev, _ = _resolve_or_discover(device, cfg)
    if dev is None:
        return {"ok": False, "error": f"no device matches '{device}'"}
    info = _fetch_status(dev, cfg)
    if "error" in info:
        return {"ok": False, "error": info["error"]}
    gen = info["gen"]

    def write(client, g):
        return client.set_light(g, channel, on="on" if brightness else None,
                                brightness=brightness, rgb=rgb, white=white)

    def readback(client, g):
        status = normalize_status(g, client.get_status(g))
        for light in status["lights"]:
            if light["index"] == channel:
                if brightness is not None:
                    return light.get("brightness")
                return True
        return None

    result = _write_with_verify(dev, cfg, write, readback,
                                brightness if brightness is not None else True)
    final = _fetch_status(dev, cfg)
    result["state"] = final.get("status") if "error" not in final else None
    result["device"] = inventory.public_view(dev)
    return result


def act_cover(device: str, op: Optional[str], position: Optional[int],
              channel: int, cfg: Dict[str, Any]) -> Dict[str, Any]:
    if op is None and position is None:
        return {"ok": False, "error": "cover needs op=open|close|stop or position=0-100"}
    dev, _ = _resolve_or_discover(device, cfg)
    if dev is None:
        return {"ok": False, "error": f"no device matches '{device}'"}
    info = _fetch_status(dev, cfg)
    if "error" in info:
        return {"ok": False, "error": info["error"]}
    gen = info["gen"]

    def write(client, g):
        return client.set_cover(g, channel, op=op, position=position)

    result = write(_client(dev, cfg), gen)
    time.sleep(0.25)
    final = _fetch_status(dev, cfg)
    return {"ok": "error" not in result, "error": result.get("error"),
            "state": final.get("status") if "error" not in final else None,
            "device": inventory.public_view(dev)}


def act_meter(device: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    result = act_status(device, cfg)
    if not result.get("ok"):
        return result
    status = result["status"]
    meters = status.get("meters") or []
    if not meters:  # PM wired as relay: power rides on the relay entries
        meters = [{"index": r["index"], "power": r.get("apower"),
                   "energy": r.get("atotal")}
                  for r in status.get("relays", []) if r.get("apower") is not None]
    return {"ok": True, "device": result["device"], "meters": meters}


def act_sensor(device: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    result = act_status(device, cfg)
    if not result.get("ok"):
        return result
    return {"ok": True, "device": result["device"],
            "sensors": result["status"].get("sensors", {})}
