# 11 — Privacy, Memory, and Safety

OpenVision Rokid V2 sees the real world. Privacy and memory rules must be explicit from the start.

## Privacy principle

Default behavior should be:

```text
local-first
minimal retention
explicit cloud escalation
clear deletion path
no hidden identity tracking
```

## Memory types

### Short-term session memory

Use for:

```text
recent tracks
recent transcripts
recent HUD events
recent keyframes/crops
```

Retention:

```text
seconds to minutes
local only by default
```

### User-saved memory

Use for:

```text
"remember this"
"save this note"
"I put my keys here"
```

Requires explicit user action.

### Skill memory

Use for:

```text
skill preferences
recent successful target queries
user-defined watch conditions
```

Should be inspectable and deletable.

## Sensitive content

Treat these as sensitive:

```text
faces
children
license plates
private documents
screens with personal information
homes/private spaces
medical/legal/financial documents
```

For sensitive content:

```text
prefer local processing
ask or require explicit cloud permission
avoid long retention
avoid background storage
```

## Face/person policy

Do not build default face recognition without explicit consent and purpose.

Allowed early features:

```text
person detection
person counting
clothing/attribute target search
anonymous track IDs
```

Avoid early features:

```text
identity recognition
background person memory
face database creation
```

## Cloud privacy gate

Before sending evidence to cloud, check:

```text
skill manifest privacy level
user mode: cloud allowed or local-only
whether evidence contains face/document/private screen
whether storage is requested
```

## Memory event schema

Example:

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

## Safety behavior

For risky or uncertain interpretations:

```text
be cautious
show uncertainty
avoid overclaiming
avoid long distracting HUD text
```

For physical danger cues:

```text
prioritize simple alerts
avoid detailed instructions that distract the user
fail soft when confidence is low
```

## Safety cue examples

Good:

```text
"Chú ý phía trước"
"Có vật cản gần"
"Không chắc · kiểm tra lại"
```

Bad:

```text
long explanations on HUD
false certainty
aggressive alarm spam
```

## Acceptance criteria

Privacy/memory foundation is acceptable when:

```text
skill manifests declare privacy level
cloud gateway checks privacy before sending evidence
memory events have retention metadata
there is a delete/export plan
face/person handling is anonymous by default
```
