from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any

from .hud_scene_runtime import (
    build_hud_scene_payload,
    scene_component,
    scene_gallery_items,
)


@dataclass(slots=True)
class TargetHudState:
    last_signature: str = ""
    last_sent_ms: int = 0
    last_positive_scene: dict[str, Any] = field(default_factory=dict)
    last_positive_ms: int = 0
    last_positive_query: str = ""


@dataclass(slots=True)
class TargetHudEvaluation:
    next_state: TargetHudState
    emit_payload: dict[str, Any] | None
    emit_log_payload: dict[str, Any] | None


def reset_target_hud_positive_state(state: TargetHudState) -> TargetHudState:
    return replace(
        state,
        last_positive_scene={},
        last_positive_ms=0,
        last_positive_query="",
    )


def _scene_text(payload: dict[str, Any], kind: str) -> str | None:
    component = scene_component(payload, kind)
    if not isinstance(component, dict):
        return None
    text = component.get("text")
    if text is None:
        return None
    return str(text)


def _build_target_hud_signature(
    *,
    query: str | None,
    payload: dict[str, Any],
    gallery_items: list[dict[str, Any]],
) -> str:
    return json.dumps(
        {
            "query": query,
            "answer": _scene_text(payload, "answer_strip") or "",
            "direction": _scene_text(payload, "direction_hint") or "",
            "gallery": [
                {
                    "label": item.get("label"),
                    "trackId": item.get("trackId"),
                    "selected": item.get("selected"),
                }
                for item in gallery_items
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _build_target_hud_hold_payload(
    *,
    session_id: str,
    scene_id: str,
    query: str | None,
    last_positive_scene: dict[str, Any],
) -> dict[str, Any]:
    held_gallery_items = scene_gallery_items(last_positive_scene)
    held_marker = scene_component(last_positive_scene, "target_marker")
    held_direction = _scene_text(last_positive_scene, "direction_hint") or "Dang quet lai"
    return build_hud_scene_payload(
        session_id=session_id,
        scene_id=scene_id,
        task_chip=f"Tim: {str(query or '')[:22]}",
        mic_chip="target search",
        answer_text=None,
        status_text=None,
        gallery_items=held_gallery_items,
        direction_hint=held_direction,
        target_marker=held_marker,
    )


def evaluate_target_hud_scene(
    *,
    state: TargetHudState,
    query: str | None,
    payload: dict[str, Any] | None,
    session_id: str,
    hold_scene_id: str,
    now_ms: int,
    candidate_grace_ms: int,
    scene_interval_ms: int,
) -> TargetHudEvaluation:
    next_state = replace(state)
    if payload is None:
        return TargetHudEvaluation(
            next_state=next_state,
            emit_payload=None,
            emit_log_payload=None,
        )

    normalized_query = str(query or "")
    gallery_items = scene_gallery_items(payload)
    emit_payload = payload
    if (
        not gallery_items
        and next_state.last_positive_scene
        and next_state.last_positive_query == normalized_query
        and now_ms - next_state.last_positive_ms <= candidate_grace_ms
    ):
        emit_payload = _build_target_hud_hold_payload(
            session_id=session_id,
            scene_id=hold_scene_id,
            query=query,
            last_positive_scene=next_state.last_positive_scene,
        )
        gallery_items = scene_gallery_items(emit_payload)
    elif gallery_items:
        next_state = replace(
            next_state,
            last_positive_scene=payload,
            last_positive_ms=now_ms,
            last_positive_query=normalized_query,
        )

    signature = _build_target_hud_signature(
        query=query,
        payload=emit_payload,
        gallery_items=gallery_items,
    )
    if signature == next_state.last_signature and now_ms - next_state.last_sent_ms < scene_interval_ms:
        return TargetHudEvaluation(
            next_state=next_state,
            emit_payload=None,
            emit_log_payload=None,
        )

    next_state = replace(
        next_state,
        last_signature=signature,
        last_sent_ms=now_ms,
    )
    return TargetHudEvaluation(
        next_state=next_state,
        emit_payload=emit_payload,
        emit_log_payload={
            "query": query,
            "candidateCount": len(gallery_items),
            "directionHint": _scene_text(emit_payload, "direction_hint"),
            "sceneId": emit_payload.get("sceneId"),
        },
    )
