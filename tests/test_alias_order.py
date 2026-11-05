"""Alias/rename, manual ordering and fast status path."""

from shelly_core import actions, inventory
from shelly_core.actions import merged_cfg

CFG = merged_cfg({"timeout_ms": 1500})


def _seed():
    return {
        "AABB": {"mac": "AABB", "id": "", "name": "Zeta Lamp", "alias": "",
                 "model": "", "gen": 2, "ip": "10.0.0.2", "kind": "relay",
                 "online": True, "channels": [], "last_seen": None},
        "CCDD": {"mac": "CCDD", "id": "", "name": "", "alias": "",
                 "model": "", "gen": 3, "ip": "10.0.0.3", "kind": "relay",
                 "online": True, "channels": [], "last_seen": None},
    }


def test_rename_sets_alias_and_display():
    inventory.save(_seed())
    r = actions.act_rename("CCDD", "Lavatrice", CFG)
    assert r["ok"] and r["device"]["alias"] == "Lavatrice"
    assert r["device"]["display"] == "Lavatrice" and r["device"]["mapped"]
    listed = actions.act_list(CFG)
    lav = [d for d in listed["devices"] if d["mac"] == "CCDD"][0]
    assert lav["display"] == "Lavatrice"


def test_rename_by_ip_and_unknown():
    inventory.save(_seed())
    assert actions.act_rename("10.0.0.2", "Lume", CFG)["ok"]
    assert not actions.act_rename("FF00", "x", CFG)["ok"]


def test_alias_wins_over_device_name_on_upsert():
    inventory.save(_seed())
    actions.act_rename("AABB", "La Mia Lampada", CFG)
    inventory.upsert(inventory.load(), [{"mac": "AABB", "name": "Zeta Lamp",
                                         "ip": "10.0.0.2"}])
    assert inventory.load()["AABB"]["alias"] == "La Mia Lampada"


def test_resolve_matches_alias():
    inv = _seed()
    inv["CCDD"]["alias"] = "Lavatrice"
    assert inventory.resolve(inv, "lavatrice")[0] is inv["CCDD"]
    assert inventory.resolve(inv, "lavat")[0] is inv["CCDD"]


def test_manual_order_persisted_and_applied():
    inventory.save(_seed())
    actions.act_rename("CCDD", "Lavatrice", CFG)
    actions.act_order(["CCDD", "AABB"], CFG)
    listed = actions.act_list(CFG)
    assert [d["mac"] for d in listed["devices"]] == ["CCDD", "AABB"]
    # without manual order, mapped sorts before unmapped
    inventory.save(_seed())  # fresh: CCDD unmapped again
    actions.act_order([], CFG)
    listed = actions.act_list(CFG)
    assert [d["mac"] for d in listed["devices"]] == ["AABB", "CCDD"]


def test_status_fast_uses_cached_gen(monkeypatch):
    inventory.save(_seed())
    calls = []
    monkeypatch.setattr(actions.ShellyClient, "probe",
                        lambda self: calls.append("probe") or {"error": "must not probe"})
    monkeypatch.setattr(actions.ShellyClient, "get_status",
                        lambda self, gen: calls.append("status") or {"switch:0": {"on": True}})
    r = actions.act_status_fast("AABB", CFG)
    assert r["ok"] and r["status"]["relays"][0]["on"] is True
    assert calls == ["status"]
