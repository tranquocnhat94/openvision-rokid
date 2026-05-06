# 13 — Roadmap and PR Sequence

This roadmap keeps V2 from drifting.

## Phase 0 — Repo inventory and foundation

Goal:

```text
Understand current repo and add docs/schema boundaries.
```

Deliverables:

```text
AGENTS.md
docs/openvision/*
schema specs
initial PR plan
repo inventory report
```

Do not modify runtime unless needed for documentation discovery.

## Phase 1 — Reliability baseline

Goal:

```text
Prove Rokid -> Jetson -> HUD/audio paths are reliable enough for V2.
```

Deliverables:

```text
stream health metrics
audio health metrics
HUD ping/test scene
session logging
baseline scorecard
```

Acceptance:

```text
video stream stable
audio path measurable
HUD scene can be rendered
logs show latency and failure reasons
```

## Phase 2 — Perception graph MVP

Goal:

```text
Create shared perception state.
```

Deliverables:

```text
perception_graph model
object detection integration
zone computation
JSON snapshot endpoint or log
basic dashboard/log display
```

## Phase 3 — Skill runtime + cloud realtime tool server

Goal:

```text
Create manifest-based skill registry, typed RealtimeToolCall/ToolResult/ToolError models, Jetson tool server dispatch, and media/display command contracts.
```

Deliverables:

```text
skill manifest schema
registry
typed cloud realtime tool-call parser
Jetson tool server
media command and media event schemas
display command schema
sample skills as placeholders
unit tests for mocked Vietnamese cloud realtime tool calls
```

## Phase 4 — Four practical skills

Implement:

```text
scene_describe
target_finder
text_reader
object_counter
```

Acceptance:

```text
each skill has manifest
each skill consumes perception graph
each skill outputs HUD scene
each skill logs latency/confidence
```

## Phase 5 — Cloud gateway enforcement

Goal:

```text
Centralize cloud calls through evidence bundles.
```

Deliverables:

```text
evidence_bundle schema
cloud_gateway module
privacy/budget checks
structured cloud_result validation
fallback logic
```

## Phase 6 — Reality Radar Flagship Skill MVP

Goal:

```text
Natural language target search in real world, built as a flagship skill on top of the shared Skill OS.
```

Reality Radar is not a separate product architecture. It should reuse and
strengthen target parsing, perception graph candidates, media budgets, cloud
evidence bundles, HUD target primitives, replay, and scorecards for the broader
skill ecosystem.

Deliverables:

```text
target query parser
candidate ranking
local direction hint
cloud verifier for ambiguous cases
HUD target marker
reusable target/candidate evidence primitives
```

## Phase 7 — Memory and task coaching

Goal:

```text
Add useful memory and guide abilities without privacy drift.
```

Deliverables:

```text
memory_event schema
user-saved memory
object location memory
task coach prototype
privacy dashboard or controls
```

## Phase 8 — Data flywheel and dashboard

Goal:

```text
Make the system easier to improve.
```

Deliverables:

```text
session dashboard
replay dataset builder
skill evaluation reports
session log-to-patch workflow
```

## Recommended first 10 PRs

1. `docs: lock cloud-realtime orchestrated V2 guidance`
2. `feat: enforce JetsonToolServer timeout privacy budget policy`
3. `feat: implement MediaCommand runtime gateway`
4. `feat: adapt DisplayCommand to HUD scene protocol`
5. `test: add mocked Vietnamese realtime tool-call tests`
6. `feat: enforce cloud gateway for ambiguous skill verification`
7. `feat: add object_counter through typed skill path`
8. `feat: add scene_describe through typed skill path`
9. `feat: add target_finder through typed skill path`
10. `feat: add text_reader local MVP through typed skill path`

## PR size rule

A PR should change one architectural layer at a time.

Avoid PRs that touch all at once:

```text
Android capture
Jetson perception
cloud gateway
dashboard
```

## Merge readiness checklist

Before merge:

```text
changed files are scoped
build/tests run or limitation stated
logs/metrics added for runtime changes
HUD output follows schema
cloud calls go through gateway
privacy impact documented
next PR is clear
```
