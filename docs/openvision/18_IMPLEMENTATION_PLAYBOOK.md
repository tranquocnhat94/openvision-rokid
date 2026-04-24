# 18 — Implementation Playbook

Updated: 2026-04-25

This is the practical step-by-step execution plan for OpenVision Rokid V2.

Use this file when starting a new implementation topic so the project does not drift, duplicate old V1 logic, or jump into advanced skills before the platform is ready.

## Current Checkpoint

Current public `main` already contains:

```text
Phase 0 docs/guidance foundation
repo inventory
shared JSON schemas
manifest-driven skill registry
perception snapshot MVP
HUD authority MVP
session replay/scorecard skeleton
Phase 1 PR 1.1 structured scorecard gates
iPhone simulator bridge
RV101 TCP ingest skeleton
OpenAI Realtime bridge
Debug STT sidecar
YOLO26 adapter disabled by default
```

Still not complete:

```text
durable replay files
real stream/audio/HUD baseline from fresh iPhone/RV101 sessions
temporal perception graph
cloud evidence gateway runtime
Vietnamese local router
production first-four skills
clean buildable V2 Android app
```

## Preflight For Every New Work Session

Before editing:

```bash
git status --short --branch
sed -n '1,120p' docs/openvision/00_INDEX.md
sed -n '1,260p' docs/openvision/18_IMPLEMENTATION_PLAYBOOK.md
```

Rules:

```text
work from main unless the user explicitly asks for another branch
do not touch dirty legacy V1 files unless the task is specifically about them
keep changes inside active V2 paths such as `jetson/`, `shared/`, `docs/openvision/`, `ops/`, and `scripts/`
run ./scripts/check_v2.sh before claiming done
commit one PR-sized phase slice
```

## Standard PR Shape

Every PR-sized change must answer:

```text
Which phase is this?
Which owner module changed?
Which schemas/contracts are used?
What telemetry or scorecard signal proves it?
What tests ran?
What remains missing?
```

Avoid one PR that touches all at once:

```text
Android capture
Jetson perception
cloud gateway
dashboard
skills
```

## Phase 0 — Foundation

Goal:

```text
Make docs, schemas, inventory, and execution rules concrete enough that future implementation work does not start from V1 assumptions.
```

Current status:

```text
mostly complete
```

Already done:

```text
docs/openvision guidance pack
repo inventory
phase docs
shared JSON schemas
manifest skill registry
replay/scorecard skeleton
V2 tests
```

Remaining cleanup:

```text
keep legacy V1 dirty files out of active V2 commits
do not add more Phase 0 docs unless they clarify execution
```

Exit rule:

```text
./scripts/check_v2.sh passes
contributors can identify active V2 paths and legacy paths correctly
```

## Phase 1 — Stream / Audio / HUD Reliability Baseline

Goal:

```text
Prove iPhone/RV101 -> Jetson -> HUD/audio paths are measurable, visible, and scoreable.
```

PR 1.1: strengthen scorecard gates

```text
owner: jetson/agent/session_replay.py
add gates for video fps, audio strong chunk ratio, HUD scene present, realtime status, debug STT status
add thresholds in one constants block
tests: session scorecard pass/warn/fail
status: done
```

PR 1.2: stream metrics baseline

```text
owner: jetson/media_gateway
record video frame count, fps estimate, last frame age, transport, resolution
surface in /api/media and /api/scorecard
tests: media gateway metrics
```

PR 1.3: audio metrics baseline

```text
owner: jetson/audio_turns + media_gateway
record avg_abs, peak_abs, non_silent_ratio, strong chunk ratio, gate open/close counts
scorecard reports weak audio clearly
tests: silence vs speech scorecard
```

PR 1.4: HUD baseline

```text
owner: jetson/hud_authority
add HUD ping/test scene with schema validation
record HUD scene count, last HUD age, latest answer strip
tests: HUD scene updates scorecard
```

Manual Phase 1 test:

```text
start V2 service
open iPhone simulator
create session
send camera/mic
start Realtime if key is present
trigger sample HUD
check /api/scorecard/{session_id}
export /api/replay/{session_id}
```

Exit rule:

```text
scorecard can tell why a session passed, warned, or failed
video/audio/HUD evidence appears in replay
no claim of RV101 success without RV101 logs
```

## Phase 2 — Perception Graph MVP

Goal:

```text
Turn detector output into shared perception state that every skill can read.
```

PR 2.1: schema-aligned graph model

```text
owner: jetson/perception
add zone field, timestamps, object age, frame dimensions
keep snapshot JSON compatible with shared schema
tests: graph serializes with optional fields missing
```

PR 2.2: zone computation

```text
owner: jetson/perception
compute left_front/front/right_front/near/far/unknown from bbox + frame size
tests: bbox-to-zone cases
```

PR 2.3: temporal graph

```text
owner: jetson/perception
keep recent snapshots per session
track last_seen, first_seen, simple object continuity by track_id/object_id
tests: object persists across updates
```

PR 2.4: YOLO26 external snapshot integration

```text
owner: jetson/perception/yolo26_rokid_adapter.py
accept only separate Rokid-specific external_snapshot source
never bind to Ring runtime process
tests: adapter disabled by default, accepts only explicit mode
```

Exit rule:

```text
skills can answer from perception graph without touching detector internals
Ops Console can show latest perception snapshot
Ring/YOLO26 security runtime remains untouched
```

## Phase 3 — Skill Runtime + Vietnamese Voice Router

Goal:

```text
Make every capability a typed skill and route Vietnamese phrases predictably.
```

PR 3.1: manifest validation

```text
owner: jetson/skills
validate every skills/manifests/*.json against skill_manifest.schema.json
fail tests if required fields are missing
```

PR 3.2: runtime dispatch map

```text
owner: jetson/skills
separate manifest loading from executor adapter dispatch
unknown skill must fail cleanly
tests: manifest exists but runtime missing returns not_implemented
```

PR 3.3: Vietnamese router MVP

```text
owner: jetson/skills or jetson/realtime_agent
map common Vietnamese phrases to skill names and args
do not use Debug STT as product brain
tests: phrases in 16_ACCEPTANCE_TESTS route correctly
```

PR 3.4: Realtime tool discipline

```text
owner: jetson/realtime_agent
only expose manifest-backed tools
tool results update skill trace and HUD authority
tests: tool call -> skill result -> HUD scene
```

Exit rule:

```text
Vietnamese phrase route can be tested without cloud
OpenAI Realtime can still choose typed tools
all skill outputs are observable and schema-backed
```

## Phase 4 — Four Practical Skills

Goal:

```text
Ship four useful skills that prove the skill OS shape.
```

Required skills:

```text
scene_describe
target_finder
text_reader
object_counter
```

Build order:

```text
1. object_counter from perception graph
2. scene_describe from perception graph summary
3. target_finder from local candidates + HUD direction
4. text_reader with OCR placeholder, then real OCR runtime
```

Each skill must have:

```text
manifest
executor adapter
tests
telemetry
HUD scene output
no direct cloud call
fallback/no-evidence behavior
```

Exit rule:

```text
each skill consumes perception graph
each skill returns short HUD output
scorecard records skill success/failure
```

## Phase 5 — Cloud Escalation Gateway

Goal:

```text
Centralize every cloud reasoning call behind evidence bundles.
```

PR 5.1: cloud gateway module

```text
owner: jetson/cloud_gateway or jetson/agent until split
input: cloud_evidence_bundle.v1
output: cloud_result.v1
no random module may call cloud directly
tests: validates request/result
```

PR 5.2: privacy and budget gates

```text
owner: cloud_gateway
block cloud when allow_cloud=false
log privacy level, contains_face, max_answer_chars
tests: blocked case returns safe HUD fallback
```

PR 5.3: target attribute resolver

```text
owner: cloud_gateway + skills/target_finder
send only selected crops/evidence, not full video stream
validate structured answer
update HUD through HUD authority
```

Exit rule:

```text
skills never call cloud directly
cloud timeout/failure has safe fallback
cloud usage appears in replay/scorecard
```

## Phase 6 — Reality Radar MVP

Goal:

```text
Natural-language real-world target search with local candidates, optional cloud verification, and compact HUD direction.
```

Build only after Phase 2, 3, and 5 are stable.

Minimum behavior:

```text
"tìm người áo vàng" -> target_finder
local graph narrows person candidates
cloud verifies ambiguous attributes only when needed
HUD shows short answer + direction/marker/thumb
not-found does not hallucinate
```

Exit rule:

```text
simple target search works within measurable latency
ambiguous attributes use cloud gateway
scorecard shows local/cloud split
```

## Phase 7 — Memory + Task Coaching

Goal:

```text
Add useful memory and task guidance without privacy drift.
```

Build only after memory policy and cloud gateway are real.

Minimum behavior:

```text
memory_event.v1
session-only memory by default
explicit user_saved memory only on user intent
delete_allowed always true for user memories
task coach emits short HUD steps, not long paragraphs
```

Exit rule:

```text
no long-term visual memory without explicit intent
memory events are visible and deletable
HUD remains small
```

## Phase 8 — Dashboard + Data Flywheel

Goal:

```text
Make sessions easier to improve by replaying, scoring, and turning failures into scoped patches.
```

Build order:

```text
durable replay export
score_session CLI
session dashboard
skill evaluation reports
failure reason clustering
developer issue template from session failure
```

Exit rule:

```text
one failed session can produce a reproducible replay and a narrow next patch
```

## Do Not Skip List

Do not do these early:

```text
full AR UI
face recognition by default
continuous full-video cloud upload
20 skills at once
skill-specific HUD rendering
direct cloud calls inside skills
moving heavy AI to glasses
touching Ring/YOLO26 security runtime
```

## Current Next Step

Start with Phase 1:

```text
PR 1.2 stream metrics baseline
PR 1.3 audio metrics baseline
PR 1.4 HUD baseline
```

Only after Phase 1 is measurable, continue to Phase 2 perception graph hardening.
