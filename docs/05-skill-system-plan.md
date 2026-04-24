# Skill System Plan

OpenVision Rokid should grow like an OpenClaw-style agent system, but vision-first.

OpenAI chooses intent and typed tools. Jetson executes trusted local capabilities and returns grounded evidence.

## Skill Contract

Every skill declares:

- `name`;
- `description`;
- JSON schema for args;
- required session capabilities;
- local resources needed;
- whether cloud evidence is allowed;
- internal runtime profile if needed;
- timeout;
- cancellation behavior;
- result schema;
- HUD result policy;
- telemetry fields;
- tests and fixtures.

## Internal Runtime Profiles

Internal modes are implementation details, not glasses UI.

Allowed examples:

- `person_count_runtime`;
- `target_search_runtime`;
- `traffic_count_runtime`;
- `selected_target_followup`;
- `cloud_attribute_resolution`;
- `yolo26_person_tracking`.

Each runtime profile must be owned by a skill or module and must be visible in trace.

## Core v2 Skills

### `query_scene`

General visual question about the current scene.

Jetson responsibilities:

- collect recent frames/crops;
- provide object summaries;
- decide if local answer is enough;
- ask cloud vision only when needed.

### `count_people`

Counts visible people.

Jetson responsibilities:

- use local person detection/tracking through a Rokid-specific adapter;
- de-duplicate tracks;
- return count, confidence, timestamp, and evidence summary.

HUD:

- compact answer strip, for example `100 người`.

### `search_targets`

Finds people/objects matching attributes.

Example:

```text
"Tìm người mặc áo màu xanh."
```

Jetson responsibilities:

- detect people locally;
- crop candidates;
- maintain object IDs and track IDs;
- send small candidate images to cloud if attribute reasoning is hard;
- map cloud result back to Jetson IDs;
- return thumbnails and target candidates.

Cloud responsibilities:

- reason over colors, posture, glasses, carried objects, standing/sitting, and other visual attributes.

HUD:

- edge thumbnails;
- selected candidate cue;
- short answer strip.

### `select_target`

Sets the active target for follow-up questions.

Jetson responsibilities:

- persist selected target in session state;
- track target across frames;
- update HUD reticle/thumbnail;
- report target lost/reacquired.

### `analyze_selected_target`

Answers follow-up questions about the selected target.

Jetson responsibilities:

- gather current and recent selected-target crops;
- include track history;
- call cloud if needed;
- return compact HUD-safe result.

### `clear_target`

Clears selected target and removes target HUD cues.

## Local vs Cloud Routing

Jetson should do local work first when it is reliable:

- object detection;
- people count;
- bounding boxes;
- tracking;
- crop extraction;
- selected-target continuity.

Cloud should be used when the task needs stronger visual reasoning:

- clothing color under difficult light;
- posture;
- glasses/hat/bag attributes;
- relation between people/objects;
- ambiguous target disambiguation;
- natural-language scene explanation.

## Debug STT Is Not A Skill

Debug STT can show what the operator said in the Ops Console. It is not a skill, not a command router, and not a fallback brain.

## OpenClaw Bridge Later

Document/mail/workflow actions should live behind a separate bridge:

- `external_action_bridge`;
- explicit permissions;
- separate audit log;
- no silent mixing with visual perception skills.

Future chain:

```text
OpenAI Realtime
  -> Jetson visual skill
  -> selected evidence / target / answer
  -> external OpenClaw bridge if user asks for document/mail/action work
```

## First Skill Build Order

1. `count_people` with real schema and local adapter stub.
2. `query_scene` with frame evidence envelope.
3. `search_targets` with candidate crop result shape.
4. `select_target` and target HUD cues.
5. Cloud attribute resolver for `search_targets`.
6. Selected-target follow-up.
7. External action bridge after vision loop is stable.
