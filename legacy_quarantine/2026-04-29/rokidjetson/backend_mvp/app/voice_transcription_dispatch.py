from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TranscriptionAttempt:
    backend: str
    result_source: str
    partial_mode: bool = False


@dataclass(frozen=True, slots=True)
class TranscriptionDispatchPlan:
    attempts: tuple[TranscriptionAttempt, ...]
    terminal_source: str
    skip_reason: str | None = None
    skip_backend: str | None = None


def build_segment_transcription_plan(config: dict[str, Any]) -> TranscriptionDispatchPlan:
    backend = str(config.get("asrBackend") or "openai_realtime_skills").strip()

    if backend == "disabled":
        return TranscriptionDispatchPlan(
            attempts=(),
            terminal_source="disabled",
            skip_reason="backend_disabled",
        )

    if backend == "local_http":
        return TranscriptionDispatchPlan(
            attempts=(TranscriptionAttempt("local_http", "local_http"),),
            terminal_source="local_http",
        )

    if backend == "local_command":
        return TranscriptionDispatchPlan(
            attempts=(TranscriptionAttempt("local_command", "local_command"),),
            terminal_source="local_command",
        )

    if backend == "openai":
        return TranscriptionDispatchPlan(
            attempts=(TranscriptionAttempt("openai", "openai"),),
            terminal_source="openai",
        )

    if backend == "hybrid_local_openai":
        attempts = [
            TranscriptionAttempt("local_http", "local_http"),
            TranscriptionAttempt("local_command", "local_command"),
        ]
        if config.get("allowOpenAITranscriptionFallback", True):
            attempts.append(TranscriptionAttempt("openai", "openai"))
        return TranscriptionDispatchPlan(
            attempts=tuple(attempts),
            terminal_source="hybrid_local_openai",
        )

    return TranscriptionDispatchPlan(
        attempts=(),
        terminal_source=backend,
        skip_reason="unknown_backend",
        skip_backend=backend,
    )


def build_partial_transcription_plan(config: dict[str, Any]) -> TranscriptionDispatchPlan:
    backend = str(config.get("asrBackend") or "openai_realtime_skills").strip()

    if backend == "local_http":
        return TranscriptionDispatchPlan(
            attempts=(TranscriptionAttempt("local_http", "local_http_partial", partial_mode=True),),
            terminal_source="local_http_partial",
        )

    if backend == "local_command":
        return TranscriptionDispatchPlan(
            attempts=(TranscriptionAttempt("local_command", "local_command_partial"),),
            terminal_source="local_command_partial",
        )

    if backend == "hybrid_local_openai":
        return TranscriptionDispatchPlan(
            attempts=(
                TranscriptionAttempt("local_http", "local_http_partial", partial_mode=True),
                TranscriptionAttempt("local_command", "local_command_partial"),
            ),
            terminal_source="hybrid_local_partial",
        )

    return TranscriptionDispatchPlan(
        attempts=(),
        terminal_source=backend,
    )
