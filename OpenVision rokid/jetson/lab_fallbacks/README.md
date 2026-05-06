# Lab Fallbacks

Fallback runtimes live here and must stay out of the primary product route.

Source package:

- `openvision_jetson/debug_stt.py`

Allowed examples:

- mini PC PhoWhisper Debug STT sidecar;
- replay-only analysis;
- fake camera/audio fixtures;
- diagnostic-only skill stubs.

Rules:

- fallback output must be labelled in Ops Console traces;
- fallback output must not choose commands;
- fallback output must not update HUD;
- fallback controls must stay out of normal product controls;
- every fallback must have a promote/quarantine/remove condition.
