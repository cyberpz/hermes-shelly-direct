# Shelly Direct — Hermes Plugin (Hackathon Entry)

**Goal:** first-class Shelly smart-home control in Hermes with **zero infrastructure** — no Home Assistant, no MQTT broker, no cloud. Direct LAN HTTP to Shelly Gen1/2/3 devices.

**Catalog key:** `shelly-direct` · **Category:** `automation` · **Tier:** community · **Repo:** `cyberpz/hermes-shelly-direct` (owner submits → rule 5 ✓)
**Competition check:** 978 catalog entries, zero Shelly plugins. `homeassistant.yaml` exists but is a different product (needs HA server); ours is direct-device. Rule 16 clear.

## Why a plugin, not a skill
Real device I/O: UDP discovery, per-gen HTTP protocol handling, digest auth, verify-after-write. A prompt cannot touch a relay. (Judges' stated preference.)

## Tool surface — one tool `shelly`, action enum

| action | args | behavior |
|---|---|---|
| `discover` | — | UDP broadcast :10100 (`GET /HTTP/1.0`) + `extra_hosts` probe → rebuild inventory cache |
| `list` | `filter?` | inventory from cache (name, model, gen, ip, channels, kind) |
| `status` | `device` | compact status: relays, power, sensors, covers |
| `on` / `off` / `toggle` | `device`, `channel?` | relay switch; verify-after-write |
| `set` | `device`, `channel?`, `brightness?`, `rgb?`, `white?`, `position?` | dimmer/RGBW/white, cover position |
| `cover` | `device`, `op` (open/close/stop), `position?` | roller shutters |
| `meter` | `device`, `channel?` | instant W, voltage, total kWh (PM/Plug/EM/3PM) |
| `sensor` | `device` | temperature/humidity/leak/etc. readings |

- **Device resolution:** friendly name (substring, unique) → device id → MAC → IP. Cache miss → auto one-shot discovery before failing.
- **Gen handling:** probe `POST /rpc/Shelly.GetInfo` (Gen2/3) else `GET /` (Gen1). Gen1 control: `GET /relay/0?turn=on`, `/light`, `/cover`; Gen2/3: `POST /rpc/Switch.Set`, `Light.Set`, `Cover.Set`, `Switch.GetStatus`…
- **Verify-after-write** (our proven pattern): after every write, re-read status, report actual state + mismatch warning.
- Handlers return JSON strings, never raise (catalog "common mistakes" compliance).

## Discovery & inventory
- UDP broadcast 255.255.255.255:10100 (all gens answer with `{addr, mac, id, gen, ...}`), stdlib `socket`, 2 s window, plus `extra_hosts` for routed/VLAN subnets. No nmap, no mDNS dependency.
- Inventory keyed by **MAC** (stable identity), stored in `ctx.state` (profile-scoped, survives restarts, 10 MiB cap — plenty).

## config_schema (also renders Desktop settings form)
```yaml
config_schema:
  extra_hosts:   {type: list, default: [], description: "IPs/CIDRs outside the local segment"}
  timeout_ms:    {type: int,  default: 3000}
  verify_writes: {type: bool, default: true}
  auth_user:     {type: str,  default: ""}
  auth_password: {type: secret, default: ""}   # digest auth, read via get_secret
```
Secrets only via Hermes secret route (rule 11 ✓). No `.env` reads, no credential files.

## Dependencies
`requests>=2.28,<3` only (already a Hermes core dep → `validate --install-deps` trivially green). Upper bound ✓ (rule 10).

## Extras (polish points, all cheap)
- **Bundled skill** via `ctx.register_skill()` — usage guide so the model uses the tool well.
- **CLI** `hermes shelly discover|list|status <dev>` via `ctx.register_cli_command()`.
- **Banner 1200×600 + 2 screenshots** on raw.githubusercontent at pinned SHA (catalog page candy).
- `requires_hermes: ">=0.19"` in plugin.yaml + catalog entry (honest floor; current release 0.22.6).

## Repo layout
```
hermes-shelly-direct/
├── plugin.yaml            # manifest v2: name, version, tags[smart-home,iot,shelly],
│                          # config_schema, provides_tools:[shelly], requires_hermes
├── __init__.py            # register(ctx): tool + skill + CLI
├── schemas.py             # SHEDLY tool schema (action enum, rich description)
├── client.py              # ShellyClient: gen detect, gen1/gen2 calls, digest auth
├── discovery.py           # UDP broadcast + extra_hosts probe
├── inventory.py           # MAC-keyed cache in ctx.state, device resolution
├── actions.py             # action handlers → JSON strings, verify-after-write
├── skills/shelly-direct/SKILL.md
├── tests/                 # pytest: fake Gen1 + Gen2 http.server stubs, discovery monkeypatched
├── docs/banner.png, docs/screenshot-*.png
└── README.md              # install, config, disclosure section (rule 13)
```

## Rule-compliance checklist
| rule | status |
|---|---|
| 2 SHA pin | tag v1.0.0, pin full 40-hex |
| 3 no self-updater | none |
| 6 declared = registered | provides_tools:[shelly] matches register() |
| 9 no core override | pure ctx.register_* |
| 10 deps bounded | requests>=2.28,<3 |
| 11 secrets via Hermes | config_schema secret + get_secret |
| 13 disclosure | README: LAN-only HTTP+UDP broadcast, optional device digest password, no third-party calls, no telemetry |
| 14 requires_hermes | ">=0.19" both places |
| 17 source only | pure Python, no binaries |

## Test plan
- Unit: gen detection, payload normalization (Gen1 vs Gen2/3 status → common shape), device resolution (name/id/mac/ip, ambiguity error), verify-after-write mismatch path, cover/dimmer edge cases.
- Integration: two stub servers (Gen1 + Gen2/3 RPC semantics) on localhost; full action matrix against them.
- `hermes plugins doctor . --ci` + `hermes plugins validate . --install-deps` green locally = catalog CI green.
- Live smoke on real fleet (Shelly devices at home) for the demo.

## Demo video (<90 s, X post + tag NousResearch)
1. 0–10 s: `hermes plugins install shelly-direct` (or local path) — clean install
2. 10–25 s: "discover my Shelly devices" → inventory table appears
3. 25–50 s: "turn on the office light" → **real light turns on** (camera on device)
4. 50–70 s: "how much power is the washing machine drawing?" → live wattage
5. 70–85 s: close: "no Home Assistant, no cloud — just your LAN." + repo URL

## Timeline (deadline Nov 11, 17:00 EST)
| day | milestone |
|---|---|
| Nov 4–5 | repo skeleton, client.py (gen detect + gen1/gen2 verbs), discovery |
| Nov 6 | all actions + verify + config + state cache |
| Nov 7 | tests green, doctor/validate green, README + skill + CLI |
| Nov 8 | polish, banner/screenshots, clean-HERMES_HOME install test |
| Nov 9 | demo video, tag v1.0.0, **catalog PR + Typeform** |
| Nov 10 | buffer for maintainer feedback |

## Submission artifacts
1. PR to `NousResearch/hermes-agent`: `plugin-catalog/shelly-direct.yaml` (schema above)
2. Demo video on X tagged NousResearch
3. Typeform FwJLvOln with both links
