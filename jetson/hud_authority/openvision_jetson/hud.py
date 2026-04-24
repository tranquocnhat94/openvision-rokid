"""HUD scene helpers for early debug UI."""

from __future__ import annotations

from .contracts import HudScene, new_id, to_jsonable


def sample_hud_scene(session_id: str | None = None) -> dict[str, object]:
    scene = HudScene(
        scene_id=new_id("hud"),
        session_id=session_id,
        answer_strip="OpenVision v2 ready",
        edge_chips=["Jetson", "Realtime", "Skills"],
        thumbnails=[],
        target_hint=None,
        priority="normal",
        ttl_ms=2500,
    )
    return to_jsonable(scene)
