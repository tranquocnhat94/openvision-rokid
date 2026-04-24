# 15 — Do Not Build Yet

These ideas may be exciting, but building them too early will hurt V2.

## Do not build full AR UI yet

Avoid:

```text
large panels
menus
multi-screen UI
full-screen dashboards on glasses
```

Build tiny HUD scenes first.

## Do not stream all video to cloud by default

This creates:

```text
privacy risk
cost risk
latency risk
network dependency
hard debugging
```

Use evidence bundles.

## Do not build face recognition by default

Early allowed:

```text
person detection
anonymous tracking
clothing/attribute search
```

Do not build without explicit user design and consent:

```text
identity database
background face memory
automatic recognition of people
```

## Do not add 20 skills at once

First build:

```text
scene_describe
target_finder
text_reader
object_counter
```

These prove the runtime.

## Do not run giant models continuously on Jetson

Jetson is powerful but limited. Favor:

```text
small detector
tracking
on-demand OCR/VLM
cloud escalation
```

## Do not scatter cloud calls

All cloud calls must go through:

```text
cloud_gateway
```

## Do not let skills own HUD rendering directly

All HUD output must go through:

```text
hud_scene protocol
```

## Do not optimize before measuring

Before model tuning, add:

```text
session logs
scorecards
replay scripts
latency metrics
```

## Do not turn V2 into a data marketplace first

Data flywheel is valuable only after useful skills exist.

Order:

```text
useful skills -> consented logs -> evaluation -> improvement -> optional data flywheel
```

Not:

```text
data platform first -> unclear user value
```
