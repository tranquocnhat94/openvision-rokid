# Schema Spec — skill_manifest.v1

## Purpose

Declare every skill so the runtime can route, test, and control privacy/cloud usage.

## Example

```yaml
schema_version: skill_manifest.v1
id: target_finder
name: Target Finder
description: Find a target in the current field of view.
latency_class: interactive
local_first: true
cloud_allowed: true
privacy_level: high
inputs:
  - transcript_event
  - perception_graph
outputs:
  - hud_scene
  - voice_reply
activation_phrases_vi:
  - tìm người áo vàng
  - tìm cái balo
acceptance_tests:
  - routes Vietnamese query to target_finder
  - returns direction hint if found
failure_modes:
  - no target found
  - cloud unavailable
```

## Required fields

```text
schema_version
id
name
description
latency_class
local_first
cloud_allowed
privacy_level
inputs
outputs
activation_phrases_vi
acceptance_tests
failure_modes
```
