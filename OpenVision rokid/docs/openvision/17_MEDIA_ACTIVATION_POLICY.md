# 17 — Media Activation Policy: Skill/Tool-Driven Capture

OpenVision Rokid V2 must be low-power and cloud-realtime orchestrated.

## Core rule

```text
Voice can open a cloud realtime session.
Camera stays off unless a typed tool/skill requests visual media.
```

## Media modes

```text
none        no camera required
snapshot    one image
burst_clip  short 2-3 second clip or sampled frames
live_video  temporary live stream with timeout and budget
```

## Who decides?

Cloud realtime decides what it needs, but Jetson validates and executes.

```text
Cloud Realtime -> RealtimeToolCall -> Jetson Tool Server -> MediaCommand -> Rokid
```

## Why not always-on video?

Always-on video hurts:

```text
battery
thermal headroom
privacy
network reliability
latency predictability
scorecard clarity
```

Most useful skills only need snapshot or burst clip.

## MediaCommand contract

Every media command should include:

```yaml
version: "1.0"
command_id: string
session_id: string
requested_by: cloud_realtime | jetson_skill | debug
skill_id: string | null
mode: none | snapshot | burst_clip | live_video
reason: string
max_duration_ms: integer
preferred_fps: integer | null
preferred_resolution: string | null
privacy_level: low | medium | high | sensitive
auto_stop: boolean
```

## Live video requirements

A live video command is invalid unless it has:

```text
skill_id
reason
max_duration_ms
preferred_fps
preferred_resolution
auto_stop=true
```

Suggested defaults:

```text
Reality Radar flagship skill / tracking: rv101_medium_yolo, 800x600, 15 FPS, 15-30 seconds
scene monitor: 3-10 FPS, 640x360, short session
traffic count: 5-10 FPS, 640x360, bounded duration
```

## Skill examples

### Text reader

```yaml
visual: snapshot
max_duration_ms: 1000
cloud_allowed: true
```

### Object counter

```yaml
visual: snapshot
max_duration_ms: 1500
cloud_allowed: false
```

### Target finder

```yaml
visual: snapshot or live_video
max_duration_ms: 3000 for snapshot, 15000-30000 for live_video
cloud_allowed: true
```

### Person info / known-person snapshot

```yaml
visual: snapshot
max_duration_ms: 3000 normally, 5000 when params.quality_gate requests a multi-frame mini-burst
cloud_allowed: true only through Jetson evidence bundles
```

### Reality Radar

```yaml
visual: live_video
max_duration_ms: 30000
preferred_profile: "rv101_medium_yolo"
preferred_fps: 15
preferred_resolution: "800x600"
cloud_allowed: true
architecture: shared_skill_runtime_only
```

## Scorecard requirements

Log:

```text
media_command_id
mode
skill_id
reason
capture_start_ms
capture_ready_ms
first_frame_ms
stop_ms
duration_ms
frames_sent
dropped_frames
bytes_sent
```

## Voice mode note

Voice has two different concepts that must not be confused:

```text
manual-turn PTT        app/user explicitly closes a short audio turn
cloud server_vad       OpenAI Realtime detects turn boundaries from streamed audio
```

The desired product conversation path is app-open `conversation_realtime` with
Cloud Realtime `server_vad`, not Jetson-side audio gating. When the RV101 app
opens an OpenVision session, the glasses may stream microphone audio through
the Jetson bridge to Cloud Realtime until Cloud/Jetson/session policy ends the
session. Jetson should relay, validate tools, log telemetry, and enforce
budgets; it should not become the semantic voice gate.

Manual-turn remains valid only for debug signoff, noisy fallback, or explicit
push-to-talk mode:

```text
ptt_down -> audio append stream -> audio stream close -> input_audio_buffer.commit -> response.create
```

For the RV101 app topic, `session_accept.voiceOutput` is the product contract
for assistant audio. The app should connect to the accepted voice-output
websocket and should not start/restart Realtime through an app-side REST
bootstrap. The normal accepted RV101 product session should declare
`conversation_realtime` with `turn_policy=server_vad`, and the app should stream
audio continuously for that bounded foreground session. If the accepted session
declares `push_to_talk_realtime`, the app should use manual turns as fallback.

Every realtime voice mode still needs a visible active state, session budget,
idle timeout, stop behavior, and scorecard telemetry so a stuck cloud or network
session cannot leave the glasses streaming forever.

Future battery optimization may replace app-open voice with a lightweight
glasses wake trigger:

```text
standby -> "Hey Vision" -> conversation_realtime -> Cloud/Jetson stop -> standby
```

That wake trigger is activation only. It must not perform semantic STT or route
skills locally on the glasses.
