"""Fast status polling must heal the online flag on real reads."""

from shelly_core import actions, inventory
from shelly_core.actions import merged_cfg

CFG = merged_cfg({"timeout_ms": 500})


def _seed(online):
    return {"AABB": {"mac": "AABB", "id": "", "name": "Lamp", "alias": "",
                     "model": "", "gen": 2, "ip": "10.0.0.2", "kind": "relay",
                     "online": online, "channels": [], "last_seen": None}}


def test_fast_status_heals_stale_offline(monkeypatch):
    inventory.save(_seed(online=False))
    monkeypatch.setattr(actions.ShellyClient, "get_status",
                        lambda self, gen: {"switch:0": {"on": False}})
    r = actions.act_status_fast("AABB", CFG)
    assert r["ok"] and r["device"]["online"] is True
    assert inventory.load()["AABB"]["online"] is True


def test_fast_status_marks_dead_device_offline(monkeypatch):
    inventory.save(_seed(online=True))
    monkeypatch.setattr(actions.ShellyClient, "get_status",
                        lambda self, gen: {"error": "timeout"})
    r = actions.act_status_fast("AABB", CFG)
    assert not r["ok"]
    assert inventory.load()["AABB"]["online"] is False
