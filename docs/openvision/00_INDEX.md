# OpenVision Rokid V2 — Documentation Index

This directory defines the architecture and execution path for OpenVision Rokid V2.

## Reading order

1. `01_NORTH_STAR_AND_PHILOSOPHY.md`
2. `02_SYSTEM_ARCHITECTURE.md`
3. `03_V1_LESSONS_TO_PRESERVE.md`
4. `04_JETSON_EDGE_SKILLS.md`
5. `05_CLOUD_AI_SKILLS.md`
6. `06_SKILL_RUNTIME_AND_REGISTRY.md`
7. `07_PERCEPTION_GRAPH.md`
8. `08_HUD_SCENE_PROTOCOL.md`
9. `09_CLOUD_ESCALATION_GATEWAY.md`
10. `10_REALITY_RADAR_MVP.md`
11. `11_PRIVACY_MEMORY_SAFETY.md`
12. `12_BENCHMARKING_AND_REPLAY.md`
13. `13_ROADMAP_AND_PR_SEQUENCE.md`
14. `15_DO_NOT_BUILD_YET.md`
15. `16_ACCEPTANCE_TESTS.md`
16. `17_REPO_INVENTORY.md`
17. `18_IMPLEMENTATION_PLAYBOOK.md`

## V2 in one sentence

```text
OpenVision Rokid V2 is a local-first AI skill runtime for smart glasses where Rokid captures reality, Jetson understands it in realtime, and cloud AI helps only when deeper reasoning is needed.
```

## Immediate build priority

Do not start by adding many flashy skills. First create shared runtime foundation:

```text
1. repo inventory
2. schema docs
3. perception graph MVP
4. skill registry
5. HUD scene protocol
6. cloud evidence bundle
7. benchmark/replay tools
```

Then implement the first four practical skills:

```text
scene_describe
target_finder
text_reader
object_counter
```

Then implement the ambitious skill:

```text
reality_radar
```

## Current decision framework

When proposing work, evaluate it by asking:

```text
Does it improve the runtime platform?
Does it reduce future feature drift?
Does it make one of the first four practical skills possible?
Does it create measurable behavior?
Does it keep glasses thin and Jetson central?
```
