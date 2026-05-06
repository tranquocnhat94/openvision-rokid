"""HUD scene authority for OpenVision v2."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .contracts import HudScene, new_id, to_jsonable
from .event_store import InMemoryEventStore


HUD_REQUIRED_FIELDS = {"scene_id", "edge_chips", "thumbnails", "priority", "ttl_ms", "created_at"}
HUD_ALLOWED_PRIORITIES = {"low", "normal", "high", "urgent"}


class HudAuthority:
    def __init__(self, *, events: InMemoryEventStore) -> None:
        self._events = events
        self._latest: dict[str, dict[str, Any]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any] | None]]] = {}
        self._last_event_signature: dict[str, str] = {}

    def latest(self, session_id: str) -> dict[str, Any] | None:
        return self._latest.get(session_id)

    def list_latest(self) -> list[dict[str, Any]]:
        return list(self._latest.values())

    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any] | None]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=1)
        self._subscribers.setdefault(session_id, set()).add(queue)
        scene = self._latest.get(session_id)
        if scene:
            self._offer_latest(queue, scene)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        subscribers = self._subscribers.get(session_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(session_id, None)

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
            priority=_coerce_priority(priority),
            ttl_ms=_coerce_ttl_ms(ttl_ms),
        )
        payload = to_jsonable(scene)
        return self._store_scene(session_id=session_id, payload=payload, event_type="scene_updated")

    def update_realtime_text(
        self,
        *,
        session_id: str,
        text: str,
        edge_chips: list[str] | None = None,
        ttl_ms: int = 2500,
    ) -> dict[str, Any]:
        latest = self.latest(session_id) or {}
        chips = _merge_chips(_coerce_string_list(latest.get("edge_chips")), edge_chips or [])
        scene = HudScene(
            scene_id=new_id("hud"),
            session_id=session_id,
            answer_strip=text,
            edge_chips=chips,
            thumbnails=_coerce_object_list(latest.get("thumbnails")),
            target_hint=latest.get("target_hint") if isinstance(latest.get("target_hint"), dict) else None,
            priority=_coerce_priority(latest.get("priority")),
            ttl_ms=_coerce_ttl_ms(ttl_ms),
        )
        payload = to_jsonable(scene)
        return self._store_scene(session_id=session_id, payload=payload, event_type="realtime_text_updated")

    def update_test_scene(self, *, session_id: str) -> dict[str, Any]:
        scene = HudScene(
            scene_id=new_id("hud"),
            session_id=session_id,
            answer_strip="HUD test OK",
            edge_chips=["hud", "test"],
            priority="normal",
            ttl_ms=3000,
        )
        payload = to_jsonable(scene)
        return self._store_scene(session_id=session_id, payload=payload, event_type="test_scene_updated")

    def update_display_scene(
        self,
        *,
        session_id: str,
        answer_strip: str | None = None,
        edge_chips: list[str] | None = None,
        thumbnails: list[dict[str, Any]] | None = None,
        target_hint: dict[str, Any] | None = None,
        priority: str = "normal",
        ttl_ms: int = 2500,
    ) -> dict[str, Any]:
        scene = HudScene(
            scene_id=new_id("hud"),
            session_id=session_id,
            answer_strip=answer_strip,
            edge_chips=edge_chips or [],
            thumbnails=thumbnails or [],
            target_hint=target_hint,
            priority=_coerce_priority(priority),
            ttl_ms=_coerce_ttl_ms(ttl_ms),
        )
        payload = to_jsonable(scene)
        return self._store_scene(session_id=session_id, payload=payload, event_type="display_scene_updated")

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
            priority=_coerce_priority(hud.get("priority")),
            ttl_ms=_coerce_ttl_ms(hud.get("ttl_ms")),
        )
        payload = to_jsonable(scene)
        return self._store_scene(session_id=str(session_id), payload=payload, event_type="scene_updated")

    def _store_scene(self, *, session_id: str, payload: dict[str, Any], event_type: str) -> dict[str, Any]:
        validation_errors = validate_hud_scene(payload)
        if validation_errors:
            self._events.add(
                "hud",
                "scene_validation_failed",
                {"scene_id": payload.get("scene_id"), "errors": validation_errors},
                session_id=session_id,
                severity="error",
            )
            raise ValueError(f"Invalid HUD scene: {', '.join(validation_errors)}")
        self._latest[session_id] = payload
        for queue in tuple(self._subscribers.get(session_id, ())):
            self._offer_latest(queue, payload)
        signature = _event_signature(event_type=event_type, payload=payload)
        if self._last_event_signature.get(session_id) == signature:
            return payload
        self._last_event_signature[session_id] = signature
        self._events.add(
            "hud",
            event_type,
            {
                "scene_id": payload["scene_id"],
                "answer_strip": payload.get("answer_strip"),
                "schema_valid": True,
                "scene_count": len(self._latest),
            },
            session_id=session_id,
        )
        return payload

    @staticmethod
    def _offer_latest(queue: asyncio.Queue[dict[str, Any] | None], scene: dict[str, Any] | None) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(scene)


def validate_hud_scene(scene: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(field for field in HUD_REQUIRED_FIELDS if field not in scene)
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
    if "scene_id" in scene and not isinstance(scene.get("scene_id"), str):
        errors.append("scene_id must be a string")
    if "session_id" in scene and scene.get("session_id") is not None and not isinstance(scene.get("session_id"), str):
        errors.append("session_id must be a string or null")
    if "answer_strip" in scene and scene.get("answer_strip") is not None and not isinstance(scene.get("answer_strip"), str):
        errors.append("answer_strip must be a string or null")
    if not isinstance(scene.get("edge_chips"), list) or not all(isinstance(item, str) for item in scene.get("edge_chips", [])):
        errors.append("edge_chips must be a string array")
    if not isinstance(scene.get("thumbnails"), list) or not all(isinstance(item, dict) for item in scene.get("thumbnails", [])):
        errors.append("thumbnails must be an object array")
    if scene.get("target_hint") is not None and not isinstance(scene.get("target_hint"), dict):
        errors.append("target_hint must be an object or null")
    if scene.get("priority") not in HUD_ALLOWED_PRIORITIES:
        errors.append("priority must be one of low, normal, high, urgent")
    ttl_ms = scene.get("ttl_ms")
    if not isinstance(ttl_ms, int) or isinstance(ttl_ms, bool) or ttl_ms < 0:
        errors.append("ttl_ms must be a non-negative integer")
    if not isinstance(scene.get("created_at"), str):
        errors.append("created_at must be a string")
    extra = sorted(set(scene) - {
        "scene_id",
        "session_id",
        "answer_strip",
        "edge_chips",
        "thumbnails",
        "target_hint",
        "priority",
        "ttl_ms",
        "created_at",
    })
    if extra:
        errors.append(f"unexpected fields: {', '.join(extra)}")
    return errors


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _merge_chips(existing: list[str], new_items: list[str]) -> list[str]:
    merged: list[str] = []
    for item in [*existing, *new_items]:
        text = str(item).strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def _coerce_object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _coerce_priority(value: Any) -> str:
    priority = str(value or "normal")
    return priority if priority in HUD_ALLOWED_PRIORITIES else "normal"


def _coerce_ttl_ms(value: Any) -> int:
    try:
        ttl_ms = int(value)
    except (TypeError, ValueError):
        return 2500
    return max(0, ttl_ms)


def _event_signature(*, event_type: str, payload: dict[str, Any]) -> str:
    comparable = {
        key: value
        for key, value in payload.items()
        if key not in {"scene_id", "created_at"}
    }
    return json.dumps({"event_type": event_type, "payload": comparable}, ensure_ascii=False, sort_keys=True, default=str)
