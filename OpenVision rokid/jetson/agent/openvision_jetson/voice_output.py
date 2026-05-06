"""Realtime voice output fanout for browser/glasses clients."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .contracts import utc_now


VOICE_OUTPUT_QUEUE_MAXSIZE = 96


@dataclass(slots=True)
class VoiceOutputStatus:
    session_id: str
    subscribers: int = 0
    delta_count: int = 0
    done_count: int = 0
    byte_count: int = 0
    last_delta_at: str | None = None
    last_done_at: str | None = None
    updated_at: str = field(default_factory=utc_now)


class VoiceOutputBus:
    """Small in-memory pub/sub for Realtime PCM audio deltas.

    The bus is intentionally not a command path. It only mirrors assistant audio
    output to clients that explicitly subscribed for playback.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._statuses: dict[str, VoiceOutputStatus] = {}

    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=VOICE_OUTPUT_QUEUE_MAXSIZE)
        self._subscribers.setdefault(session_id, set()).add(queue)
        status = self._status(session_id)
        status.subscribers = len(self._subscribers[session_id])
        status.updated_at = utc_now()
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subscribers = self._subscribers.get(session_id)
        if subscribers:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(session_id, None)
        status = self._status(session_id)
        status.subscribers = len(self._subscribers.get(session_id, set()))
        status.updated_at = utc_now()

    def publish_delta(self, *, session_id: str, audio_base64: str, byte_count: int) -> None:
        status = self._status(session_id)
        status.delta_count += 1
        status.byte_count += max(0, byte_count)
        status.last_delta_at = utc_now()
        status.updated_at = status.last_delta_at
        self._publish(
            session_id,
            {
                "type": "audio_delta",
                "audio_base64": audio_base64,
                "format": "pcm_s16le",
                "sample_rate": 24000,
                "channels": 1,
            },
        )

    def publish_done(self, *, session_id: str) -> None:
        status = self._status(session_id)
        status.done_count += 1
        status.last_done_at = utc_now()
        status.updated_at = status.last_done_at
        self._publish(session_id, {"type": "audio_done"})

    def statuses(self) -> list[dict[str, Any]]:
        return [
            {
                "session_id": status.session_id,
                "subscribers": status.subscribers,
                "delta_count": status.delta_count,
                "done_count": status.done_count,
                "byte_count": status.byte_count,
                "last_delta_at": status.last_delta_at,
                "last_done_at": status.last_done_at,
                "updated_at": status.updated_at,
            }
            for status in self._statuses.values()
        ]

    def _publish(self, session_id: str, message: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(session_id, set())):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    pass

    def _status(self, session_id: str) -> VoiceOutputStatus:
        status = self._statuses.get(session_id)
        if not status:
            status = VoiceOutputStatus(session_id=session_id)
            self._statuses[session_id] = status
        return status
