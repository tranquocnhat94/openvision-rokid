# Product Contract

OpenVision Rokid v2 is a wearable vision-first AI system. The glasses are a thin terminal; Jetson is the trusted local runtime; OpenAI/cloud AI is the planner and reasoning layer.

## Canonical Product Loop

```text
RV101 glasses
  camera -> hardware H.264 -> Jetson media gateway
  mic -> PCM -> Jetson audio turns
  websocket/control -> Jetson session control
  HUD scene JSON <- Jetson HUD authority

Jetson
  session manager
  media/audio ingest
  OpenAI Realtime bridge
  typed skill registry
  perception graph
  selected target state
  HUD authority

OpenAI / cloud AI
  live conversation
  Vietnamese intent understanding
  tool selection
  cloud visual reasoning when local evidence is insufficient
```

The iPhone web simulator follows the same product contract, but exists only to accelerate debugging:

```text
iPhone Safari/Chrome
  secure origin + direct tap
  getUserMedia preview
  WebRTC upstream media
  websocket/control/result
  same HUD scene renderer
```

## Voice Contract

Primary command path:

```text
audio -> gpt-realtime-1.5 conversation -> typed Jetson tool -> skill result -> HUD
```

Debug transcript path:

```text
completed audio turn -> mini PC PhoWhisper -> Ops Console only
```

The debug transcript is for the operator to inspect what was spoken. It is not the agent brain, not a router, and not a HUD product feature.

## Non-Negotiable Boundaries

- No heavy AI, tracking, reasoning, or complex screens on the glasses.
- No phone-like full-screen panels on RV101.
- No old prototype mode picker on the glasses.
- No simulator-only product behavior.
- No direct mutation of the existing Ring / YOLO26 security runtime.
- No API keys in source, app bundles, logs, docs, or debug bundles.
- No OpenAI transcription branch as a hidden second route.

## Internal Modes

Internal Jetson capability profiles are allowed when they are implementation details behind typed skills.

Examples:

- `person_count_runtime`;
- `target_search_runtime`;
- `traffic_count_runtime`;
- `selected_target_followup`;
- `yolo26_person_tracking`.

They must be owned by Jetson modules and observable in trace. They must not leak into glasses as old product modes.

## Expected User Experience

Example 1:

```text
User says: "Phía trước có bao nhiêu người?"
OpenAI chooses: count_people
Jetson executes: local person detection/tracking through Rokid-specific runtime
HUD shows: compact answer strip, "100 người"
```

Example 2:

```text
User says: "Tìm người mặc áo màu xanh."
OpenAI chooses: search_targets
Jetson executes: local person detection + crop candidates
Cloud AI resolves: color/posture/glasses/attributes from selected crops
Jetson owns: matching IDs, thumbnails, selected target state
HUD shows: small edge thumbnails and selected target cue
```

Example 3:

```text
User says: "Người đó đang làm gì?"
OpenAI chooses: analyze_selected_target
Jetson sends: selected target crop sequence / recent evidence
Cloud AI returns: compact visual answer
Jetson updates: selected target state and HUD scene
```

## Product Shape

v2 should feel like a product foundation:

- one thin-client contract for RV101 and iPhone simulator;
- one Realtime tool bridge;
- one typed skill registry;
- one perception graph;
- one selected-target state model;
- one HUD scene schema;
- one Ops Console trace for media, audio, Realtime, tools, skills, Debug STT, preview, and HUD;
- small modules with clear owners.
