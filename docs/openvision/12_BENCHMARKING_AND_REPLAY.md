# 12 — Benchmarking and Replay

V2 cannot improve by feeling. It needs measurable session scorecards.

## Required session metrics

Collect these per session:

```text
session_id
start/end time
camera FPS
frame ingest latency
detector FPS
tracker stability
OCR latency
GPU usage
RAM usage
Jetson temperature
audio RMS
VAD speech ratio
STT latency
intent routing accuracy
skill latency
cloud calls per minute
cloud latency
HUD latency
failure reasons
```

## Scorecard command

Target command:

```bash
python jetson/scripts/score_session.py --session sess_001 --logs runtime/logs
```

Output should include:

```text
Overall health: pass/warn/fail
Stream health
Audio health
Perception health
Skill success
Cloud usage
HUD latency
Top failure reasons
Recommended next fix
```

## Replay command

Target command:

```bash
python jetson/scripts/replay_session.py --session sess_001 --skill target_finder
```

Replay should let developers test without wearing glasses every time.

## Why replay matters

Replay allows:

```text
same input across patches
faster debugging
regression testing
offline skill development
cloud prompt evaluation
```

## Log format

Prefer structured JSONL logs:

```json
{"ts":1710000000000,"type":"transcript_event","session_id":"sess_001","text":"tìm người áo vàng","latency_ms":730}
{"ts":1710000000100,"type":"skill_result","skill_id":"target_finder","status":"ok","confidence":0.82}
{"ts":1710000000200,"type":"hud_scene","duration_ms":2200,"components":["answer_strip","direction_hint"]}
```

## Benchmarks by subsystem

### Stream ingest

Measure:

```text
FPS
frame drops
network reconnects
latency
```

### Audio

Measure:

```text
RMS
speech ratio
segment duration
STT calls
transcript quality
```

### Perception

Measure:

```text
detector FPS
objects per frame
track stability
latency
```

### Skill runtime

Measure:

```text
routing accuracy
skill latency
confidence
fallback rate
```

### Cloud gateway

Measure:

```text
calls/minute
latency
timeouts
cost estimate if available
privacy blocks
```

### HUD

Measure:

```text
scene generated time
scene delivered time
render ack if available
```

## Acceptance criteria

Benchmark foundation is acceptable when:

```text
at least one score_session command exists
logs are JSONL or similarly structured
skill runs include latency/confidence/failure reason
cloud calls include reason and latency
replay can validate behavior without device access
```
