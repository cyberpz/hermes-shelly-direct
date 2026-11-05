"""Invalid input hardening: bad CIDR, alias sanitisation."""

from shelly_core import actions, inventory
from shelly_core.actions import merged_cfg

CFG = merged_cfg({"timeout_ms": 500})


def _seed():
    return {"AABB": {"mac": "AABB", "id": "", "name": "Lamp", "alias": "",
                     "model": "", "gen": 2, "ip": "10.0.0.2", "kind": "relay",
                     "online": True, "channels": [], "last_seen": None}}


def test_invalid_subnet_rejected_without_touching_inventory(monkeypatch):
    inventory.save(_seed())
    calls = []
    monkeypatch.setattr(actions.discovery, "discover",
                        lambda **kw: calls.append(kw) or [])
    r = actions.act_discover(CFG, subnet="999.1.1.0/24")
    assert not r["ok"] and "invalid subnet" in r["error"]
    assert calls == [], "must not sweep on invalid subnet"
    assert inventory.load()["AABB"]["online"] is True


def test_invalid_subnet_does_not_demote_fleet(monkeypatch):
    inventory.save(_seed())
    monkeypatch.setattr(actions.discovery, "_udp_probe", lambda targets, t: [])
    # even if validation were bypassed, an empty expansion must not demote
    inv = actions._refresh_inventory(CFG, subnet="999.1.1.0/24")
    assert inv["AABB"]["online"] is True


def test_alias_sanitised():
    inventory.save(_seed())
    r = actions.act_rename("AABB", "<script>\x00alert(1)</script>", CFG)
    alias = r["device"]["alias"]
    assert "\x00" not in alias and len(alias) <= 64
    r2 = actions.act_rename("AABB", "A" * 500, CFG)
    assert len(r2["device"]["alias"]) == 64
