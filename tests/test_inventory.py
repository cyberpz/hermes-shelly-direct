"""Inventory: MAC-keyed storage, merge semantics, resolution."""

from shelly_core import inventory


def _dev(mac, name, ip="192.168.1.50", **kw):
    return {"mac": mac, "name": name, "ip": ip, "id": f"dev-{mac}",
            "model": kw.get("model", ""), "gen": kw.get("gen", 2)}


def test_upsert_and_persistence_roundtrip():
    inv = inventory.upsert({}, [_dev("AABBCCDDEEFF", "Office")])
    inventory.save(inv)
    loaded = inventory.load()
    assert loaded["AABBCCDDEEFF"]["name"] == "Office"


def test_upsert_preserves_existing_name_on_empty_update():
    inv = inventory.upsert({}, [_dev("AA", "Kitchen")])
    inv = inventory.upsert(inv, [{"mac": "AA", "name": "", "ip": "10.0.0.9"}])
    assert inv["AA"]["name"] == "Kitchen"
    assert inv["AA"]["ip"] == "10.0.0.9"


def test_resolve_exact_ip_mac_id():
    inv = {"AA": _dev("AA", "Office Light", ip="1.2.3.4")}
    assert inventory.resolve(inv, "1.2.3.4")[0] is inv["AA"]
    assert inventory.resolve(inv, "aa")[0] is inv["AA"]
    assert inventory.resolve(inv, "dev-aa")[0] is inv["AA"]


def test_resolve_name_substring_and_ambiguity():
    inv = {"AA": _dev("AA", "Office Light"), "BB": _dev("BB", "Office Desk")}
    assert inventory.resolve(inv, "office light")[0] is inv["AA"]
    assert inventory.resolve(inv, "desk")[0] is inv["BB"]
    dev, cands = inventory.resolve(inv, "office")
    assert dev is None and len(cands) == 2
    assert inventory.resolve(inv, "nonexistent")[0] is None


def test_resolve_accent_insensitive():
    inv = {"AA": _dev("AA", "Cucina Ufficio")}
    assert inventory.resolve(inv, "cucina")[0] is inv["AA"]


def test_public_view_shape():
    view = inventory.public_view(_dev("AA", "X"))
    for key in ("mac", "id", "name", "model", "gen", "ip", "kind",
                "online", "channels", "last_seen"):
        assert key in view
