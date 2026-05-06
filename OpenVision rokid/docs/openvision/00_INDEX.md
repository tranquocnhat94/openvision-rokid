# OpenVision Rokid V2 — Documentation Index

This directory defines the architecture and execution path for OpenVision Rokid V2.

## Required reading order for Codex

1. `00_CODEX_START_HERE_CLOUD_REALTIME_V2.md`
2. `01_NORTH_STAR_AND_PHILOSOPHY.md`
3. `02_SYSTEM_ARCHITECTURE.md`
4. `03_V1_LESSONS_TO_PRESERVE.md`
5. `04_JETSON_EDGE_SKILLS.md`
6. `05_CLOUD_AI_SKILLS.md`
7. `06_SKILL_RUNTIME_AND_REGISTRY.md`
8. `07_PERCEPTION_GRAPH.md`
9. `08_HUD_SCENE_PROTOCOL.md`
10. `09_CLOUD_ESCALATION_GATEWAY.md`
11. `10_REALITY_RADAR_MVP.md`
12. `11_PRIVACY_MEMORY_SAFETY.md`
13. `12_BENCHMARKING_AND_REPLAY.md`
14. `13_ROADMAP_AND_PR_SEQUENCE.md`
15. `14_CODEX_OPERATING_MANUAL.md`
16. `15_DO_NOT_BUILD_YET.md`
17. `16_ACCEPTANCE_TESTS.md`
18. `17_REPO_INVENTORY.md`
19. `18_IMPLEMENTATION_PLAYBOOK.md`
20. `17_MEDIA_ACTIVATION_POLICY.md`
21. `18_ROKID_APP_RUNTIME_CONTRACT.md`
22. `19_VOICE_AND_CLOUD_ROUTING.md`
23. `20_NEXT_PRS_PHASE_3_MEDIA_ROUTING.md`
24. `21_CLOUD_REALTIME_ORCHESTRATION_POLICY.md`
25. `22_ROKID_CLOUD_AUDIO_BRIDGE.md`
26. `23_JETSON_SKILL_TOOL_SERVER_CONTRACT.md`
27. `24_MEDIA_CAPTURE_BUDGETS_AND_MODES.md`
28. `25_DISPLAY_SKILLS_AND_HUD_OUTPUTS.md`
29. `26_NEXT_PRS_CLOUD_ORCHESTRATED_V2.md`
30. `27_ROKID_APP_CODEX_ROADMAP.md`

## V2 in one sentence

```text
OpenVision Rokid V2 is a cloud-realtime-orchestrated wearable AI Skill OS where Cloud Realtime understands and chooses typed tools, Jetson validates/executes perception/media/display skills, and Rokid senses/displays only what is needed.
```

## Platform goal, not radar-only

OpenVision Rokid V2 is a skill platform for physical-world assistance.
Reality Radar is one advanced flagship skill in that platform. It should prove
that shared perception, skill runtime, cloud evidence, HUD output, replay, and
scorecards work together, but it must not become a separate product route or
the only design target.

## Immediate build priority

Do not start by adding many flashy skills or a complex glasses app. The first cloud-realtime + Jetson tool-server foundation now exists for typed skill tools. Continue by hardening the runtime:

Already hardened:

```text
strict manifest validation for media/display/tool requirements
Vietnamese realtime mocked route coverage
cloud gateway/evidence-bundle enforcement for needs_cloud skill/tool results
optional OpenAI Responses visual verifier behind CloudGateway
session scorecards with embedded skill_eval gates
durable replay/scorecard export CLI with local retention
```

Next:

```text
1. production RV101/Rokid MediaCommand capture adapter
2. first practical skills through typed runtime
3. visual verifier prompt/eval tuning against replay fixtures
4. promote exported replay fixtures into regression scoring
```

For the separate RV101 app topic, use `27_ROKID_APP_CODEX_ROADMAP.md` as the
alignment contract. The app should follow the backend and iPhone simulator
contracts that already exist instead of rediscovering product routes.

Already in the V2 foundation: JetsonToolServer policy gates and the
MediaCommand and DisplayCommand Jetson runtime gateways.

Then implement the first four practical skills:

```text
scene_describe
target_finder
text_reader
object_counter
```

Then implement the flagship "find" skill on top of the same platform:

```text
reality_radar
```

If a future patch helps only Reality Radar but does not strengthen reusable
runtime primitives for other skills, treat it as suspicious unless the user
explicitly asks for a Radar-specific experiment.

## Device evidence packs

Real-device evidence and operational notes:

```text
rv101_adb/
```

The RV101 ADB notes record the exact connected-device identity, Android build,
ADB limits, and safe bring-up workflow for the user's Rokid Glasses RV101.
They also point to the local `RokidSpriteLive` static analysis, which captures
RV101 media-pipeline evidence for the future production glasses app without
depending on Rokid's private system service.
They now also point to the local `JsAi` / AI wake static analysis, which
captures RV101 activation-session evidence for waking or focusing OpenVision AI
without depending on Rokid's private `ai_assist` / `jsai` services.
The RV101 ADB notes also include the AI app/scene launch analysis, showing that
Rokid's AI path uses structured commands and first-party scene whitelists rather
than a proven generic Vietnamese-to-Android-package launcher.
They also include the third-party app launchability note: a normal OpenVision
APK can be made launcher-visible with Android manifest declarations, but
manifest-only native Rokid AI voice launch is not proven on this RV101 build.

## Current decision framework

When Codex proposes work, evaluate it by asking:

```text
Does it improve the runtime platform?
Does it reduce future feature drift?
Does it make one of the first four practical skills possible?
Does it strengthen the skill ecosystem rather than one hard-coded skill?
Does it create measurable behavior?
Does it keep glasses thin and Jetson central?
Does it preserve cloud realtime as orchestrator and Jetson as typed executor?
Does it keep camera off by default unless a media tool requests it?
```
