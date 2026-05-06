# Rokid HUD Scene Protocol

Updated: 2026-04-19

## Goal

Jetson decides what should be shown.

Glasses render a thin HUD scene instead of owning feature-specific UI logic.

## Message

`type = "hud_scene"`

## Shape

```json
{
  "type": "hud_scene",
  "version": 1,
  "sessionId": "sess_xxx",
  "sceneId": "scene_123",
  "layout": "rokid_hud_v1",
  "components": []
}
```

## Supported MVP components

### chip

```json
{
  "kind": "chip",
  "id": "task_chip",
  "zone": "top_center",
  "text": "voice request",
  "tone": "active"
}
```

### answer_strip

```json
{
  "kind": "answer_strip",
  "id": "answer",
  "zone": "lower_safe",
  "text": "I found 2 people in yellow."
}
```

### status_strip

```json
{
  "kind": "status_strip",
  "id": "status",
  "zone": "lower_safe",
  "text": "Jetson is processing your request."
}
```

### gallery

```json
{
  "kind": "gallery",
  "id": "candidate_gallery",
  "zone": "upper_right",
  "items": [
    {
      "label": "Nguoi 1",
      "secondary": "Ahead | 0.86",
      "trackId": "7",
      "selected": true,
      "thumbB64": "<small-base64-jpeg>"
    },
    {
      "label": "Nguoi 2",
      "secondary": "Right | 0.81",
      "trackId": "11",
      "selected": false
    }
  ]
}
```

### direction_hint

```json
{
  "kind": "direction_hint",
  "id": "target_direction",
  "zone": "upper_right",
  "text": "Ahead 2 ung vien"
}
```

### target_marker

```json
{
  "kind": "target_marker",
  "id": "primary_target",
  "zone": "center_overlay",
  "label": "Nguoi 1",
  "trackId": "7",
  "direction": "ahead",
  "selected": true,
  "normalizedX": 0.51,
  "normalizedY": 0.47
}
```

## Rendering rules

- center stays mostly clear
- HUD is Rokid-style, not phone-style
- quiet by default
- monochrome-first
- gallery/thumbs should stay small

## Phase roadmap

### MVP

- chips
- answer strip
- status strip
- gallery labels only

### Phase 2

- low-color tile thumbnails
- markers
- guide lines
- focus bubble
- directional pills

## Target Search Pattern

For search-style tasks such as `tim nguoi ao vang deo kinh`, Jetson should:

1. generate local candidates from tracked detections first;
2. assign stable labels like `Nguoi 1`, `Nguoi 2`;
3. attach compact gallery tiles and a direction hint;
4. escalate to cloud vision only when local certainty is not enough;
5. keep glasses rendering declarative and lightweight.
