# 22 — Rokid Cloud Audio Bridge

## Purpose

Define how Rokid voice reaches cloud realtime AI without falling back to the V1 local-STT-first architecture.

## The main question

Should the glasses stream voice directly to cloud realtime, or should they send voice to Jetson first and let Jetson bridge to cloud realtime?

## Option A — Rokid -> Jetson -> Cloud Realtime

```text
Rokid mic PCM/Opus
  -> Jetson realtime bridge
  -> OpenAI realtime session
  -> tool calls handled by Jetson
  -> display commands returned to Rokid
```

### Pros

- Easiest to implement before the Rokid app is mature.
- API keys stay off the glasses.
- Jetson can mint sessions, attach session IDs, log audio health, and score latency.
- Tool calls are naturally handled on Jetson.
- Cloud output and Jetson skill execution stay synchronized.
- Works even if Android WebRTC client support on the glasses is awkward.

### Cons

- Adds one network hop for audio.
- Jetson must maintain realtime bridge code.
- If Jetson audio relay is poorly implemented, latency can increase.

### Best use

Use this as the first production V2 path.

It is not V1 as long as Jetson does not transcribe locally and route locally. Jetson is only a realtime bridge and tool server.

## Option B — Rokid -> Cloud Realtime direct

```text
Rokid mic via WebRTC
  -> cloud realtime AI
  -> function/tool calls
  -> Jetson tool server
  -> display commands
  -> Rokid
```

### Pros

- Lowest conceptual voice path.
- Offloads realtime audio handling to the cloud session.
- Matches the V2 “cloud orchestrator” idea most directly.
- May feel more natural for continuous conversation.

### Cons

- Requires robust WebRTC/client session handling on Rokid/Android.
- Requires ephemeral token minting.
- Tool calls must be forwarded to Jetson safely.
- More complex reconnection/session recovery.
- Harder to keep scorecard and traces complete unless the app forwards all events.
- Cloud cannot directly command hardware; Jetson/glasses still need a trusted command path.

### Best use

Use after Option A is stable, or for explicit `conversation_realtime` mode.

## Recommended phased approach

### Phase R0 — Realtime bridge via Jetson

Implement:

```text
Rokid audio -> Jetson bridge -> cloud realtime
```

Jetson does not run local STT. Jetson only:

- forwards audio,
- receives realtime events,
- executes tool calls,
- sends tool results back,
- sends display/HUD commands to Rokid,
- and logs scorecard metrics.

### Phase R1 — Ephemeral direct-to-cloud pilot

Add optional mode:

```text
Rokid audio -> cloud realtime direct
```

Jetson mints ephemeral tokens and registers a session.

The glasses app forwards tool calls/results between cloud session and Jetson, or the cloud calls a Jetson-exposed tool gateway if the network/security setup allows it.

### Phase R2 — Hybrid selection

Choose path per session:

- app-open conversation_realtime: Option A first, Option B later when stable,
- push-to-talk fallback/debug command: Option A,
- long conversation: Option B,
- debugging: Option A,
- unstable network: Option A,
- lower latency cloud voice mode: Option B.

## Audio activation policy

RV101 product default may start cloud realtime audio when the app opens an
OpenVision foreground session. Do not keep it active forever in the background
or after session stop.

Recommended modes:

- `conversation_realtime`: default app-open voice mode with Cloud server_vad.
- `wake_realtime`: future battery mode; local "Hey Vision" trigger opens the
  same Cloud server_vad conversation path, then Cloud/Jetson stop returns to
  standby.
- `push_to_talk_realtime`: debug/noisy fallback; cloud session short-lived.
- `mission_realtime`: explicit mode for task coaching or Reality Radar.

## Budget defaults

Initial defaults:

```yaml
push_to_talk_realtime:
  max_duration_ms: 12000
  silence_end_ms: 1200
  cloud_audio: true

conversation_realtime:
  max_duration_ms: 180000
  idle_timeout_ms: 20000
  turn_policy: server_vad
  cloud_audio: true

wake_realtime:
  max_duration_ms: 180000
  idle_timeout_ms: 20000
  local_wake_only: true
  turn_policy: server_vad
  cloud_audio: true

mission_realtime:
  max_duration_ms: 300000
  idle_timeout_ms: 30000
  cloud_audio: true
```

## Required telemetry

Log for each realtime session:

- session_id,
- route: `jetson_bridge` or `direct_cloud`,
- audio start/stop time,
- first audio to first model event latency,
- model tool call latency,
- tool execution latency,
- display update latency,
- reconnect count,
- bytes sent,
- cloud token/cost estimate if available,
- and failure reason.

## Do not do

Do not implement local STT as the default route.
Do not stream camera along with voice by default.
Do not store raw audio by default.
Do not let the cloud issue unvalidated hardware commands.
