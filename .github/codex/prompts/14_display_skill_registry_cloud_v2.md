# Codex Prompt 14 — Display Skill Registry for Rokid Output

Read:

```text
AGENTS.md
docs/openvision/25_DISPLAY_SKILLS_AND_HUD_OUTPUTS.md
```

Goal: make display a typed tool/skill family.

Implement or improve display command models for:

```text
display.text_hud
display.object_card
display.thumbnail_card
display.full_image
display.live_overlay
display.debug_overlay
```

Rules:

```text
skills do not draw arbitrary UI
cloud can request display intent through typed tool calls
Jetson validates display command before sending to Rokid
Rokid remains renderer only
```

Acceptance:

```text
- display commands are versioned
- unknown display command fails safely
- text HUD behavior from realtime_manager remains preserved
- tests with mocked display tool calls pass
- pytest -q passes
```
