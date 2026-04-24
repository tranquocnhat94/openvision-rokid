# 02 — System Architecture

## One-line architecture

```text
Rokid -> Jetson local perception/skills -> optional cloud reasoning -> Jetson HUD scene -> Rokid HUD
```

## Layer 1: Rokid glasses

Responsibilities:

```text
camera capture
microphone capture
low-latency transport
session heartbeat
compact HUD rendering
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
VAD
speech segmenting
STT local or cloud
Vietnamese command normalization
intent extraction
latency metrics
```

Output:

```text
transcript_event
intent_candidate
```

## Layer 5: Skill runtime

The skill runtime decides what to do.

Inputs:

```text
transcript_event
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
cloud_escalation_request, optional
memory_event, optional
```

## Layer 6: Cloud escalation gateway

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

## Layer 7: HUD runtime

Jetson owns HUD scene generation.

Glasses only render:

```text
status chips
answer strips
direction hints
target markers
alert bursts
```

## Layer 8: Dashboard and observability

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
Rokid mic -> Jetson VAD/STT -> transcript_event
Jetson perception graph already tracks persons
Skill router activates target_finder
Target finder filters persons by shirt color/zone/confidence
If confident: emit HUD direction hint
If uncertain: send top crops to cloud gateway
Cloud returns best candidate
Jetson emits target_marker + answer_strip
Rokid renders tiny cue
```

## Required runtime boundaries

Do not let individual skills directly own everything. Avoid this anti-pattern:

```text
skill -> grabs frame -> runs detector -> calls cloud -> renders HUD directly
```

Use this instead:

```text
stream_ingest -> perception_graph -> skill_runtime -> hud_runtime/cloud_gateway
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
