# Rokid Codex Execution Pack

Updated: 2026-04-29

This is the active execution pack for future coding agents. It exists to keep OpenVision Rokid V2 from drifting back into v1-style bloat.

## First Rule

The active product is OpenVision Rokid V2.

Canonical docs:

- `AGENTS.md`
- `docs/openvision/00_INDEX.md`
- `docs/openvision/*`
- `docs/openvision/00_CODEX_START_HERE_CLOUD_REALTIME_V2.md`
- `docs/openvision/18_IMPLEMENTATION_PLAYBOOK.md`
- `PROJECT_MEMORY.md`
- `ROKID_CURRENT_STATE.md`
- `OpenVision rokid/README.md`

Legacy/reference only:

- `legacy_quarantine/2026-04-29/RokidVideoStream/`
- `legacy_quarantine/2026-04-29/rokidjetson/backend_mvp/`
- `docs/reference/`
- `docs/archive/`
- `legacy_quarantine/2026-04-29/rokidjetson/archive/`

Do not expand legacy paths unless explicitly asked.

## Architecture To Preserve

```text
Rokid / iPhone harness
  -> voice/media event
  -> Cloud Realtime AI for conversation/tool orchestration
  -> typed Jetson tool server
  -> skill / perception / media / display executor
  -> ToolResult / ToolError / DisplayCommand
  -> tiny HUD/display renderer
```

The product experience should let the user naturally ask:

- what is in front of me?
- how many people/objects are there?
- find the person/object with this attribute;
- show me a small target/thumb/direction hint;
- remember or guide me through a real-world task.

Do not reduce the product to Reality Radar. Radar is a flagship Find skill
that should prove the platform works under live target-search pressure. It is
not a separate architecture, not a product endpoint family, and not the only
goal. Build reusable Skill OS primitives first so Radar, OCR, counting,
known-person reminders, memory, and coaching all benefit.

## Required Runtime Primitives

Before adding feature volume, strengthen:

1. perception graph;
2. skill manifest and registry;
3. typed RealtimeToolCall / ToolResult / ToolError;
4. Jetson tool server contract;
5. media command and media event contract;
6. display command contract;
7. HUD scene protocol;
8. cloud evidence bundle and gateway;
9. session benchmark/replay/scorecard;
10. privacy and memory policy;
11. Codex phase prompts and PR plan.

## Phase Order

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

Do not jump to advanced skills before Phases 0-3 are solid.

## Non-Negotiable Constraints

- Do not commit or print API keys, secrets, private config, `.env` files, or raw sensitive bundles.
- Do not stop, replace, mutate, or casually reuse Ring / YOLO26 security runtime.
- Keep any YOLO26 reuse in a separate OpenVision/Rokid adapter/runtime path.
- Keep glasses thin: capture, encode, mic, transport, session, HUD.
- Keep iPhone harness aligned with RV101; it is not another product.
- Avoid direct cloud calls outside cloud gateway/evidence bundle.
- Avoid custom product HUD outside the HUD scene protocol.
- Prefer logs, metrics, replay, and scorecards over guesses.

## Voice Policy

Current live channel should use OpenAI Realtime as the cloud orchestrator, but architecture discipline remains:

```text
Rokid audio -> Jetson realtime bridge -> Cloud Realtime -> typed Jetson tool call -> skill/media/display executor -> HUD/display command
```

Debug transcript path:

```text
completed audio turn -> optional local/PhoWhisper sidecar -> Ops Console text only
```

Do not reintroduce:

- `gpt-4o-mini-transcribe`;
- `/api/voice-log`;
- OpenAI-backed `AI Heard`;
- OpenAI transcription as default product observability;
- transcript-first command routing;
- local STT as the default product brain.

## Skill Policy

Every new skill must have:

- manifest;
- typed inputs/outputs;
- typed tool mapping;
- latency class;
- media requirements;
- display capabilities;
- local/cloud behavior;
- privacy level;
- activation phrases;
- acceptance tests;
- failure modes;
- telemetry;
- HUD scene output.

Old modes can become internal capability profiles only when activated behind typed skills.

## Work Order

1. Read `AGENTS.md`, `docs/openvision/00_INDEX.md`, and `docs/openvision/00_CODEX_START_HERE_CLOUD_REALTIME_V2.md`.
2. Identify current phase and subsystem owner.
3. Locate the smallest safe patch.
4. Keep edits within the owner.
5. Add telemetry/tests/docs when behavior changes.
6. Run available checks.
7. State what was not tested.

## Useful Checks

V2 backend:

```bash
cd "OpenVision rokid"
./scripts/check_v2.sh
```

Docs drift:

```bash
rg -n "gpt-4o-mini-transcribe|/api/voice-log|AI Heard|actual OpenAI key|private API key" AGENTS.md README.md PROJECT_MEMORY.md ROKID_CURRENT_STATE.md ROKID_CODEX_EXECUTION_PACK.md docs "OpenVision rokid"
```

Legacy Android only when intentionally touched:

```bash
cd legacy_quarantine/2026-04-29/RokidVideoStream
./gradlew assembleDebug
./gradlew testDebugUnitTest
```

## Next High-Value PRs

Follow `docs/openvision/18_IMPLEMENTATION_PLAYBOOK.md`.

Immediate next PRs:

1. `feat: enforce strict skill manifest schema validation`
2. `test: add Vietnamese realtime mocked route coverage`
3. `feat: enforce cloud gateway evidence bundles across ambiguous skills`
4. `feat: add MediaCommand client capture adapter for simulator/Rokid`
5. `feat: add object_counter scene_describe target_finder text_reader through typed tools`

## Completion Standard

A patch is complete only when it:

- strengthens the shared runtime;
- preserves cloud realtime as the V2 orchestrator;
- keeps Jetson as typed executor/tool server;
- keeps camera off by default unless media is requested;
- preserves thin-glasses principle;
- keeps Jetson as realtime authority;
- uses cloud as typed escalation;
- emits measurable behavior;
- avoids privacy drift;
- does not revive legacy bloat.
