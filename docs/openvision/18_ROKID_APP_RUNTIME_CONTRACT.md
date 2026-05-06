# 18 — Rokid App Runtime Contract

The Rokid app is not the product brain. It is a sensor, input, transport, and HUD terminal controlled by Jetson.

This contract exists so the Android/Rokid app can be written later without forcing backend rewrites.

## Backend alignment rule

The RV101 app topic should not rediscover the product route. It should implement
the backend contract already exercised by the iPhone simulator and earlier RV101
tests:

```text
Jetson session_accept is the source of truth for session, media, audio, and voice output.
MediaCommand / MediaEvent is the only product visual-media path.
hud_scene / DisplayCommand is the only product display path.
Default RV101 voice mode comes from Jetson/session_accept:
conversation_realtime starts automatically when the app opens and uses Cloud
Realtime server_vad; push_to_talk_realtime is debug/fallback.
```

V1 notes and research are lessons to preserve, not architecture to restore. Use
them for measured device facts such as audio source choice, PCM energy metrics,
Camera2 lifecycle constraints, and RV101 optics.

## Responsibilities

The glasses app should do:

```text
- connect to Jetson session manager
- send health/heartbeat/battery/network status
- start foreground conversation audio when session_accept declares conversation_realtime
- capture push-to-talk audio only in explicit debug/fallback mode
- capture snapshot when commanded
- capture burst clip when commanded
- stream live video only when commanded
- receive and render hud_scene messages
- report media start/stop/failure telemetry
```

The glasses app should not do:

```text
- choose product skill
- call cloud AI directly by default
- render custom skill UI outside hud_scene
- keep video running by default
- store long-term memory
- decide privacy/cloud policy
```

## State machine

```text
DISCONNECTED
  -> CONNECTING
  -> IDLE
  -> VOICE_ARMED
  -> VOICE_COMMAND
  -> SNAPSHOT_CAPTURE
  -> BURST_CLIP_CAPTURE
  -> LIVE_VIDEO
  -> REALTIME_CONVERSATION
  -> ERROR
```

### IDLE

```text
camera off
voice stream off until app opens/accepts an OpenVision session
heartbeat on
HUD can show status/debug
```

### VOICE_ARMED

```text
waiting for button/touchpad/wake/VAD
no cloud stream
optional pre-roll buffer
```

### VOICE_COMMAND

```text
explicit debug/fallback push-to-talk audio sent to Jetson realtime bridge
Cloud Realtime decides language/tool choreography
Jetson validates and executes typed skills/tools
manual stop/commit when voice_mode=push_to_talk_realtime
```

### SNAPSHOT_CAPTURE

```text
single image capture
send to Jetson with frame metadata
return to IDLE or previous live state
```

### BURST_CLIP_CAPTURE

```text
capture 2-3 sec clip or sampled frames
send to Jetson
auto-stop
```

### LIVE_VIDEO

```text
stream frames to Jetson
bounded by timeout/fps/resolution
used only for live skills
```

### REALTIME_CONVERSATION

```text
voice session for natural conversation through Cloud Realtime server_vad
Jetson remains authority for tool/skill/HUD
mic stream stays open until Cloud/Jetson/session policy ends the session
requires explicit active state, idle timeout, stop behavior, and budget
```

## RV101 voice modes

The app should support two Jetson-declared voice modes. The product default is
`conversation_realtime`.

### `conversation_realtime`

Use this for the default app-open product conversation:

```text
app opens / reconnects
  -> client_hello asks for voiceOutput and conversation_realtime
  -> session_accept declares voice_mode=conversation_realtime
  -> turn_policy=server_vad is configured on Cloud Realtime by Jetson
  -> app starts foreground mic PCM stream through Jetson to Cloud Realtime
  -> Cloud Realtime detects turns and calls typed Jetson tools
  -> Cloud/Jetson/session policy sends stop when the conversation should end
  -> app stops mic stream and returns to IDLE or disconnected
```

In this mode, `server_vad` means Cloud Realtime VAD, not Jetson audio gate.
Jetson audio gating should be monitor-only unless a separately declared policy
explicitly enables suppression. The app must not start or restart Realtime
through REST bootstrap; it should follow the voice mode and voiceOutput contract
from `session_accept`.

### `wake_realtime`

Use this later for battery-optimized standby:

```text
app/glasses in standby with camera off and no cloud audio stream
  -> lightweight local wake trigger, for example "Hey Vision"
  -> app asks Jetson to open conversation_realtime
  -> Jetson bridges mic stream to Cloud Realtime server_vad
  -> Cloud/Jetson ends the session when the conversation is done
  -> app stops mic stream and returns to standby
```

The wake trigger is only activation. It must not do semantic STT, choose skills,
or route commands on the glasses.

### `push_to_talk_realtime`

Use this only for debug, noisy environments, or fallback:

```text
client_hello voiceOutput=true
  -> session_accept includes voiceOutput / voice_output
  -> app connects to /ws/realtime/{session_id}/audio for assistant audio
  -> ptt_down
  -> PCM tcp_pcm stream
  -> audio stream close
  -> ptt_up
  -> Jetson commits audio and creates the response
```

## Message protocol

All messages should include:

```json
{
  "version": "1.0",
  "session_id": "sess_...",
  "message_id": "msg_...",
  "timestamp_ms": 123456789
}
```

## Jetson -> Glasses commands

### Start voice command

```json
{
  "version": "1.0",
  "type": "start_voice_command",
  "session_id": "sess_001",
  "reason": "user_touchpad",
  "audio_format": {
    "sample_rate": 16000,
    "channels": 1,
    "encoding": "pcm_s16le"
  },
  "pre_roll_ms": 300,
  "max_duration_ms": 8000,
  "silence_timeout_ms": 900
}
```

### Stop voice

```json
{
  "version": "1.0",
  "type": "stop_voice",
  "session_id": "sess_001",
  "reason": "silence_timeout"
}
```

### Capture snapshot

```json
{
  "version": "1.0",
  "type": "capture_snapshot",
  "session_id": "sess_001",
  "skill_id": "text_reader",
  "reason": "skill_media_requirement",
  "resolution": "1280x720",
  "quality": 80
}
```

### Capture burst clip

```json
{
  "version": "1.0",
  "type": "capture_burst_clip",
  "session_id": "sess_001",
  "skill_id": "task_coach",
  "duration_ms": 2500,
  "fps": 8,
  "resolution": "640x360"
}
```

### Start live video

```json
{
  "version": "1.0",
  "type": "start_live_video",
  "session_id": "sess_001",
  "skill_id": "reality_radar",
  "fps": 15,
  "resolution": "800x600",
  "max_duration_ms": 30000,
  "params": {
    "profile_authority": "jetson",
    "camera_contract_version": "openvision.camera_profile.v1",
    "media_profile": "rv101_medium_yolo",
    "camera_profile": "rv101_medium_yolo",
    "fov_mode": "wide",
    "crop_policy": "no_crop",
    "digital_zoom": 1.0,
    "preserve_resolution": true,
    "app_auto_quality": false
  }
}
```

The RV101 app must treat Jetson `MediaCommand` camera fields as authoritative.
It may fall back only to the nearest supported same-FOV Camera2 Surface H.264
size/FPS, and every fallback must be reported in the media event telemetry with
requested vs selected/source dimensions, FPS, camera ID, profile, fallback
reason, orientation, and rotation metadata. The app must not silently upscale,
crop, enable stabilization, or auto-select a quality profile outside the active
command.

### Stop live video

```json
{
  "version": "1.0",
  "type": "stop_live_video",
  "session_id": "sess_001",
  "reason": "skill_completed"
}
```

### HUD scene

The app must render only the HUD protocol:

```json
{
  "version": "1.0",
  "type": "hud_scene",
  "scene": {
    "version": "1.0",
    "type": "answer_strip",
    "text": "Áo vàng · bên trái",
    "duration_ms": 1800,
    "source_skill": "target_finder"
  }
}
```

## Glasses -> Jetson events

### Health

```json
{
  "version": "1.0",
  "type": "glasses_health",
  "session_id": "sess_001",
  "battery_pct": 72,
  "thermal_state": "normal",
  "network_rtt_ms": 24,
  "app_state": "IDLE"
}
```

### Voice chunk

```json
{
  "version": "1.0",
  "type": "audio_chunk",
  "session_id": "sess_001",
  "seq": 42,
  "sample_rate": 16000,
  "channels": 1,
  "encoding": "pcm_s16le",
  "duration_ms": 40,
  "avg_abs": 213,
  "peak_abs": 3021,
  "callback_silenced": false
}
```

### Snapshot ready

```json
{
  "version": "1.0",
  "type": "snapshot_ready",
  "session_id": "sess_001",
  "frame_id": "frame_001",
  "width": 1280,
  "height": 720,
  "encoding": "jpeg",
  "bytes": 123456
}
```

Snapshot, burst, and live-video events should also include orientation and
capture-profile metadata when available:

```json
{
  "orientation": "portrait",
  "profile": "full_res",
  "rotation_degrees": 90,
  "source_width": 720,
  "source_height": 1280,
  "selected_width": 720,
  "selected_height": 1280,
  "requested_width": 1280,
  "requested_height": 720,
  "sensorOrientationDegrees": 270,
  "captureFpsMin": 8,
  "captureFpsMax": 8,
  "sentFpsEstimate": 7.9,
  "droppedFrames": 0,
  "cameraId": "0"
}
```

### Media status

```json
{
  "version": "1.0",
  "type": "media_status",
  "session_id": "sess_001",
  "media_mode": "LIVE_VIDEO",
  "state": "started",
  "skill_id": "reality_radar",
  "reason": "skill_media_requirement"
}
```

## Audio guidance

Use the V1 lesson:

```text
PCM energy is the source of truth.
Callback silence metadata is only a hint.
```

The app should report:

```text
source id
avgAbs
peakAbs
nonSilentRatio
callbackSilenced
selected source
switch reason
queue drops
```

## Video guidance

Video must be:

```text
skill-activated
bounded by timeout
fps/resolution controlled
dropping stale frames instead of queueing forever
```

## Minimum Android/Rokid MVP

Start with this:

```text
1. connect to Jetson
2. heartbeat
3. render hud_scene text
4. touchpad/button starts VOICE_COMMAND
5. capture SNAPSHOT on command
6. optional LIVE_VIDEO on command with timeout
```

Do not start with:

```text
- complex UI modes
- always-on live video
- direct cloud calls
- local skill decisions on glasses
```

## Acceptance criteria

The app contract is valid when:

```text
- backend can run without app present using simulator
- app can be simulated by iPhone/debug sidecar or test harness
- RV101 behavior matches the iPhone simulator contract unless hardware requires a documented exception
- every media command has a start/stop event
- every media activation is visible in scorecard
- app never bypasses hud_scene
- app does not route commands from transcripts, call OpenAI directly, or choose skills
- conversation_realtime starts on app open, streams foreground mic audio, and uses Cloud Realtime server_vad
- push_to_talk_realtime uses manual-turn Realtime only as debug/fallback
```
