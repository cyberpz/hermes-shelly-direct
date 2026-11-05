"""Protocol layer: gen detection, normalization, classification."""

from shelly_core.client import ShellyClient, classify_kind, normalize_status

from stub_shelly import _Gen1Handler, _Gen3Handler, start_stub


def test_gen1_probe_and_status():
    server, port = start_stub(_Gen1Handler)
    try:
        client = ShellyClient(f"127.0.0.1:{port}", timeout=2)
        # NOTE: client targets ip:port as one host string — works for stubs
        info = client.probe()
        assert info["gen"] == 1
        status = normalize_status(1, client.get_status(1))
        assert status["relays"][0]["on"] is False
        assert status["lights"][0]["brightness"] == 50
        assert status["covers"][0]["state"] == "stop"
        assert status["meters"][0]["power"] == 61.2
        assert status["sensors"]["temperature"] == 21.5
    finally:
        server.shutdown()


def test_gen3_probe_status_and_switch():
    server, port = start_stub(_Gen3Handler)
    try:
        client = ShellyClient(f"127.0.0.1:{port}", timeout=2)
        info = client.probe()
        assert info["gen"] == 3 and info["model"] == "ShellyPlus2PM"
        assert client.device_info(3)["name"] == "Stub Gen3"
        assert client.device_info(3)["mac"] == ""
        assert client.set_switch(3, 0, "on").get("ok") is True
        status = normalize_status(3, client.get_status(3))
        assert status["relays"][0]["on"] is True
        assert status["relays"][0]["apower"] == 42.1
        assert status["meters"][0]["voltage"] == 234.1
        assert status["sensors"]["humidity"] == 45
    finally:
        server.shutdown()


def test_gen3_cover():
    server, port = start_stub(_Gen3Handler)
    try:
        client = ShellyClient(f"127.0.0.1:{port}", timeout=2)
        assert client.set_cover(3, 0, op="open").get("ok") is True
        status = normalize_status(3, client.get_status(3))
        assert status["covers"][0]["state"] == "open"
        client.set_cover(3, 0, position=40)
        status = normalize_status(3, client.get_status(3))
        assert status["covers"][0]["position"] == 40
    finally:
        server.shutdown()


def test_offline_device_returns_error_not_exception():
    client = ShellyClient("127.0.0.1:1", timeout=0.3)
    assert "error" in client.probe()
    assert "error" in client.get_status(2)


def test_normalize_garbage_is_safe():
    assert normalize_status(2, {"error": "boom"})["relays"] == []
    assert normalize_status(1, "not a dict")["sensors"] == {}
    assert normalize_status(3, {"weird:9": "string"})["relays"] == []


def test_classify_kind():
    assert classify_kind({"relays": [{"index": 0}]}) == "relay"
    assert classify_kind({"covers": [{"index": 0}]}) == "cover"
    assert classify_kind({"meters": [{"index": 0}]}) == "meter"
    assert classify_kind({"sensors": {"temperature": 1}}) == "sensor"
    assert classify_kind({"lights": [{"index": 0}]}, "Shelly Color Bulb") == "rgbw"
    assert classify_kind({"relays": [1], "covers": [1]}) == "mixed"
    assert classify_kind({}) == "unknown"
