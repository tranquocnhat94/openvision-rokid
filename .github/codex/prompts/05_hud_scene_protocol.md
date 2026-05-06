# Codex Prompt — HUD Scene Protocol

```text
Read AGENTS.md and docs/openvision/08_HUD_SCENE_PROTOCOL.md.

Goal: implement or refine shared HUD scene protocol.

Tasks:
1. Define hud_scene data model/schema.
2. Add builder helpers for:
   - answer_strip
   - status_chip
   - direction_hint
   - target_marker
   - alert_burst
3. Add validation or safe construction.
4. Ensure unknown components are ignored or safely handled by renderer if renderer is in repo.
5. Add tests for scene construction.

Rules:
- Do not add phone-like UI.
- Do not let skills render HUD directly.
- Keep text short.
- Center view should stay mostly clear.

Output:
- changed files
- example HUD JSON
- test results
- next PR
```
