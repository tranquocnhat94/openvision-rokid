# Reuse, Quarantine, Remove

This v2 workspace starts clean. Nothing is copied automatically from v1.

Every old feature, experiment, or fallback must end in one of three states:

- `promote`: imported into v2 as a typed, tested, observable product/skill runtime;
- `quarantine`: moved to lab/archive, off by default, clearly labelled;
- `remove`: deleted from active code, config, UI, tests, and docs.

There is no fourth state called "leave it active just in case".

## Reuse Candidates

Reuse only after extracting into small modules and tests.

### Glasses

- Camera2 + MediaCodec H.264 surface pipeline.
- Dedicated TCP video transport shape.
- Dedicated PCM audio transport shape.
- HUD renderer concepts: lower answer strip, edge chips, compact overlays.
- Reconnect telemetry and simple local diagnostics.

Do not port:

- old mode pickers;
- phone-like feature screens;
- fake local results;
- heavy debug surfaces;
- local reasoning/routing.

### Jetson

- Realtime tool-call loop concepts.
- Skill schema/registry concepts.
- HUD scene protocol ideas.
- Browser WebRTC ingest ideas.
- Frame/preview techniques that do not become product transport.
- Existing tests as behavior references.

Do not port:

- backend monolith shape;
- OpenAI transcription branch;
- local STT as command router;
- legacy JPEG/PCM simulator upload path;
- fake skill output;
- old UI controls that make fallbacks look like product paths.

### Debug STT

Allowed:

- mini PC PhoWhisper as `Debug STT` sidecar;
- completed-turn Vietnamese text in Ops Console;
- warm/health status;
- clear labeling that it is not the agent brain.

Not allowed:

- using Debug STT to choose tools;
- showing Debug STT as product HUD;
- treating Debug STT as a replacement for Realtime tool discipline.

### YOLO26

Allowed later:

- reuse assets through a separate Rokid-specific adapter;
- typed skills such as `count_people` and `search_targets`;
- explicit config gates and tests.

Not allowed:

- touching the Ring/security runtime;
- sharing mutable runtime paths;
- changing Ring service behavior;
- hiding YOLO integration inside old mode code.

## Porting Questions

Before importing anything, answer:

- What v2 module owns this?
- Which shared contract does it implement?
- Which old behavior is intentionally dropped?
- What telemetry proves it works?
- What test or fixture covers it?
- How is it removed or quarantined if it fails?

## Quarantine Rules

Quarantined code must be:

- off by default;
- labelled as lab/fallback/archive;
- excluded from normal product UI;
- absent from default prompts/tool schemas;
- absent from ordinary settings unless under Advanced/Lab;
- documented with an exit condition.

## Removal Rules

Remove a branch when:

- it duplicates the product route;
- it confuses future agents;
- it exists only to preserve history;
- tests only keep obsolete behavior alive;
- UI exposes it as if it is a supported path.

History belongs in archive docs, not in active runtime.
