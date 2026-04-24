"""Session replay export and scorecard helpers for V2 hardening."""

from __future__ import annotations

from typing import Any

from .contracts import utc_now


def build_session_replay(
    *,
    session_id: str | None,
    sessions: list[dict[str, Any]],
    events: list[dict[str, Any]],
    media: list[dict[str, Any]],
    perception: list[dict[str, Any]],
    hud_scenes: list[dict[str, Any]],
    realtime: list[dict[str, Any]],
    debug_stt: list[dict[str, Any]],
    limit: int = 1000,
) -> dict[str, Any]:
    """Build a redacted in-memory replay bundle.

    This is intentionally storage-free for the first skeleton. Persisting the
    bundle to disk belongs in a later PR once privacy and retention policies are
    wired into ops settings.
    """

    filtered_events = _filter_by_session(events, session_id)[-limit:]
    return {
        "schema_version": "openvision.session_replay.v1",
        "generated_at": utc_now(),
        "session_id": session_id,
        "redacted": True,
        "sessions": _filter_by_session(sessions, session_id),
        "events": filtered_events,
        "media": _filter_by_session(media, session_id),
        "perception": _filter_by_session(perception, session_id),
        "hud_scenes": _filter_by_session(hud_scenes, session_id),
        "realtime": _filter_by_session(realtime, session_id),
        "debug_stt": _filter_by_session(debug_stt, session_id),
        "limits": {"events": limit},
    }


def build_session_scorecard(replay: dict[str, Any]) -> dict[str, Any]:
    events = replay.get("events") if isinstance(replay.get("events"), list) else []
    media = replay.get("media") if isinstance(replay.get("media"), list) else []
    perception = replay.get("perception") if isinstance(replay.get("perception"), list) else []
    hud_scenes = replay.get("hud_scenes") if isinstance(replay.get("hud_scenes"), list) else []
    realtime = replay.get("realtime") if isinstance(replay.get("realtime"), list) else []
    debug_stt = replay.get("debug_stt") if isinstance(replay.get("debug_stt"), list) else []

    error_events = [event for event in events if event.get("severity") == "error"]
    warning_events = [event for event in events if event.get("severity") == "warning"]
    skill_events = [event for event in events if event.get("module") == "skills"]
    hud_events = [event for event in events if event.get("module") == "hud"]

    video_seen = any((item.get("video") or {}).get("state") == "receiving" for item in media)
    audio_seen = any((item.get("audio") or {}).get("state") == "receiving" for item in media)
    strong_chunk_ratio = _max_audio_ratio(media)
    perception_object_count = sum(len(item.get("objects") or []) for item in perception if isinstance(item, dict))

    gates = {
        "session_created": bool(replay.get("sessions")),
        "video_seen": video_seen,
        "audio_seen": audio_seen,
        "perception_seen": perception_object_count > 0,
        "skill_seen": bool(skill_events),
        "hud_seen": bool(hud_scenes or hud_events),
        "no_errors": not error_events,
    }
    passed = sum(1 for value in gates.values() if value)
    total = len(gates)
    status = "pass" if passed == total else "warn" if passed >= 3 and not error_events else "fail"

    return {
        "schema_version": "openvision.session_scorecard.v1",
        "generated_at": utc_now(),
        "session_id": replay.get("session_id"),
        "status": status,
        "score": round(passed / total, 4),
        "gates": gates,
        "metrics": {
            "event_count": len(events),
            "error_count": len(error_events),
            "warning_count": len(warning_events),
            "media_session_count": len(media),
            "max_audio_strong_chunk_ratio": strong_chunk_ratio,
            "perception_snapshot_count": len(perception),
            "perception_object_count": perception_object_count,
            "skill_event_count": len(skill_events),
            "hud_scene_count": len(hud_scenes),
            "hud_event_count": len(hud_events),
            "realtime_session_count": len(realtime),
            "debug_stt_turn_count": len(debug_stt),
        },
        "top_failures": [
            {
                "module": event.get("module"),
                "event_type": event.get("event_type"),
                "payload": event.get("payload") or {},
            }
            for event in error_events[-5:]
        ],
    }


def _filter_by_session(items: list[dict[str, Any]], session_id: str | None) -> list[dict[str, Any]]:
    if not session_id:
        return list(items)
    return [item for item in items if item.get("session_id") == session_id]


def _max_audio_ratio(media: list[dict[str, Any]]) -> float:
    ratios: list[float] = []
    for item in media:
        audio = item.get("audio") if isinstance(item, dict) else None
        if isinstance(audio, dict):
            try:
                ratios.append(float(audio.get("strong_chunk_ratio") or 0.0))
            except (TypeError, ValueError):
                ratios.append(0.0)
    return round(max(ratios) if ratios else 0.0, 4)
