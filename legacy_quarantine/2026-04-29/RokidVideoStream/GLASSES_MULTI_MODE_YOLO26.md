# Rokid Multi-Mode YOLO26

## Goal

Turn one shared YOLO26 detector on Jetson into multiple lightweight glasses features without adding heavy work on the glasses.

Main rule:

- glasses: capture, encode, send, render small HUD
- Jetson: detect, smooth, prioritize, format, overlay

## Design direction

These modes are for **smart glasses HUD**, not for a phone screen.

That means:

- center vision is precious
- real world stays primary
- HUD must feel assistive, not app-like
- glanceability matters more than richness

Always prefer:

- short headline
- directional hint
- one priority object
- edge or bottom UI
- quiet defaults

Avoid:

- full phone-style cards in the middle
- CCTV-style object dumps
- large persistent boxes everywhere
- dense menus and lists
- anything that competes with the real scene for attention

## Modes

### Face Memory

- purpose: identify saved people and show memory cues
- glasses HUD: bottom memory card only
- Jetson cost: separate face pipeline later, not part of shared YOLO26 shell

### Traffic Count

- purpose: clean vehicle watch with a single guide line
- detector: YOLO26 filtered to vehicle classes
- glasses HUD:
  - keep center mostly clear
  - one thin guide line
  - compact vehicle mix and left/ahead/right lane counts

### Visual Assistant

- purpose: short actionable scene cues
- detector: shared YOLO26
- glasses HUD:
  - short headline
  - 2-3 small tags like `Left bag`, `Ahead person`, `Right car`
  - no cluttered list

### Focus Bubble

- purpose: lock one meaningful object only
- detector: shared YOLO26
- glasses HUD:
  - small bubble card
  - one focused object
  - almost everything else hidden

### AR Radar

- purpose: peripheral awareness
- detector: shared YOLO26
- glasses HUD:
  - left / ahead / right zone pills
  - center remains readable
  - no need to show all objects

### Alert Burst

- purpose: stay quiet until something matters
- detector: shared YOLO26
- glasses HUD:
  - silent most of the time
  - small burst chip only when priority object/event appears

## Jetson Strategy

One detector is reused for:

- `traffic_count`
- `visual_assistant`
- `focus_bubble`
- `ar_radar`
- `alert_burst`
- `scene_monitor` legacy shell

Optimization rules:

- one raw frame bus from H.264 decode
- one YOLO26 runtime shared logically across scene modes
- mode-specific formatting happens after detection
- mode-specific infer cadence reduces waste
- mode-specific track hold balances stability vs responsiveness

Current cadence targets:

- `focus_bubble`: fastest
- `traffic_count`: fast
- `visual_assistant`: balanced
- `ar_radar`: medium
- `alert_burst`: slowest and quietest

## Glasses Strategy

Keep glasses cheap:

- Camera2 + MediaCodec surface path
- no local AI
- no frame-by-frame CPU analysis in the hot path
- HUD only updates from Jetson results
- selector shows six product modes in two rows

## Guardrails

Do not regress back to:

- always-on noisy object lists
- large center cards that block vision
- per-frame heavy processing on glasses
- separate heavy detector processes per mode on Jetson
