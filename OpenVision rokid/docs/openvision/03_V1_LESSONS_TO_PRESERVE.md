# 03 — V1 Lessons to Preserve

V2 should use V1 as proof, not as a prison. Keep what worked, discard what created drift.

## What V1 proved

V1 proved these paths are feasible:

```text
Rokid can stream video to Jetson
Jetson can ingest and process streams
OpenAI/cloud STT can be called from backend
HUD can receive useful output from Jetson
Jetson can act as local orchestration layer
```

This means V2 should stop asking:

```text
Can the system work at all?
```

And start asking:

```text
How do we make this extensible, measurable, reliable, and useful?
```

## Biggest V1 technical lesson

For voice-first systems, capture quality matters more than model intelligence.

Rules to preserve:

```text
PCM energy is more trustworthy than silence callback metadata
source switching needs hysteresis
queue should be shallow and latency-first
near-silent segments should not be sent to STT
segmenter must be replayable offline
```

## Biggest V1 product lesson

Do not turn Rokid into a phone.

V1 showed the stronger direction:

```text
Rokid = sensor + HUD
Jetson = brain
Cloud = deep reasoning
```

## Biggest V1 architecture lesson

Modes are weaker than skills.

Avoid:

```text
visual mode
traffic mode
face mode
radar mode
```

Prefer:

```text
skills activated by context and voice, all sharing the same perception graph
```

## What to reuse from V1

Reuse concepts:

```text
dedicated video/audio transport
Jetson-owned HUD authority
backend session management
logs and scorecards
local detection runtime
cloud STT/reasoning as optional escalation
```

Reuse code carefully:

```text
copy only what helps V2 boundaries
avoid dragging mode-based UI logic into V2
avoid coupling V2 to old experimental paths
```

## What to avoid from V1

Avoid:

```text
adding features before observability
hardcoding model decisions inside endpoints
letting glasses choose product mode
scattering cloud calls across unrelated files
building UI panels that compete with the real world
retesting the same bug manually without replay scripts
```

## Migration principle

Do not delete working V1 code just to look clean. Instead:

```text
1. create V2 runtime boundaries
2. migrate one capability at a time
3. compare behavior with scorecards
4. retire old paths only after V2 path is verified
```
