from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionRetentionSnapshot:
    connected_at: float
    last_ping_at: float
    last_message_at: float
    control_connected: bool
    video_connected: bool
    audio_connected: bool

    @property
    def active(self) -> bool:
        return self.control_connected or self.video_connected or self.audio_connected


def session_last_activity_ts(snapshot: SessionRetentionSnapshot) -> float:
    return max(
        float(snapshot.connected_at or 0.0),
        float(snapshot.last_ping_at or 0.0),
        float(snapshot.last_message_at or 0.0),
    )


def session_prune_eligible(
    snapshot: SessionRetentionSnapshot,
    *,
    now_ts: float,
    retention_sec: float,
) -> bool:
    if snapshot.active:
        return False
    if retention_sec <= 0:
        return True
    return (now_ts - session_last_activity_ts(snapshot)) >= retention_sec
