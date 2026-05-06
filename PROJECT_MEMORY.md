# Project Memory

Updated: 2026-05-01

This is the short active memory for OpenVision Rokid V2. Read it after `AGENTS.md`, `docs/openvision/00_INDEX.md`, and `docs/openvision/00_CODEX_START_HERE_CLOUD_REALTIME_V2.md`.

## North Star

OpenVision Rokid V2 is a cloud-realtime-orchestrated, Jetson-executed real-world AI Skill OS for smart glasses.

```text
Cloud Realtime AI = conversation brain + typed tool/skill orchestrator
Jetson = trusted tool server + perception/media/display/privacy authority
Rokid = low-power mic/camera/display terminal
```

This project is a platform, not a single Radar feature. Reality Radar is a
flagship skill in the Find family, but the end goal is a reusable ecosystem
where many skills share perception, media, HUD, cloud evidence, memory, replay,
and scorecard infrastructure.

The product should grow around:

- See: scene description, object detection, OCR, counting;
- Understand: visual reasoning, anomaly explanation, context;
- Find: target/object/person search, direction hints, and Reality Radar as a flagship skill;
- Remember: privacy-aware event/object/location memory;
- Guide: step-by-step coaching in the physical world.

## Active Source Of Truth

- Canonical guidance: `docs/openvision/`
- Active V2 workspace: `OpenVision rokid/`
- V2-local mirror: `OpenVision rokid/docs/openvision/`
- Phase prompts: `.github/codex/prompts/`
- Current V2 routing start file: `docs/openvision/00_CODEX_START_HERE_CLOUD_REALTIME_V2.md`
- Rokid app/media/display guidance: `docs/openvision/17_MEDIA_ACTIVATION_POLICY.md` through `docs/openvision/26_NEXT_PRS_CLOUD_ORCHESTRATED_V2.md`
- Legacy reference only: `legacy_quarantine/2026-04-29/RokidVideoStream/`, `legacy_quarantine/2026-04-29/rokidjetson/backend_mvp/`, `docs/reference/`, `docs/archive/`, `legacy_quarantine/2026-04-29/rokidjetson/archive/`

The old V1 implementation remains useful as historical material on this Mac, but it must not define new V2 product work.

## Current Runtime Status

Implemented in V2:

- Jetson FastAPI agent service;
- RV101 split TCP video/audio ingest;
- iPhone WebRTC simulator bridge;
- event/session trace;
- typed skill executor;
- HUD authority and HUD scene contracts;
- perception graph scaffolding;
- Ops Console surfaces;
- OpenAI Realtime bridge as current live cloud AI channel;
- cloud realtime output/audio transcript handling and optional voice output;
- cloud gateway foundation with typed evidence/result validation, privacy gates, request budget, and provider fallback;
- optional mini PC PhoWhisper Debug STT sidecar;
- deploy/check scripts;
- V2 backend tests.
- shared JSON schemas for skill manifest, perception snapshot, cloud evidence/result, memory event, replay, and scorecard.
- structured session scorecard gates for video FPS, audio signal strength, HUD scene presence, Realtime status, and Debug STT status.
- stream liveness metrics for real video frames: estimated FPS, last frame age, frame count, transport, and resolution.
- audio signal and gate metrics: avg/peak energy, non-silent ratio, strong chunk ratio, gate open/close counts, and forwarded chunk counts. Realtime audio uses `monitor_only` gate mode by default. RV101 sessions now default to app-open `conversation_realtime` with Cloud Realtime `server_vad`; `push_to_talk_realtime` remains an explicit debug/noisy fallback.
- `target_finder` person searches now opportunistically check the local contact identity DB when face vectors exist, so generic live queries can still surface known contacts while no-match frames keep anonymous aim assist active.
- `target_finder` live-video media commands now request a 1280x720 stream budget from the client so the face identity worker receives usable face detail for known-person reminders.
- Face identity worker now upscales small preview frames, tries orientation fallback, reports face-size/identity-quality telemetry, and marks tiny faces as `low_quality_face` so the HUD can ask the wearer to move closer instead of treating the DB check as a true no-match.
- `person_info` is now a typed snapshot-first skill for "có ai quen không", "người này là ai", and profile follow-ups. By default it captures one image, runs local Face Identity on the snapshot, compares with the local contact identity DB, enriches confirmed matches from People Registry, and returns compact HUD/voice answers by requested focus (`name`, `summary`, `contact`, `relationship`, or `full`). If a snapshot contains multiple people, HUD thumbnails carry known names and the user can ask who to focus on.
- `person_info` still has an explicit bounded live branch for realtime name reminders (`scan_mode=name_reminder` / `live_video`), but this is no longer the default path.
- Face / People Registry metadata now supports flexible profile fields for the identity skills: age/birthday, where lives, relationship/why known, first met, and arbitrary facts in addition to phone, address, links, and notes.
- HUD baseline validation: schema-checked HUD scenes, HUD test scene endpoint, latest answer strip, valid scene count, and last HUD age in scorecards.
- completed-session replay scoring: iPhone simulator sessions can be signed off from recorded video/audio/HUD evidence after the browser tab closes.
- session scorecards now embed `skill_eval` gates for typed skill invocation, tool contract, visual media evidence, HUD output, cloud evidence, identity checks, and skill latency.
- `scripts/export_session_replay.py` exports `/api/replay` plus `/api/scorecard` into ignored `runtime/replays/` artifacts with retention, and can re-score a saved replay offline.
- perception graph schema baseline: object zone field, object timestamps, object age, and frame dimensions are serialized into shared schema-compatible snapshots.
- perception graph zone computation: Jetson computes `left_front`, `front`, `right_front`, `near`, `far`, or `unknown` from bbox/frame size when upstream does not provide a valid zone.
- perception graph temporal baseline: recent snapshots are kept per session and objects persist across updates by `track_id` or `object_id`.
- YOLO26 Rokid adapter baseline: disabled by default, accepts only `external_snapshot` mode from Rokid/OpenVision sources, rejects Ring/security sources, and filters detections by minimum confidence before updating the perception graph.
- YOLO26 live product path must route detector frames through a Rokid/OpenVision stabilizer before skills, HUD, or Ops Preview consume bbox data. DeepStream/YOLO26 is detector metadata; the product bbox authority is the Jetson perception graph stable layer, with DeepStream OSD kept diagnostic-only.
- Phase 2 hardening: selected-target skills now publish HUD scenes, Realtime text preserves rich skill HUD elements, skill execution validates manifest input schemas, Realtime tool calls run off the websocket receive loop with bounded send queues, and RV101 TCP ingest no longer defaults to advertising localhost when bound for LAN clients.
- iPhone simulator startup now requests microphone permission before creating the session, starting Realtime, or sending the WebRTC offer, and stops local tracks if startup fails.
- iPhone simulator camera capture is now MediaCommand-driven: the browser keeps camera off at Start, opens it only for `snapshot`, `burst_clip`, or `live_video`, reports typed `MediaEvent` client status back to Jetson, and turns it off after snapshot/burst/stop/timeout.
- RV101 Android client now has a measured typed snapshot MediaCommand path: the app polls Jetson after `session_accept`, opens Camera2 only for a Jetson `snapshot` command while interactive/foreground, uploads JPEG evidence to `/api/preview/{session_id}/frame`, reports typed `MediaEvent` status, and closes the camera after capture.
- Real RV101 tailnet snapshot verification passed through `jay.tail8dd874.ts.net`: latest retest produced `/api/preview/sess_368047352882/frame.jpg`, 640x480 JPEG, 99,470 bytes, 796 ms capture latency, 526 ms upload latency, `Active Camera Clients: []`, and no app crash/dead-thread warning.
- RV101 Android client has real-device verified bounded `burst_clip` support using a Camera2 JPEG still burst and honest sampled-frame telemetry. Tailnet test `media_cmd_1e033b512a19` on `sess_51d3320c2ae7` reported status `ok`, uploaded a 640x480 JPEG preview, sampled 3 frames over 3001 ms, and cleaned up with `Active Camera Clients: []`.
- RV101 Android client now has a thin `live_video` adapter using Camera2 -> MediaCodec H.264 -> RVS1 `tcp_h264`, plus guarded timeout based on Jetson `created_at` and app auto-reconnect after WebSocket close/error. Real-device H.264 smoke delivered frames to Jetson, but product promotion was blocked after a 2026-05-01 foreground retest coincided with Jetson service SIGKILL/restart and in-memory state reset.
- Jetson live-video hardening now has runtime epoch metadata on `/api/health` and `scripts/score_rv101_live_no_restart.py` for before/after no-restart scoring. The script is read-only by default and only sends a live_video command when explicitly run with `--start-live`. Guarded RV101 tailnet scorecards passed on `sess_63ce93e47ee8`: `media_cmd_591604215332` plus three repeats all had client-reported final timeout, stable runtime epoch, `active_live_count=0`, H.264 frames recorded, and RV101 camera cleanup `Active Camera Clients: []`.
- RV101 H.264 live preview decode now exists as an optional Jetson runtime hook. `OPENVISION_RV101_H264_PREVIEW=1` enables throttled PyAV decode from RVS1 `tcp_h264` samples into PreviewStore with `/api/health` status; it remains disabled by default in env examples. A bounded USB-tunneled RV101 smoke passed on `sess_29915aa4bc42` / `media_cmd_df5156b5106a`: final timeout, 117 H.264 frames, 115 decoded frames, 4 JPEG previews, HTTP 200 640x360 preview, stable runtime epoch, and RV101 camera cleanup `Active Camera Clients: []`.
- RV101 live-video scorecard now fails if the client reports final `error` or cancellation; `timeout` / `ok` are the accepted successful final states for bounded live smoke tests.
- RV101 Android app is now aligned with the current backend media/HUD contract: live_video timeout parsing accepts Jetson budgets up to 60000 ms, person_info snapshot `params.quality_gate` uses a Camera2 mini-burst and uploads each JPEG to PreviewStore, HUD scenes parse/render thumbnails plus target_hint aim/zoom, and PTT sends `ptt_up` only after the PCM relay reports stopped. Real-device USB-tunneled verification on `sess_7fac55167834` passed: `media_cmd_365205d21714` quality_gate snapshot uploaded 4/4 frames in 2437 ms, `media_cmd_2daaa212b7cb` live_video honored a 15000 ms command and timed out after about 14.6s with active_live_count returning to 0, and target_finder produced a HUD scene with thumbnail/aim/zoom without Android crash.
- RV101 Android HUD now enforces Jetson `ttl_ms` locally. A real-device tunneled HUD test on `sess_163da4d0114b` showed `TTL test` for a `text_hud` command with `ttl_ms=3000`, then cleared back to `Ready` after expiry.
- RV101 Android media capture now checks remaining Jetson budget before opening camera for snapshot, burst, and live. This prevents stale commands from firing after Wi-Fi sleep/reconnect delays. Real-device tunneled retest `media_cmd_f3e733b80a8d` on `sess_3d7c572adaea` used 2703 ms remaining budget and completed a 4/4 quality_gate snapshot in 2620 ms with camera cleanup empty.
- RV101 Android lifecycle now treats foreground Activity as the owner for media safety. On Activity stop, media command polling pauses and active voice/snapshot/burst/live capture is cancelled. Real-device tunneled retest `media_cmd_1a1531d46f92` on `sess_384ba8cf70a0` sent HOME during live_video; Jetson received final `cancelled`, `active_live_video=false`, `active_live_count=0`, and RV101 camera cleanup was empty.
- RV101 Android app intentionally does not hold Wi-Fi awake. Rokid glasses should be allowed to power-manage radios for battery life; if Wi-Fi/VPN sleeps, the user can wake it and reconnect. OpenVision should not add phone-style always-on network locks unless a future explicit mission mode declares that battery tradeoff.
- During the same RV101 retest, direct glasses-to-tailnet connectivity was not healthy: RV101 `curl http://jay.tail8dd874.ts.net:8765/api/health` timed out and Tailscale logs reported `network is unreachable` to control/log/bootstrap endpoints. App/backend verification therefore used SSH local forward plus ADB reverse; VPN activation/routing remains outside the OpenVision app.
- RV101 product-contract signoff harness exists at `scripts/score_rv101_product_signoff.py`. It safely checks ADB/package state, no WifiLock/WakeLock, `session_accept` voice contract, HUD TTL, `person_info` quality_gate snapshot, bounded live_video cleanup, optional PTT fallback, camera cleanup, and stable runtime epoch. It verifies/creates the full USB tunnel path for 8765 control/HTTP, 8770 H.264, and 8771 PCM audio.
- RV101 tunnel signoff passed on `sess_7900c7843583`: HUD TTL pass, quality_gate snapshot `media_cmd_4d903ed0e5fa` uploaded 4/4 frames in 2394 ms, live_video `media_cmd_e1a4abc394e1` sent 108 frames and returned `active_live_count=0`, historical PTT fallback sent 179 chunks / 343680 bytes and got a response, camera cleanup was empty, and runtime epoch stayed stable. Status is `warn` only because it used USB/ADB tunnel instead of the normal tailnet route.
- Jetson PTT ordering fixes remain available for the explicit `push_to_talk_realtime` fallback: manual commit/response.create are ordered behind queued audio appends, and Jetson waits for RV101 TCP audio stream close before committing. The default RV101 product path is no longer manual-turn PTT.
- Jetson `person_info` quality_gate snapshot budget is now 5000 ms, while ordinary snapshot remains 3000 ms.
- Realtime visual skills now request a typed `MediaCommand` before returning `no_evidence` when a session lacks perception/preview evidence, so Cloud Realtime tool calls such as `scene_describe`, `query_scene`, or `count_people` can cause Jetson to ask the client for fresh camera capture.
- Completed snapshot/burst `MediaEvent` reports from skill-requested media commands now continue back into the skill runtime once Jetson has preview/perception evidence, updating HUD and telemetry instead of leaving the user at "Đang bật camera".
- `count_people` now reports a captured-preview/no-detector state when snapshot evidence exists but no perception snapshot is available, and `scene_describe`/`query_scene` package captured preview evidence through the cloud gateway when local perception is missing.
- Phase 4 has started with `scene_describe`: open Vietnamese scene requests route to a dedicated typed skill, request a fresh snapshot for each Realtime scene turn, and use CloudGateway visual verifier output for concise HUD/voice answers.
- Media continuation is now voice-aware and failure-safe: completed skill-requested snapshots prompt Realtime to speak the post-capture result, while timeout/error/cancelled media events publish a clear HUD/user message instead of leaving the session stuck at "Đang bật camera".
- Realtime cloud session startup now retries transient opening-handshake failures before marking the session failed, improving first-session reliability on unstable network starts.
- Realtime response creation is now serialized: Jetson defers `response.create` while a Realtime response is active to avoid `conversation_already_has_active_response` errors and overlapping speech.
- Realtime `session_expired` server errors are now treated as terminal: Jetson marks the session `expired`, clears response state, closes the websocket, and allows the next start to create a clean cloud session.
- Server VAD is more patient and supports barge-in: longer silence duration reduces mid-sentence turn cuts, while user speech can interrupt active AI audio.
- RV101 backend sessions now default to `voice_mode=conversation_realtime` with Cloud Realtime `turn_policy=server_vad`, expose `voiceMode` / `voice_mode` and `turnPolicy` / `turn_policy` in `session_accept`, and keep `push_to_talk_realtime` manual-turn as an explicit fallback. If an old app sends `ptt_down` / `ptt_up` during a `server_vad` session, Jetson logs it but does not force manual clear/commit.
- Session scorecards now surface the RV101 voice contract: `rv101_voice_contract`, `rv101_voice_mode`, `rv101_turn_policy`, and observed Realtime turn policies make `conversation_realtime/server_vad` vs explicit PTT fallback visible in `/api/scorecard/{session_id}`.
- RV101 `glasses_health` control messages are now coalesced in the event log: repeated identical heartbeats are throttled, while state changes and periodic summaries remain visible so logs do not hide skill/realtime events.
- `object_counter` has been added as a typed Phase 4 MVP skill for non-person visual counting requests such as "có bao nhiêu hạt" or "đếm mấy cái", using local perception when available and CloudGateway preview verification otherwise.
- Cloud escalation is now enforced at the skill/tool boundary: any `needs_cloud` skill payload must include a schema-valid `cloud_evidence_bundle`, `cloud_gateway` response, and `cloud_result`, or SkillExecutor/JetsonToolServer returns `invalid_cloud_escalation`.
- CloudGateway can now use an opt-in OpenAI Responses visual verifier provider. Jetson resolves local preview refs into data URLs, requests structured `cloud_result.v1`, and keeps the provider disabled unless `OPENVISION_CLOUD_VERIFY_ENABLED=1`.
- cloud-realtime V2 guidance docs are installed for media activation, Rokid app runtime contract, voice/cloud routing, Jetson tool server, media budgets, display command families, and next PRs.
- typed `RealtimeToolCall`, `ToolResult`, and `ToolError` contracts now exist in shared schemas and Jetson dataclasses.
- Realtime function calls now route through `JetsonToolServer` for skill-tool validation and dispatch before returning typed tool results/errors to Cloud Realtime.
- `JetsonToolServer` enforces session, timeout, privacy, cloud-capability, and per-session budget policy gates.
- Vietnamese Realtime mocked route coverage now locks in that greetings/social turns stay conversational with no tool call, while open visual scene questions route through typed `scene_describe` tool results.
- skill manifests now expose `tool_name`, media requirements, display capabilities, memory allowance, and cloud behavior fields.
- skill manifests are validated at registry load against `skill_manifest.schema.json` plus V2 media/cloud/HUD policy checks, so invalid skill contracts fail fast before reaching Realtime tools.
- shared `MediaCommand`, `MediaEvent`, and `DisplayCommand` JSON schemas are installed as contracts.
- MediaCommand Jetson runtime gateway validates session, skill, reason, timeout, FPS/resolution budget, auto-stop, and start/stop live-video state.
- DisplayCommand Jetson runtime adapter validates text HUD, object cards, thumbnail cards, full images, live overlays, debug overlays, and clear commands before adapting them to HUD scenes.
- scorecards now surface realtime tool, media command, and display command counts/errors/latency metrics from event logs.
- SkillExecutor now writes compact replay summaries for args/results without raw names, profile text, phone numbers, addresses, or full user queries; sensitive visible answers remain only in the normal HUD/replay surfaces that are local and ignored from git.

Not finished:

- full normal-route RV101 product APK signoff;
- release APK signing/config/operator install docs;
- long-run RV101 battery/thermal/memory soak;
- production detector/tracker feeding the perception graph;
- repeated preview-enabled scorecards on the normal target route, then replay/eval hardening before RV101 `live_video` becomes a product skill path;
- visual verifier prompt/eval tuning and fresh iPhone/RV101 signoff logs using exported replay fixtures;
- replay/scorecard tooling deep enough for real benchmarks beyond the first skill_eval/export baseline;
- remaining first-four skills at production quality: `target_finder`, `person_info`, and `text_reader`; `scene_describe` and `object_counter` have MVP runtime paths but still need replay/eval tuning.

## Current Phase

The project is now moving from Phase 3 into:

```text
Phase 4: first practical skills through typed runtime
```

Read `docs/openvision/18_IMPLEMENTATION_PLAYBOOK.md` before continuing implementation. It is the practical checklist for Phase 1 through Phase 8.

The next work should strengthen primitives before adding feature volume:

1. keep using fresh iPhone simulator sessions as the Phase 1 regression loop;
2. repeat preview-enabled Jetson scorecards on the normal target route before routing product skills to RV101 `live_video`;
3. harden preview-backed `scene_describe` with replay fixtures and answer-quality checks;
4. tune/evaluate the CloudGateway visual verifier prompts against replay fixtures;
5. promote exported replay fixtures into regression tests and retention docs.

## Voice Direction

Current V2 should use OpenAI Realtime as the live cloud AI channel for conversation/tool choice.

Target discipline:

- Jetson remains the runtime owner;
- Cloud Realtime is the conversational/tool orchestrator;
- Jetson is the typed executor/tool server and media/display/privacy authority;
- skills, media commands, display commands, and tool calls are typed and observable;
- cloud calls become evidence-bundle escalations;
- Debug STT is only operator visibility;
- local STT must not route commands unless it is explicitly promoted into a typed runtime owner.

Do not re-add `gpt-4o-mini-transcribe`, `/api/voice-log`, OpenAI-backed `AI Heard`, or transcript-first product routing.

## Cleanliness Rule

Every experiment must end as one of:

- `promote`: active runtime, tested, documented, observable;
- `quarantine`: lab/archive path, off by default and labelled;
- `remove`: gone from active code/config/UI/tests/docs.

Do not keep failed branches, stale settings, hidden flags, dead tests, or old docs in the active path.

## Hard Boundaries

- Do not touch or break Ring / YOLO26 security runtime.
- If YOLO26 assets are reused, create a separate OpenVision/Rokid runtime path.
- Do not commit secrets or private config.
- Do not claim device success without logs.
- Keep Rokid thin and HUD small.
- Keep the iPhone simulator aligned with the glasses contract.
