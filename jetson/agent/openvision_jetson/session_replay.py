"""Session replay export and scorecard helpers for V2 hardening."""

from __future__ import annotations

from typing import Any

from .contracts import utc_now


SCORECARD_THRESHOLDS: dict[str, float | int] = {
    "video_fps_pass": 15.0,
    "video_fps_warn": 5.0,
    "audio_strong_chunk_ratio_pass": 0.5,
    "audio_strong_chunk_ratio_warn": 0.2,
    "hud_scene_min_count": 1,
}

REQUIRED_SCORECARD_GATES = (
    "session_created",
    "video_fps",
    "audio_signal",
    "hud_scene",
    "no_errors",
)


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
    debug_stt_status: dict[str, Any] | None = None,
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
        "debug_stt_status": debug_stt_status or {"enabled": False, "status": "unknown"},
        "limits": {"events": limit},
    }


def build_session_scorecard(replay: dict[str, Any]) -> dict[str, Any]:
    events = replay.get("events") if isinstance(replay.get("events"), list) else []
    media = replay.get("media") if isinstance(replay.get("media"), list) else []
    perception = replay.get("perception") if isinstance(replay.get("perception"), list) else []
    hud_scenes = replay.get("hud_scenes") if isinstance(replay.get("hud_scenes"), list) else []
    realtime = replay.get("realtime") if isinstance(replay.get("realtime"), list) else []
    debug_stt = replay.get("debug_stt") if isinstance(replay.get("debug_stt"), list) else []
    debug_stt_status = replay.get("debug_stt_status") if isinstance(replay.get("debug_stt_status"), dict) else {}

    error_events = [event for event in events if event.get("severity") == "error"]
    warning_events = [event for event in events if event.get("severity") == "warning"]
    skill_events = [event for event in events if event.get("module") == "skills"]
    hud_events = [event for event in events if event.get("module") == "hud"]

    video = _video_metrics(media)
    audio = _audio_metrics(media)
    strong_chunk_ratio = _max_audio_ratio(media)
    perception_object_count = sum(len(item.get("objects") or []) for item in perception if isinstance(item, dict))
    hud_scene_count = len(hud_scenes)
    hud_event_count = len(hud_events)
    realtime_metrics = _realtime_metrics(realtime)

    gates = {
        "session_created": _session_created_gate(replay),
        "video_fps": _video_gate(video),
        "audio_signal": _audio_gate(audio),
        "hud_scene": _hud_gate(hud_scene_count=hud_scene_count, hud_event_count=hud_event_count),
        "realtime_status": _realtime_gate(realtime_metrics),
        "debug_stt_status": _debug_stt_gate(debug_stt=debug_stt, debug_stt_status=debug_stt_status),
        "perception_seen": _presence_gate(
            present=perception_object_count > 0,
            required=False,
            pass_message=f"perception graph has {perception_object_count} objects",
            warn_message="no perception objects in replay",
            observed={"object_count": perception_object_count, "snapshot_count": len(perception)},
        ),
        "skill_seen": _presence_gate(
            present=bool(skill_events),
            required=False,
            pass_message=f"{len(skill_events)} skill events recorded",
            warn_message="no typed skill event recorded",
            observed={"skill_event_count": len(skill_events)},
        ),
        "no_errors": _no_errors_gate(error_events),
    }
    status = _overall_status(gates)
    score = _score_gates(gates)

    return {
        "schema_version": "openvision.session_scorecard.v1",
        "generated_at": utc_now(),
        "session_id": replay.get("session_id"),
        "status": status,
        "score": score,
        "gates": gates,
        "metrics": {
            "event_count": len(events),
            "error_count": len(error_events),
            "warning_count": len(warning_events),
            "media_session_count": len(media),
            "max_video_fps": video["max_fps"],
            "video_receiving": video["receiving"],
            "video_frame_count": video["frame_count"],
            "audio_receiving": audio["receiving"],
            "audio_chunk_count": audio["chunk_count"],
            "audio_strong_chunk_count": audio["strong_chunk_count"],
            "max_audio_strong_chunk_ratio": strong_chunk_ratio,
            "perception_snapshot_count": len(perception),
            "perception_object_count": perception_object_count,
            "skill_event_count": len(skill_events),
            "hud_scene_count": hud_scene_count,
            "hud_event_count": hud_event_count,
            "realtime_session_count": len(realtime),
            "realtime_connected_count": realtime_metrics["connected_count"],
            "realtime_error_count": realtime_metrics["error_count"],
            "debug_stt_turn_count": len(debug_stt),
            "debug_stt_status": debug_stt_status.get("status") or "unknown",
            "required_gate_fail_count": sum(
                1 for name in REQUIRED_SCORECARD_GATES if gates[name]["status"] == "fail"
            ),
            "gate_pass_count": sum(1 for gate in gates.values() if gate["status"] == "pass"),
            "gate_warn_count": sum(1 for gate in gates.values() if gate["status"] == "warn"),
            "gate_fail_count": sum(1 for gate in gates.values() if gate["status"] == "fail"),
        },
        "top_failures": _top_failures(error_events=error_events, gates=gates),
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
            chunk_count = _to_int(audio.get("chunk_count"))
            strong_chunk_count = _to_int(audio.get("strong_chunk_count"))
            if chunk_count:
                ratios.append(strong_chunk_count / chunk_count)
                continue
            try:
                ratios.append(float(audio.get("strong_chunk_ratio") or 0.0))
            except (TypeError, ValueError):
                ratios.append(0.0)
    return round(max(ratios) if ratios else 0.0, 4)


def _gate(
    *,
    status: str,
    required: bool,
    message: str,
    observed: dict[str, Any] | None = None,
    threshold: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "required": required,
        "message": message,
        "observed": observed or {},
        "threshold": threshold or {},
    }


def _session_created_gate(replay: dict[str, Any]) -> dict[str, Any]:
    sessions = replay.get("sessions") if isinstance(replay.get("sessions"), list) else []
    return _gate(
        status="pass" if sessions else "fail",
        required=True,
        message="session exists" if sessions else "no session record in replay",
        observed={"session_count": len(sessions)},
    )


def _video_metrics(media: list[dict[str, Any]]) -> dict[str, Any]:
    receiving = False
    frame_count = 0
    fps_values: list[float] = []
    transports: list[str] = []
    for item in media:
        video = item.get("video") if isinstance(item, dict) else None
        if not isinstance(video, dict):
            continue
        if video.get("state") == "receiving":
            receiving = True
        frame_count += _to_int(video.get("frame_count"))
        fps = _to_float(video.get("fps"))
        if fps is not None:
            fps_values.append(fps)
        transport = video.get("transport")
        if isinstance(transport, str) and transport and transport not in transports:
            transports.append(transport)
    return {
        "receiving": receiving,
        "frame_count": frame_count,
        "max_fps": round(max(fps_values), 4) if fps_values else None,
        "transports": transports,
    }


def _video_gate(video: dict[str, Any]) -> dict[str, Any]:
    threshold = {
        "pass_min_fps": SCORECARD_THRESHOLDS["video_fps_pass"],
        "warn_min_fps": SCORECARD_THRESHOLDS["video_fps_warn"],
    }
    observed = {
        "receiving": video["receiving"],
        "max_fps": video["max_fps"],
        "frame_count": video["frame_count"],
        "transports": video["transports"],
    }
    if not video["receiving"]:
        return _gate(
            status="fail",
            required=True,
            message="no receiving video stream",
            observed=observed,
            threshold=threshold,
        )
    fps = video["max_fps"]
    if fps is None:
        return _gate(
            status="warn",
            required=True,
            message="video is receiving but fps is not measured yet",
            observed=observed,
            threshold=threshold,
        )
    if fps >= SCORECARD_THRESHOLDS["video_fps_pass"]:
        return _gate(
            status="pass",
            required=True,
            message=f"video fps is healthy at {fps:g}",
            observed=observed,
            threshold=threshold,
        )
    if fps >= SCORECARD_THRESHOLDS["video_fps_warn"]:
        return _gate(
            status="warn",
            required=True,
            message=f"video fps is low at {fps:g}",
            observed=observed,
            threshold=threshold,
        )
    return _gate(
        status="fail",
        required=True,
        message=f"video fps is too low at {fps:g}",
        observed=observed,
        threshold=threshold,
    )


def _audio_metrics(media: list[dict[str, Any]]) -> dict[str, Any]:
    receiving = False
    chunk_count = 0
    strong_chunk_count = 0
    sources: list[str] = []
    transports: list[str] = []
    for item in media:
        audio = item.get("audio") if isinstance(item, dict) else None
        if not isinstance(audio, dict):
            continue
        if audio.get("state") == "receiving":
            receiving = True
        chunk_count += _to_int(audio.get("chunk_count"))
        strong_chunk_count += _to_int(audio.get("strong_chunk_count"))
        source = audio.get("source")
        if isinstance(source, str) and source and source not in sources:
            sources.append(source)
        transport = audio.get("transport")
        if isinstance(transport, str) and transport and transport not in transports:
            transports.append(transport)
    ratio = round(strong_chunk_count / chunk_count, 4) if chunk_count else 0.0
    return {
        "receiving": receiving,
        "chunk_count": chunk_count,
        "strong_chunk_count": strong_chunk_count,
        "strong_chunk_ratio": ratio,
        "sources": sources,
        "transports": transports,
    }


def _audio_gate(audio: dict[str, Any]) -> dict[str, Any]:
    threshold = {
        "pass_min_strong_chunk_ratio": SCORECARD_THRESHOLDS["audio_strong_chunk_ratio_pass"],
        "warn_min_strong_chunk_ratio": SCORECARD_THRESHOLDS["audio_strong_chunk_ratio_warn"],
    }
    observed = {
        "receiving": audio["receiving"],
        "chunk_count": audio["chunk_count"],
        "strong_chunk_count": audio["strong_chunk_count"],
        "strong_chunk_ratio": audio["strong_chunk_ratio"],
        "sources": audio["sources"],
        "transports": audio["transports"],
    }
    if not audio["receiving"]:
        return _gate(
            status="fail",
            required=True,
            message="no receiving audio stream",
            observed=observed,
            threshold=threshold,
        )
    ratio = audio["strong_chunk_ratio"]
    if ratio >= SCORECARD_THRESHOLDS["audio_strong_chunk_ratio_pass"]:
        return _gate(
            status="pass",
            required=True,
            message=f"audio strong chunk ratio is healthy at {ratio:.2f}",
            observed=observed,
            threshold=threshold,
        )
    if ratio >= SCORECARD_THRESHOLDS["audio_strong_chunk_ratio_warn"]:
        return _gate(
            status="warn",
            required=True,
            message=f"audio is present but speech energy is weak at {ratio:.2f}",
            observed=observed,
            threshold=threshold,
        )
    return _gate(
        status="fail",
        required=True,
        message=f"audio strong chunk ratio is too weak at {ratio:.2f}",
        observed=observed,
        threshold=threshold,
    )


def _hud_gate(*, hud_scene_count: int, hud_event_count: int) -> dict[str, Any]:
    observed = {"hud_scene_count": hud_scene_count, "hud_event_count": hud_event_count}
    present = hud_scene_count >= SCORECARD_THRESHOLDS["hud_scene_min_count"] or hud_event_count > 0
    return _gate(
        status="pass" if present else "fail",
        required=True,
        message="HUD scene observed" if present else "no HUD scene or HUD update event observed",
        observed=observed,
        threshold={"min_hud_scene_count": SCORECARD_THRESHOLDS["hud_scene_min_count"]},
    )


def _realtime_metrics(realtime: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: list[str] = []
    event_count = 0
    error_count = 0
    for item in realtime:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "unknown")
        statuses.append(status)
        event_count += _to_int(item.get("event_count"))
        if status == "error" or (item.get("error") and status not in {"blocked"}):
            error_count += 1
    return {
        "statuses": statuses,
        "connected_count": sum(1 for status in statuses if status == "connected"),
        "blocked_count": sum(1 for status in statuses if status == "blocked"),
        "connecting_count": sum(1 for status in statuses if status == "connecting"),
        "error_count": error_count,
        "event_count": event_count,
    }


def _realtime_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    observed = dict(metrics)
    if metrics["connected_count"] > 0:
        return _gate(
            status="pass",
            required=False,
            message="Realtime cloud channel connected",
            observed=observed,
        )
    if metrics["error_count"] > 0:
        return _gate(
            status="fail",
            required=False,
            message="Realtime cloud channel has errors",
            observed=observed,
        )
    if metrics["blocked_count"] > 0:
        return _gate(
            status="warn",
            required=False,
            message="Realtime cloud channel is blocked by config",
            observed=observed,
        )
    if metrics["connecting_count"] > 0:
        return _gate(
            status="warn",
            required=False,
            message="Realtime cloud channel is still connecting",
            observed=observed,
        )
    return _gate(
        status="warn",
        required=False,
        message="Realtime cloud channel was not started for this replay",
        observed=observed,
    )


def _debug_stt_gate(
    *,
    debug_stt: list[dict[str, Any]],
    debug_stt_status: dict[str, Any],
) -> dict[str, Any]:
    runtime_status = str(debug_stt_status.get("status") or "unknown")
    enabled = bool(debug_stt_status.get("enabled"))
    ok_turns = sum(1 for item in debug_stt if isinstance(item, dict) and item.get("status", "ok") == "ok")
    observed = {
        "enabled": enabled,
        "runtime_status": runtime_status,
        "turn_count": len(debug_stt),
        "ok_turn_count": ok_turns,
        "last_error": debug_stt_status.get("last_error"),
    }
    if enabled and runtime_status == "enabled" and ok_turns > 0:
        return _gate(
            status="pass",
            required=False,
            message="Debug STT sidecar produced completed transcript turns",
            observed=observed,
        )
    if enabled and runtime_status == "enabled":
        return _gate(
            status="warn",
            required=False,
            message="Debug STT sidecar is enabled but no completed transcript is in this replay",
            observed=observed,
        )
    if enabled:
        return _gate(
            status="warn",
            required=False,
            message=f"Debug STT sidecar is {runtime_status}",
            observed=observed,
        )
    return _gate(
        status="warn",
        required=False,
        message="Debug STT sidecar is disabled; product routing is unaffected",
        observed=observed,
    )


def _presence_gate(
    *,
    present: bool,
    required: bool,
    pass_message: str,
    warn_message: str,
    observed: dict[str, Any],
) -> dict[str, Any]:
    return _gate(
        status="pass" if present else "warn",
        required=required,
        message=pass_message if present else warn_message,
        observed=observed,
    )


def _no_errors_gate(error_events: list[dict[str, Any]]) -> dict[str, Any]:
    return _gate(
        status="pass" if not error_events else "fail",
        required=True,
        message="no error events" if not error_events else f"{len(error_events)} error events recorded",
        observed={"error_count": len(error_events)},
    )


def _overall_status(gates: dict[str, dict[str, Any]]) -> str:
    required_gates = [gates[name] for name in REQUIRED_SCORECARD_GATES]
    if any(gate["status"] == "fail" for gate in required_gates):
        return "fail"
    if any(gate["status"] == "warn" for gate in required_gates):
        return "warn"
    if any(not gate["required"] and gate["status"] == "fail" for gate in gates.values()):
        return "warn"
    return "pass"


def _score_gates(gates: dict[str, dict[str, Any]]) -> float:
    values = {"pass": 1.0, "warn": 0.5, "fail": 0.0}
    if not gates:
        return 0.0
    return round(sum(values.get(gate["status"], 0.0) for gate in gates.values()) / len(gates), 4)


def _top_failures(
    *,
    error_events: list[dict[str, Any]],
    gates: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = [
        {
            "source": "gate",
            "gate": name,
            "status": gate["status"],
            "message": gate["message"],
            "observed": gate["observed"],
        }
        for name, gate in gates.items()
        if gate["status"] == "fail" or (gate["required"] and gate["status"] == "warn")
    ]
    failures.extend(
        {
            "source": "event",
            "module": event.get("module"),
            "event_type": event.get("event_type"),
            "payload": event.get("payload") or {},
        }
        for event in error_events[-5:]
    )
    return failures[:8]


def _to_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
