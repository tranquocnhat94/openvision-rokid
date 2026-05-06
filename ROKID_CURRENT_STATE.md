# Rokid Current State

Updated: 2026-05-01

This file is the active engineering handoff. It intentionally replaces v1-heavy handoffs with the OpenVision guidance-pack philosophy.

## Product Identity

OpenVision Rokid V2 is a cloud-realtime-orchestrated, Jetson-executed wearable AI Skill OS:

```text
glasses / iPhone harness
  -> live camera + microphone + tiny HUD
  -> Cloud Realtime AI for conversation, Vietnamese understanding, and tool choreography
  -> typed Jetson tool server
  -> skill / perception / media / display executors
  -> ToolResult / ToolError / DisplayCommand
  -> glasses / simulator HUD, cards, thumbnails, images, or overlays
```

The long-term shape is OpenClaw-style, but optimized for the physical world: scene understanding, target search, object/person attributes, selected-target follow-up, privacy-aware memory, task coaching, and later external document/mail/tool actions through explicit bridges.

The product direction is platform-first. Reality Radar is an advanced Find
skill and a useful proof point, but it is not the whole product and must not
become a separate route around the shared Skill OS. Build Radar-quality
experiences by strengthening reusable skill, perception, media, HUD, cloud,
memory, replay, and scorecard primitives.

## Ownership

### Rokid Glasses

Owns capture, hardware H.264 encode when commanded, microphone PCM capture, transport, session state, typed media-command execution, thin HUD/display rendering, heartbeat, and minimal diagnostics.

Does not own heavy AI, skill planning, tracking, cloud routing decisions, memory, old mode UI, or complex settings screens.

### iPhone Web Harness

Owns fast backend/cloud/runtime debugging through secure browser capture, WebRTC media, and the same HUD scene contract as the glasses.

It is not a second product. Any simulator-only behavior must be temporary, labelled, and portable back to RV101.

### Jetson

Owns media ingest, audio/video health, local perception runtimes, perception graph, skill registry/runtime, selected-target state, HUD authority, cloud escalation decision, Ops Console, redacted logs, replay, and metrics.

Jetson should stay modular. It must not become another mixed v1 backend pile.

### Cloud AI

Cloud AI owns hard reasoning, ambiguous visual verification, language, web/file/tool workflows, high-value planning, conversation state, Vietnamese understanding, and typed tool selection.

Cloud must mutate Jetson state only through typed tools/results. Direct cloud calls from random skills, UI code, or the glasses app are not acceptable.

### Mini PC / Pi5 / Other Machines

They are helper machines behind Jetson. They can host auxiliary local services, but they must not become command brains unless exposed through a typed Jetson capability.

Current example: mini PC PhoWhisper is a Debug STT sidecar for Ops Console text visibility only.

## Active V2 Status

Implemented in `OpenVision rokid/`:

- Jetson FastAPI service skeleton;
- session store and event trace;
- RV101 TCP H.264/PCM ingest;
- iPhone WebRTC simulator bridge;
- sensor preview MJPEG endpoint for Ops Console;
- OpenAI Realtime bridge as current live cloud AI channel;
- output-audio transcript handling and optional realtime voice output;
- cloud gateway foundation;
- typed skill executor foundation;
- HUD authority and HUD scene contracts;
- perception graph scaffolding;
- optional Debug STT sidecar;
- Ops Console;
- deploy scripts and systemd unit;
- backend test suite.
- docs for cloud-realtime orchestration, media activation, Rokid app runtime contract, Jetson tool server contract, media budgets, and display command families.
- shared schemas and dataclasses for `RealtimeToolCall`, `ToolResult`, `ToolError`, `MediaCommand`, `MediaEvent`, and `DisplayCommand`;
- `JetsonToolServer` skill-tool dispatch path from OpenAI Realtime function calls to manifest-validated skill execution;
- `JetsonToolServer` policy gates for sessions, timeouts, privacy, cloud capability, and per-session budgets;
- MediaCommand Jetson runtime gateway for snapshot, burst clip, and bounded live video start/stop;
- DisplayCommand Jetson runtime adapter to HUD scene protocol;
- skill manifest fields for tool name, media requirements, display capabilities, memory allowance, and cloud behavior;
- skill manifest registry load now enforces `skill_manifest.schema.json` and V2 policy consistency for media modes, cloud behavior, HUD policy, and required non-empty operational declarations;
- replay/scorecard metrics for realtime tool, media command, and display command counts/errors/latency.
- session scorecards now include embedded `skill_eval` gates for typed skill invocation, tool contract, media evidence, HUD output, cloud evidence, identity checks, and skill latency.
- `scripts/export_session_replay.py` can export `/api/replay` plus `/api/scorecard` into ignored `runtime/replays/` artifacts with retention, or re-score a saved replay offline.
- iPhone simulator MediaCommand client adapter: startup is microphone-first, camera stays off until `snapshot`, `burst_clip`, or `live_video`, and client execution reports typed `MediaEvent` status back to Jetson.
- RV101 Android client foundation: control WebSocket, HUD, PTT PCM relay, tailnet default endpoint, Wi-Fi settings assist, and typed snapshot MediaCommand execution are verified on real glasses.
- RV101 snapshot capture now uses Camera2 only after a typed Jetson `snapshot` command, uploads JPEG evidence to `/api/preview/{session_id}/frame`, reports typed `MediaEvent` status, and cleans up with `Active Camera Clients: []` after capture.
- RV101 Android client has real-device verified bounded `burst_clip` execution using Camera2 JPEG still bursts and typed `MediaEvent` telemetry. Tailnet test `media_cmd_1e033b512a19` on `sess_51d3320c2ae7` reported status `ok`, uploaded a 640x480 JPEG preview, sampled 3 frames over 3001 ms, and cleaned up with `Active Camera Clients: []`.
- RV101 Android client now has a thin `live_video` adapter using Camera2 -> MediaCodec H.264 -> RVS1 `tcp_h264`, guarded by Jetson command deadlines, plus app auto-reconnect after WebSocket close/error. H.264 smoke delivered frames to Jetson; product use remains gated until repeated no-restart scorecards and the H.264 decode/preview path are in place.
- Jetson live-video hardening now has runtime epoch metadata on `/api/health` and `scripts/score_rv101_live_no_restart.py` for before/after no-restart scoring. The script is read-only by default and only sends a live_video command when explicitly run with `--start-live`. Guarded RV101 tailnet scorecards passed on `sess_63ce93e47ee8`: `media_cmd_591604215332` plus three repeats all had client-reported final timeout, stable runtime epoch, `active_live_count=0`, H.264 frames recorded, and RV101 camera cleanup `Active Camera Clients: []`.
- RV101 H.264 live preview decode now exists as an optional Jetson runtime hook. `OPENVISION_RV101_H264_PREVIEW=1` enables throttled PyAV decode from RVS1 `tcp_h264` samples into PreviewStore with `/api/health` status; it remains disabled by default in env examples. A bounded USB-tunneled RV101 smoke passed on `sess_29915aa4bc42` / `media_cmd_df5156b5106a`: final timeout, 117 H.264 frames, 115 decoded frames, 4 JPEG previews, HTTP 200 640x360 preview, stable runtime epoch, and RV101 camera cleanup `Active Camera Clients: []`.
- RV101 live-video scorecard now fails if the client reports final `error` or cancellation; `timeout` / `ok` are the accepted successful final states for bounded live smoke tests.
- Realtime visual skills now request typed MediaCommand capture when no perception/preview evidence exists, so cloud tool calls can activate the simulator camera path through Jetson.
- Skill-requested snapshot/burst completion now continues back into the skill runtime after the client reports `MediaEvent` status `ok`, preserving original skill args, updating HUD, and logging `media_continuation_completed`.
- Captured-preview fallback states are explicit: `count_people` reports that a detector/perception snapshot is still missing, while `scene_describe` and `query_scene` build cloud-gateway evidence bundles from preview frames when local perception is unavailable.
- Cloud escalation is enforced at both SkillExecutor and JetsonToolServer boundaries: `needs_cloud` payloads must carry schema-valid `cloud_evidence_bundle`, `cloud_gateway`, and `cloud_result` objects before Cloud Realtime receives them.
- OpenAI Responses visual verification is available behind CloudGateway as an opt-in provider. Jetson can convert local preview refs to data URLs and request structured `cloud_result.v1` without exposing `/api/preview` publicly.
- `scene_describe` is now the first Phase 4 practical skill MVP: open Vietnamese scene questions route through a dedicated typed skill, request fresh snapshot evidence on repeated asks, and return CloudGateway visual verifier answers through HUD/Realtime.
- Skill-requested media continuation now closes the voice loop: after a snapshot/burst completes and the skill re-runs, Jetson sends a constrained internal continuation prompt back to Realtime so the verified result can be spoken, not only rendered as HUD text.
- Snapshot timeout/error/cancelled events from the media client now produce explicit HUD/telemetry failure states, so the user is not left stuck at "Đang bật camera".
- Realtime cloud startup retries transient opening-handshake failures before marking the session as `error`.
- Realtime response creation is serialized so internal media-continuation prompts defer `response.create` while another response is active, preventing overlapping response errors and reducing speech pileups.
- Realtime `session_expired` server errors now expire and close the Jetson connection cleanly instead of leaving the session looking connected after the 60-minute cloud limit.
- Server VAD now waits longer before ending a user turn and allows barge-in interruption of active AI audio.
- Jetson audio gate now defaults to monitor-only for Realtime: it records signal/gate diagnostics, but does not block audio chunks before OpenAI server VAD unless `OPENVISION_REALTIME_AUDIO_GATE_MODE=suppress_idle_noise` is explicitly enabled.
- RV101 backend `session_accept` now declares `voiceMode=conversation_realtime`, `turnPolicy=server_vad`, and the existing voice-output websocket contract by default, while `push_to_talk_realtime` remains an explicit manual-turn fallback. Jetson observes old PTT events during `server_vad` sessions without forcing manual audio clear/commit.
- Session scorecards now include an RV101 voice-contract gate and metrics for voice mode, turn policy, voice output, and observed Realtime turn policies, so a session replay can show whether the product path used `conversation_realtime/server_vad` or an explicit fallback.
- RV101 `glasses_health` event logging is throttled/coalesced so repeated heartbeat-style health messages no longer flood the 1000-event in-memory log and hide skill/realtime errors.
- `target_finder` live person searches opportunistically check the local contact identity DB when face vectors are present, request a 1280x720 live stream budget for person lookup, and keep anonymous HUD aim assist active when no known contact matches.
- Face identity worker now upscales small preview frames, tries rotated orientations, posts face-size/identity-quality attributes, and separates `low_quality_face` from real identity no-match frames before posting detections/embeddings back to Jetson.
- `person_info` has been added as a snapshot-first known-person/profile skill for "có ai quen không", "người này tôi đã gặp chưa", "người này là ai", "cho tôi thông tin về người này", and follow-ups like "còn thông tin gì không". It captures one image by default, runs local Face Identity on the snapshot, compares against the contact identity DB, and enriches confirmed matches from People Registry metadata for short HUD/voice responses.
- `person_info` supports a separate explicit realtime branch for name-reminder mode (`scan_mode=name_reminder` / `live_video`). This is intended for continuous small HUD name hints and is not the default path.
- Face / People Registry now stores extra profile metadata for identity skills: age/birthday, where lives, relationship/why known, first met, flexible facts, phone, address, links, and notes.
- `object_counter` is available as a typed MVP skill for non-person visual counting through fresh snapshot capture, local perception when available, and CloudGateway preview verification otherwise.
- Vietnamese Realtime mocked route tests cover conversational greetings without tool calls and open visual scene questions through typed `scene_describe` tool output.

Recently verified:

- V2 backend tests pass locally;
- Phase 3 typed tool-server contract tests pass locally;
- RV101 debug APK installs and launches against the Jetson tailnet endpoint;
- RV101 snapshot MediaCommand through `jay.tail8dd874.ts.net` produced decoded 640x480 JPEG previews with measured capture/upload latency;
- RV101 bounded burst_clip MediaCommand through `jay.tail8dd874.ts.net` produced a decoded 640x480 JPEG preview and cleaned up the camera;
- RV101 live_video H.264 smoke reached Jetson media metrics; after runtime epoch hardening, four guarded no-restart scorecards passed through `jay.tail8dd874.ts.net`, and preview-enabled USB-tunneled smokes passed. The Android app now honors long live_video budgets beyond the old 10s clamp: `media_cmd_2daaa212b7cb` requested 15000 ms and ended as timeout after about 14.6s with `active_live_count=0`;
- RV101 Android app now supports the backend `person_info` snapshot quality gate: `media_cmd_365205d21714` captured/uploaded 4/4 JPEG frames to PreviewStore in 2437 ms, reported `rv101_snapshot_quality_gate_ready`, and did not timeout;
- RV101 Android HUD now parses/renders Jetson `thumbnails`, `target_hint.aim`, and `target_hint.zoom` in addition to answer/chips. A target_finder HUD scene on `sess_7fac55167834` contained 1 thumbnail, aim arrow `up`, and zoom image URL, with no AndroidRuntime/FATAL/ANR/OOM log after render;
- RV101 PTT stop ordering is corrected in app code: audio relay stop/flush happens before `ptt_up`, which is emitted from `onVoiceStopped`;
- RV101 Android HUD now enforces Jetson `ttl_ms` locally. A tunneled real-device HUD test on `sess_163da4d0114b` showed a `text_hud` command with `ttl_ms=3000`, then cleared back to `Ready` after expiry;
- RV101 Android media capture now checks remaining Jetson command budget before opening camera for snapshot, burst, and live. A tunneled quality-gate retest on `sess_3d7c572adaea` used 2703 ms of remaining budget, completed 4/4 frames in 2620 ms, and left `Active Camera Clients: []`;
- RV101 Android lifecycle now treats the foreground Activity as the media owner. On Activity stop, media polling pauses and active voice/snapshot/burst/live capture is cancelled. A tunneled live_video retest on `sess_384ba8cf70a0` sent HOME while live_video was active; Jetson received final `cancelled`, `active_live_video=false`, `active_live_count=0`, and RV101 camera cleanup was empty;
- RV101 Android app deliberately does not hold `WAKE_LOCK` or `WifiLock`. Wi-Fi/VPN availability is user/device managed so the glasses can sleep radios for battery life;
- RV101 product signoff harness now exists at `OpenVision rokid/scripts/score_rv101_product_signoff.py`. It checks ADB, package permissions, no WifiLock/WakeLock, `session_accept` voice contract, HUD TTL, `person_info` quality_gate snapshot, bounded live_video cleanup, optional PTT fallback, camera cleanup, and stable runtime epoch. It is device-safe and only uses app/user-space ADB actions;
- RV101 PTT Realtime is now an explicit fallback path aligned with the Realtime WebSocket push-to-talk contract: when `push_to_talk_realtime` is requested, audio append events are ordered before commit/response.create and Jetson waits for the RV101 audio stream to close before committing. Default RV101 sessions use `conversation_realtime/server_vad`;
- Jetson `person_info` snapshot quality_gate media commands now get a 5000 ms budget instead of the normal 3000 ms snapshot budget so the RV101 mini-burst can reliably upload 4/4 frames without widening ordinary snapshot cost;
- RV101 tunnel product signoff passed on `sess_7900c7843583` using `scripts/score_rv101_product_signoff.py`: HUD TTL pass, `person_info` quality_gate snapshot `media_cmd_4d903ed0e5fa` uploaded 4/4 frames in 2394 ms, bounded live_video `media_cmd_e1a4abc394e1` sent 108 frames and cleaned up with `active_live_count=0`, historical PTT fallback sent 179 chunks / 343680 bytes and received a Realtime response, runtime epoch stayed stable, no OpenVision WifiLock/WakeLock was held, and RV101 camera cleanup was empty. The report status is `warn` only because the route was USB/ADB tunnel rather than normal tailnet;
- Current caveat: on the latest retest, direct RV101 route to `jay.tail8dd874.ts.net:8765` timed out and Tailscale logs on the glasses reported `network is unreachable`; app/backend verification used SSH local forward plus ADB reverse for 8765/8770/8771. Wi-Fi sleep is considered acceptable product behavior, but normal-route tailnet soak still needs a clean signoff when VPN/routing is healthy;
- Jetson V2 service can start;
- Ring service remains separate;
- OpenAI transcription code paths were removed from V2 active code;
- Debug STT is optional and sidecar-only.

Not finished:

- full normal-route RV101 product APK signoff;
- normal-route RV101 tailnet soak without USB/ADB reverse once Wi-Fi/VPN routing is healthy;
- real-optics HUD polish for thumbnail/aim/zoom sizing, contrast, and occlusion;
- release APK signing/config packaging and operator install docs;
- long-run RV101 battery/thermal/memory soak across repeated snapshot, burst, live_video, HUD, sleep, and reconnect cycles;
- production detector/tracker feeding perception graph;
- repeated preview-enabled Jetson scorecards on the normal target route, then replay/eval hardening before production RV101/Rokid `live_video` media commands;
- visual verifier prompt/eval tuning and fresh iPhone/RV101 signoff logs using exported replay fixtures;
- remaining production practical skills: `target_finder`, `person_info`, and `text_reader`; `object_counter` exists as an MVP and needs replay/eval hardening;
- scorecard/replay tooling deep enough for regression checks beyond the first skill_eval/export baseline;
- YOLO26 integration through a separate Rokid-specific path;
- YOLO26 live preview/perception cleanup: product bbox should come from Jetson-stabilized perception graph output, not raw DeepStream OSD drawing. DeepStream remains a separate OpenVision detector/diagnostic runtime and must not become the product preview authority.
- fresh normal-route RV101 signoff logs.

## Voice And Understanding

There are two different observability questions:

- "What did the mic capture?" can be shown by optional Debug STT.
- "What did the agent decide?" must be shown by tool calls, skill args, skill results, latency, errors, and HUD scene output.

Current policy:

- OpenAI Realtime is the preferred live cloud AI channel for conversation/tool orchestration.
- MVP route is Rokid audio -> Jetson realtime bridge -> Cloud Realtime -> typed Jetson tools -> Rokid display.
- Jetson must not become the local STT/router brain by default.
- Debug STT is only for Web UI visibility of completed Vietnamese speech.
- Debug STT must not route commands, update HUD, or change skill state.
- `gpt-4o-mini-transcribe`, `/api/voice-log`, and OpenAI-backed `AI Heard` must not return.

Target policy:

- cloud-realtime orchestration;
- Jetson typed tool server validates and executes skill/media/display calls;
- camera is off by default and activated only by typed media commands;
- display output goes through typed display/HUD commands;
- cloud escalation uses evidence bundles, privacy/budget gates, and structured results.

## YOLO26 / Ring Boundary

The existing Ring / YOLO26 security runtime is protected.

Rules:

- do not stop it;
- do not replace it;
- do not bind V2 directly to live Ring internals;
- do not share mutable runtime paths;
- build a separate OpenVision/Rokid adapter if YOLO26 assets are reused.

YOLO26 deep integration should wait until the skill registry and perception graph are stable.

## Web UI / Ops Console Direction

Ops Console is product operations tooling, not throwaway debug.

It should show:

- service health and redacted settings;
- media/audio metrics;
- session timeline;
- perception graph snapshot;
- skill registry and skill calls;
- cloud evidence requests/results;
- HUD scene mirror;
- Debug STT sidecar text if enabled;
- replay/export with secrets redacted.

It should not show:

- old mode controls as product UX;
- direct cloud prompts scattered across panels;
- fake skill output as if it were real;
- raw secrets.

## Immediate Next Work

1. Finish canonical docs/schema alignment from `docs/openvision`.
2. Run fresh iPhone simulator and/or RV101 session for stream/audio/HUD/snapshot regression.
3. Add or harden perception graph validation and telemetry.
4. Make skill manifest/registry the product path for all capabilities.
5. Repeat preview-enabled Jetson scorecards on the normal target route before routing product skills to RV101 `live_video`.
6. Harden `scene_describe`, then build remaining first practical skills in order: `target_finder`, `person_info`, `text_reader`, `object_counter`.
7. Tune/evaluate CloudGateway visual verifier prompts against replay fixtures.
8. Promote exported replay fixtures into repeatable regression tests and retention docs.

## Completion Standard

A change is not complete just because code runs. It must:

- match the V2 ownership model;
- preserve thin glasses;
- keep Jetson as realtime authority;
- use cloud through typed escalation;
- produce measurable logs/metrics;
- avoid privacy drift;
- avoid reviving v1 bloat.
