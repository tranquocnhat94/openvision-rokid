# Web UI / Ops Console

The Web UI is the V2 operator console for setup, live QA, product verification, and deep debugging.

Core surfaces:

- overview;
- session timeline;
- agent/skill understanding;
- live cloud AI trace;
- audio lab;
- skills lab;
- perception graph lab;
- cloud evidence lab;
- HUD scene studio;
- iPhone simulator;
- optional Debug STT;
- settings;
- logs and replay.

The console is product operations tooling, not a throwaway debug page.

Rules:

- redact secrets;
- separate product behavior from lab-only controls;
- show local perception/skill evidence before cloud interpretation;
- show tool/skill args, results, latency, failure reasons, and HUD scene output;
- keep Debug STT sidecar-only;
- do not add old mode controls as product UX.

The proof of understanding is not just transcript text. It is the chain from user turn to router/cloud decision, typed skill args, skill result, cloud evidence result if used, and HUD scene.
