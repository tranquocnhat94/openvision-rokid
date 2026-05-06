# Codex Prompt — Phase 6 Reality Radar MVP

```text
Read AGENTS.md and docs/openvision/10_REALITY_RADAR_MVP.md.

Goal: build Reality Radar MVP after perception graph, skill runtime, HUD protocol, and cloud gateway exist.

Tasks:
1. Add target_query parser for Vietnamese commands.
2. Rank candidates from perception_graph.
3. Use local class/color/zone/track confidence first.
4. If ambiguous and cloud allowed, send top candidates through cloud_gateway.
5. Output HUD direction_hint and target_marker.
6. Log ranking reasons.

Rules:
- Do not build full 3D AR.
- Do not build face recognition.
- Do not stream full video to cloud.
- Do not hallucinate target if not found.

Tests:
- "tìm người áo vàng" finds mock yellow-shirt person
- multiple candidates triggers cloud verifier mock
- no candidate returns not-found HUD
- ranking reasons are logged

Output:
- changed files
- sample target query JSON
- sample HUD output
- tests run
- next PR
```
