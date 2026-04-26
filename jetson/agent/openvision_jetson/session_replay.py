"""Session replay export and scorecard helpers for V2 hardening."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .contracts import utc_now
from .hud_authority import validate_hud_scene


SCORECARD_THRESHOLDS: dict[str, float | int] = {
    "video_fps_pass": 15.0,
    "video_fps_warn": 5.0,
    "video_last_frame_age_ms_pass": 2_000,
    "video_last_frame_age_ms_warn": 5_000,
    "audio_strong_chunk_ratio_pass": 0.5,
    "audio_strong_chunk_ratio_warn": 0.2,
    "audio_avg_abs_pass": 120.0,
    "audio_avg_abs_warn": 80.0,
    "audio_non_silent_ratio_pass": 0.02,
    "audio_non_silent_ratio_warn": 0.01,
    "audio_peak_abs_warn": 320,
    "audio_gate_open_min": 1,
    "hud_scene_min_count": 1,
    "hud_last_scene_age_ms_pass": 5_000,
    "hud_last_scene_age_ms_warn": 15_000,
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
    generated_at = utc_now()
    session_completed = _session_completed(events=events, media=media)
    hud = _hud_metrics(hud_scenes=hud_scenes, hud_events=hud_events, generated_at=generated_at)
    realtime_metrics = _realtime_metrics(realtime)

    gates = {
        "session_created": _session_created_gate(replay),
        "video_fps": _video_gate(video),
        "audio_signal": _audio_gate(audio),
        "hud_scene": _hud_gate(hud, session_completed=session_completed),
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
        "generated_at": generated_at,
        "session_id": replay.get("session_id"),
        "status": status,
        "score": score,
        "gates": gates,
        "metrics": {
            "event_count": len(events),
            "error_count": len(error_events),
            "warning_count": len(warning_events),
            "media_session_count": len(media),
            "session_completed": session_completed,
            "max_video_fps": video["max_fps"],
            "max_video_reported_fps": video["max_reported_fps"],
            "max_video_estimated_fps": video["max_estimated_fps"],
            "video_last_frame_age_ms": video["last_frame_age_ms"],
            "video_receiving": video["receiving"],
            "video_frame_count": video["frame_count"],
            "video_resolution": video["resolution"],
            "audio_receiving": audio["receiving"],
            "audio_chunk_count": audio["chunk_count"],
            "audio_strong_chunk_count": audio["strong_chunk_count"],
            "audio_max_avg_abs": audio["max_avg_abs"],
            "audio_max_peak_abs": audio["max_peak_abs"],
            "audio_max_non_silent_ratio": audio["max_non_silent_ratio"],
            "audio_gate_open_count": audio["gate_open_count"],
            "audio_gate_close_count": audio["gate_close_count"],
            "audio_gate_forwarded_chunk_count": audio["gate_forwarded_chunk_count"],
            "audio_gate_state": audio["gate_state"],
            "max_audio_strong_chunk_ratio": strong_chunk_ratio,
            "perception_snapshot_count": len(perception),
            "perception_object_count": perception_object_count,
            "skill_event_count": len(skill_events),
            "hud_scene_count": hud_scene_count,
            "hud_event_count": hud_event_count,
            "hud_valid_scene_count": hud["valid_scene_count"],
            "hud_invalid_scene_count": hud["invalid_scene_count"],
            "hud_last_scene_age_ms": hud["last_scene_age_ms"],
            "hud_latest_answer_strip": hud["latest_answer_strip"],
            "hud_latest_priority": hud["latest_priority"],
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
    closed = False
    frame_count = 0
    reported_fps_values: list[float] = []
    estimated_fps_values: list[float] = []
    frame_age_values: list[int] = []
    transports: list[str] = []
    resolution: dict[str, int] | None = None
    for item in media:
        video = item.get("video") if isinstance(item, dict) else None
        if not isinstance(video, dict):
            continue
        if video.get("state") == "receiving":
            receiving = True
        if video.get("state") == "closed":
            closed = True
        frame_count += _to_int(video.get("frame_count"))
        reported_fps = _to_float(video.get("fps"))
        if reported_fps is not None:
            reported_fps_values.append(reported_fps)
        estimated_fps = _to_float(video.get("estimated_fps"))
        if estimated_fps is not None:
            estimated_fps_values.append(estimated_fps)
        last_frame_age_ms = _to_int_or_none(video.get("last_frame_age_ms"))
        if last_frame_age_ms is not None:
            frame_age_values.append(last_frame_age_ms)
        transport = video.get("transport")
        if isinstance(transport, str) and transport and transport not in transports:
            transports.append(transport)
        width = _to_int(video.get("width"))
        height = _to_int(video.get("height"))
        if width > 0 and height > 0:
            resolution = {"width": width, "height": height}
    max_reported_fps = round(max(reported_fps_values), 4) if reported_fps_values else None
    max_estimated_fps = round(max(estimated_fps_values), 4) if estimated_fps_values else None
    max_fps = max(value for value in [max_estimated_fps, max_reported_fps] if value is not None) if (
        max_estimated_fps is not None or max_reported_fps is not None
    ) else None
    return {
        "receiving": receiving,
        "closed": closed,
        "frame_count": frame_count,
        "max_fps": max_fps,
        "max_reported_fps": max_reported_fps,
        "max_estimated_fps": max_estimated_fps,
        "last_frame_age_ms": min(frame_age_values) if frame_age_values else None,
        "transports": transports,
        "resolution": resolution,
    }


def _video_gate(video: dict[str, Any]) -> dict[str, Any]:
    threshold = {
        "pass_min_fps": SCORECARD_THRESHOLDS["video_fps_pass"],
        "warn_min_fps": SCORECARD_THRESHOLDS["video_fps_warn"],
        "pass_max_last_frame_age_ms": SCORECARD_THRESHOLDS["video_last_frame_age_ms_pass"],
        "warn_max_last_frame_age_ms": SCORECARD_THRESHOLDS["video_last_frame_age_ms_warn"],
    }
    observed = {
        "receiving": video["receiving"],
        "closed": video["closed"],
        "max_fps": video["max_fps"],
        "max_reported_fps": video["max_reported_fps"],
        "max_estimated_fps": video["max_estimated_fps"],
        "last_frame_age_ms": video["last_frame_age_ms"],
        "frame_count": video["frame_count"],
        "transports": video["transports"],
        "resolution": video["resolution"],
    }
    if not video["receiving"] and not video["closed"]:
        return _gate(
            status="fail",
            required=True,
            message="no receiving video stream",
            observed=observed,
            threshold=threshold,
        )
    if video["frame_count"] <= 0:
        return _gate(
            status="fail",
            required=True,
            message="video heartbeat exists but no real frame sample was observed",
            observed=observed,
            threshold=threshold,
        )
    frame_age = video["last_frame_age_ms"]
    if frame_age is None:
        return _gate(
            status="warn",
            required=True,
            message=(
                "video stream ended with frame evidence but last frame age is not measured"
                if video["closed"]
                else "video frames were observed but last frame age is not measured yet"
            ),
            observed=observed,
            threshold=threshold,
        )
    if not video["closed"] and frame_age > SCORECARD_THRESHOLDS["video_last_frame_age_ms_warn"]:
        return _gate(
            status="fail",
            required=True,
            message=f"video stream is stale; last frame age is {frame_age}ms",
            observed=observed,
            threshold=threshold,
        )
    fps = video["max_fps"]
    if fps is None:
        return _gate(
            status="warn",
            required=True,
            message=(
                "video stream ended with frame evidence but fps is not measured"
                if video["closed"]
                else "video is receiving but fps is not measured yet"
            ),
            observed=observed,
            threshold=threshold,
        )
    if not video["closed"] and frame_age > SCORECARD_THRESHOLDS["video_last_frame_age_ms_pass"]:
        return _gate(
            status="warn",
            required=True,
            message=f"video frames are recent but aging at {frame_age}ms",
            observed=observed,
            threshold=threshold,
        )
    if fps >= SCORECARD_THRESHOLDS["video_fps_pass"]:
        return _gate(
            status="pass",
            required=True,
            message=(
                f"video stream ended after healthy evidence at {fps:g} fps"
                if video["closed"]
                else f"video fps is healthy at {fps:g}"
            ),
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
    closed = False
    chunk_count = 0
    strong_chunk_count = 0
    gate_open_count = 0
    gate_close_count = 0
    gate_decision_count = 0
    gate_forwarded_chunk_count = 0
    max_avg_abs_values: list[float] = []
    peak_values: list[int] = []
    max_non_silent_values: list[float] = []
    sources: list[str] = []
    transports: list[str] = []
    gate_state = "idle"
    for item in media:
        audio = item.get("audio") if isinstance(item, dict) else None
        if not isinstance(audio, dict):
            continue
        if audio.get("state") == "receiving":
            receiving = True
        if audio.get("state") == "closed":
            closed = True
        chunk_count += _to_int(audio.get("chunk_count"))
        strong_chunk_count += _to_int(audio.get("strong_chunk_count"))
        gate_open_count += _to_int(audio.get("gate_open_count"))
        gate_close_count += _to_int(audio.get("gate_close_count"))
        gate_decision_count += _to_int(audio.get("gate_decision_count"))
        gate_forwarded_chunk_count += _to_int(audio.get("gate_forwarded_chunk_count"))
        max_avg_abs = _to_float(audio.get("max_avg_abs", audio.get("avg_abs")))
        if max_avg_abs is not None:
            max_avg_abs_values.append(max_avg_abs)
        max_peak_abs = _to_int_or_none(audio.get("max_peak_abs", audio.get("peak_abs")))
        if max_peak_abs is not None:
            peak_values.append(max_peak_abs)
        max_non_silent_ratio = _to_float(audio.get("max_non_silent_ratio", audio.get("non_silent_ratio")))
        if max_non_silent_ratio is not None:
            max_non_silent_values.append(max_non_silent_ratio)
        source = audio.get("source")
        if isinstance(source, str) and source and source not in sources:
            sources.append(source)
        transport = audio.get("transport")
        if isinstance(transport, str) and transport and transport not in transports:
            transports.append(transport)
        if audio.get("gate_state") == "open":
            gate_state = "open"
    ratio = round(strong_chunk_count / chunk_count, 4) if chunk_count else 0.0
    return {
        "receiving": receiving,
        "closed": closed,
        "chunk_count": chunk_count,
        "strong_chunk_count": strong_chunk_count,
        "strong_chunk_ratio": ratio,
        "max_avg_abs": round(max(max_avg_abs_values), 4) if max_avg_abs_values else None,
        "max_peak_abs": max(peak_values) if peak_values else None,
        "max_non_silent_ratio": round(max(max_non_silent_values), 4) if max_non_silent_values else None,
        "gate_open_count": gate_open_count,
        "gate_close_count": gate_close_count,
        "gate_decision_count": gate_decision_count,
        "gate_forwarded_chunk_count": gate_forwarded_chunk_count,
        "gate_state": gate_state,
        "sources": sources,
        "transports": transports,
    }


def _audio_gate(audio: dict[str, Any]) -> dict[str, Any]:
    threshold = {
        "pass_min_strong_chunk_ratio": SCORECARD_THRESHOLDS["audio_strong_chunk_ratio_pass"],
        "warn_min_strong_chunk_ratio": SCORECARD_THRESHOLDS["audio_strong_chunk_ratio_warn"],
        "pass_min_avg_abs": SCORECARD_THRESHOLDS["audio_avg_abs_pass"],
        "warn_min_avg_abs": SCORECARD_THRESHOLDS["audio_avg_abs_warn"],
        "pass_min_non_silent_ratio": SCORECARD_THRESHOLDS["audio_non_silent_ratio_pass"],
        "warn_min_non_silent_ratio": SCORECARD_THRESHOLDS["audio_non_silent_ratio_warn"],
        "warn_min_peak_abs": SCORECARD_THRESHOLDS["audio_peak_abs_warn"],
        "pass_min_gate_open_count": SCORECARD_THRESHOLDS["audio_gate_open_min"],
    }
    observed = {
        "receiving": audio["receiving"],
        "closed": audio["closed"],
        "chunk_count": audio["chunk_count"],
        "strong_chunk_count": audio["strong_chunk_count"],
        "strong_chunk_ratio": audio["strong_chunk_ratio"],
        "max_avg_abs": audio["max_avg_abs"],
        "max_peak_abs": audio["max_peak_abs"],
        "max_non_silent_ratio": audio["max_non_silent_ratio"],
        "gate_open_count": audio["gate_open_count"],
        "gate_close_count": audio["gate_close_count"],
        "gate_decision_count": audio["gate_decision_count"],
        "gate_forwarded_chunk_count": audio["gate_forwarded_chunk_count"],
        "gate_state": audio["gate_state"],
        "sources": audio["sources"],
        "transports": audio["transports"],
    }
    if not audio["receiving"] and not audio["closed"]:
        return _gate(
            status="fail",
            required=True,
            message="no receiving audio stream",
            observed=observed,
            threshold=threshold,
        )
    if audio["chunk_count"] <= 0:
        return _gate(
            status="fail",
            required=True,
            message="audio stream is receiving but no PCM chunks were measured",
            observed=observed,
            threshold=threshold,
        )
    ratio = audio["strong_chunk_ratio"]
    avg_abs = float(audio["max_avg_abs"] or 0.0)
    peak_abs = int(audio["max_peak_abs"] or 0)
    non_silent_ratio = float(audio["max_non_silent_ratio"] or 0.0)
    signal_pass = ratio >= SCORECARD_THRESHOLDS["audio_strong_chunk_ratio_pass"] or (
        avg_abs >= SCORECARD_THRESHOLDS["audio_avg_abs_pass"]
        and non_silent_ratio >= SCORECARD_THRESHOLDS["audio_non_silent_ratio_pass"]
    )
    signal_warn = ratio >= SCORECARD_THRESHOLDS["audio_strong_chunk_ratio_warn"] or (
        avg_abs >= SCORECARD_THRESHOLDS["audio_avg_abs_warn"]
        and non_silent_ratio >= SCORECARD_THRESHOLDS["audio_non_silent_ratio_warn"]
    ) or peak_abs >= SCORECARD_THRESHOLDS["audio_peak_abs_warn"]
    if signal_pass and audio["gate_open_count"] >= SCORECARD_THRESHOLDS["audio_gate_open_min"]:
        return _gate(
            status="pass",
            required=True,
            message=(
                f"audio stream ended after healthy signal at strong ratio {ratio:.2f}"
                if audio["closed"]
                else f"audio signal is healthy at strong ratio {ratio:.2f}"
            ),
            observed=observed,
            threshold=threshold,
        )
    if signal_pass:
        return _gate(
            status="warn",
            required=True,
            message="audio signal is healthy but the forward gate did not open",
            observed=observed,
            threshold=threshold,
        )
    if signal_warn:
        return _gate(
            status="warn",
            required=True,
            message=f"audio is present but speech energy is weak at strong ratio {ratio:.2f}",
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


def _hud_metrics(
    *,
    hud_scenes: list[dict[str, Any]],
    hud_events: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    valid_scenes: list[dict[str, Any]] = []
    invalid_scene_count = 0
    for scene in hud_scenes:
        if not isinstance(scene, dict):
            invalid_scene_count += 1
            continue
        if validate_hud_scene(scene):
            invalid_scene_count += 1
        else:
            valid_scenes.append(scene)
    latest = _latest_hud_scene(valid_scenes)
    last_scene_age_ms = _age_ms(latest.get("created_at"), generated_at) if latest else None
    latest_answer = latest.get("answer_strip") if latest and isinstance(latest.get("answer_strip"), str) else None
    latest_priority = latest.get("priority") if latest and isinstance(latest.get("priority"), str) else None
    return {
        "scene_count": len(hud_scenes),
        "event_count": len(hud_events),
        "valid_scene_count": len(valid_scenes),
        "invalid_scene_count": invalid_scene_count,
        "last_scene_age_ms": last_scene_age_ms,
        "latest_answer_strip": latest_answer,
        "latest_priority": latest_priority,
    }


def _hud_gate(hud: dict[str, Any], *, session_completed: bool) -> dict[str, Any]:
    threshold = {
        "min_hud_scene_count": SCORECARD_THRESHOLDS["hud_scene_min_count"],
        "pass_max_last_scene_age_ms": SCORECARD_THRESHOLDS["hud_last_scene_age_ms_pass"],
        "warn_max_last_scene_age_ms": SCORECARD_THRESHOLDS["hud_last_scene_age_ms_warn"],
    }
    observed = dict(hud)
    if hud["valid_scene_count"] < SCORECARD_THRESHOLDS["hud_scene_min_count"]:
        return _gate(
            status="fail",
            required=True,
            message="no schema-valid HUD scene observed",
            observed=observed,
            threshold=threshold,
        )
    if hud["invalid_scene_count"] > 0:
        return _gate(
            status="fail",
            required=True,
            message=f"{hud['invalid_scene_count']} invalid HUD scenes observed",
            observed=observed,
            threshold=threshold,
        )
    age_ms = hud["last_scene_age_ms"]
    if session_completed:
        return _gate(
            status="pass",
            required=True,
            message="schema-valid HUD scene observed before session ended",
            observed=observed,
            threshold=threshold,
        )
    if age_ms is None:
        return _gate(
            status="warn",
            required=True,
            message="HUD scene is valid but age is unknown",
            observed=observed,
            threshold=threshold,
        )
    if age_ms > SCORECARD_THRESHOLDS["hud_last_scene_age_ms_warn"]:
        return _gate(
            status="fail",
            required=True,
            message=f"HUD scene is stale at {age_ms}ms",
            observed=observed,
            threshold=threshold,
        )
    if age_ms > SCORECARD_THRESHOLDS["hud_last_scene_age_ms_pass"]:
        return _gate(
            status="warn",
            required=True,
            message=f"HUD scene is aging at {age_ms}ms",
            observed=observed,
            threshold=threshold,
        )
    return _gate(
        status="pass",
        required=True,
        message="schema-valid HUD scene observed",
        observed=observed,
        threshold=threshold,
    )


def _session_completed(*, events: list[dict[str, Any]], media: list[dict[str, Any]]) -> bool:
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("module") == "media" and event.get("event_type") == "session_closed":
            return True
        if event.get("module") == "simulator" and event.get("event_type") == "webrtc_state":
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if payload.get("state") == "closed":
                return True
    for item in media:
        if not isinstance(item, dict):
            continue
        video = item.get("video") if isinstance(item.get("video"), dict) else {}
        audio = item.get("audio") if isinstance(item.get("audio"), dict) else {}
        if video.get("state") == "closed" or audio.get("state") == "closed":
            return True
    return False


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


def _latest_hud_scene(scenes: list[dict[str, Any]]) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    latest_timestamp: datetime | None = None
    for scene in scenes:
        created_at = _parse_timestamp(scene.get("created_at"))
        if created_at and (latest_timestamp is None or created_at >= latest_timestamp):
            latest = scene
            latest_timestamp = created_at
    return latest or (scenes[-1] if scenes else None)


def _age_ms(start: Any, end: Any) -> int | None:
    start_time = _parse_timestamp(start)
    end_time = _parse_timestamp(end)
    if not start_time or not end_time:
        return None
    return max(0, int((end_time - start_time).total_seconds() * 1000))


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _to_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _to_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
