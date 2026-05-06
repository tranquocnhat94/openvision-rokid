"""Audio signal helpers for forwarding live PCM into Realtime."""

from __future__ import annotations

from dataclasses import dataclass, field
import struct
from typing import Any


def pcm16_metrics(pcm: bytes) -> dict[str, Any]:
    sample_count = len(pcm) // 2
    if sample_count <= 0:
        return {"sample_count": 0, "avg_abs": 0.0, "peak_abs": 0, "non_silent_ratio": 0.0}
    values = struct.unpack(f"<{sample_count}h", pcm[: sample_count * 2])
    abs_values = [abs(value) for value in values]
    strong = sum(1 for value in abs_values if value >= 120)
    return {
        "sample_count": sample_count,
        "avg_abs": sum(abs_values) / sample_count,
        "peak_abs": max(abs_values),
        "non_silent_ratio": strong / sample_count,
    }


def is_voice_like(metrics: dict[str, Any]) -> bool:
    avg_abs = float(metrics.get("avg_abs") or 0.0)
    peak_abs = float(metrics.get("peak_abs") or 0.0)
    non_silent_ratio = float(metrics.get("non_silent_ratio") or 0.0)
    return (avg_abs >= 120.0 and non_silent_ratio >= 0.02) or (
        avg_abs >= 80.0 and peak_abs >= 320.0 and non_silent_ratio >= 0.01
    )


@dataclass(slots=True)
class AudioGateDecision:
    chunks: list[bytes]
    strong: bool
    state: str
    transition: str | None = None
    buffered_chunks: int = 0


@dataclass(slots=True)
class AudioForwardGate:
    """Suppress idle noise while preserving short prefix and trailing silence."""

    prefix_chunks: int = 12
    start_strong_chunks: int = 2
    hangover_chunks: int = 40
    _prefix: list[bytes] = field(default_factory=list)
    _consecutive_strong: int = 0
    _hangover_remaining: int = 0
    _open: bool = False

    def accept(self, pcm: bytes, metrics: dict[str, Any]) -> AudioGateDecision:
        strong = is_voice_like(metrics)
        transition: str | None = None
        chunks: list[bytes] = []

        if strong:
            self._consecutive_strong += 1
        else:
            self._consecutive_strong = 0

        if not self._open:
            self._remember_prefix(pcm)
            if self._consecutive_strong >= self.start_strong_chunks:
                self._open = True
                self._hangover_remaining = self.hangover_chunks
                transition = "opened"
                chunks = self._prefix
                self._prefix = []
            return AudioGateDecision(
                chunks=chunks,
                strong=strong,
                state="open" if self._open else "idle",
                transition=transition,
                buffered_chunks=len(self._prefix),
            )

        chunks.append(pcm)
        if strong:
            self._hangover_remaining = self.hangover_chunks
        else:
            self._hangover_remaining -= 1
            if self._hangover_remaining <= 0:
                self._open = False
                self._consecutive_strong = 0
                self._prefix = []
                transition = "closed"

        return AudioGateDecision(
            chunks=chunks,
            strong=strong,
            state="open" if self._open else "idle",
            transition=transition,
            buffered_chunks=len(self._prefix),
        )

    def _remember_prefix(self, pcm: bytes) -> None:
        self._prefix.append(pcm)
        if len(self._prefix) > self.prefix_chunks:
            self._prefix = self._prefix[-self.prefix_chunks :]
