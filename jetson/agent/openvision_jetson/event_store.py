"""In-memory trace store for the early v2 control plane."""

from __future__ import annotations

from collections import deque
from threading import RLock
from typing import Any

from .contracts import TraceEvent, new_id, to_jsonable


class InMemoryEventStore:
    def __init__(self, max_events: int = 1000) -> None:
        self._events: deque[TraceEvent] = deque(maxlen=max_events)
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
        return event

    def list(self, *, session_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)
        if session_id:
            events = [event for event in events if event.session_id == session_id]
        return [to_jsonable(event) for event in events[-limit:]]

