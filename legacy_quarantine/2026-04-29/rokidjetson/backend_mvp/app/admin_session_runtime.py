import json
import os
from pathlib import Path
from typing import Any


def tail_session_log_lines(path: Path, limit: int = 120) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    chunk_size = 4096
    with path.open("rb") as source:
        source.seek(0, os.SEEK_END)
        file_size = source.tell()
        buffer = bytearray()
        offset = file_size
        while offset > 0 and buffer.count(b"\n") <= limit:
            read_size = min(chunk_size, offset)
            offset -= read_size
            source.seek(offset)
            buffer[:0] = source.read(read_size)
    raw_lines = buffer.decode("utf-8", errors="ignore").splitlines()[-limit:]
    items: list[dict[str, Any]] = []
    for line in raw_lines:
        try:
            payload = json.loads(line)
        except Exception:
            payload = {"raw": line}
        items.append(payload)
    return items


def serialize_session(
    session: Any,
    *,
    latest_ai_result: Any,
    voice_context: Any,
) -> dict[str, Any]:
    summary = session.summary()
    summary["latestAiResult"] = latest_ai_result
    summary["voiceContext"] = voice_context
    summary["latestSpeechState"] = session.latest_speech_state
    summary["latestHudScene"] = session.latest_hud_scene
    summary["latestSkillTrace"] = session.latest_skill_trace[-20:]
    return summary


def serialize_live_voice_session(session: Any) -> dict[str, Any]:
    return {
        "sessionId": session.session_id,
        "active": session.active,
        "controlConnected": session.control_connected,
        "audioConnected": session.audio_connected,
        "videoConnected": session.video_connected,
        "mode": session.mode,
        "latestSpeechState": session.latest_speech_state,
        "latestHudScene": session.latest_hud_scene,
        "latestVoiceCommand": session.latest_voice_command,
        "latestSkillTrace": session.latest_skill_trace[-12:],
        "selectedTarget": {
            "trackId": session.selected_target_track_id,
            "label": session.selected_target_label,
            "summary": session.selected_target_summary,
            "query": session.selected_target_query,
            "visible": session.selected_target_visible,
            "updatedMs": session.selected_target_updated_ms,
        }
        if (session.selected_target_track_id or session.selected_target_label)
        else None,
    }


def sort_sessions_by_connected_at(sessions: list[Any]) -> list[Any]:
    return sorted(sessions, key=lambda item: item.connected_at, reverse=True)


def latest_session_id(sorted_sessions: list[Any]) -> str | None:
    latest_session = sorted_sessions[0] if sorted_sessions else None
    return latest_session.session_id if latest_session is not None else None
