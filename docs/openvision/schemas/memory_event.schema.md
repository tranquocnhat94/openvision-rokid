# Schema Spec — memory_event.v1

## Purpose

Represent memory events created by user action or skill output.

## Example

```json
{
  "schema_version": "memory_event.v1",
  "event_id": "mem_001",
  "session_id": "sess_001",
  "timestamp_ms": 1710000000000,
  "type": "object_location",
  "summary": "Keys seen on desk",
  "evidence_ref": "runtime/crops/keys_001.jpg",
  "retention": "user_saved",
  "cloud_synced": false,
  "delete_allowed": true
}
```

## Retention values

```text
session_only
user_saved
expires_24h
expires_7d
```

## Rule

Do not create long-term visual memory without explicit user intent or policy.
