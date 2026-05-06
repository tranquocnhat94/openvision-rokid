# Codex Prompt — Phase 4 First Four Practical Skills

```text
Read AGENTS.md, docs/openvision/06_SKILL_RUNTIME_AND_REGISTRY.md, and docs/openvision/16_ACCEPTANCE_TESTS.md.

Goal: implement the first four practical skills using existing runtime primitives.

Skills:
1. scene_describe
2. target_finder
3. text_reader
4. object_counter

Rules:
- Each skill must have a manifest.
- Each skill consumes perception_graph.
- Each skill outputs hud_scene.
- Cloud use must go through cloud_gateway and only if needed.
- Add metrics: latency, confidence, failure reason.

Implement in small commits or one narrow PR if codebase is small.

Tests:
- Vietnamese phrase routing
- each skill returns expected SkillResult on mock graph
- not-found fallback for target_finder
- low-confidence fallback for text_reader

Output:
- changed files
- example inputs/outputs
- tests run
- next PR
```
