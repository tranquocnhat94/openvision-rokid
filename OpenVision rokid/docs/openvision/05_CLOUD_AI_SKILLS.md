# 05 — Cloud AI Skills

Cloud Realtime AI should be used as the V2 conversation/tool orchestrator and as a powerful reasoning layer, not as a default raw-video processor.

## Cloud AI responsibilities

Cloud is best for:

```text
realtime conversation
Vietnamese understanding
typed tool/skill choreography
hard visual reasoning
ambiguous image/crop verification
natural conversation
Vietnamese language robustness
web search
file/project memory search
long-form explanations
multi-step planning
tool calling
Codex/code debugging workflows
```

## Cloud AI should not do by default

Avoid:

```text
continuous full video streaming
unvalidated hardware/media/display commands
cloud call for every frame
cloud call for every detection
cloud call for simple counting
cloud call for obvious OCR
cloud call when Jetson confidence is high
```

## Evidence bundle principle

Jetson should validate every cloud tool call and send compact context for visual reasoning:

```text
user query
local perception graph summary
selected keyframe or crop candidates
local confidence and uncertainty
privacy flags
requested structured output
```

Do not send raw continuous streams unless explicitly implementing a special live session.

## Cloud skill categories

### 1. Visual verifier

Input:

```text
query
candidate crops
object detections
track metadata
```

Output:

```text
best candidate
confidence
reason
short HUD text
```

Use case:

```text
"tìm người áo vàng đeo balo"
```

Jetson narrows to candidate persons. Cloud verifies ambiguous attributes.

### 2. Visual explainer

Input:

```text
keyframe
perception graph
user question
```

Output:

```text
brief answer
confidence
optional next action
```

Use cases:

```text
"cái này là gì?"
"máy này có lỗi gì không?"
"có gì bất thường không?"
```

### 3. Web-grounded assistant

Input:

```text
OCR result or object identity
user question
location/time context if allowed
```

Output:

```text
grounded short answer
sources when available
HUD summary
```

Use cases:

```text
"biển báo này nghĩa là gì?"
"thiết bị này thông số ra sao?"
"tra giá món này"
```

### 4. File/project memory assistant

Input:

```text
query
file/project memory context
current scene if relevant
```

Output:

```text
answer
retrieved memory references
next action
```

Use cases:

```text
"nhắc tôi checklist setup Jetson"
"lỗi này giống lần trước không?"
```

### 5. Task coach

Input:

```text
current frame
perception graph
task goal
previous steps
```

Output:

```text
next step
safety note
verification prompt
```

Use cases:

```text
repair setup
assembly
cooking
lab/workshop procedure
```

## Cloud response format

Cloud should return structured JSON that Jetson can validate.

Example:

```json
{
  "schema_version": "cloud_result.v1",
  "answer_short": "Áo vàng · bên trái",
  "answer_long": "Ứng viên phù hợp nhất là người ở phía trước bên trái.",
  "confidence": 0.82,
  "hud": {
    "type": "direction_hint",
    "text": "Áo vàng · bên trái",
    "anchor": "left_front",
    "duration_ms": 2200
  },
  "memory_suggestion": null,
  "safety_flags": []
}
```

## Escalation triggers

Escalate to cloud when:

```text
local confidence is below threshold
multiple candidates tie
attribute query is complex
text is blurry or OCR confidence is low
user asks a conceptual question
web/file/tool access is required
skill manifest says cloud is allowed
privacy policy permits sending evidence
```

## Do not escalate when

Do not call cloud when:

```text
the user asked to disable cloud
privacy policy blocks it
local answer is high confidence and simple
network is unavailable
battery/thermal policy says local only
```

## Cloud budget policy

Each skill should declare:

```text
max_cloud_calls_per_minute
max_images_per_call
max_context_tokens
fallback_if_cloud_fails
```

This prevents runaway cost and latency.
