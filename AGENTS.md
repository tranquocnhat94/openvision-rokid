# AGENTS.md - OpenVision Rokid V2

## First Read Order

Before substantial work, read these in order:

1. `AGENTS.md`
2. `docs/openvision/00_INDEX.md`
3. `docs/openvision/00_CODEX_START_HERE_CLOUD_REALTIME_V2.md`
4. `PROJECT_MEMORY.md`
5. `ROKID_CURRENT_STATE.md`
6. `ROKID_CODEX_EXECUTION_PACK.md`
7. `OpenVision rokid/README.md`

The canonical architecture and operating philosophy now live in `docs/openvision/`. Older docs are reference or archive unless explicitly named in the current task.

## Mission

Build **OpenVision Rokid V2** as a practical real-world AI Skill OS for smart glasses:

```text
Rokid glasses = eyes + ears + tiny HUD
Cloud Realtime AI = conversational brain + typed tool/skill orchestrator
Jetson = trusted tool server + perception executor + media/display/privacy authority
```

The product should help the user see, understand, find, remember, and act in the physical world.

OpenVision is not a single-feature "radar app". Reality Radar, target finding,
known-person reminders, OCR, counting, scene understanding, memory, and task
coaching are all skills that must run on the same shared Skill OS platform.
Reality Radar is an advanced flagship skill and proof point for the platform,
not the product boundary or the only destination.

## Current V2 Master Direction

The active direction is now **cloud-realtime orchestrated, Jetson-executed, and Rokid-commanded**.

Canonical route:

```text
Rokid voice stream
  -> Cloud Realtime AI, usually relayed by Jetson for the MVP
  -> typed RealtimeToolCall
  -> Jetson tool server
  -> skill / perception / media / display executors
  -> ToolResult / ToolError / DisplayCommand
  -> Rokid HUD, cards, thumbs, images, or overlays
```

Do not restore the old default route:

```text
Rokid -> local STT -> Jetson local router -> cloud fallback
```

Local STT may remain as a debug sidecar, benchmark, emergency fallback, or future explicit offline mode. It must not become the required V2 voice path.

Cloud Realtime may choose tool chains, but it cannot bypass Jetson. Jetson validates every tool, media command, display command, budget, privacy policy, schema, timeout, and scorecard event.

## Core Philosophy

### Rokid stays thin

Rokid should only own:

- camera capture;
- microphone capture;
- low-latency transport to Jetson;
- session state needed for transport;
- typed media-command execution;
- compact HUD/display-command rendering;
- minimal diagnostics.

Rokid must not own heavy AI, skill orchestration, cloud routing decisions, memory, phone-like screens, old mode menus, or product-level skill choice.

### Jetson owns realtime intelligence

Jetson should own:

- stream ingest and health;
- video/audio metrics;
- local detection, tracking, light OCR, and audio gating;
- perception graph;
- typed tool server, skill runtime, and registry;
- local-first skill execution;
- HUD scene generation and authority;
- media command gateway to Rokid;
- display command gateway to Rokid;
- cloud tool-call validation and evidence-bundle enforcement;
- session logs, metrics, replay, and scorecards.

### Cloud Realtime is orchestrator, not unrestricted executor

Cloud Realtime is the preferred conversational/intent/tool orchestration path for V2. It owns Vietnamese understanding, conversation state, high-level planning, tool selection, and final response composition.

Cloud visual reasoning is still bounded: do not send every frame, every simple count, or every high-confidence local answer to cloud. Visual evidence should go through Jetson first so Jetson can run local perception, crop/filter evidence, enforce privacy/budgets, and log scorecards.

Cloud must use typed calls only:

```text
RealtimeToolCall -> JetsonToolServer -> ToolResult / ToolError
```

### V2 is skill-runtime based

Avoid one-off product endpoints such as `/detect`, `/ask`, `/read`, or `/radar` unless they are adapters into the shared runtime.

Preferred flow:

```text
voice/media event -> cloud realtime tool call -> Jetson tool server -> skill runtime / media command / display command
```

### Small HUD, big intelligence

HUD output must be short, useful, and non-distracting. Use typed display commands and shared HUD scene primitives such as answer strips, status chips, direction hints, target markers, alert bursts, object cards, thumbnails, full-image cards when explicitly requested, live overlays, and debug overlays only in debug mode.

## Media Activation Policy

Camera is off by default. Voice may be the primary interaction channel, but it must still have session budget, idle timeout, and explicit stop behavior.

Canonical visual modes:

```text
none
snapshot
burst_clip
live_video
```

Canonical voice modes:

```text
idle
push_to_talk_realtime
wake_realtime
conversation_realtime
mission_realtime
```

Live video is allowed only for explicit live skills such as Reality Radar, active target tracking, navigation-like awareness, traffic/live counting, or scene monitoring. It must include `skill_id`, reason, timeout, FPS/resolution budget, auto-stop, and telemetry.

## Active Workspace

- Active V2 product foundation: `OpenVision rokid/`
- Canonical docs: `docs/openvision/`
- Mirrored V2-local docs: `OpenVision rokid/docs/openvision/`
- V2 Jetson runtime: `OpenVision rokid/jetson/`
- V2 glasses contract: `OpenVision rokid/glasses/`
- V2 iPhone simulator harness: `OpenVision rokid/iphone_web_simulator/`

For RV101/glasses app work, also read
`docs/openvision/27_ROKID_APP_CODEX_ROADMAP.md`. The app topic should follow
the backend and iPhone simulator contracts already proven in this repo; do not
rediscover voice, media, or HUD routes through app-only experiments.

Legacy/reference only:

- `legacy_quarantine/2026-04-29/RokidVideoStream/`
- `legacy_quarantine/2026-04-29/rokidjetson/backend_mvp/`
- `docs/reference/`
- `docs/archive/`
- `legacy_quarantine/2026-04-29/rokidjetson/archive/`

Do not expand legacy paths into the active product unless the user explicitly asks.

## Non-Negotiable Rules

- Do not commit, print, duplicate, or document API keys, secrets, tokens, `.env` files, SSH keys, or private config.
- Do not break, stop, replace, or casually reuse the existing Ring / YOLO26 security runtime on Jetson.
- If reusing YOLO26 assets, use a separate Rokid/OpenVision-specific runtime path.
- Do not claim real-device success unless a real Rokid + Jetson test log proves it.
- Do not add many features before shared schemas/runtime boundaries exist.
- Do not add hidden second brains: local STT, simulator code, dashboard code, or fallback scripts must not route product commands unless they are typed skills or documented runtime owners.
- Do not add direct cloud calls outside the cloud gateway/evidence-bundle architecture.
- Do not render custom product HUD outside the HUD scene protocol.
- Prefer telemetry, replay, and scorecards over guesses.
- Every new skill must declare inputs, outputs, latency class, local/cloud behavior, privacy level, acceptance tests, and failure modes.

## Required Architectural Primitives

Before advanced feature growth, the repo should contain and preserve:

1. perception graph;
2. skill manifest and registry;
3. HUD scene protocol;
4. typed realtime tool-call contract;
5. Jetson tool server contract;
6. media command and media event contract;
7. display command contract;
8. cloud evidence bundle and gateway;
9. session benchmark and replay tools;
10. privacy and memory policy;
11. Codex phase prompts and PR plan.

If these are missing or weak, strengthen them before adding flashy skills.

## Phase Order

Work in this order unless the user explicitly overrides it:

```text
Phase 0: repo inventory + docs/schema foundation
Phase 1: stream/audio/HUD reliability baseline
Phase 2: perception graph MVP
Phase 3: skill runtime + cloud realtime tool server + media/display command contracts
Phase 4: scene_describe, target_finder, text_reader, object_counter
Phase 5: cloud escalation gateway + evidence bundles
Phase 6: Reality Radar flagship-skill MVP
Phase 7: memory + task coaching
Phase 8: dashboard + data flywheel
```

Do not jump to Reality Radar, memory, or large skill packs before Phases 0-3 are solid.
Do not bend the platform around Reality Radar alone. Build reusable primitives
so Radar and future skills share the same runtime, media, perception, HUD,
cloud, memory, replay, and scorecard paths.

## Current Implementation Note

The current V2 code already has a Jetson service, media ingest, iPhone simulator bridge, typed skill executor, typed Realtime tool-call/result/error contracts, a JetsonToolServer skill-tool dispatch skeleton, HUD authority, Ops Console, OpenAI Realtime bridge, cloud gateway foundation, and Debug STT sidecar.

Treat OpenAI Realtime as the current live cloud AI voice/conversation/tool orchestrator. Do not let it justify scattered cloud calls, untyped tool execution, skill-specific media hacks, or display bypasses. The target architecture is cloud-realtime orchestration plus Jetson validation/execution.

Debug STT is an operator visibility sidecar only. It must not become command routing, HUD authority, or a second agent.

## Voice And Skill Policy

Product command path:

```text
Rokid mic -> Jetson Realtime bridge -> Cloud Realtime -> typed Jetson tool call -> skill/media/display executor -> HUD/display command
```

Debug transcript path:

```text
completed audio turn -> optional local/PhoWhisper sidecar -> Ops Console text only
```

Do not reintroduce `gpt-4o-mini-transcribe`, `/api/voice-log`, OpenAI-backed `AI Heard`, transcript-first command routing, or local STT as the default product brain.

Old modes may return only as internal capability profiles behind typed skills. They must not return as glasses UI mode screens.

## Build And Verification

For V2 backend changes:

```bash
cd "OpenVision rokid"
./scripts/check_v2.sh
```

For legacy RV101 app reference changes only:

```bash
cd legacy_quarantine/2026-04-29/RokidVideoStream
./gradlew assembleDebug
./gradlew testDebugUnitTest
```

Docs hygiene:

```bash
rg -n "gpt-4o-mini-transcribe|/api/voice-log|AI Heard|actual OpenAI key|private API key" AGENTS.md README.md PROJECT_MEMORY.md ROKID_CURRENT_STATE.md ROKID_CODEX_EXECUTION_PACK.md docs OpenVision\ rokid
```

## Codex Workflow

For non-trivial work:

1. Read the required docs.
2. Identify the current phase and subsystem owner.
3. Summarize the smallest safe patch, risks, files, and checks before editing when the task is broad.
4. Make one PR-sized change.
5. Add telemetry/tests/docs when behavior changes.
6. Run available checks.
7. Summarize changed files, behavior, tests, and next PR.

Before finalizing, ask:

- Does this preserve cloud realtime as the V2 orchestrator?
- Does this avoid making local STT a main-path dependency?
- Does this keep Jetson as typed executor/tool server, not the language brain?
- Does this keep camera off by default unless a skill/tool requests media?
- Does this route display through typed display/HUD commands?
- Does this strengthen the shared runtime?
- Does this preserve thin glasses?
- Does this keep Jetson central?
- Does this use cloud only as typed escalation?
- Does this create measurable behavior?
- Does this avoid privacy drift and legacy bloat?
