"""HUD scene authority for OpenVision v2."""

from __future__ import annotations

from typing import Any

from .contracts import HudScene, new_id, to_jsonable
from .event_store import InMemoryEventStore


class HudAuthority:
    def __init__(self, *, events: InMemoryEventStore) -> None:
        self._events = events
        self._latest: dict[str, dict[str, Any]] = {}

    def latest(self, session_id: str) -> dict[str, Any] | None:
        return self._latest.get(session_id)

    def list_latest(self) -> list[dict[str, Any]]:
        return list(self._latest.values())

    def update_answer(
        self,
        *,
        session_id: str,
        answer_strip: str,
        edge_chips: list[str] | None = None,
        priority: str = "normal",
        ttl_ms: int = 2500,
    ) -> dict[str, Any]:
        scene = HudScene(
            scene_id=new_id("hud"),
            session_id=session_id,
            answer_strip=answer_strip,
            edge_chips=edge_chips or [],
            priority=priority,
            ttl_ms=ttl_ms,
        )
        payload = to_jsonable(scene)
        self._latest[session_id] = payload
        self._events.add(
            "hud",
            "scene_updated",
            {"scene_id": payload["scene_id"], "answer_strip": payload.get("answer_strip")},
            session_id=session_id,
        )
        return payload

    def update_from_skill_result(self, skill_result: dict[str, Any]) -> dict[str, Any] | None:
        session_id = skill_result.get("session_id")
        result = skill_result.get("result")
        if not session_id or not isinstance(result, dict):
            return None
        hud = result.get("hud")
        if not isinstance(hud, dict):
            return None
        scene = HudScene(
            scene_id=new_id("hud"),
            session_id=str(session_id),
            answer_strip=hud.get("answer_strip") if isinstance(hud.get("answer_strip"), str) else None,
            edge_chips=_coerce_string_list(hud.get("edge_chips")),
            thumbnails=_coerce_object_list(hud.get("thumbnails")),
            target_hint=hud.get("target_hint") if isinstance(hud.get("target_hint"), dict) else None,
            priority=str(hud.get("priority") or "normal"),
            ttl_ms=int(hud.get("ttl_ms") or 2500),
        )
        payload = to_jsonable(scene)
        self._latest[str(session_id)] = payload
        self._events.add(
            "hud",
            "scene_updated",
            {"scene_id": payload["scene_id"], "answer_strip": payload.get("answer_strip")},
            session_id=str(session_id),
        )
        return payload


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _coerce_object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
