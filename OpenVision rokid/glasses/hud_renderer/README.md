# HUD Renderer

HUD renderer displays Jetson-owned `HudScene` data.

Read first:

```text
../../docs/openvision/27_ROKID_APP_CODEX_ROADMAP.md
../../docs/openvision/25_DISPLAY_SKILLS_AND_HUD_OUTPUTS.md
```

Supported scene elements:

- lower-safe-zone answer strip;
- edge chips;
- small thumbnails;
- selected target cue;
- short alerts.
- small target reticle / aim arrow;
- zoom tile;
- ttl_ms expiry / clear.

Avoid full-screen panels and keep the center view mostly clear.

The iPhone simulator HUD is the behavior reference, but RV101 must size output
for real optics and the measured 480x640 physical display. The renderer should
not implement skill-specific UI, mode pickers, phone-like screens, or custom
visual output outside `hud_scene` / `DisplayCommand` primitives. Debug panels
must stay hidden or explicitly operator-triggered.
