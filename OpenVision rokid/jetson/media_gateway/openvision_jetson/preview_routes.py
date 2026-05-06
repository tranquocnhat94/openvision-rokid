"""Jetson-owned Sensor Preview route contracts.

The live Sensor Preview is a compressed video route, not the decoded JPEG
evidence store. Snapshot/evidence images remain available for skills, cloud
bundles, and review pages, but live skill preview selection is centralized here
so the browser does not accidentally mix raw video, DeepStream OSD video, and
stale JPEG bbox artifacts.
"""

from __future__ import annotations

from typing import Any

from .contracts import utc_now


PREVIEW_ROUTE_SCHEMA_VERSION = "openvision.preview_route.v1"

ROUTE_RAW_H264 = "raw_h264"
ROUTE_DEEPSTREAM_OSD_H264 = "deepstream_osd_h264"
ROUTE_STABLE_OVERLAY_H264 = "stable_overlay_h264"
ROUTE_SNAPSHOT_IMAGE = "snapshot_image"

BRANCH_RAW_LIVE = "raw_live"
BRANCH_YOLO26_OBJECTS = "yolo26_objects"
BRANCH_FACE_IDENTITY = "face_identity"
BRANCH_SNAPSHOT_EVIDENCE = "snapshot_evidence"

YOLO26_ROUTE_SKILLS = {"target_finder"}
FACE_IDENTITY_ROUTE_SKILLS = {"person_info"}


def skill_preview_route_spec(*, skill_id: str | None, mode: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the Jetson-authoritative preview/perception route for a skill media command."""

    clean_skill = str(skill_id or "").strip()
    clean_mode = str(mode or "").strip()
    _ = args or {}
    if clean_mode == "live_video":
        if clean_skill in YOLO26_ROUTE_SKILLS:
            branches = [BRANCH_YOLO26_OBJECTS]
            requires = ["rv101_h264", "yolo26_stream_worker", "yolo26_live_stabilizer"]
            if _target_finder_needs_identity_branch(args or {}):
                branches.append(BRANCH_FACE_IDENTITY)
                requires.append("face_identity_worker")
            return {
                "schema_version": PREVIEW_ROUTE_SCHEMA_VERSION,
                "route_kind": ROUTE_STABLE_OVERLAY_H264,
                "primary_branch": BRANCH_YOLO26_OBJECTS,
                "perception_branches": branches,
                "overlay_policy": "stable_perception_overlay",
                "bbox_authority": "perception_graph_stable",
                "diagnostic_route_kind": ROUTE_DEEPSTREAM_OSD_H264,
                "live_video_required": True,
                "jpeg_live_fallback_allowed": False,
                "requires": requires,
            }
        if clean_skill in FACE_IDENTITY_ROUTE_SKILLS:
            return {
                "schema_version": PREVIEW_ROUTE_SCHEMA_VERSION,
                "route_kind": ROUTE_RAW_H264,
                "primary_branch": BRANCH_FACE_IDENTITY,
                "perception_branches": [BRANCH_FACE_IDENTITY],
                "overlay_policy": "metadata_only",
                "bbox_authority": "face_identity_stream",
                "live_video_required": True,
                "jpeg_live_fallback_allowed": False,
                "requires": ["rv101_h264", "face_identity_worker"],
            }
        return {
            "schema_version": PREVIEW_ROUTE_SCHEMA_VERSION,
            "route_kind": ROUTE_RAW_H264,
            "primary_branch": BRANCH_RAW_LIVE,
            "perception_branches": [BRANCH_RAW_LIVE],
            "overlay_policy": "none",
            "bbox_authority": "none",
            "live_video_required": True,
            "jpeg_live_fallback_allowed": False,
            "requires": ["rv101_h264"],
        }
    if clean_mode in {"snapshot", "burst_clip"}:
        return {
            "schema_version": PREVIEW_ROUTE_SCHEMA_VERSION,
            "route_kind": ROUTE_SNAPSHOT_IMAGE,
            "primary_branch": BRANCH_SNAPSHOT_EVIDENCE,
            "perception_branches": [BRANCH_SNAPSHOT_EVIDENCE],
            "overlay_policy": "none",
            "bbox_authority": "perception_metadata",
            "live_video_required": False,
            "jpeg_live_fallback_allowed": False,
            "requires": ["snapshot_evidence"],
        }
    return {
        "schema_version": PREVIEW_ROUTE_SCHEMA_VERSION,
        "route_kind": "none",
        "primary_branch": "none",
        "perception_branches": [],
        "overlay_policy": "none",
        "bbox_authority": "none",
        "live_video_required": False,
        "jpeg_live_fallback_allowed": False,
        "requires": [],
    }


def active_live_uses_adapter(active_live: dict[str, Any], *, adapter: str) -> bool:
    """Check whether an active live command opted into an adapter branch."""

    params = active_live.get("params") if isinstance(active_live.get("params"), dict) else {}
    branches = _string_set(params.get("perception_branches"))
    preview_route = params.get("preview_route") if isinstance(params.get("preview_route"), dict) else {}
    primary_branch = str(preview_route.get("primary_branch") or "").strip()
    skill_id = str(active_live.get("skill_id") or "").strip()
    if adapter == "yolo26":
        return (
            BRANCH_YOLO26_OBJECTS in branches
            or primary_branch == BRANCH_YOLO26_OBJECTS
            or (not branches and skill_id in YOLO26_ROUTE_SKILLS)
        )
    if adapter == "face_identity":
        return (
            BRANCH_FACE_IDENTITY in branches
            or primary_branch == BRANCH_FACE_IDENTITY
            or (not branches and skill_id in (YOLO26_ROUTE_SKILLS | FACE_IDENTITY_ROUTE_SKILLS))
        )
    return False


def build_sensor_preview_route(
    *,
    session_id: str,
    active_live: dict[str, Any] | None = None,
    raw_h264: dict[str, Any] | None = None,
    deepstream_h264: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Materialize the current Sensor Preview route for a session."""

    if active_live:
        params = active_live.get("params") if isinstance(active_live.get("params"), dict) else {}
        spec = params.get("preview_route") if isinstance(params.get("preview_route"), dict) else {}
        if not spec:
            spec = skill_preview_route_spec(
                skill_id=str(active_live.get("skill_id") or ""),
                mode="live_video",
                args=params.get("skill_args") if isinstance(params.get("skill_args"), dict) else {},
            )
        desired_route_kind = str(spec.get("route_kind") or ROUTE_RAW_H264)
        route_kind = desired_route_kind
        live = deepstream_h264 if desired_route_kind == ROUTE_DEEPSTREAM_OSD_H264 else raw_h264
        fallback_reason = None
        if (
            desired_route_kind == ROUTE_DEEPSTREAM_OSD_H264
            and _live_sample_count(deepstream_h264) <= 0
            and _live_sample_count(raw_h264) > 0
        ):
            route_kind = ROUTE_RAW_H264
            live = raw_h264
            fallback_reason = "deepstream_osd_no_samples_raw_h264_live"
        if desired_route_kind == ROUTE_STABLE_OVERLAY_H264:
            route_kind = ROUTE_STABLE_OVERLAY_H264
            live = raw_h264
        return _live_route_payload(
            session_id=session_id,
            active_live=active_live,
            spec=spec,
            route_kind=route_kind,
            desired_route_kind=desired_route_kind,
            live=live,
            fallback_reason=fallback_reason,
        )
    if snapshot:
        return _snapshot_route_payload(session_id=session_id, snapshot=snapshot)
    if deepstream_h264:
        return _orphan_live_payload(session_id=session_id, route_kind=ROUTE_DEEPSTREAM_OSD_H264, live=deepstream_h264)
    if raw_h264:
        return _orphan_live_payload(session_id=session_id, route_kind=ROUTE_RAW_H264, live=raw_h264)
    return {
        "schema_version": PREVIEW_ROUTE_SCHEMA_VERSION,
        "session_id": session_id,
        "route_id": f"{session_id}:none",
        "route_kind": "none",
        "status": "idle",
        "updated_at": utc_now(),
    }


def _live_route_payload(
    *,
    session_id: str,
    active_live: dict[str, Any],
    spec: dict[str, Any],
    route_kind: str,
    desired_route_kind: str,
    live: dict[str, Any] | None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    command_id = str(active_live.get("command_id") or "").strip()
    skill_id = str(active_live.get("skill_id") or "").strip()
    is_deepstream = route_kind == ROUTE_DEEPSTREAM_OSD_H264
    uses_raw_h264 = route_kind in {ROUTE_RAW_H264, ROUTE_STABLE_OVERLAY_H264}
    ws_url = f"/ws/preview/{session_id}/deepstream-h264" if is_deepstream else f"/ws/preview/{session_id}/h264"
    sample_count = int((live or {}).get("sample_count") or 0)
    status = "live" if sample_count > 0 else "pending"
    if fallback_reason and sample_count > 0:
        status = "live_waiting_for_osd"
    metadata = (live or {}).get("metadata") if isinstance((live or {}).get("metadata"), dict) else {}
    overlay_policy = spec.get("overlay_policy")
    bbox_authority = spec.get("bbox_authority")
    if fallback_reason:
        overlay_policy = "pending_deepstream_osd"
        bbox_authority = "pending_deepstream_osd"
    return {
        "schema_version": PREVIEW_ROUTE_SCHEMA_VERSION,
        "session_id": session_id,
        "route_id": f"{session_id}:{command_id or 'live'}:{route_kind}",
        "route_kind": route_kind,
        "desired_route_kind": desired_route_kind,
        "status": status,
        "media_mode": "live_video",
        "skill_id": skill_id or None,
        "command_id": command_id or None,
        "primary_branch": spec.get("primary_branch"),
        "perception_branches": list(spec.get("perception_branches") or []),
        "overlay_policy": overlay_policy,
        "bbox_authority": bbox_authority,
        "desired_overlay_policy": spec.get("overlay_policy"),
        "desired_bbox_authority": spec.get("bbox_authority"),
        "live_video_required": True,
        "jpeg_live_fallback_allowed": False,
        "requires": list(spec.get("requires") or []),
        "fallback_reason": fallback_reason,
        "source": "deepstream_yolo26_osd" if is_deepstream else str((live or {}).get("transport") or "rv101_tcp"),
        "codec": "video/avc",
        "container": "annexb_h264",
        "ws_url": ws_url,
        "h264_ws_url": ws_url,
        "width": (live or {}).get("width") or _resolution_value(active_live, "width"),
        "height": (live or {}).get("height") or _resolution_value(active_live, "height"),
        "fps": active_live.get("fps"),
        "frame_count": sample_count,
        "sample_count": sample_count,
        "updated_at": (live or {}).get("updated_at") or utc_now(),
        "metadata": {
            **metadata,
            "sensor_preview_route": route_kind,
            "desired_sensor_preview_route": desired_route_kind,
            "skill_id": skill_id or None,
            "command_id": command_id or None,
            "primary_branch": spec.get("primary_branch"),
            "jpeg_live_fallback_allowed": False,
            "deepstream_osd_pending": bool(fallback_reason),
            "fallback_reason": fallback_reason,
            "osd_burned_in": bool(is_deepstream),
            "stable_overlay": route_kind == ROUTE_STABLE_OVERLAY_H264,
            "overlay_source": "perception_graph" if route_kind == ROUTE_STABLE_OVERLAY_H264 else None,
            "raw_h264_transport": bool(uses_raw_h264),
        },
    }


def _snapshot_route_payload(*, session_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    image_url = str(snapshot.get("image_url") or "")
    return {
        "schema_version": PREVIEW_ROUTE_SCHEMA_VERSION,
        "session_id": session_id,
        "route_id": f"{session_id}:snapshot:{snapshot.get('frame_count') or 0}",
        "route_kind": ROUTE_SNAPSHOT_IMAGE,
        "status": "ready" if snapshot.get("has_frame") else "pending",
        "media_mode": "snapshot",
        "primary_branch": BRANCH_SNAPSHOT_EVIDENCE,
        "perception_branches": [BRANCH_SNAPSHOT_EVIDENCE],
        "overlay_policy": "none",
        "bbox_authority": "perception_metadata",
        "live_video_required": False,
        "jpeg_live_fallback_allowed": False,
        "source": snapshot.get("source"),
        "image_url": image_url,
        "width": snapshot.get("width"),
        "height": snapshot.get("height"),
        "frame_count": snapshot.get("frame_count") or 0,
        "updated_at": snapshot.get("updated_at") or utc_now(),
        "metadata": {
            **(snapshot.get("metadata") if isinstance(snapshot.get("metadata"), dict) else {}),
            "sensor_preview_route": ROUTE_SNAPSHOT_IMAGE,
            "jpeg_live_fallback_allowed": False,
        },
    }


def _orphan_live_payload(*, session_id: str, route_kind: str, live: dict[str, Any]) -> dict[str, Any]:
    is_deepstream = route_kind == ROUTE_DEEPSTREAM_OSD_H264
    ws_url = f"/ws/preview/{session_id}/deepstream-h264" if is_deepstream else f"/ws/preview/{session_id}/h264"
    return {
        "schema_version": PREVIEW_ROUTE_SCHEMA_VERSION,
        "session_id": session_id,
        "route_id": f"{session_id}:orphan:{route_kind}",
        "route_kind": route_kind,
        "status": "orphaned",
        "media_mode": "live_video",
        "source": "deepstream_yolo26_osd" if is_deepstream else str(live.get("transport") or "rv101_tcp"),
        "codec": "video/avc",
        "container": "annexb_h264",
        "ws_url": ws_url,
        "h264_ws_url": ws_url,
        "width": live.get("width"),
        "height": live.get("height"),
        "frame_count": live.get("sample_count") or 0,
        "sample_count": live.get("sample_count") or 0,
        "updated_at": live.get("updated_at") or utc_now(),
        "metadata": {
            **(live.get("metadata") if isinstance(live.get("metadata"), dict) else {}),
            "sensor_preview_route": route_kind,
            "orphaned_live_route": True,
            "jpeg_live_fallback_allowed": False,
            "osd_burned_in": bool(is_deepstream),
        },
    }


def _resolution_value(active_live: dict[str, Any], key: str) -> int | None:
    resolution = active_live.get("resolution") if isinstance(active_live.get("resolution"), dict) else {}
    value = resolution.get(key)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _string_set(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    if isinstance(value, str) and value.strip():
        return {value.strip()}
    return set()


def _live_sample_count(live: dict[str, Any] | None) -> int:
    try:
        return int((live or {}).get("sample_count") or 0)
    except (TypeError, ValueError):
        return 0


def _target_finder_needs_identity_branch(args: dict[str, Any]) -> bool:
    target_type = str(args.get("target_type") or "person").strip().lower()
    if target_type == "person":
        return True
    if bool(args.get("identity_query")):
        return True
    if str(args.get("target_name") or "").strip():
        return True
    query = str(args.get("query") or "").lower()
    return any(token in query for token in ("người quen", "nguoi quen", "người nhà", "nguoi nha", "contact", "known person"))
