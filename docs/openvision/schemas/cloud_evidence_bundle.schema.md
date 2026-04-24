# Schema Spec — cloud_evidence_bundle.v1

## Purpose

Compact evidence sent from Jetson to cloud AI when local confidence is not enough.

## Example

```json
{
  "schema_version": "cloud_evidence_bundle.v1",
  "session_id": "sess_001",
  "skill_id": "target_finder",
  "user_query": "tìm người áo vàng",
  "timestamp_ms": 1710000000000,
  "local_summary": {
    "candidate_count": 2,
    "uncertainty": "shirt color ambiguous"
  },
  "candidates": [],
  "requested_output": {
    "format": "json",
    "max_answer_chars": 60,
    "hud_allowed": true
  },
  "privacy": {
    "contains_face": true,
    "allow_cloud": true,
    "store_result": false
  }
}
```

## Rule

Skills do not call cloud directly. They request cloud escalation through this bundle.
