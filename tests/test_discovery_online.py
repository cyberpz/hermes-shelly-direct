"""Zero-hit discovery must not mark the known fleet offline (blocked UDP)."""

from shelly_core import actions, inventory
from shelly_core.actions import merged_cfg

CFG = merged_cfg({"timeout_ms": 500})


def test_zero_hit_discovery_keeps_online_state(monkeypatch):
    inventory.save({"AABB": {"mac": "AABB", "id": "", "name": "Lamp", "alias": "",
                             "model": "", "gen": 2, "ip": "10.0.0.2", "kind": "relay",
                             "online": True, "channels": [], "last_seen": None}})
    monkeypatch.setattr(actions.discovery, "_udp_probe", lambda targets, t: [])
    result = actions.act_discover(CFG)  # no subnet, no extra_hosts: UDP-only
    assert result["ok"]
    assert inventory.load()["AABB"]["online"] is True, \
        "blocked UDP discovery must not demote known devices to offline"


def test_sweep_discovery_does_demote_missing(monkeypatch):
    inventory.save({"AABB": {"mac": "AABB", "id": "", "name": "Lamp", "alias": "",
                             "model": "", "gen": 2, "ip": "10.0.0.2", "kind": "relay",
                             "online": True, "channels": [], "last_seen": None}})
    monkeypatch.setattr(actions.discovery, "_udp_probe", lambda targets, t: [])
    monkeypatch.setattr(actions.discovery, "_tcp_open", lambda ip, port=80, timeout=0.15: False)
    monkeypatch.setattr(actions.discovery, "expand_hosts", lambda entries: ["10.0.0.9"])
    actions.act_discover(CFG, subnet="10.0.0.0/24")
    assert inventory.load()["AABB"]["online"] is False, \
        "an executed sweep that misses the device must mark it offline"
