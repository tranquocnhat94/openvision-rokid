# 27 - Rokid App Alignment Roadmap

This file is the contract for the separate glasses-app topic. It exists to keep
RV101 app work aligned with the OpenVision Rokid V2 backend and to prevent the
app from rediscovering paths that are already proven by V1 notes, RV101 tests,
and the iPhone simulator harness.

## App topic mission

Build the Rokid app as a thin product client for the OpenVision AI Skill OS:

```text
Rokid app = microphone + camera + H.264/PCM transport + tiny HUD + diagnostics
Jetson = session authority + media/display command gateway + skill executor
Cloud Realtime = conversation brain + typed tool orchestrator
```

The app should make the backend platform usable on real glasses. It should not
become a second product brain.

## Required read order for the app topic

Read these before implementing app changes:

```text
1. AGENTS.md
2. docs/openvision/00_INDEX.md
3. docs/openvision/18_ROKID_APP_RUNTIME_CONTRACT.md
4. docs/openvision/17_MEDIA_ACTIVATION_POLICY.md
5. docs/openvision/19_VOICE_AND_CLOUD_ROUTING.md
6. docs/openvision/24_MEDIA_CAPTURE_BUDGETS_AND_MODES.md
7. docs/openvision/25_DISPLAY_SKILLS_AND_HUD_OUTPUTS.md
8. OpenVision rokid/glasses/README.md
9. OpenVision rokid/glasses/android_client/PROGRESS.md
10. OpenVision rokid/glasses/android_client/MEASURED_DECISIONS.md
11. OpenVision rokid/glasses/android_client/RELEASE_SIGNOFF.md
```

The iPhone simulator is the fast executable reference for backend behavior. The
RV101 app should converge toward that same media/HUD/session contract, with
hardware-specific implementation only where RV101 requires it.

## Do not rediscover the route

V1 and earlier RV101 research already proved useful lessons:

```text
PCM energy is more reliable than callback silence metadata.
MIC 16000 Hz on RV101 is more reliable than forcing VOICE_RECOGNITION 24000 Hz.
The app must report audio peak/avg/non-silent metrics.
Camera2 can be denied when the app is backgrounded or the display is asleep.
RV101 display/HUD needs compact physical-pixel sizing, not phone-style screens.
Tailnet/VPN readiness is operator/device state, not something OpenVision owns.
```

Use those lessons. Do not rebuild a local-STT route, a phone-like mode UI, or an
always-on camera pipeline to test ideas already settled by the backend and
simulator.

## Golden runtime route

The current product route is:

```text
RV101 mic/button/media event
  -> Jetson control/session/realtime bridge
  -> Cloud Realtime typed tool call
  -> JetsonToolServer validation
  -> skill runtime / media command / display command
  -> RV101 HUD, audio output, snapshot, burst, or bounded live video
```

The app must never bypass this with direct cloud calls, direct skill selection,
local transcript routing, custom skill HUD, or camera decisions made on-device.

## RV101 voice contract

The app must support Jetson-declared voice modes rather than hard-coding one
turn policy. The product default is app-open `conversation_realtime`.

### `conversation_realtime`

The default product path starts when the app opens and uses Cloud Realtime
`server_vad`:

```text
app opens / reconnects
  -> client_hello asks for voiceOutput and conversation_realtime
  -> Jetson creates Cloud Realtime session with turn_policy=server_vad
  -> session_accept tells the app voice_mode=conversation_realtime
  -> app starts foreground mic PCM stream through Jetson to Cloud Realtime
  -> Cloud Realtime detects turn boundaries and chooses typed tools
  -> Cloud/Jetson/session policy ends the conversation
  -> app stops streaming and returns to idle/disconnected
```

### `wake_realtime`

Later battery-optimized flow:

```text
RV101 standby, camera off, cloud audio off
  -> local lightweight wake trigger such as "Hey Vision"
  -> app starts/requests conversation_realtime
  -> mic streams RV101 -> Jetson -> Cloud Realtime server_vad
  -> Cloud AI handles turns/tools
  -> Cloud/Jetson stops the stream when done
  -> RV101 returns to standby
```

The wake trigger must remain a trigger only. Do not turn it into local STT,
local intent routing, or a second assistant on the glasses.

### `push_to_talk_realtime`

Manual-turn PTT remains useful only for debug signoff, noisy fallback, and
operator testing:

```text
client_hello voiceOutput=true
  -> session_accept includes voiceOutput / voice_output endpoint
  -> app opens /ws/realtime/{session_id}/audio for assistant audio
  -> user presses Talk
  -> app sends ptt_down
  -> app streams PCM over tcp_pcm
  -> app stops the TCP audio stream
  -> app sends ptt_up
  -> Jetson commits audio and creates the Realtime response
```

Current requirements:

```text
- App opens into conversation_realtime by default.
- App must prefer voiceOutput from session_accept.
- App must follow session_accept voice_mode / turn_policy.
- App must not start or restart Realtime through REST bootstrap.
- App must not run local STT, local intent routing, or Jetson-style voice gate.
- Cloud server_vad is the default turn detector for conversation_realtime and
  should receive the raw-enough mic stream through Jetson bridge.
- wake_realtime may later avoid unnecessary battery use by opening the same
  conversation path only after "Hey Vision" or another lightweight trigger.
- Manual-turn is valid only for push_to_talk_realtime debug/noisy fallback and
  product signoff checks.
- Every non-PTT realtime session needs visible active state, idle timeout,
  budget, explicit stop, and scorecard telemetry.
```

## Media command requirements

Camera is off by default. The app captures visual media only after a typed
Jetson MediaCommand.

Supported product modes:

```text
none
snapshot
burst_clip
live_video
```

For every visual command, the app must:

```text
- verify the command session_id matches the active session;
- reject stale commands whose remaining budget is too small;
- treat command resolution/fps/params.media_profile as Jetson-authoritative;
- never silently auto-upscale, crop, stabilize, or choose another quality profile;
- if exact media profile is unavailable, choose nearest same-FOV Camera2 Surface
  H.264 fallback and report the fallback reason;
- refuse camera work when Activity is not foreground/interactive;
- report started/ok/error/timeout/cancelled MediaEvent states;
- upload preview evidence to Jetson only, not cloud directly;
- stop camera/encoder/audio work on timeout, command completion, Activity stop,
  websocket disconnect, or session supersede;
- leave Android camera cleanup empty after completion.
```

Canonical RV101 live profiles from backend:

```text
rv101_eco_live       640x360@8    lightweight/debug
rv101_medium_yolo    800x600@15   default YOLO/target/person live skill profile
rv101_high_detail    1280x720@15  explicit detail/identity live
rv101_diagnostic_30  1280x720@30  short diagnostic only
```

The current backend default for target_finder/person_info live is
`rv101_medium_yolo`, based on the v1 MEDIUM Camera2 Surface path that proved
stable enough for perception.

## Required media metadata

The app must send enough metadata for Jetson preview, perception, scorecards,
and replay to interpret RV101 images correctly.

Normalize and report these keys when available:

```text
orientation
profile
media_profile
camera_profile
requested_media_profile
resolved_media_profile
profile_authority
camera_contract_version
profile_fallback_reason
rotation_degrees
source_width
source_height
selected_width
selected_height
requested_width
requested_height
sensorOrientationDegrees
sensor_orientation_degrees
requestedWidth
requestedHeight
captureFpsMin
captureFpsMax
sentFpsEstimate
droppedFrames
cameraId
```

Backend scorecards compare selected/estimated FPS against command budgets. If
RV101 sends 30 FPS for an 8 FPS command, that is an app bug unless explicitly
explained by the metadata.

## HUD requirements

The app renders only Jetson HUD/display scene primitives.

Required primitives:

```text
answer strip
status/edge chips
thumbnail strip
target hint / small reticle / direction arrow
zoom tile
clear / TTL expiry
debug overlay only when operator debug is visible
```

The iPhone simulator HUD is the layout reference, but RV101 must adapt sizes to
real optics and the 480x640 physical display. The normal HUD must not become a
phone screen, settings panel, mode picker, or large debug dashboard.

## Session and reconnect requirements

The app and backend must agree on session ownership:

```text
- one active RV101 session per device_id;
- reconnect with the same device_id supersedes the previous session;
- disconnected, expired, superseded, stopped, and closed sessions are inactive;
- late HUD/audio/tool results must not render into a stale session;
- websocket disconnect must stop polling, active media, mic relay, and voice
  output playback for that session;
- reconnect must not execute stale queued MediaCommands.
```

## iPhone simulator as the lead reference

Use the iPhone simulator to validate backend behavior before or alongside RV101
work:

```text
- microphone permission before session start;
- camera off at idle;
- MediaCommand-driven snapshot/burst/live;
- HUD scene rendering and TTL;
- visual skill continuation after media completion;
- scorecard/replay evidence.
```

If the app topic wants a different behavior from the iPhone simulator, it must
first explain why the RV101 hardware requires that difference.

## Product signoff gates

The app is not product-ready until these pass on a real RV101 route, preferably
normal LAN/tailnet rather than USB tunnel:

```text
connect/session_accept
session supersede/reconnect cleanup
app-open conversation_realtime Cloud server_vad response
manual-turn PTT fallback response
assistant voice output from session_accept endpoint
snapshot MediaCommand with preview metadata
person_info quality_gate mini-burst
bounded burst_clip
bounded live_video with FPS budget compliance
HUD answer/chips/thumb/aim/zoom/TTL through real optics
camera cleanup empty after every visual command
no local STT, no direct OpenAI/cloud key, no skill router
no WAKE_LOCK/WifiLock unless a future mission mode explicitly accepts battery cost
scorecard and replay export show media/audio/HUD/tool status
```

## Do not build yet

Do not add these to the app topic unless the backend contract explicitly asks:

```text
local STT or local intent router
OpenAI client/key on RV101
always-on video
always-on cloud listening
Radar-specific app mode
phone-style settings/navigation UI
custom HUD outside hud_scene
Tailscale/VPN control from OpenVision
background camera capture
long-running WifiLock/WakeLock
```

## Immediate app-topic requirements

The next app-topic PRs should target:

```text
1. Remove or gate the legacy REST realtime bootstrap fallback.
2. Treat session_accept voiceOutput and voice_mode as canonical.
3. Make app-open conversation_realtime the default RV101 voice path.
4. Implement/verify Cloud Realtime server_vad with Jetson audio gate monitor-only.
5. Keep push_to_talk_realtime manual-turn as fallback/signoff mode.
6. Keep app HUD aligned with iPhone simulator primitives but sized for RV101 optics.
7. Preserve all orientation/profile/FPS metadata in MediaEvent and preview upload.
8. Run the backend signoff harness after each app protocol change.
9. Document every measured RV101 exception in MEASURED_DECISIONS.md.
```
