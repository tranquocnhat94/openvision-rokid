"""In-memory trace store for the early v2 control plane."""

from __future__ import annotations

from collections import deque
from threading import RLock
from typing import Any

from .contracts import TraceEvent, new_id, to_jsonable


class InMemoryEventStore:
    def __init__(self, max_events: int = 5000, max_key_events: int = 1000) -> None:
        self._events: deque[TraceEvent] = deque(maxlen=max_events)
        self._key_events: deque[TraceEvent] = deque(maxlen=max(1, max_key_events))
        self._lock = RLock()

    def add(
        self,
        module: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        severity: str = "info",
    ) -> TraceEvent:
        event = TraceEvent(
            event_id=new_id("evt"),
            module=module,
            event_type=event_type,
            payload=payload or {},
            session_id=session_id,
            severity=severity,
        )
        with self._lock:
            self._events.append(event)
            if _is_key_event(module=module, event_type=event_type, payload=event.payload):
                self._key_events.append(event)
        return event

    def list(self, *, session_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rolling_events = list(self._events)
            key_events = list(self._key_events)
        key_ids = {event.event_id for event in key_events}
        rolling_ids = {event.event_id for event in rolling_events}
        events = [event for event in key_events if event.event_id not in rolling_ids] + rolling_events
        if session_id:
            events = [event for event in events if event.session_id == session_id]
        events = _limit_preserving_key_events(events, key_ids=key_ids, limit=limit)
        return [to_jsonable(event) for event in events]


def _limit_preserving_key_events(events: list[TraceEvent], *, key_ids: set[str], limit: int) -> list[TraceEvent]:
    safe_limit = max(1, int(limit or 200))
    if len(events) <= safe_limit:
        return events
    key_events = [event for event in events if event.event_id in key_ids]
    non_key_events = [event for event in events if event.event_id not in key_ids]
    key_events = key_events[-safe_limit:]
    remaining = max(0, safe_limit - len(key_events))
    kept_ids = {
        event.event_id
        for event in [*key_events, *(non_key_events[-remaining:] if remaining else [])]
    }
    return [event for event in events if event.event_id in kept_ids]


def _is_key_event(*, module: str, event_type: str, payload: dict[str, Any]) -> bool:
    module = str(module or "").strip()
    event_type = str(event_type or "").strip()
    if module == "rv101_control" and event_type in {
        "session_accept",
        "session_resumed",
        "app_session_closed",
        "disconnected",
        "realtime_parked",
    }:
        return True
    if module in {"session", "sessions"} and event_type in {"created", "closed", "disconnected", "superseded", "resumed"}:
        return True
    if module == "realtime" and event_type in {
        "connecting",
        "session_update_sent",
        "connected",
        "blocked",
        "error",
        "stopped",
        "session_expired",
        "reconnect_grace_expired",
    }:
        return True
    if module == "realtime_tool" and event_type in {"call_received", "call_completed", "call_failed", "call_dropped"}:
        return True
    if module == "media_command" and event_type in {"command_completed", "command_failed"}:
        return True
    if module == "media" and event_type in {"session_closed", "video_stream_stopped", "audio_stream_closed"}:
        return True
    if module == "rv101_stream_recorder" and event_type in {
        "recording_started",
        "recording_closed",
        "recording_closed_empty",
        "recording_close_requested",
    }:
        return True
    status = str(payload.get("status") or "").strip().lower() if isinstance(payload, dict) else ""
    return status in {"ok", "timeout", "cancelled", "error"} and module in {"media_command", "realtime_tool"}
