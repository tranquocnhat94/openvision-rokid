# Codex Prompt — Display Skill Registry

Read docs/openvision/25_DISPLAY_SKILLS_AND_HUD_OUTPUTS.md.

Goal:
Treat display as a typed skill/capability family.

Add or harden display types:

- text_hud,
- warning_hud,
- object_card,
- thumbnail_card,
- full_image,
- live_overlay,
- debug_overlay,
- clear.

Rules:

- Skills and cloud tool calls must not emit ad-hoc display strings.
- Jetson validates display payloads before sending to Rokid.
- Product HUD should be short.
- Debug overlay must be gated.
- Existing text HUD realtime behavior must continue to pass tests.

Run tests and summarize.
