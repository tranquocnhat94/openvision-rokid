from __future__ import annotations

from typing import Any


def build_hud_scene_payload(
    *,
    session_id: str,
    scene_id: str,
    task_chip: str | None = None,
    mic_chip: str | None = None,
    answer_text: str | None = None,
    status_text: str | None = None,
    gallery_labels: list[str] | None = None,
    gallery_items: list[dict[str, Any]] | None = None,
    direction_hint: str | None = None,
    target_marker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    if task_chip:
        components.append(
            {"kind": "chip", "id": "task_chip", "zone": "top_center", "text": task_chip, "tone": "active"}
        )
    if mic_chip:
        components.append(
            {"kind": "chip", "id": "mic_chip", "zone": "top_center", "text": mic_chip, "tone": "status"}
        )
    if answer_text:
        components.append(
            {"kind": "answer_strip", "id": "answer", "zone": "lower_safe", "text": answer_text}
        )
    if status_text:
        components.append(
            {"kind": "status_strip", "id": "status", "zone": "lower_safe", "text": status_text}
        )
    gallery_payload = gallery_items or ([{"label": label} for label in gallery_labels] if gallery_labels else [])
    if gallery_payload:
        components.append(
            {
                "kind": "gallery",
                "id": "candidate_gallery",
                "zone": "upper_right",
                "items": gallery_payload,
            }
        )
    if direction_hint:
        components.append(
            {"kind": "direction_hint", "id": "target_direction", "zone": "upper_right", "text": direction_hint}
        )
    if target_marker:
        components.append(target_marker)
    return {
        "type": "hud_scene",
        "version": 1,
        "sessionId": session_id,
        "sceneId": scene_id,
        "layout": "rokid_hud_v1",
        "components": components,
    }


def build_target_search_hud_scene_payload(
    *,
    session_id: str,
    scene_id: str,
    query: str,
    selected_target_track_id: str,
    selected_target_visible: bool,
    selected_target_label: str,
    gallery_items: list[dict[str, Any]],
    direction_hint: str | None,
    target_marker: dict[str, Any] | None,
) -> dict[str, Any] | None:
    query_label = str(query or "").strip()
    if not query_label:
        return None
    clipped_query = query_label[:20].strip()
    candidate_count = len(gallery_items)
    if selected_target_track_id and selected_target_visible and candidate_count > 0:
        answer_text = f"{selected_target_label or 'Doi tuong'} dang duoc theo doi"
        status_text = None
    elif candidate_count <= 0:
        answer_text = None
        status_text = f"Dang quet {clipped_query}"
        direction_hint = "Dang quet khung hinh"
    elif candidate_count == 1:
        answer_text = f"1 ung vien cho {clipped_query}"
        status_text = None
    else:
        answer_text = f"{candidate_count} ung vien cho {clipped_query}"
        status_text = None
    return build_hud_scene_payload(
        session_id=session_id,
        scene_id=scene_id,
        task_chip=f"Tim: {query_label[:22]}",
        mic_chip="target search",
        answer_text=answer_text,
        status_text=status_text,
        gallery_items=gallery_items,
        direction_hint=direction_hint,
        target_marker=target_marker,
    )


def scene_gallery_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    gallery_component = next(
        (
            component
            for component in payload.get("components", [])
            if isinstance(component, dict) and component.get("kind") == "gallery"
        ),
        None,
    )
    if not isinstance(gallery_component, dict):
        return []
    items = gallery_component.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def scene_component(payload: dict[str, Any], kind: str) -> dict[str, Any] | None:
    component = next(
        (
            component
            for component in payload.get("components", [])
            if isinstance(component, dict) and component.get("kind") == kind
        ),
        None,
    )
    return component if isinstance(component, dict) else None
