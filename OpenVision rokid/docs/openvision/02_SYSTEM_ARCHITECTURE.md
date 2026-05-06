# 02 — System Architecture

## One-line architecture

```text
Rokid voice/media -> Cloud Realtime tool orchestration -> Jetson typed tool server -> skills/media/display -> Rokid HUD/display
```

MVP voice route may relay audio through Jetson:

```text
Rokid mic -> Jetson Realtime bridge -> Cloud Realtime -> Jetson typed tools -> Rokid display
```

This replaces the older default path where Jetson/local STT was the language brain.

## Layer 1: Rokid glasses

Responsibilities:

```text
camera capture
microphone capture
low-latency transport when commanded
session heartbeat
typed media command execution
compact HUD/display rendering
basic user input if available
```

Non-responsibilities:

```text
heavy AI
complex model inference
cloud routing decisions
skill orchestration
long-term memory
phone-like UI screens
```

## Layer 2: Stream ingest

This layer receives and normalizes raw input:

```text
video frames / encoded stream
audio PCM / encoded audio
session metadata
clock/timestamp alignment
network health
```

Outputs:

```text
frame events
audio chunks
stream health metrics
session id
```

## Layer 3: Local perception runtime

This layer creates the shared world state.

Core functions:

```text
object detection
tracking
OCR
pose/keypoints, optional
simple attributes: color, zone, direction, motion
risk cues
frame crop/evidence management
```

Output:

```text
perception_graph
```

## Layer 4: Audio/voice runtime

Core functions:

```text
short-lived realtime audio session management
optional Jetson relay to Cloud Realtime
tool-call event capture
latency metrics
local STT only as debug/fallback, not default brain
```

Cloud Realtime owns:

```text
conversation state
Vietnamese understanding
tool and skill choreography
multi-step planning
final response composition
```

Output:

```text
RealtimeToolCall
ToolResult / ToolError
latency metrics
```
## Layer 5: Jetson tool server

Jetson validates and executes every cloud-requested action.

Inputs:

```text
RealtimeToolCall
session state
skill manifests
privacy/media budgets
perception graph
```

Outputs:

```text
ToolResult
ToolError
MediaCommand
DisplayCommand
scorecard events
```

## Layer 6: Skill runtime

The skill runtime executes typed skills. It should not be the default language brain.

Inputs:

```text
transcript_event
RealtimeToolCall
perception_graph
session state
memory context
skill manifests
```

Outputs:

```text
skill_result
hud_scene
voice_reply
cloud_evidence_bundle, optional
memory_event, optional
```

## Layer 7: Cloud escalation gateway

This layer decides when and how to call cloud AI.

It should send compact evidence, not raw continuous streams:

```text
user query
perception graph summary
keyframe/crop candidates
local confidence
requested output format
privacy flags
```

Output:

```text
structured cloud answer
confidence
hud suggestion
memory suggestion
```

## Layer 8: HUD / display runtime

Jetson owns display/HUD validation and adaptation.

Glasses only render:

```text
status chips
answer strips
direction hints
target markers
alert bursts
object cards
thumbnails
full image cards when explicitly requested
live overlays for active live skills
```

## Layer 9: Dashboard and observability

Dashboard should show:

```text
stream health
latency
current perception graph
active skill
last transcript
cloud calls
HUD events
session logs
benchmark scorecard
```

## Data flow example: target finder

User says:

```text
"tìm người áo vàng"
```

Flow:

```text
Rokid mic -> Jetson Realtime bridge -> Cloud Realtime
Cloud Realtime understands Vietnamese and chooses skill.target_finder
Jetson validates RealtimeToolCall and media budget
Jetson perception graph already tracks persons
Target finder filters persons by shirt color/zone/confidence
If confident: emit HUD direction hint
If uncertain: send top crops to cloud gateway
Cloud returns best candidate
Jetson emits DisplayCommand / HUD scene
Rokid renders tiny cue
```

## Required runtime boundaries

Do not let individual skills directly own everything. Avoid this anti-pattern:

```text
skill -> grabs frame -> runs detector -> calls cloud -> renders HUD directly
```

Use this instead:

```text
RealtimeToolCall -> JetsonToolServer -> skill_runtime/media_gateway/display_runtime -> ToolResult/DisplayCommand
```

## Failure behavior

If one subsystem fails:

```text
video failure -> show status chip, keep audio alive
audio failure -> keep visual skills alive
cloud failure -> local fallback answer
HUD failure -> log and keep backend alive
skill failure -> fail soft, do not crash session
```
