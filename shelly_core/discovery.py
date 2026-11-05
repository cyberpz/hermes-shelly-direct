"""Zero-config LAN discovery for Shelly devices.

Every Shelly firmware generation answers a UDP datagram on port 10100 with a
JSON blob (addr, mac, id, gen, model, fw, auth). One broadcast packet finds
everything on the local segment; ``extra_hosts`` covers routed/VLAN subnets
where broadcast cannot reach (UDP unicast probe per host instead).
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from .client import ShellyClient, friendly_model

DISCOVERY_PORT = 10100
_PROBE_PAYLOAD = b"GET /HTTP/1.0\r\n\r\n"
_MAX_CIDR_HOSTS = 1024  # refuse to scan absurd ranges


def _udp_probe(targets: List[str], timeout_s: float) -> List[Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.4)
    try:
        for target in targets:
            try:
                sock.sendto(_PROBE_PAYLOAD, (target, DISCOVERY_PORT))
            except OSError:
                continue
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(4096)
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            try:
                info = json.loads(data.decode("utf-8", "replace"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(info, dict):
                continue
            ip = info.get("addr") or addr[0]
            mac = str(info.get("mac", "")).replace(":", "").upper()
            key = mac or ip
            found[key] = {
                "ip": ip,
                "mac": mac,
                "id": info.get("id", ""),
                "gen": int(info.get("gen", 1) or 1),
                "model": info.get("model", ""),
                "fw": info.get("fw", ""),
                "auth": bool(info.get("auth")),
            }
    finally:
        sock.close()
    return list(found.values())


def _tcp_open(ip: str, port: int = 80, timeout: float = 0.15) -> bool:
    """Fast liveness gate so a /24 sweep costs seconds, not minutes."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((ip, port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def local_broadcasts() -> List[str]:
    """Directed broadcast addresses of local global-scope IPv4 interfaces
    (255.255.255.255 only egresses one interface on multi-homed hosts)."""
    import subprocess
    targets: List[str] = []
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"],
                             capture_output=True, text=True, timeout=2).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[2] == "brd":
                targets.append(parts[3])
    except Exception:  # noqa: BLE001 — non-Linux or no iproute2
        pass
    return targets


def expand_hosts(entries: List[str]) -> List[str]:
    """Accept plain IPs and CIDRs (prefix >= /22 only) from config."""
    hosts: List[str] = []
    for entry in entries or []:
        entry = str(entry).strip()
        if not entry:
            continue
        if "/" in entry:
            try:
                net = ipaddress.ip_network(entry, strict=False)
            except ValueError:
                continue
            if net.prefixlen < 22 or net.num_addresses > _MAX_CIDR_HOSTS:
                continue
            hosts.extend(str(h) for h in net.hosts())
        else:
            hosts.append(entry)
    return hosts


def enrich(device: Dict[str, Any], timeout: float,
           auth_user: str = "", auth_password: str = "",
           gate_tcp: bool = False) -> Dict[str, Any]:
    """Confirm gen/model/name with an HTTP probe (UDP hints can be stale).
    ``gate_tcp`` first checks port 80 — used for sweep candidates, where most
    IPs are empty addresses."""
    if gate_tcp and not _tcp_open(device["ip"]):
        device["online"] = False
        return device
    client = ShellyClient(device["ip"], timeout=timeout,
                          auth_user=auth_user, auth_password=auth_password)
    info = client.probe()
    if "error" not in info:
        device["gen"] = info["gen"]
        device["model"] = friendly_model(info["model"] or device.get("model", ""))
        device["fw"] = info["fw"] or device.get("fw", "")
        device["online"] = True
        info_extra = client.device_info(info["gen"])
        if info_extra.get("name"):
            device["name"] = info_extra["name"]
        if not device.get("mac"):
            device["mac"] = info.get("mac") or info_extra.get("mac", "")
        if not device.get("id"):
            device["id"] = info.get("id") or info_extra.get("id", "")
    else:
        device["online"] = False
    return device


def discover(timeout_s: float = 2.0, extra_hosts: List[str] | None = None,
             http_timeout: float = 3.0, auth_user: str = "",
             auth_password: str = "", subnet: str = "") -> List[Dict[str, Any]]:
    """Three discovery layers, cheapest first:
      1. UDP broadcast (255.255.255.255 + each local interface's directed
         broadcast) — instant, but blocked by some APs/IoT VLANs;
      2. extra_hosts from config (static IPs/CIDRs behind a router);
      3. explicit ``subnet`` CIDR sweep (opt-in TCP-gated HTTP probe) for
         networks where UDP is dead.
    Returns raw device dicts (inventory layer turns them into Devices)."""
    targets = ["255.255.255.255"] + local_broadcasts()
    hits = _udp_probe(targets, timeout_s)
    known_ips = {h["ip"] for h in hits}
    swept = False
    candidates = expand_hosts(extra_hosts or [])
    if subnet:
        candidates = expand_hosts([subnet]) + candidates
        swept = True
    for host in candidates:
        if host not in known_ips:
            hits.append({"ip": host, "mac": "", "id": "", "gen": 0,
                         "model": "", "fw": "", "auth": False})
            known_ips.add(host)
    gate = swept or bool(candidates)
    with ThreadPoolExecutor(max_workers=32) as pool:
        enriched = list(pool.map(
            lambda d: enrich(d, http_timeout, auth_user, auth_password,
                             gate_tcp=gate), hits))
    return [d for d in enriched if d.get("online")]
