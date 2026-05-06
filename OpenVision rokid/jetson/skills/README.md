# Skills

Skills are typed Jetson capabilities that OpenAI can call.

Source package:

- `openvision_jetson/skill_registry.py`
- `openvision_jetson/skill_executor.py`

Initial skill families:

- scene query;
- text/OCR reading;
- person count;
- target search;
- known-person/profile lookup;
- remember person / Immich People Registry capture;
- target selection;
- selected-target analysis;
- cloud evidence resolution;
- future external action bridge.

Each skill must have a schema, tests, timeout, telemetry, and HUD result policy.

Current known-person skill:

- `person_info`: snapshot-first or bounded live camera, local Face Identity, local contact identity DB, People Registry enrichment, face-quality diagnostics, compact HUD/voice answer focus (`name`, `summary`, `contact`, `relationship`, `full`).

Current OCR skill:

- `text_reader`: snapshot-first visible-text reading for signs, labels, screens, and documents. It uses Jetson-owned preview evidence through CloudGateway until a local OCR engine is promoted.
