# Codex Prompt — Phase 3 Skill Runtime MVP

```text
Read AGENTS.md and docs/openvision/06_SKILL_RUNTIME_AND_REGISTRY.md.

Goal: implement a manifest-based skill runtime MVP.

Tasks:
1. Define SkillManifest model.
2. Define SkillContext and SkillResult model.
3. Add a SkillRegistry.
4. Add Vietnamese phrase router for initial phrases.
5. Register placeholder or minimal implementations for:
   - scene_describe
   - target_finder
   - text_reader
   - object_counter
6. Ensure each skill outputs hud_scene through shared schema.

Rules:
- Do not create skill-specific HUD rendering code.
- Do not call cloud directly from skills.
- Do not add advanced memory yet.
- Keep PR scoped to runtime/registry/router.

Tests:
- route "nhìn phía trước có gì" -> scene_describe
- route "đếm xe" -> object_counter
- route "tìm người áo vàng" -> target_finder
- route "đọc chữ này" -> text_reader

Output:
- changed files
- routing behavior
- test results
- next PR
```
