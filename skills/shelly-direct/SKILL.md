---
name: shelly-direct
description: Use when the user asks about Shelly smart-home devices — lights, plugs, rollers, meters, sensors — controlled directly on the LAN.
---

# Shelly Direct

Control Shelly devices (Gen1/2/3) on the local network with the `shelly` tool.
No Home Assistant, no MQTT, no cloud.

## Workflow
1. **First use or "find my devices"** → `{"action":"discover"}`. Returns every
   device with name, model, gen, IP. Cache it; re-run only when devices change.
   If it finds 0 devices, UDP broadcast is likely blocked (IoT VLAN / AP
   isolation): retry `{"action":"discover","subnet":"<your-net>/24"}` with the
   user's LAN CIDR.
2. **Act** → address devices by the human name from `list`/`discover`
   (substring matching is fine: "office" matches "Office Light").
3. **Confirm state** → `{"action":"status","device":"office"}` before claiming
   something is on/off. Writes report `verified: true|false` — if false, say
   the device did not confirm; do not claim success.

## Actions
| want | call |
|---|---|
| scan LAN | `{"action":"discover"}` |
| known devices | `{"action":"list"}` |
| full state | `{"action":"status","device":"office"}` |
| switch on/off/toggle | `{"action":"on","device":"coffee machine"}` |
| multi-channel device | add `"channel":1` (0-based, see `channels` in status) |
| dim | `{"action":"set","device":"desk","brightness":40}` |
| color | `{"action":"set","device":"desk","rgb":"#ff8800"}` |
| roller shutter | `{"action":"cover","device":"bedroom","op":"close"}` or `"position":30` |
| live power | `{"action":"meter","device":"washer"}` → W and kWh |
| climate | `{"action":"sensor","device":"attic"}` → temp/humidity/battery |

## Gotchas
- Battery devices (H&T, Door/Window) sleep: `status` may fail until the device
  wakes — say so instead of retrying in a loop.
- A device name matching several devices returns candidates — ask which one.
- `cover position`: 0 = fully open (shutter up), 100 = fully closed, per Shelly.
- Protected devices need digest auth configured in plugin settings; an
  "Unauthorized" error means configure `auth_password`, not retry.
