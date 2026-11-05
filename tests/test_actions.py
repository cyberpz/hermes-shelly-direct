"""Action layer end-to-end against stub devices (discovery monkeypatched)."""

import json

import shelly_core.discovery as discovery_mod
from shelly_core import actions
from shelly_core.actions import merged_cfg

from stub_shelly import _Gen1Handler, _Gen3Handler, start_stub

CFG = merged_cfg({"timeout_ms": 1500})


def _use_stubs(monkeypatch, gen1_port, gen3_port):
    hits = [
        {"ip": f"127.0.0.1:{gen1_port}", "mac": "112233445566",
         "id": "shelly-stub-g1", "gen": 1, "model": "SHSW-21", "fw": "", "auth": False},
        {"ip": f"127.0.0.1:{gen3_port}", "mac": "AABBCCDDEEFF",
         "id": "shellyplus2pm-stub", "gen": 3, "model": "ShellyPlus2PM",
         "fw": "", "auth": False},
    ]
    monkeypatch.setattr(discovery_mod, "_udp_probe", lambda targets, t: hits)


def test_discover_populates_inventory(monkeypatch):
    s1, p1 = start_stub(_Gen1Handler)
    s3, p3 = start_stub(_Gen3Handler)
    _use_stubs(monkeypatch, p1, p3)
    try:
        result = actions.act_discover(CFG)
        assert result["ok"] and result["count"] == 2
        names = {d["name"] for d in result["devices"]}
        assert {"Stub Gen1", "Stub Gen3"} <= names
        listed = actions.act_list(CFG)
        assert listed["count"] == 2
    finally:
        s1.shutdown()
        s3.shutdown()


def test_switch_on_with_verify(monkeypatch):
    s1, p1 = start_stub(_Gen1Handler)
    s3, p3 = start_stub(_Gen3Handler)
    _use_stubs(monkeypatch, p1, p3)
    _Gen1Handler.state["relays"] = [{"ison": False}]
    try:
        actions.act_discover(CFG)
        result = actions.act_switch("stub gen1", "on", 0, CFG)
        assert result["ok"] and result["verified"] is True
        assert result["state"]["relays"][0]["on"] is True
        result = actions.act_switch("stub gen1", "off", 0, CFG)
        assert result["verified"] is True
    finally:
        s1.shutdown()
        s3.shutdown()


def test_cover_position(monkeypatch):
    s1, p1 = start_stub(_Gen1Handler)
    s3, p3 = start_stub(_Gen3Handler)
    _use_stubs(monkeypatch, p1, p3)
    _Gen3Handler.state["cover:0"] = {"state": "stopped", "apower": 0, "position": 100}
    try:
        actions.act_discover(CFG)
        result = actions.act_cover("stub gen3", "open", None, 0, CFG)
        assert result["ok"] and result["state"]["covers"][0]["state"] == "open"
        result = actions.act_cover("stub gen3", None, 30, 0, CFG)
        assert result["state"]["covers"][0]["position"] == 30
    finally:
        s1.shutdown()
        s3.shutdown()


def test_meter_falls_back_to_relay_power(monkeypatch):
    s1, p1 = start_stub(_Gen1Handler)
    s3, p3 = start_stub(_Gen3Handler)
    _use_stubs(monkeypatch, p1, p3)
    try:
        actions.act_discover(CFG)
        result = actions.act_meter("stub gen1", CFG)
        assert result["ok"] and result["meters"][0]["power"] == 61.2
        result = actions.act_meter("stub gen3", CFG)
        assert result["meters"][0]["power"] == 61.2
    finally:
        s1.shutdown()
        s3.shutdown()


def test_unknown_device_error_shape():
    result = actions.act_status("does-not-exist", CFG)
    assert result["ok"] is False and "error" in result


def test_tool_handler_returns_json_never_raises(monkeypatch):
    # no stubs running: every device call must degrade to JSON errors
    from shelly_core import inventory as inv_mod
    inv_mod.save({"FF": {"mac": "FF", "name": "ghost", "ip": "127.0.0.1",
                         "id": "", "model": "", "gen": 2, "kind": "relay",
                         "online": False, "channels": [], "last_seen": None}})
    result = actions.act_status("ghost", CFG)
    assert result["ok"] is False
    assert json.dumps(result)  # serializable
