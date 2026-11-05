"""Stateful stub Shelly devices over http.server — Gen1 REST + Gen3 RPC."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class _Gen1Handler(BaseHTTPRequestHandler):
    state = {"relays": [{"ison": False}], "lights": [{"ison": True, "brightness": 50}],
             "rollers": [{"state": "stop", "current_pos": 0}],
             "meters": [{"power": 61.2, "energy": 1234.5}],
             "temperature": 21.5, "humidity": 43}

    def log_message(self, *a):  # silence
        pass

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/shelly":
            self._json({"type": "SHSW-21", "ver": "20231011-114218/v1.14.0"})
        elif url.path == "/settings":
            self._json({"name": "Stub Gen1"})
        elif url.path == "/status":
            self._json(type(self).state)
        elif url.path.startswith("/relay/"):
            idx = int(url.path.split("/")[2])
            turn = qs.get("turn", "toggle")
            cur = type(self).state["relays"][idx]["ison"]
            type(self).state["relays"][idx]["ison"] = \
                {"on": True, "off": False}.get(turn, not cur)
            self._json({"ison": type(self).state["relays"][idx]["ison"]})
        elif url.path.startswith("/light/"):
            idx = int(url.path.split("/")[2])
            light = type(self).state["lights"][idx]
            if "turn" in qs:
                light["ison"] = qs["turn"] == "on"
            if "brightness" in qs:
                light["brightness"] = int(qs["brightness"])
            if "rgb" in qs:
                light["rgb"] = qs["rgb"]
            self._json(dict(light))
        elif url.path.startswith("/roller/"):
            roller = type(self).state["rollers"][0]
            if qs.get("go") == "to_pos":
                roller["current_pos"] = int(qs["roller_pos"])
                roller["state"] = "stop"
            elif "go" in qs:
                roller["state"] = {"open": "open", "close": "close",
                                   "stop": "stop"}[qs["go"]]
            self._json(dict(roller))
        else:
            self._json({"error": "not found"}, 404)


class _Gen3Handler(BaseHTTPRequestHandler):
    state = {"switch:0": {"on": False, "apower": 42.1, "atotal": 10.5},
             "cover:0": {"state": "stopped", "apower": 0, "position": 100},
             "pm:0": {"apower": 61.2, "voltage": 234.1, "atotal": 88.0},
             "temperature:0": {"tC": 22.0}, "humidity:0": {"rh": 45}}

    def log_message(self, *a):
        pass

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self._dispatch()

    def do_POST(self):  # noqa: N802
        self._dispatch()

    def _dispatch(self):
        # Real Shelly Gen2/3 accept both GET and POST on /rpc/*
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        path = urlparse(self.path).path
        state = type(self).state
        if path == "/shelly":
            self._json({"gen": 3, "model": "ShellyPlus2PM", "fw": "1.0.0"})
        elif path == "/rpc/Shelly.GetStatus":
            self._json(dict(type(self).state))
        elif path == "/rpc/Shelly.GetDeviceInfo":
            self._json({"name": "Stub Gen3", "id": "shellyplus2pm-stub"})
        elif path == "/rpc/Switch.Set":
            key = f"switch:{body.get('id', 0)}"
            state.setdefault(key, {})["on"] = bool(body.get("on"))
            self._json({"ok": True})
        elif path.startswith("/rpc/Cover."):
            verb = path.rsplit(".", 1)[-1].lower()
            cover = state.setdefault("cover:0", {})
            if verb == "gotoposition":
                cover["position"] = body.get("pos")
                cover["state"] = "stopped"
            elif verb == "open":
                cover["state"] = "opened"
            elif verb == "close":
                cover["state"] = "closed"
            else:
                cover["state"] = "stopped"
            self._json({"ok": True})
        elif path == "/rpc/Light.Set":
            self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)


def start_stub(handler_cls) -> tuple:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]
