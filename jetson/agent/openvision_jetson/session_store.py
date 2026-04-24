"""Session store for RV101 and simulator clients."""

from __future__ import annotations

from threading import RLock
from typing import Any

from .contracts import ClientSession, new_id, to_jsonable, utc_now


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ClientSession] = {}
        self._lock = RLock()

    def create(self, client_kind: str, capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
        session = ClientSession(
            session_id=new_id("sess"),
            client_kind=client_kind,
            capabilities=capabilities or {},
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return to_jsonable(session)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [to_jsonable(session) for session in sessions]

    def touch(self, session_id: str, status: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if status:
                session.status = status
            session.updated_at = utc_now()
            return to_jsonable(session)
