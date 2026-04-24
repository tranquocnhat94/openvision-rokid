"""Concrete v2 skill executor backed by the perception graph."""

from __future__ import annotations

from typing import Any

from .contracts import new_id, utc_now
from .event_store import InMemoryEventStore
from .perception_graph import PerceptionGraph


class SkillExecutor:
    def __init__(self, *, perception: PerceptionGraph, events: InMemoryEventStore) -> None:
        self._perception = perception
        self._events = events
        self._selected_targets: dict[str, dict[str, Any]] = {}

    def execute(self, *, name: str, args: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
        started_at = utc_now()
        if name == "count_people":
            result = self._count_people(args=args, session_id=session_id)
        elif name == "search_targets":
            result = self._search_targets(args=args, session_id=session_id)
        elif name == "select_target":
            result = self._select_target(args=args, session_id=session_id)
        elif name == "clear_target":
            result = self._clear_target(session_id=session_id)
        elif name == "query_scene":
            result = self._query_scene(args=args, session_id=session_id)
        elif name == "analyze_selected_target":
            result = self._analyze_selected_target(args=args, session_id=session_id)
        else:
            result = {
                "status": "error",
                "error": {"code": "unknown_skill", "message": f"Unknown skill: {name}"},
            }
        payload = {
            "skill_call_id": new_id("skill"),
            "name": name,
            "args": args,
            "session_id": session_id,
            "status": result.get("status", "ok"),
            "result": result.get("result"),
            "error": result.get("error"),
            "created_at": started_at,
            "updated_at": utc_now(),
        }
        self._events.add(
            "skills",
            "executed",
            {"name": name, "status": payload["status"]},
            session_id=session_id,
            severity="error" if payload["status"] == "error" else "info",
        )
        return payload

    def _count_people(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        snapshot = self._require_snapshot(session_id)
        if not snapshot:
            return _no_evidence("No perception snapshot is available for this session.")
        min_confidence = float(args.get("min_confidence", 0.25))
        people = [
            item
            for item in snapshot["objects"]
            if item["label"] in {"person", "people"} and float(item["confidence"]) >= min_confidence
        ]
        return {
            "status": "ok",
            "result": {
                "count": len(people),
                "confidence": _mean_confidence(people),
                "evidence": [item["object_id"] for item in people],
                "snapshot_id": snapshot["snapshot_id"],
                "hud": {"answer_strip": f"{len(people)} người"},
            },
        }

    def _search_targets(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        snapshot = self._require_snapshot(session_id)
        if not snapshot:
            return _no_evidence("No perception snapshot is available for target search.")
        query = str(args.get("query") or "").lower()
        max_candidates = int(args.get("max_candidates") or 6)
        person_query = any(token in query for token in ("người", "person", "áo", "mặc", "đứng", "ngồi"))
        requires_cloud = _requires_cloud_attribute_resolution(query)
        objects = snapshot["objects"]
        if person_query:
            objects = [item for item in objects if item["label"] in {"person", "people"}]
        candidates = [
            {
                "target_id": item["object_id"],
                "label": item["label"],
                "confidence": item["confidence"],
                "bbox": item.get("bbox"),
                "track_id": item.get("track_id"),
                "crop_ref": item.get("crop_ref"),
                "match_status": "unverified_attribute_candidate" if requires_cloud else "label_match",
                "cloud_attribute_resolution": "required" if requires_cloud else "not_requested",
            }
            for item in objects[:max_candidates]
        ]
        thumbnails = [_candidate_thumbnail(candidate, index=index) for index, candidate in enumerate(candidates, start=1)]
        if requires_cloud:
            user_message = f"{len(candidates)} ứng viên người; chưa xác minh thuộc tính cần tìm."
            summary = (
                f"{len(candidates)} unverified candidates; cloud attribute resolution is required "
                "before confirming the requested visual attributes."
            )
            hud = {
                "answer_strip": user_message,
                "edge_chips": ["needs_cloud"],
                "thumbnail_count": len(candidates),
                "thumbnails": thumbnails,
            }
        else:
            user_message = f"{len(candidates)} ứng viên"
            summary = f"{len(candidates)} label candidates"
            hud = {"thumbnail_count": len(candidates), "thumbnails": thumbnails}
        return {
            "status": "needs_cloud" if requires_cloud else "ok",
            "result": {
                "user_message": user_message,
                "summary": summary,
                "candidates": candidates,
                "candidate_count": len(candidates),
                "confirmed_match_count": 0 if requires_cloud else len(candidates),
                "candidate_semantics": "unverified_attribute_candidates" if requires_cloud else "label_matches",
                "cloud_attribute_resolution": "required" if requires_cloud else "not_requested",
                "snapshot_id": snapshot["snapshot_id"],
                "hud": hud,
            },
        }

    def _select_target(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        target_id = str(args.get("target_id") or "").strip()
        if not target_id:
            return {"status": "error", "error": {"code": "missing_target_id", "message": "target_id is required"}}
        selected = {
            "target_id": target_id,
            "reason": str(args.get("reason") or ""),
            "selected_at": utc_now(),
        }
        if session_id:
            self._selected_targets[session_id] = selected
        return {"status": "ok", "result": {"selected_target": selected, "hud_hint": {"target_id": target_id}}}

    def _clear_target(self, *, session_id: str | None) -> dict[str, Any]:
        if session_id:
            self._selected_targets.pop(session_id, None)
        return {"status": "ok", "result": {"cleared": True}}

    def _query_scene(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        snapshot = self._require_snapshot(session_id)
        if not snapshot:
            return _no_evidence("No perception snapshot is available for scene query.")
        counts: dict[str, int] = {}
        for item in snapshot["objects"]:
            counts[item["label"]] = counts.get(item["label"], 0) + 1
        answer = ", ".join(f"{count} {label}" for label, count in sorted(counts.items())) or "No objects"
        return {
            "status": "ok",
            "result": {
                "answer": answer,
                "counts": counts,
                "snapshot_id": snapshot["snapshot_id"],
                "hud": {"answer_strip": answer},
            },
        }

    def _analyze_selected_target(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        selected = self._selected_targets.get(session_id or "")
        if not selected:
            return _no_evidence("No selected target is active.")
        return {
            "status": "needs_cloud",
            "result": {
                "target_id": selected["target_id"],
                "question": str(args.get("question") or ""),
                "cloud_attribute_resolution": "required",
            },
        }

    def _require_snapshot(self, session_id: str | None) -> dict[str, Any] | None:
        return self._perception.latest(session_id) if session_id else None


def _mean_confidence(items: list[dict[str, Any]]) -> float:
    if not items:
        return 0.0
    return round(sum(float(item["confidence"]) for item in items) / len(items), 4)


def _no_evidence(message: str) -> dict[str, Any]:
    return {
        "status": "no_evidence",
        "result": {
            "message": message,
            "hud": {"answer_strip": "Chưa có dữ liệu hình ảnh"},
        },
    }


def _requires_cloud_attribute_resolution(query: str) -> bool:
    if not query:
        return False
    attribute_tokens = {
        "áo",
        "ao",
        "mặc",
        "mac",
        "màu",
        "mau",
        "xanh",
        "đỏ",
        "do",
        "đen",
        "den",
        "trắng",
        "trang",
        "vàng",
        "vang",
        "kính",
        "kinh",
        "đứng",
        "dung",
        "ngồi",
        "ngoi",
        "đội",
        "doi",
        "cầm",
        "cam",
        "wearing",
        "shirt",
        "color",
        "glasses",
        "standing",
        "sitting",
    }
    return any(token in query for token in attribute_tokens)


def _candidate_thumbnail(candidate: dict[str, Any], *, index: int) -> dict[str, Any]:
    caption_parts = [str(candidate.get("label") or "target")]
    if candidate.get("track_id"):
        caption_parts.append(str(candidate["track_id"]))
    thumbnail: dict[str, Any] = {
        "thumbnail_id": candidate["target_id"],
        "target_id": candidate["target_id"],
        "caption": f"{index}. {' '.join(caption_parts)}",
        "label": candidate.get("label"),
        "confidence": candidate.get("confidence"),
        "bbox": candidate.get("bbox"),
        "crop_ref": candidate.get("crop_ref"),
        "match_status": candidate.get("match_status"),
    }
    crop_ref = candidate.get("crop_ref")
    if isinstance(crop_ref, str) and crop_ref.startswith(("/", "http://", "https://")):
        thumbnail["image_url"] = crop_ref
    return thumbnail
