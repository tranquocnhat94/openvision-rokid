# 25 — Display Skills and HUD Outputs

## Purpose

V2 should treat display as a skill family, not as ad-hoc strings.

The cloud realtime orchestrator may decide what kind of information should be shown. Jetson validates and sends the correct display command to Rokid.

## Display capability families

### 1. Text HUD

Small text strip.

Use for:

- short answers,
- status,
- confirmations,
- warnings.

Example:

```json
{
  "type": "text_hud",
  "text": "Áo vàng · bên trái",
  "priority": "normal",
  "duration_ms": 1800
}
```

### 2. Object card

Thumbnail/crop with metadata.

Use for:

- target selection,
- object identity,
- focus by track ID,
- Reality Radar candidate.

Example:

```json
{
  "type": "object_card",
  "track_id": "person_3",
  "title": "Possible match",
  "subtitle": "yellow shirt · backpack",
  "thumbnail_uri": "session://sess_abc/crops/person_3.jpg",
  "duration_ms": 3000
}
```

### 3. Full image card

Show a full image returned by a visual skill.

Use sparingly due to display and bandwidth constraints.

### 4. Live overlay

Use for active video-based skills.

Example:

```json
{
  "type": "live_overlay",
  "overlay_mode": "target_hint",
  "targets": [
    {
      "track_id": "person_3",
      "anchor": "left_front",
      "label": "match"
    }
  ]
}
```

### 5. Debug overlay

Only in debug mode.

Shows:

- session ID,
- FPS,
- latency,
- cloud session status,
- current skill,
- media mode.

## Display execution pipeline

```text
Cloud realtime proposes response/display
  -> Jetson display tool validates schema
  -> Jetson chooses Rokid-compatible representation
  -> Rokid renders lightweight UI
  -> display event is logged in scorecard
```

## Do not do

Do not let every skill invent its own HUD payload.
Do not show long text on glasses unless explicitly requested.
Do not keep image cards on screen too long.
Do not stream full video to glasses unless the display skill requires it.

## Display skill manifest

A display skill should declare:

```yaml
id: display.object_card
version: 0.1
inputs:
  - display_payload
  - session_state
outputs:
  - rokid_display_command
latency_budget_ms: 200
media_requirements:
  voice: none
  visual: none
cloud_allowed: false
memory_allowed: false
```

## Why display as skill matters

It lets cloud say:

```text
show this target as an object card
```

without knowing the exact Rokid UI implementation.

Jetson becomes the display adapter and policy layer.
