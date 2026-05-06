# 24 — Media Capture Budgets and Modes

## Purpose

The glasses have limited battery, thermals, CPU, and network bandwidth.

V2 must use media capture only when the cloud realtime orchestrator or Jetson skill tool server needs it.

## Canonical visual modes

### `none`

No camera use.

Use for:

- pure conversation,
- system status,
- session management,
- simple commands.

### `snapshot`

Capture one image.

Use for:

- text reading,
- object question,
- scene description,
- count people/objects,
- “what is this?”.

Recommended budget:

```yaml
resolution: 1280x720 or lower
max_images_per_turn: 1-3
timeout_ms: 1500
```

### `burst_clip`

Capture short clip or sampled frames for 2-3 seconds.

Use for:

- short temporal events,
- gesture/motion check,
- “what just happened?”,
- checking a short physical action.

Recommended budget:

```yaml
duration_ms: 2000-3000
fps: 5-10
resolution: 640x360 or 720p if needed
```

### `live_video`

Enable continuous stream to Jetson only.

Use for:

- Reality Radar,
- active target tracking,
- navigation-like awareness,
- traffic/live counting,
- active scene monitor.

Recommended budget:

```yaml
default_profile: rv101_eco_live
skill_profile: rv101_medium_yolo
fps: 5-15 normally, 30 only for explicit diagnostic/perf validation
resolution: 640x360 low-power, 800x600 balanced YOLO/live skills, 1280x720 only for explicit high-detail or diagnostic live
max_duration_ms: 15000-60000 default
hard_stop_ms: 60000 unless explicit mission mode
```

## Jetson-authoritative camera profiles

Rokid should not choose product media quality by itself. The app executes the
typed `MediaCommand` from Jetson and reports what it actually selected.

Canonical RV101 live profiles:

```yaml
rv101_eco_live:
  resolution: 640x360
  fps: 8
  use_for: lightweight debug/live skills
rv101_medium_yolo:
  resolution: 800x600
  fps: 15
  encoder_bitrate_target: about 3 Mbps
  stable_overlay_target: raw H.264 plus Jetson-stabilized perception bbox metadata
  deepstream_osd_bitrate_target: about 4 Mbps for diagnostic preview only
  use_for: default target_finder/object/person aim assist, Reality Radar MVP
  origin: v1 MEDIUM Camera2 Surface path proved stable enough for YOLO/perception
rv101_high_detail:
  resolution: 1280x720
  fps: 15
  use_for: person_info name_reminder and explicit named/known-person identity live requests
rv101_diagnostic_30:
  resolution: 1280x720
  fps: 30
  use_for: explicit short performance validation only
```

Each command should include `params.profile_authority=jetson`,
`params.camera_contract_version=openvision.camera_profile.v1`,
`params.media_profile`, `params.camera_profile`, `params.fov_mode=wide`,
`params.crop_policy=no_crop`, `params.digital_zoom=1.0`, and
`params.app_auto_quality=false`.

If exact size/FPS is unsupported, the app may choose the nearest supported
same-FOV Camera2 Surface H.264 profile, but it must report requested width,
requested height, selected/source width, selected/source height, target FPS,
capture FPS range, sent FPS estimate, camera ID, profile fallback reason, and
orientation/rotation metadata.

## Sensor Preview route contract

Sensor Preview live output is a Jetson-owned route, not a decoded JPEG/MJPEG
fallback and not a raw detector OSD authority. Each live `MediaCommand` should
carry a `preview_route` and declared `perception_branches` so Jetson can choose
exactly one product live video path while keeping diagnostic routes separate:

```text
target_finder live_video   -> stable_overlay_h264, yolo26_objects branch
person_info name_reminder  -> raw RV101 H.264, face_identity branch
other live skills          -> raw RV101 H.264 unless a skill manifest declares another route
snapshot/burst evidence    -> snapshot_image route
```

Live Sensor Preview must connect to the route `ws_url` and must not cut JPEG or
MJPEG frames for live playback. Processed JPEG/MJPEG artifacts are allowed only
for QA, evidence bundles, recording review, and debugging.

For YOLO26 object live routes, DeepStream/YOLO26 is a detector metadata feed,
not the product bbox renderer. Product bbox authority belongs to the
Jetson-stabilized perception layer: confidence gates, class filtering, NMS,
track hold, min hits, and bbox smoothing run before skills, HUD, or Ops Preview
consume boxes. DeepStream OSD H.264 may remain available as a diagnostic route,
but it must not be the default product preview authority.

## Jetson quality-review recordings

For RV101 real-device sessions, Jetson may save bounded local recordings under
`OPENVISION_RUNTIME_DIR/recordings` when `OPENVISION_RV101_STREAM_RECORDING=1`.

The recorder is Jetson-side only and should not add app-side storage logic:

```text
raw/video.h264                         compressed RV101 H.264 samples
raw/audio.wav                          RV101 mic PCM as a playable WAV
processed/preview_annotated.mjpeg      review-only perception bbox/label frames
processed/latest_annotated.jpg         latest annotated frame for quick inspection
manifest.jsonl                         session metadata and file paths
```

This is for product QA, stream-quality inspection, and replay/debug. Recording
must stay behind Jetson config, use a bounded writer queue, and close on session
close/video disconnect so live ingest is not blocked by SSD I/O.

## Canonical voice modes

### `idle`

No cloud audio session.

### `push_to_talk_realtime`

User explicitly activates voice.

Debug/noisy fallback and signoff mode.

### `wake_realtime`

Future battery-optimized mode.

Wake detection may run on glasses if lightweight, for example "Hey Vision".
Full audio streams to Jetson -> Cloud Realtime only after wake, and Cloud/Jetson
can end the session so glasses return to standby.

### `conversation_realtime`

Default RV101 app-open cloud realtime conversation mode.

Uses Cloud Realtime `server_vad`, with Jetson audio gate monitor-only. Must
have visible active state, idle timeout, stop behavior, and scorecard telemetry.

### `mission_realtime`

Explicit longer session for guided task, Reality Radar, or scene monitor.

Must have max duration and visible status.

## Media command shape

```json
{
  "command_id": "media_cmd_123",
  "session_id": "sess_abc",
  "source_tool_call_id": "call_456",
  "mode": "snapshot",
  "reason": "text_reader requires current image",
  "constraints": {
    "max_duration_ms": 1500,
    "preferred_resolution": "1280x720",
    "preferred_fps": null,
    "max_bytes": 1500000
  }
}
```

## Media event shape

```json
{
  "event_id": "media_evt_123",
  "command_id": "media_cmd_123",
  "session_id": "sess_abc",
  "type": "snapshot_ready",
  "uri": "session://sess_abc/snapshots/001.jpg",
  "metrics": {
    "capture_latency_ms": 160,
    "upload_latency_ms": 80,
    "bytes": 420000
  }
}
```

## Display budget

Avoid display spam.

Recommended defaults:

```yaml
max_hud_updates_per_second: 3
min_answer_display_ms: 1200
max_answer_display_ms: 5000
max_debug_overlay_rate_hz: 1
```

## Important policy

Camera is off by default.

Cloud realtime audio does not imply camera streaming.

A cloud tool call must explicitly request visual media through Jetson's media tool server.
