# 16 — Acceptance Tests

This file defines concrete tests for V2.

## System-level acceptance

A V2 build is useful when:

```text
Rokid streams video/audio to Jetson
Jetson maintains perception graph
voice commands route to skills
skills output HUD scenes
cloud is used only when needed
session scorecard shows latency/failures
```

## Core Vietnamese test phrases

Use these phrases repeatedly:

```text
nhìn phía trước có gì
mô tả cảnh này
đếm xe phía trước
có bao nhiêu người
tìm người áo vàng
tìm cái balo
đọc chữ này
biển này ghi gì
có gì nguy hiểm không
nhắc tôi nếu thấy người giao hàng
```

## Phase 0 tests

Docs/foundation complete when:

```text
openvision docs exist
phase prompts exist
schema specs exist
Contributors can summarize phase order correctly
```

## Phase 1 tests

Reliability baseline complete when:

```text
stream health is logged
audio health is logged
HUD test scene works
session id links logs together
scorecard can summarize session
```

## Phase 2 tests

Perception graph complete when:

```text
detector output becomes graph objects
objects include class/confidence/bbox/zone
graph serializes to JSON
skills can read graph without detector internals
```

## Phase 3 tests

Skill runtime complete when:

```text
skill manifests exist
registry loads skills
router maps Vietnamese phrases
skill result includes HUD scene
metrics are logged
```

## Phase 4 tests

First four skills complete when:

```text
scene_describe returns short scene answer
target_finder returns direction hint or not-found
text_reader returns OCR text or low-confidence fallback
object_counter returns count and zone
```

## Phase 5 tests

Cloud gateway complete when:

```text
evidence bundle is generated
privacy/budget checks run
cloud result is validated
fallback works on timeout
skills do not call cloud directly
```

## Phase 6 tests

Reality Radar complete when:

```text
"tìm người áo vàng" activates target_finder
local candidate ranking works
HUD direction shown within target latency
cloud verifier used only for ambiguity
not-found case does not hallucinate
```

## Quality gates

Each implementation PR should answer:

```text
What was measured?
What improved?
What failed?
What is the next bottleneck?
```

If there is no measurement, do not call it optimized.
