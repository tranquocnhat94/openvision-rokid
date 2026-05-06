"""Session store for RV101 and simulator clients."""

from __future__ import annotations

from threading import RLock
from typing import Any

from .contracts import ClientSession, new_id, to_jsonable, utc_now


INACTIVE_SESSION_STATUSES = {
    "closed",
    "disconnected",
    "expired",
    "replaced",
    "stopped",
    "superseded",
}


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

    def supersede_active_device_sessions(
        self,
        *,
        client_kind: str,
        device_id: str,
        replacement_status: str = "superseded",
    ) -> list[dict[str, Any]]:
        """Mark older active sessions for the same physical device as superseded."""

        clean_device_id = str(device_id or "").strip()
        if not clean_device_id:
            return []
        superseded: list[dict[str, Any]] = []
        with self._lock:
            for session in self._sessions.values():
                if session.client_kind != client_kind:
                    continue
                if str(session.status or "").lower() in INACTIVE_SESSION_STATUSES:
                    continue
                capabilities = session.capabilities if isinstance(session.capabilities, dict) else {}
                if str(capabilities.get("device_id") or "").strip() != clean_device_id:
                    continue
                session.status = replacement_status
                session.updated_at = utc_now()
                superseded.append(to_jsonable(session))
        return superseded

    def replace_active_device_sessions(
        self,
        *,
        client_kind: str,
        device_id: str,
        replacement_status: str = "superseded",
    ) -> list[dict[str, Any]]:
        """Backward-compatible alias for superseding active device sessions."""

        return self.supersede_active_device_sessions(
            client_kind=client_kind,
            device_id=device_id,
            replacement_status=replacement_status,
        )

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [to_jsonable(session) for session in sessions]

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            return to_jsonable(session) if session else None

    def touch(self, session_id: str, status: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if status:
                session.status = status
            session.updated_at = utc_now()
            return to_jsonable(session)

    def mark_inactive(self, session_id: str, *, status: str) -> dict[str, Any] | None:
        """Move an active session to an inactive status without clobbering terminal state."""

        normalized_status = str(status or "").strip().lower()
        if not normalized_status:
            return self.get(session_id)
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if str(session.status or "").lower() not in INACTIVE_SESSION_STATUSES:
                session.status = normalized_status
                session.updated_at = utc_now()
            return to_jsonable(session)
