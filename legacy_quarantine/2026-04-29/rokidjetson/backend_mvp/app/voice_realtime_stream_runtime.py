from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class GenerationReplayDecision:
    next_input_offset: int
    next_generation: int
    replay_from: int | None = None
    replay_to: int | None = None


def plan_generation_replay(
    *,
    current_input_offset: int,
    current_generation: int,
    ready_generation: int,
    window_start: int,
    replay_bytes: int,
) -> GenerationReplayDecision:
    if ready_generation <= current_generation:
        return GenerationReplayDecision(
            next_input_offset=current_input_offset,
            next_generation=current_generation,
        )
    replay_from = max(window_start, current_input_offset - max(0, replay_bytes))
    if replay_from < current_input_offset:
        return GenerationReplayDecision(
            next_input_offset=replay_from,
            next_generation=ready_generation,
            replay_from=replay_from,
            replay_to=current_input_offset,
        )
    return GenerationReplayDecision(
        next_input_offset=current_input_offset,
        next_generation=ready_generation,
    )


@dataclass(frozen=True, slots=True)
class BufferWindowDecision:
    has_audio: bool
    start_offset: int
    next_input_offset: int
    log_overrun: bool = False
    next_overrun_log_ms: int = 0
    requested_offset: int = 0
    buffer_start_offset: int = 0
    buffered_bytes: int = 0


def resolve_buffer_window(
    *,
    requested_offset: int,
    window_start: int,
    window_end: int,
    now_ms: int,
    last_overrun_log_ms: int,
    overrun_log_interval_ms: int = 1500,
) -> BufferWindowDecision:
    if window_end <= window_start:
        return BufferWindowDecision(
            has_audio=False,
            start_offset=requested_offset,
            next_input_offset=requested_offset,
            next_overrun_log_ms=last_overrun_log_ms,
            requested_offset=requested_offset,
            buffer_start_offset=window_start,
            buffered_bytes=max(0, window_end - window_start),
        )

    normalized_offset = requested_offset
    log_overrun = False
    next_overrun_log_ms = last_overrun_log_ms
    if window_start > requested_offset:
        normalized_offset = window_start
        if now_ms - last_overrun_log_ms >= overrun_log_interval_ms:
            log_overrun = True
            next_overrun_log_ms = now_ms

    return BufferWindowDecision(
        has_audio=True,
        start_offset=normalized_offset,
        next_input_offset=normalized_offset,
        log_overrun=log_overrun,
        next_overrun_log_ms=next_overrun_log_ms,
        requested_offset=requested_offset,
        buffer_start_offset=window_start,
        buffered_bytes=max(0, window_end - window_start),
    )


@dataclass(frozen=True, slots=True)
class PcmPumpResult:
    next_offset: int
    appended_chunks: int
    saw_voice: bool = False
    voiced_bytes: int = 0


def pump_pcm_chunks(
    *,
    payload_start: int,
    payload: bytes,
    chunk_bytes: int,
    append_pcm: Callable[[bytes], bool],
    chunk_has_voice: Callable[[bytes], bool] | None = None,
) -> PcmPumpResult:
    safe_chunk_bytes = max(1, chunk_bytes)
    next_offset = payload_start
    appended_chunks = 0
    saw_voice = False
    voiced_bytes = 0
    for offset in range(0, len(payload), safe_chunk_bytes):
        chunk = payload[offset : offset + safe_chunk_bytes]
        if not chunk:
            continue
        if not append_pcm(chunk):
            break
        appended_chunks += 1
        next_offset = payload_start + offset + len(chunk)
        if chunk_has_voice is not None and chunk_has_voice(chunk):
            saw_voice = True
            voiced_bytes += len(chunk)
    return PcmPumpResult(
        next_offset=next_offset,
        appended_chunks=appended_chunks,
        saw_voice=saw_voice,
        voiced_bytes=voiced_bytes,
    )


@dataclass(frozen=True, slots=True)
class LiveCaptionCommitDecision:
    should_commit: bool = False
    reason: str = ""
    next_state_label: str = ""
    deactivate_after_commit: bool = False
    bytes_since_commit: int = 0
    voice_gap_ms: int = 0


def decide_live_caption_commit(
    *,
    active: bool,
    now_ms: int,
    last_voice_ms: int,
    input_offset: int,
    commit_offset: int,
    rolling_commit_bytes: int,
    min_commit_bytes: int,
    silence_commit_ms: int,
) -> LiveCaptionCommitDecision:
    voice_gap_ms = max(0, now_ms - last_voice_ms) if last_voice_ms else 10_000
    bytes_since_commit = max(0, input_offset - commit_offset)
    if not active:
        return LiveCaptionCommitDecision(
            bytes_since_commit=bytes_since_commit,
            voice_gap_ms=voice_gap_ms,
        )
    if bytes_since_commit >= rolling_commit_bytes and voice_gap_ms <= silence_commit_ms:
        return LiveCaptionCommitDecision(
            should_commit=True,
            reason="rolling",
            next_state_label="captioning",
            bytes_since_commit=bytes_since_commit,
            voice_gap_ms=voice_gap_ms,
        )
    if bytes_since_commit >= min_commit_bytes and voice_gap_ms > silence_commit_ms:
        return LiveCaptionCommitDecision(
            should_commit=True,
            reason="tail",
            next_state_label="transcribing",
            deactivate_after_commit=True,
            bytes_since_commit=bytes_since_commit,
            voice_gap_ms=voice_gap_ms,
        )
    return LiveCaptionCommitDecision(
        bytes_since_commit=bytes_since_commit,
        voice_gap_ms=voice_gap_ms,
    )
