"""MAC-keyed device inventory with durable JSON storage.

MAC is the stable identity (IPs are ephemeral DHCP leases). The file lives in
the Hermes plugin-data directory so it survives plugin updates and is shared
between the agent tool and the dashboard API process.
"""

from __future__ import annotations

import json
import os
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PLUGIN_ID = "shelly-direct"
_SAVE_LOCK = threading.Lock()


def data_dir() -> Path:
    """Plugin data dir via Hermes when available; env override for tests."""
    override = os.environ.get("SHELLY_DIRECT_DATA")
    if override:
        path = Path(override)
    else:
        try:
            from plugins.plugin_storage import plugin_data_dir
            path = Path(plugin_data_dir(PLUGIN_ID))
        except Exception:  # noqa: BLE001 — standalone/tests
            path = Path.home() / ".hermes" / "plugin-data" / PLUGIN_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def _inventory_file() -> Path:
    return data_dir() / "inventory.json"


def _order_file() -> Path:
    return data_dir() / "order.json"


def load_order() -> List[str]:
    try:
        data = json.loads(_order_file().read_text())
        return [str(m).upper() for m in data.get("order", [])]
    except (OSError, ValueError):
        return []


def save_order(macs: List[str]) -> None:
    _order_file().write_text(json.dumps({"order": [str(m).upper() for m in macs]}))


def load() -> Dict[str, Dict[str, Any]]:
    try:
        raw = json.loads(_inventory_file().read_text())
        devices = raw.get("devices", {}) if isinstance(raw, dict) else {}
        return {str(k).upper(): v for k, v in devices.items()}
    except (OSError, ValueError):
        return {}


def save(inventory: Dict[str, Dict[str, Any]]) -> None:
    # unique tmp name + lock: the dashboard fetches many device statuses
    # concurrently and a shared tmp path races (ENOENT on replace)
    with _SAVE_LOCK:
        tmp = _inventory_file().with_suffix(f".json.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"devices": inventory,
                                   "updated": _now()},
                                  ensure_ascii=False, indent=1))
        tmp.replace(_inventory_file())


def _now() -> str:
    # timezone-aware ISO: dashboard timeAgo() needs the offset
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def upsert(inventory: Dict[str, Dict[str, Any]],
           discovered: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Merge discovery results, keeping user-visible fields (name) and filling
    gaps. Devices keyed by MAC; MAC-less hits keyed by IP."""
    now = _now()
    ip_index = {d.get("ip"): k for k, d in inventory.items()
                if d.get("ip") and not d.get("mac")}
    for dev in discovered:
        mac = str(dev.get("mac", "")).replace(":", "").upper()
        key = mac or f"ip:{dev.get('ip', '')}"
        # a sweep hit that finally yielded its MAC migrates the old ip-key record
        if mac and dev.get("ip") in ip_index:
            old_key = ip_index[dev["ip"]]
            if old_key != key:
                inventory[key] = inventory.pop(old_key)
        existing = inventory.get(key, {})
        record = {
            "mac": mac,
            "id": dev.get("id") or existing.get("id", ""),
            "name": dev.get("name") or existing.get("name", ""),
            "alias": existing.get("alias", ""),  # user-set name always wins
            "model": dev.get("model") or existing.get("model", ""),
            "gen": int(dev.get("gen") or existing.get("gen", 1)),
            "ip": dev.get("ip") or existing.get("ip", ""),
            "kind": dev.get("kind") or existing.get("kind", "unknown"),
            "online": bool(dev.get("online", True)),
            "channels": dev.get("channels") or existing.get("channels", []),
            "last_seen": now if dev.get("online", True) else existing.get("last_seen"),
        }
        inventory[key] = record
    return inventory


def _norm(text: Any) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return " ".join(text.lower().split())


def resolve(inventory: Dict[str, Dict[str, Any]],
            query: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Resolve a user query to one device: MAC/IP/id first, then exact name,
    then all-words substring. Returns (device, candidates) — device is None
    when zero or several matched; candidates lists near-misses for hints."""
    if not query:
        return None, []
    q = _norm(query)
    compact = "".join(ch for ch in str(query).upper() if ch.isalnum())
    for dev in inventory.values():
        if (dev.get("ip") == query
                or (dev.get("mac") and dev["mac"] == compact)
                or _norm(dev.get("id", "")) == q):
            return dev, []
    exact = [d for d in inventory.values()
             if d.get("alias") and _norm(d["alias"]) == q]
    if not exact:
        exact = [d for d in inventory.values()
                 if d.get("name") and _norm(d["name"]) == q]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, exact
    words = q.split()
    subs = [d for d in inventory.values()
            if d.get("alias") and all(w in _norm(d["alias"]) for w in words)]
    if not subs:
        subs = [d for d in inventory.values()
                if d.get("name") and all(w in _norm(d["name"]) for w in words)]
    if len(subs) == 1:
        return subs[0], []
    return None, subs


def display_name(dev: Dict[str, Any]) -> str:
    return dev.get("alias") or dev.get("name") or dev.get("id") or dev.get("mac") or dev.get("ip", "?")


def public_view(dev: Dict[str, Any]) -> Dict[str, Any]:
    """Device shape served to the dashboard and tool `list`."""
    return {
        "mac": dev.get("mac", ""),
        "id": dev.get("id", ""),
        "name": dev.get("name", ""),
        "alias": dev.get("alias", ""),
        "display": display_name(dev),
        "mapped": bool(dev.get("alias") or dev.get("name")),
        "model": dev.get("model", ""),
        "gen": dev.get("gen", 1),
        "ip": dev.get("ip", ""),
        "kind": dev.get("kind", "unknown"),
        "online": bool(dev.get("online")),
        "channels": dev.get("channels", []),
        "last_seen": dev.get("last_seen"),
    }
