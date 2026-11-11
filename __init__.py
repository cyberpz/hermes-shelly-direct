"""Shelly Direct — Hermes plugin entry point.

Registers:
  * the ``shelly`` tool (agent-side control of LAN Shelly devices)
  * a bundled skill teaching the model the action vocabulary
  * ``hermes shelly discover|list|status`` CLI commands
  * (dashboard tab + REST API live under ./dashboard/, loaded by the dashboard)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

try:  # loaded as a Hermes plugin package (normal path)
    from .shelly_core import actions
    from .shelly_core.actions import merged_cfg
except ImportError:  # imported standalone (test runner with repo root on sys.path)
    from shelly_core import actions
    from shelly_core.actions import merged_cfg

log = logging.getLogger(__name__)

TOOL_SCHEMA = {
    "name": "shelly",
    "description": (
        "Control Shelly smart-home devices (Gen1/2/3) directly on the local "
        "network — no Home Assistant, no MQTT, no cloud. "
        "Workflow: run action='discover' once, then address devices by name, "
        "id, MAC or IP in the 'device' field. "
        "Actions: discover (scan LAN, refresh inventory), list (known devices), "
        "status (full state of one device), on/off/toggle (relays/plugs, "
        "optional channel), set (brightness 0-100, rgb '#RRGGBB', or white "
        "level on dimmers/RGB), cover (op=open|close|stop or position=0-100 "
        "for rollers), meter (live power W / energy kWh), sensor "
        "(temperature/humidity/battery). Writes are verified by reading the "
        "device back; 'verified: false' means the device did not confirm the "
        "command — report that honestly."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["discover", "list", "status", "on", "off", "toggle",
                         "set", "cover", "meter", "sensor", "rename"],
            },
            "device": {
                "type": "string",
                "description": "Device name (substring ok), id, MAC or IP. "
                               "Required for everything except discover/list.",
            },
            "channel": {
                "type": "integer",
                "description": "Channel/component index, default 0.",
                "default": 0,
            },
            "brightness": {"type": "integer", "minimum": 0, "maximum": 100},
            "rgb": {"type": "string", "description": "Hex color, e.g. '#ff8800'."},
            "white": {"type": "integer", "minimum": 0, "maximum": 100},
            "op": {"type": "string", "enum": ["open", "close", "stop"]},
            "position": {"type": "integer", "minimum": 0, "maximum": 100},
            "subnet": {
                "type": "string",
                "description": "discover only: CIDR to sweep when UDP broadcast "
                               "finds nothing (e.g. '192.168.1.0/24').",
            },
            "name": {
                "type": "string",
                "description": "rename only: local alias for the device "
                               "(takes precedence over the device's own name).",
            },
        },
        "required": ["action"],
    },
}


def _settings(ctx) -> dict:
    settings = {}
    for key in ("timeout_ms", "verify_writes", "extra_hosts", "auth_user"):
        try:
            value = ctx.get_config(key, default=None)
            if value is not None:
                settings[key] = value
        except Exception:  # noqa: BLE001
            pass
    try:  # secret values live in the Hermes secret store, never in config.yaml
        from agent.secret_scope import get_secret
        secret = get_secret("SHELLY_DIRECT_AUTH_PASSWORD")
        if secret:
            settings["auth_password"] = secret
    except Exception:  # noqa: BLE001 — no secret configured
        pass
    return settings


def _make_handler(ctx):
    def handle(args: dict, **_kwargs) -> str:
        try:
            cfg = merged_cfg(_settings(ctx))
            action = args.get("action", "list")
            device = str(args.get("device", "") or "")
            channel = int(args.get("channel", 0) or 0)
            if action == "discover":
                subnet = str(args.get("subnet", "") or "").strip()
                if subnet and not cfg.get("allow_model_sweep"):
                    # Model-chosen sweep ranges are opt-in: unmapped CIDRs from
                    # a prompt are a scanner waiting to happen.
                    result = actions.act_discover(cfg)
                    result["note"] = ("subnet ignored: sweeps picked by the model are disabled. "
                                      "Use the dashboard Discover field, or set "
                                      "allow_model_sweep: true in the plugin settings.")
                else:
                    result = actions.act_discover(cfg, subnet)
            elif action == "list":
                result = actions.act_list(cfg)
            elif action == "status":
                result = actions.act_status(device, cfg)
            elif action in ("on", "off", "toggle"):
                result = actions.act_switch(device, action, channel, cfg)
            elif action == "set":
                result = actions.act_set(
                    device, channel, args.get("brightness"),
                    args.get("rgb"), args.get("white"), cfg)
            elif action == "cover":
                result = actions.act_cover(
                    device, args.get("op"), args.get("position"), channel, cfg)
            elif action == "meter":
                result = actions.act_meter(device, cfg)
            elif action == "sensor":
                result = actions.act_sensor(device, cfg)
            elif action == "rename":
                result = actions.act_rename(device, str(args.get("name", "") or ""), cfg)
            else:
                result = {"ok": False, "error": f"unknown action '{action}'"}
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 — tools return errors, never raise
            log.exception("shelly tool failed")
            return json.dumps({"ok": False, "error": str(exc)})
    return handle


def _cli_setup(subparsers):
    sub = subparsers.add_parser("discover", help="Scan the LAN for Shelly devices")
    sub.set_defaults(shelly_cmd="discover")
    sub = subparsers.add_parser("list", help="List known Shelly devices")
    sub.set_defaults(shelly_cmd="list")
    sub = subparsers.add_parser("status", help="Show one device's live state")
    sub.add_argument("device", help="name, id, MAC or IP")
    sub.set_defaults(shelly_cmd="status")


def _cli_handler(args):
    cfg = merged_cfg()
    cmd = getattr(args, "shelly_cmd", "list")
    if cmd == "discover":
        result = actions.act_discover(cfg)
    elif cmd == "status":
        result = actions.act_status(args.device, cfg)
    else:
        result = actions.act_list(cfg)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def register(ctx):
    ctx.register_tool(
        name="shelly",
        toolset="shelly",
        schema=TOOL_SCHEMA,
        handler=_make_handler(ctx),
        description="Control Shelly smart-home devices directly on the LAN",
        emoji="💡",
    )
    skill_path = Path(__file__).parent / "skills" / "shelly-direct" / "SKILL.md"
    if skill_path.exists():
        try:
            # register_skill takes the file PATH (it reads/validates it itself);
            # passing the text raised FileNotFoundError and the skill never loaded.
            ctx.register_skill("shelly-direct", skill_path)
        except Exception:  # noqa: BLE001 — skill is additive polish
            log.exception("could not register bundled skill")
    try:
        ctx.register_cli_command(
            name="shelly",
            help="Discover and control Shelly smart-home devices",
            setup_fn=_cli_setup,
            handler_fn=_cli_handler,
        )
    except Exception:  # noqa: BLE001 — CLI is additive polish
        log.exception("could not register CLI command")
