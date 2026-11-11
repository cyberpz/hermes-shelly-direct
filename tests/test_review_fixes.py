"""Review fixes: skill path, sweep target policy, settings parsing."""

import json
import sys
import types
from pathlib import Path

import pytest

from shelly_core import actions, discovery, inventory
from shelly_core.actions import merged_cfg

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CFG = merged_cfg({"timeout_ms": 500})


# ---------------------------------------------------------------- fix 1: skill
def _fake_ctx():
    reg = {"tools": [], "skills": []}

    class Ctx:
        def register_tool(self, **kw):
            reg["tools"].append(kw["name"])

        def register_skill(self, name, path):
            p = Path(path)
            if not p.exists():
                raise FileNotFoundError(f"SKILL.md not found at {p}")
            reg["skills"].append((name, str(p)))

        def register_cli_command(self, **kw):
            raise RuntimeError("cli not available in host mode")

    return Ctx(), reg


def test_register_skill_passes_path_not_text():
    mod = __import__("importlib").import_module("__init__")
    ctx, reg = _fake_ctx()
    mod.register(ctx)
    assert reg["skills"], "bundled skill was not registered"
    name, path = reg["skills"][0]
    assert name == "shelly-direct"
    assert path.endswith("SKILL.md") and Path(path).exists()
    assert reg["tools"] == ["shelly"]


# ------------------------------------------------------- fix 2: sweep policy
@pytest.mark.parametrize("cidr", [
    "8.8.8.0/24",          # public
    "1.1.1.0/24",          # public
    "127.0.0.0/24",        # loopback
    "169.254.0.0/24",      # link-local / APIPA
    "0.0.0.0/24",          # unspecified
    "224.0.0.0/24",        # multicast
])
def test_expand_hosts_refuses_non_lan(cidr):
    assert discovery.expand_hosts([cidr]) == []


@pytest.mark.parametrize("cidr", ["192.168.1.0/24", "10.10.10.0/24", "172.16.5.0/24"])
def test_expand_hosts_allows_private_lan(cidr):
    hosts = discovery.expand_hosts([cidr])
    assert 250 <= len(hosts) <= 254
    assert all(discovery._target_allowed(h) for h in hosts)


def test_plain_public_ip_refused():
    assert discovery.expand_hosts(["8.8.8.8"]) == []
    assert discovery.expand_hosts(["192.168.1.10"]) == ["192.168.1.10"]


def test_model_sweep_ignored_without_optin(monkeypatch):
    inventory.save({"AABB": {"mac": "AABB", "id": "", "name": "Lamp", "alias": "",
                             "model": "", "gen": 2, "ip": "10.0.0.2", "kind": "relay",
                             "online": True, "channels": [], "last_seen": None}})
    seen = {}

    def fake_discover(**kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(discovery, "discover", fake_discover)
    mod = __import__("importlib").import_module("__init__")
    handler = mod._make_handler(None)
    out = json.loads(handler({"action": "discover", "subnet": "8.8.8.0/24"}))
    assert out["ok"] is True
    assert "subnet ignored" in out.get("note", "")
    assert seen.get("subnet", "") == "", "model-supplied subnet must not reach discovery"


def test_model_sweep_honoured_when_enabled(monkeypatch):
    seen = {}

    def fake_discover(**kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(discovery, "discover", fake_discover)
    cfg = dict(CFG, allow_model_sweep=True)
    mod = __import__("importlib").import_module("__init__")
    monkeypatch.setattr(mod, "merged_cfg", lambda s=None: cfg)
    handler = mod._make_handler(None)
    json.loads(handler({"action": "discover", "subnet": "192.168.1.0/24"}))
    assert seen.get("subnet") == "192.168.1.0/24"


# ---------------------------------------------------- fix 3: dashboard settings
def test_dashboard_settings_uses_hermes_yaml_and_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "plugins:\n  entries:\n    shelly-direct:\n      settings:\n"
        "        timeout_ms: 1234\n        extra_hosts: ['10.9.9.0/24']\n"
        "        allow_model_sweep: true\n"
    )
    consts = types.ModuleType("hermes_constants")
    consts.get_hermes_home = lambda: home
    yml = types.ModuleType("hermes_yaml")
    try:
        import ruamel.yaml  # noqa: F401

        def _safe_load(text):
            from ruamel.yaml import YAML
            return YAML(typ="safe").load(text)
    except Exception:  # pragma: no cover
        pytest.skip("no yaml implementation available")
    yml.safe_load = _safe_load
    monkeypatch.setitem(sys.modules, "hermes_constants", consts)
    monkeypatch.setitem(sys.modules, "hermes_yaml", yml)

    sys.path.insert(0, str(PLUGIN_ROOT))
    try:
        api = __import__("importlib").import_module("dashboard.plugin_api")
    finally:
        sys.path.pop(0)
    settings = api._settings()
    assert settings["timeout_ms"] == 1234
    assert settings["extra_hosts"] == ["10.9.9.0/24"]
    assert settings["allow_model_sweep"] is True
