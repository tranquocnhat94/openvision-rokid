"""Session replay export and scorecard helpers for V2 hardening."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .contracts import utc_now
from .hud_authority import validate_hud_scene
from .skill_eval import build_skill_eval


SCORECARD_THRESHOLDS: dict[str, float | int] = {
    "video_fps_pass": 15.0,
    "video_fps_warn": 5.0,
    "video_fps_budget_overrun_tolerance": 1.0,
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

CLOUD_RESULT_EVENT_TYPES = {
    "result",
    "provider_missing",
    "provider_error",
    "privacy_blocked",
    "budget_blocked",
    "bundle_rejected",
    "result_rejected",
    "verification_completed",
    "verification_failed",
    "verification_blocked",
}
CLOUD_BLOCKED_EVENT_TYPES = {"privacy_blocked", "budget_blocked", "verification_blocked"}
CLOUD_INVALID_CONTRACT_EVENT_TYPES = {"bundle_rejected", "result_rejected"}
CLOUD_INVALID_CONTRACT_CODES = {"invalid_evidence_bundle", "invalid_cloud_result"}
CLOUD_SUCCESS_STATUSES = {"ok", "no_match", "uncertain"}


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
    sessions = replay.get("sessions") if isinstance(replay.get("sessions"), list) else []

    error_events = [event for event in events if event.get("severity") == "error"]
    warning_events = [event for event in events if event.get("severity") == "warning"]
    skill_events = [event for event in events if event.get("module") == "skills"]
    hud_events = [event for event in events if event.get("module") == "hud"]
    cloud_events = [event for event in events if event.get("module") == "cloud_gateway"]

    video = _video_metrics(media, events=events)
    audio = _audio_metrics(media)
    strong_chunk_ratio = _max_audio_ratio(media)
    perception_object_count = sum(len(item.get("objects") or []) for item in perception if isinstance(item, dict))
    hud_scene_count = len(hud_scenes)
    hud_event_count = len(hud_events)
    generated_at = utc_now()
    session_completed = _session_completed(events=events, media=media)
    hud = _hud_metrics(hud_scenes=hud_scenes, hud_events=hud_events, generated_at=generated_at)
    realtime_metrics = _realtime_metrics(realtime)
    rv101_voice = _rv101_voice_contract_metrics(
        sessions=sessions,
        events=events,
        realtime=realtime,
    )
    realtime_tool_metrics = _event_latency_metrics(events, module="realtime_tool")
    media_command_metrics = _event_latency_metrics(events, module="media_command")
    display_command_metrics = _event_latency_metrics(events, module="display_command")
    cloud_gateway_metrics = _cloud_gateway_metrics(cloud_events)
    skill_eval = build_skill_eval(replay, generated_at=generated_at)
    idle_rv101_realtime = _idle_rv101_realtime_context(
        sessions=sessions,
        events=events,
        realtime_metrics=realtime_metrics,
        video=video,
        perception=perception,
        hud_scenes=hud_scenes,
    )

    gates = {
        "session_created": _session_created_gate(replay),
        "video_fps": _video_gate(video, idle_rv101_realtime=idle_rv101_realtime),
        "audio_signal": _audio_gate(audio, idle_rv101_realtime=idle_rv101_realtime),
        "hud_scene": _hud_gate(hud, session_completed=session_completed, idle_rv101_realtime=idle_rv101_realtime),
        "realtime_status": _realtime_gate(realtime_metrics),
        "rv101_voice_contract": _rv101_voice_contract_gate(rv101_voice),
        "typed_tool_calls": _typed_tool_gate(realtime_tool_metrics),
        "cloud_gateway": _cloud_gateway_gate(cloud_gateway_metrics),
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
    gates.update({f"skill_{name}": gate for name, gate in skill_eval["gates"].items()})
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
            "idle_rv101_realtime": idle_rv101_realtime,
            "max_video_fps": video["max_fps"],
            "max_video_reported_fps": video["max_reported_fps"],
            "max_video_estimated_fps": video["max_estimated_fps"],
            "max_video_sent_fps_estimate": video["max_sent_fps_estimate"],
            "max_video_actual_fps": video["max_actual_fps"],
            "max_video_budget_fps": video["max_budget_fps"],
            "video_dropped_frames": video["dropped_frames"],
            "video_camera_ids": video["camera_ids"],
            "video_last_frame_age_ms": video["last_frame_age_ms"],
            "video_receiving": video["receiving"],
            "video_frame_count": video["frame_count"],
            "video_resolution": video["resolution"],
            "video_clean_live_end": video["clean_live_end"],
            "video_final_status": video["final_status"],
            "video_final_adapter_status": video["final_adapter_status"],
            "video_sent_frames": video["sent_frames"],
            "video_sent_bytes": video["sent_bytes"],
            "video_keyframe_count": video["keyframe_count"],
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
            "realtime_turn_policies": realtime_metrics["turn_policies"],
            "rv101_voice_mode": rv101_voice["voice_mode"],
            "rv101_turn_policy": rv101_voice["turn_policy"],
            "rv101_voice_output_enabled": rv101_voice["voice_output_enabled"],
            "rv101_voice_contract_status": rv101_voice["status"],
            "realtime_tool_call_count": realtime_tool_metrics["call_count"],
            "realtime_tool_error_count": realtime_tool_metrics["error_count"],
            "realtime_tool_avg_latency_ms": realtime_tool_metrics["avg_latency_ms"],
            "realtime_tool_max_latency_ms": realtime_tool_metrics["max_latency_ms"],
            "media_command_count": media_command_metrics["call_count"],
            "media_command_error_count": media_command_metrics["error_count"],
            "media_command_avg_latency_ms": media_command_metrics["avg_latency_ms"],
            "media_command_max_latency_ms": media_command_metrics["max_latency_ms"],
            "display_command_count": display_command_metrics["call_count"],
            "display_command_error_count": display_command_metrics["error_count"],
            "display_command_avg_latency_ms": display_command_metrics["avg_latency_ms"],
            "display_command_max_latency_ms": display_command_metrics["max_latency_ms"],
            "cloud_gateway_event_count": cloud_gateway_metrics["event_count"],
            "cloud_gateway_bundle_count": cloud_gateway_metrics["bundle_count"],
            "cloud_gateway_result_count": cloud_gateway_metrics["result_count"],
            "cloud_gateway_success_count": cloud_gateway_metrics["success_count"],
            "cloud_gateway_blocked_count": cloud_gateway_metrics["blocked_count"],
            "cloud_gateway_fallback_count": cloud_gateway_metrics["fallback_count"],
            "cloud_gateway_missing_provider_count": cloud_gateway_metrics["missing_provider_count"],
            "cloud_gateway_provider_error_count": cloud_gateway_metrics["provider_error_count"],
            "cloud_gateway_invalid_contract_count": cloud_gateway_metrics["invalid_contract_count"],
            "cloud_gateway_validation_error_count": cloud_gateway_metrics["validation_error_count"],
            "cloud_gateway_error_count": cloud_gateway_metrics["error_count"],
            "cloud_gateway_avg_latency_ms": cloud_gateway_metrics["avg_latency_ms"],
            "cloud_gateway_max_latency_ms": cloud_gateway_metrics["max_latency_ms"],
            "cloud_gateway_statuses": cloud_gateway_metrics["statuses"],
            "cloud_gateway_error_codes": cloud_gateway_metrics["error_codes"],
            "skill_eval_status": skill_eval["status"],
            "skill_eval_score": skill_eval["score"],
            "skill_eval_skill_call_count": skill_eval["metrics"]["skill_call_count"],
            "skill_eval_visual_skill_call_count": skill_eval["metrics"]["visual_skill_call_count"],
            "skill_eval_media_visual_success_count": skill_eval["metrics"]["media_visual_success_count"],
            "skill_eval_cloud_result_count": skill_eval["metrics"]["cloud_result_count"],
            "skill_eval_identity_check_count": skill_eval["metrics"]["identity_check_count"],
            "skill_eval_hud_skill_chip_match_count": skill_eval["metrics"]["hud_skill_chip_match_count"],
            "debug_stt_turn_count": len(debug_stt),
            "debug_stt_status": debug_stt_status.get("status") or "unknown",
            "required_gate_fail_count": sum(
                1 for name in REQUIRED_SCORECARD_GATES if gates[name]["status"] == "fail"
            ),
            "gate_pass_count": sum(1 for gate in gates.values() if gate["status"] == "pass"),
            "gate_warn_count": sum(1 for gate in gates.values() if gate["status"] == "warn"),
            "gate_fail_count": sum(1 for gate in gates.values() if gate["status"] == "fail"),
        },
        "skill_eval": skill_eval,
        "top_failures": _top_failures(
            error_events=error_events,
            gates=gates,
            skill_failures=skill_eval.get("top_failures") if isinstance(skill_eval, dict) else None,
        ),
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


def _video_metrics(media: list[dict[str, Any]], *, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    receiving = False
    closed = False
    frame_count = 0
    reported_fps_values: list[float] = []
    estimated_fps_values: list[float] = []
    sent_fps_estimate_values: list[float] = []
    budget_fps_values: list[float] = []
    dropped_frame_values: list[int] = []
    camera_ids: list[str] = []
    frame_age_values: list[int] = []
    transports: list[str] = []
    resolution: dict[str, int] | None = None
    sent_frame_values: list[int] = []
    sent_byte_values: list[int] = []
    keyframe_values: list[int] = []
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
        metadata = video.get("metadata") if isinstance(video.get("metadata"), dict) else {}
        sent_fps_estimate = _to_float(metadata.get("sent_fps_estimate"))
        if sent_fps_estimate is not None:
            sent_fps_estimate_values.append(sent_fps_estimate)
        budget_fps = _to_float(metadata.get("capture_fps_max"))
        if budget_fps is None:
            budget_fps = _to_float(metadata.get("requested_fps"))
        if budget_fps is not None:
            budget_fps_values.append(budget_fps)
        dropped_frames = _to_int_or_none(metadata.get("dropped_frames"))
        if dropped_frames is not None:
            dropped_frame_values.append(dropped_frames)
        camera_id = metadata.get("camera_id")
        if isinstance(camera_id, str) and camera_id and camera_id not in camera_ids:
            camera_ids.append(camera_id)
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
    final = _live_video_final_metrics(events or [])
    if final:
        closed = closed or bool(final.get("clean_live_end"))
        final_sent_fps = _to_float(final.get("sent_fps_estimate"))
        if final_sent_fps is not None:
            sent_fps_estimate_values.append(final_sent_fps)
        final_budget_fps = _to_float(final.get("capture_fps_max"))
        if final_budget_fps is None:
            final_budget_fps = _to_float(final.get("requested_fps"))
        if final_budget_fps is not None:
            budget_fps_values.append(final_budget_fps)
        final_dropped = _to_int_or_none(final.get("dropped_frames"))
        if final_dropped is not None:
            dropped_frame_values.append(final_dropped)
        camera_id = final.get("camera_id")
        if isinstance(camera_id, str) and camera_id and camera_id not in camera_ids:
            camera_ids.append(camera_id)
        sent_frames = _to_int_or_none(final.get("sent_frames"))
        if sent_frames is not None:
            sent_frame_values.append(sent_frames)
            frame_count = max(frame_count, sent_frames)
        sent_bytes = _to_int_or_none(final.get("sent_bytes"))
        if sent_bytes is not None:
            sent_byte_values.append(sent_bytes)
        keyframe_count = _to_int_or_none(final.get("keyframe_count"))
        if keyframe_count is not None:
            keyframe_values.append(keyframe_count)
        final_width = _first_positive_int(
            final.get("selected_width"),
            final.get("width"),
            final.get("source_width"),
            final.get("requested_width"),
        )
        final_height = _first_positive_int(
            final.get("selected_height"),
            final.get("height"),
            final.get("source_height"),
            final.get("requested_height"),
        )
        if final_width and final_height:
            resolution = {"width": final_width, "height": final_height}
    max_reported_fps = round(max(reported_fps_values), 4) if reported_fps_values else None
    max_estimated_fps = round(max(estimated_fps_values), 4) if estimated_fps_values else None
    max_sent_fps_estimate = round(max(sent_fps_estimate_values), 4) if sent_fps_estimate_values else None
    max_actual_fps = max(value for value in [max_estimated_fps, max_sent_fps_estimate] if value is not None) if (
        max_estimated_fps is not None or max_sent_fps_estimate is not None
    ) else None
    max_budget_fps = round(max(budget_fps_values), 4) if budget_fps_values else None
    max_fps = max_actual_fps if max_actual_fps is not None else max_reported_fps
    dropped_frames = max(dropped_frame_values) if dropped_frame_values else None
    return {
        "receiving": receiving,
        "closed": closed,
        "frame_count": frame_count,
        "max_fps": max_fps,
        "max_reported_fps": max_reported_fps,
        "max_estimated_fps": max_estimated_fps,
        "max_sent_fps_estimate": max_sent_fps_estimate,
        "max_actual_fps": max_actual_fps,
        "max_budget_fps": max_budget_fps,
        "dropped_frames": dropped_frames,
        "camera_ids": camera_ids,
        "last_frame_age_ms": min(frame_age_values) if frame_age_values else None,
        "transports": transports,
        "resolution": resolution,
        "clean_live_end": bool(final.get("clean_live_end")) if final else False,
        "final_status": final.get("status") if final else None,
        "final_adapter_status": final.get("adapter_status") if final else None,
        "sent_frames": max(sent_frame_values) if sent_frame_values else None,
        "sent_bytes": max(sent_byte_values) if sent_byte_values else None,
        "keyframe_count": max(keyframe_values) if keyframe_values else None,
    }


def _video_gate(video: dict[str, Any], *, idle_rv101_realtime: bool = False) -> dict[str, Any]:
    pass_min_fps = float(SCORECARD_THRESHOLDS["video_fps_pass"])
    reported_fps = video.get("max_reported_fps")
    budget_fps = video.get("max_budget_fps")
    if isinstance(reported_fps, (int, float)) and reported_fps > 0:
        pass_min_fps = min(pass_min_fps, float(reported_fps))
    if isinstance(budget_fps, (int, float)) and budget_fps > 0:
        pass_min_fps = min(pass_min_fps, float(budget_fps))
    pass_min_fps_with_tolerance = round(pass_min_fps * 0.85, 4)
    threshold = {
        "pass_min_fps": pass_min_fps,
        "pass_min_fps_with_tolerance": pass_min_fps_with_tolerance,
        "warn_min_fps": SCORECARD_THRESHOLDS["video_fps_warn"],
        "budget_overrun_tolerance_fps": SCORECARD_THRESHOLDS["video_fps_budget_overrun_tolerance"],
        "pass_max_last_frame_age_ms": SCORECARD_THRESHOLDS["video_last_frame_age_ms_pass"],
        "warn_max_last_frame_age_ms": SCORECARD_THRESHOLDS["video_last_frame_age_ms_warn"],
    }
    observed = {
        "receiving": video["receiving"],
        "closed": video["closed"],
        "max_fps": video["max_fps"],
        "max_reported_fps": video["max_reported_fps"],
        "max_estimated_fps": video["max_estimated_fps"],
        "max_sent_fps_estimate": video["max_sent_fps_estimate"],
        "max_actual_fps": video["max_actual_fps"],
        "max_budget_fps": video["max_budget_fps"],
        "dropped_frames": video["dropped_frames"],
        "camera_ids": video["camera_ids"],
        "last_frame_age_ms": video["last_frame_age_ms"],
        "frame_count": video["frame_count"],
        "transports": video["transports"],
        "resolution": video["resolution"],
        "clean_live_end": video.get("clean_live_end"),
        "final_status": video.get("final_status"),
        "final_adapter_status": video.get("final_adapter_status"),
        "sent_frames": video.get("sent_frames"),
        "sent_bytes": video.get("sent_bytes"),
        "keyframe_count": video.get("keyframe_count"),
    }
    if not video["receiving"] and not video["closed"]:
        if idle_rv101_realtime and video["frame_count"] <= 0:
            return _gate(
                status="warn",
                required=False,
                message="idle RV101 realtime session has no video; camera is off by default",
                observed=observed,
                threshold=threshold,
            )
        if video["frame_count"] > 0:
            return _gate(
                status="warn",
                required=True,
                message="video is idle after frame evidence; no active live stream is receiving",
                observed=observed,
                threshold=threshold,
            )
        return _gate(
            status="fail",
            required=True,
            message="no receiving video stream",
            observed=observed,
            threshold=threshold,
        )
    if video.get("clean_live_end") and video["frame_count"] > 0:
        fps = video["max_fps"]
        if fps is None:
            return _gate(
                status="warn",
                required=True,
                message="live_video ended cleanly with frame evidence but fps is not measured",
                observed=observed,
                threshold=threshold,
            )
        budget_fps = video["max_budget_fps"]
        actual_fps = video["max_actual_fps"]
        if (
            budget_fps is not None
            and actual_fps is not None
            and actual_fps > budget_fps + SCORECARD_THRESHOLDS["video_fps_budget_overrun_tolerance"]
        ):
            return _gate(
                status="warn",
                required=True,
                message=f"live_video ended cleanly, but actual fps {actual_fps:g} exceeds requested budget {budget_fps:g}",
                observed=observed,
                threshold=threshold,
            )
        if fps >= pass_min_fps_with_tolerance:
            return _gate(
                status="pass",
                required=True,
                message=f"live_video ended cleanly after healthy app-reported evidence at {fps:g} fps",
                observed=observed,
                threshold=threshold,
            )
        if fps >= SCORECARD_THRESHOLDS["video_fps_warn"]:
            return _gate(
                status="warn",
                required=True,
                message=f"live_video ended cleanly but fps is low at {fps:g}",
                observed=observed,
                threshold=threshold,
            )
        return _gate(
            status="fail",
            required=True,
            message=f"live_video ended cleanly but fps is too low at {fps:g}",
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
    budget_fps = video["max_budget_fps"]
    actual_fps = video["max_actual_fps"]
    if (
        budget_fps is not None
        and actual_fps is not None
        and actual_fps > budget_fps + SCORECARD_THRESHOLDS["video_fps_budget_overrun_tolerance"]
    ):
        return _gate(
            status="warn",
            required=True,
            message=f"video actual fps {actual_fps:g} exceeds requested budget {budget_fps:g}",
            observed=observed,
            threshold=threshold,
        )
    if fps >= pass_min_fps_with_tolerance:
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


def _audio_gate(audio: dict[str, Any], *, idle_rv101_realtime: bool = False) -> dict[str, Any]:
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
    if idle_rv101_realtime:
        return _gate(
            status="warn",
            required=False,
            message="RV101 mic stream is present but no speech energy has been detected yet",
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


def _hud_gate(
    hud: dict[str, Any],
    *,
    session_completed: bool,
    idle_rv101_realtime: bool = False,
) -> dict[str, Any]:
    threshold = {
        "min_hud_scene_count": SCORECARD_THRESHOLDS["hud_scene_min_count"],
        "pass_max_last_scene_age_ms": SCORECARD_THRESHOLDS["hud_last_scene_age_ms_pass"],
        "warn_max_last_scene_age_ms": SCORECARD_THRESHOLDS["hud_last_scene_age_ms_warn"],
    }
    observed = dict(hud)
    if hud["valid_scene_count"] < SCORECARD_THRESHOLDS["hud_scene_min_count"]:
        if idle_rv101_realtime:
            return _gate(
                status="warn",
                required=False,
                message="idle RV101 realtime session has no HUD scene yet",
                observed=observed,
                threshold=threshold,
            )
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
        if event.get("module") in {"session", "sessions"} and event.get("event_type") in {"closed", "disconnected"}:
            return True
        if event.get("module") == "rv101_control" and event.get("event_type") in {"app_session_closed", "disconnected"}:
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


def _live_video_final_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    latest_timestamp = ""
    for event in events:
        if not isinstance(event, dict) or event.get("module") != "media_command":
            continue
        if event.get("event_type") != "command_completed":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if str(payload.get("mode") or "").strip() != "live_video":
            continue
        status = str(payload.get("status") or "").strip().lower()
        if status not in {"ok", "timeout", "cancelled", "error"}:
            continue
        timestamp = str(event.get("timestamp") or "")
        if latest and timestamp < latest_timestamp:
            continue
        latest_timestamp = timestamp
        latest = dict(payload)
    if not latest:
        return {}
    status = str(latest.get("status") or "").strip().lower()
    adapter_status = str(latest.get("adapter_status") or "").strip().lower()
    reason = str(latest.get("reason") or latest.get("action") or "").strip().lower()
    sent_frames = _to_int(latest.get("sent_frames"))
    clean_cancel_reason = any(
        token in f"{adapter_status} {reason}"
        for token in ("app_exit", "activity_stopped", "live_video_cancelled", "client_goodbye", "session_close")
    )
    clean_live_end = status in {"ok", "timeout"} or (
        status == "cancelled" and (clean_cancel_reason or sent_frames > 0)
    )
    return {
        **latest,
        "status": status,
        "adapter_status": adapter_status or None,
        "clean_live_end": clean_live_end,
    }


def _idle_rv101_realtime_context(
    *,
    sessions: list[dict[str, Any]],
    events: list[dict[str, Any]],
    realtime_metrics: dict[str, Any],
    video: dict[str, Any],
    perception: list[dict[str, Any]],
    hud_scenes: list[dict[str, Any]],
) -> bool:
    is_rv101 = any(
        isinstance(session, dict) and session.get("client_kind") == "rv101_glasses"
        for session in sessions
    )
    if not is_rv101 or realtime_metrics.get("connected_count", 0) <= 0:
        return False
    active_modules = {"skills", "realtime_tool", "media_command", "display_command", "cloud_gateway"}
    if any(isinstance(event, dict) and event.get("module") in active_modules for event in events):
        return False
    if perception or hud_scenes:
        return False
    if video.get("receiving") or video.get("closed") or _to_int(video.get("frame_count")) > 0:
        return False
    return True


def _realtime_metrics(realtime: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: list[str] = []
    turn_policies: list[str] = []
    event_count = 0
    error_count = 0
    for item in realtime:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "unknown")
        statuses.append(status)
        turn_policy = str(item.get("turn_policy") or "").strip().lower()
        if turn_policy and turn_policy not in turn_policies:
            turn_policies.append(turn_policy)
        event_count += _to_int(item.get("event_count"))
        if status == "error" or (item.get("error") and status not in {"blocked"}):
            error_count += 1
    return {
        "statuses": statuses,
        "turn_policies": turn_policies,
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


def _rv101_voice_contract_metrics(
    *,
    sessions: list[dict[str, Any]],
    events: list[dict[str, Any]],
    realtime: list[dict[str, Any]],
) -> dict[str, Any]:
    is_rv101 = any(
        isinstance(session, dict) and session.get("client_kind") == "rv101_glasses"
        for session in sessions
    )
    accept_payloads = [
        event.get("payload")
        for event in events
        if event.get("module") == "rv101_control"
        and event.get("event_type") == "session_accept"
        and isinstance(event.get("payload"), dict)
    ]
    if accept_payloads:
        is_rv101 = True
    latest = accept_payloads[-1] if accept_payloads else {}
    voice_output = latest.get("voice_output") or latest.get("voiceOutput") or {}
    if not isinstance(voice_output, dict):
        voice_output = {}
    voice_mode = str(latest.get("voice_mode") or latest.get("voiceMode") or "").strip()
    turn_policy = str(latest.get("turn_policy") or latest.get("turnPolicy") or "").strip()
    realtime_turn_policies = []
    for item in realtime:
        if not isinstance(item, dict):
            continue
        value = str(item.get("turn_policy") or "").strip().lower()
        if value and value not in realtime_turn_policies:
            realtime_turn_policies.append(value)

    if not is_rv101:
        status = "not_applicable"
    elif not accept_payloads:
        if realtime_turn_policies and not any(policy != "server_vad" for policy in realtime_turn_policies):
            status = "inferred_server_vad_missing_accept"
        else:
            status = "missing_session_accept"
    elif voice_mode == "conversation_realtime" and turn_policy == "server_vad" and not any(
        policy not in {"server_vad"} for policy in realtime_turn_policies
    ):
        status = "ok"
    elif voice_mode == "push_to_talk_realtime" or turn_policy == "manual":
        status = "ptt_fallback"
    else:
        status = "misaligned"

    return {
        "status": status,
        "is_rv101": is_rv101,
        "session_accept_count": len(accept_payloads),
        "voice_mode": voice_mode or None,
        "turn_policy": turn_policy or None,
        "realtime_turn_policies": realtime_turn_policies,
        "voice_output_enabled": voice_output.get("enabled") if voice_output else None,
        "voice_output_path": voice_output.get("path") if voice_output else None,
    }


def _rv101_voice_contract_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    observed = dict(metrics)
    status = metrics.get("status")
    if status == "not_applicable":
        return _gate(
            status="pass",
            required=False,
            message="RV101 voice contract is not applicable for this replay",
            observed=observed,
        )
    if status == "ok":
        return _gate(
            status="pass",
            required=False,
            message="RV101 session uses conversation_realtime with Cloud Realtime server_vad",
            observed=observed,
        )
    if status == "ptt_fallback":
        return _gate(
            status="warn",
            required=False,
            message="RV101 session used explicit push_to_talk/manual fallback",
            observed=observed,
        )
    if status == "inferred_server_vad_missing_accept":
        return _gate(
            status="warn",
            required=False,
            message="RV101 session_accept was not retained, but Realtime still shows server_vad",
            observed=observed,
        )
    return _gate(
        status="fail",
        required=False,
        message="RV101 voice contract is missing or not aligned with conversation_realtime/server_vad",
        observed=observed,
    )


def _typed_tool_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    observed = dict(metrics)
    if metrics["call_count"] <= 0:
        return _gate(
            status="warn",
            required=False,
            message="no typed realtime tool call recorded",
            observed=observed,
        )
    if metrics["error_count"] > 0:
        return _gate(
            status="fail",
            required=False,
            message=f"{metrics['error_count']} typed realtime tool calls failed",
            observed=observed,
        )
    return _gate(
        status="pass",
        required=False,
        message=f"{metrics['call_count']} typed realtime tool calls completed",
        observed=observed,
    )


def _event_latency_metrics(events: list[dict[str, Any]], *, module: str) -> dict[str, Any]:
    call_count = 0
    error_count = 0
    latencies: list[int] = []
    statuses: list[str] = []
    for event in events:
        if not isinstance(event, dict) or event.get("module") != module:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        event_type = str(event.get("event_type") or "")
        if event_type.endswith("_completed") or event_type in {"call_completed", "command_completed"}:
            call_count += 1
        elif event_type.endswith("_failed") or event_type in {"call_failed", "command_failed"}:
            call_count += 1
            error_count += 1
        else:
            continue
        status = str(payload.get("status") or ("error" if event.get("severity") == "error" else "ok"))
        statuses.append(status)
        duration = _to_int_or_none(payload.get("duration_ms"))
        if duration is not None:
            latencies.append(duration)
    return {
        "call_count": call_count,
        "error_count": error_count,
        "statuses": statuses,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "max_latency_ms": max(latencies) if latencies else None,
    }


def _cloud_gateway_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    bundle_count = 0
    result_count = 0
    success_count = 0
    blocked_count = 0
    fallback_count = 0
    missing_provider_count = 0
    provider_error_count = 0
    invalid_contract_count = 0
    validation_error_count = 0
    error_count = 0
    statuses: list[str] = []
    error_codes: list[str] = []
    latencies: list[int] = []
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        event_type = str(event.get("event_type") or "")
        severity = str(event.get("severity") or "")
        status = str(payload.get("status") or "").strip()
        error_code = str(payload.get("error_code") or "").strip()
        if event_type == "bundle_created":
            bundle_count += 1
        is_result_event = event_type in CLOUD_RESULT_EVENT_TYPES or (event_type != "bundle_created" and bool(status))
        if is_result_event:
            result_count += 1
        if status in CLOUD_SUCCESS_STATUSES:
            success_count += 1
        if status == "blocked" or event_type in CLOUD_BLOCKED_EVENT_TYPES or error_code in {"privacy_blocked", "budget_exceeded"}:
            blocked_count += 1
        if event_type == "provider_missing" or error_code == "cloud_provider_missing":
            missing_provider_count += 1
            fallback_count += 1
        elif event_type == "provider_error":
            provider_error_count += 1
            fallback_count += 1
        elif status == "error" and error_code not in CLOUD_INVALID_CONTRACT_CODES:
            fallback_count += 1
        payload_validation_errors = _validation_error_count(payload)
        if (
            event_type in CLOUD_INVALID_CONTRACT_EVENT_TYPES
            or error_code in CLOUD_INVALID_CONTRACT_CODES
            or payload_validation_errors > 0
        ):
            invalid_contract_count += 1
        validation_error_count += payload_validation_errors
        if severity == "error" or status == "error":
            error_count += 1
        if status and status not in statuses:
            statuses.append(status)
        if error_code and error_code not in error_codes:
            error_codes.append(error_code)
        latency_ms = _to_int_or_none(payload.get("latency_ms"))
        if latency_ms is not None:
            latencies.append(latency_ms)
    return {
        "event_count": len(events),
        "bundle_count": bundle_count,
        "result_count": result_count,
        "success_count": success_count,
        "blocked_count": blocked_count,
        "fallback_count": fallback_count,
        "missing_provider_count": missing_provider_count,
        "provider_error_count": provider_error_count,
        "invalid_contract_count": invalid_contract_count,
        "validation_error_count": validation_error_count,
        "error_count": error_count,
        "statuses": statuses,
        "error_codes": error_codes,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "max_latency_ms": max(latencies) if latencies else None,
    }


def _cloud_gateway_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    observed = dict(metrics)
    if metrics["event_count"] <= 0:
        return _gate(
            status="pass",
            required=False,
            message="no cloud escalation was required",
            observed=observed,
        )
    if metrics["invalid_contract_count"]:
        return _gate(
            status="fail",
            required=False,
            message=f"{metrics['invalid_contract_count']} invalid cloud evidence/result contracts",
            observed=observed,
        )
    if metrics["bundle_count"] and not metrics["result_count"]:
        return _gate(
            status="fail",
            required=False,
            message="cloud evidence bundle was created without a result event",
            observed=observed,
        )
    if metrics["provider_error_count"]:
        return _gate(
            status="warn",
            required=False,
            message="cloud provider failed; safe fallback was returned",
            observed=observed,
        )
    if metrics["fallback_count"] or metrics["blocked_count"]:
        return _gate(
            status="warn",
            required=False,
            message="cloud gateway used a safe fallback/block path",
            observed=observed,
        )
    if metrics["success_count"]:
        return _gate(
            status="pass",
            required=False,
            message="cloud gateway returned structured result",
            observed=observed,
        )
    return _gate(
        status="warn",
        required=False,
        message="cloud gateway events were observed without a successful structured result",
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
    skill_failures: list[dict[str, Any]] | None = None,
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
    failures.extend(skill_failures or [])
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


def _first_positive_int(*values: Any) -> int | None:
    for value in values:
        parsed = _to_int_or_none(value)
        if parsed and parsed > 0:
            return parsed
    return None


def _validation_error_count(payload: dict[str, Any]) -> int:
    count = _to_int_or_none(payload.get("validation_error_count"))
    if count is not None:
        return count
    validation_errors = payload.get("validation_errors")
    return len(validation_errors) if isinstance(validation_errors, list) else 0


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
