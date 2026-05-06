from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class VoiceAudioState:
    last_seen_ms: int = 0
    last_energy_ms: int = 0


@dataclass(slots=True)
class VoiceSegmentState:
    last_processed_offset: int = 0
    transcribe_inflight: bool = False
    inflight_start_offset: int = 0
    inflight_end_offset: int = 0
    last_segment_queued_ms: int = 0
    last_overrun_log_ms: int = 0


@dataclass(slots=True)
class VoiceRouteState:
    last_transcript_ms: int = 0
    last_transcript: str = ""
    last_answer: str = ""
    last_intent: str = "idle"
    last_mode: str | None = None
    last_target_query: str | None = None
    pending_transcript: str = ""
    pending_ms: int = 0

    def clear_pending(self) -> None:
        self.pending_transcript = ""
        self.pending_ms = 0

    def record_action(
        self,
        *,
        now_ms: int,
        transcript: str,
        answer: str,
        intent: str,
        mode: str | None,
        target_query: str | None,
    ) -> None:
        self.clear_pending()
        self.last_transcript_ms = now_ms
        self.last_transcript = transcript
        self.last_answer = answer
        self.last_intent = intent
        self.last_mode = mode
        self.last_target_query = target_query


@dataclass(slots=True)
class VoiceRealtimeState:
    input_offset: int = 0
    commit_offset: int = 0
    generation: int = 0
    last_voice_ms: int = 0
    last_commit_ms: int = 0
    voice_bytes_since_commit: int = 0
    active: bool = False


@dataclass(slots=True)
class VoiceCaptionState:
    input_offset: int = 0
    commit_offset: int = 0
    generation: int = 0
    last_voice_ms: int = 0
    last_commit_ms: int = 0
    committed_text: str = ""
    partial_text: str = ""
    last_text: str = ""
    last_emit_ms: int = 0
    active: bool = False

    def reset_text(self) -> None:
        self.committed_text = ""
        self.partial_text = ""
        self.last_text = ""
        self.last_emit_ms = 0
        self.active = False


@dataclass(slots=True)
class VoicePartialState:
    last_transcript: str = ""
    last_ms: int = 0
    local_inflight: bool = False
    local_last_probe_ms: int = 0
    local_last_text: str = ""
    local_last_emit_ms: int = 0

    def clear(self) -> None:
        self.last_transcript = ""
        self.last_ms = 0
        self.local_last_text = ""
        self.local_last_emit_ms = 0


@dataclass(slots=True)
class VoiceSessionState:
    session_id: str
    audio: VoiceAudioState = field(default_factory=VoiceAudioState)
    segment: VoiceSegmentState = field(default_factory=VoiceSegmentState)
    route: VoiceRouteState = field(default_factory=VoiceRouteState)
    realtime: VoiceRealtimeState = field(default_factory=VoiceRealtimeState)
    caption: VoiceCaptionState = field(default_factory=VoiceCaptionState)
    partial: VoicePartialState = field(default_factory=VoicePartialState)

    def reset_caption_feedback(self) -> None:
        self.partial.clear()
        self.caption.reset_text()

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "last_processed_offset": self.segment.last_processed_offset,
            "last_transcript_ms": self.route.last_transcript_ms,
            "last_audio_seen_ms": self.audio.last_seen_ms,
            "last_transcript": self.route.last_transcript,
            "last_answer": self.route.last_answer,
            "last_intent": self.route.last_intent,
            "last_mode": self.route.last_mode,
            "last_target_query": self.route.last_target_query,
            "transcribe_inflight": self.segment.transcribe_inflight,
            "inflight_start_offset": self.segment.inflight_start_offset,
            "inflight_end_offset": self.segment.inflight_end_offset,
            "last_segment_queued_ms": self.segment.last_segment_queued_ms,
            "last_overrun_log_ms": self.segment.last_overrun_log_ms,
            "realtime_input_offset": self.realtime.input_offset,
            "realtime_commit_offset": self.realtime.commit_offset,
            "realtime_generation": self.realtime.generation,
            "realtime_last_voice_ms": self.realtime.last_voice_ms,
            "realtime_last_commit_ms": self.realtime.last_commit_ms,
            "realtime_voice_bytes_since_commit": self.realtime.voice_bytes_since_commit,
            "realtime_active": self.realtime.active,
            "live_caption_input_offset": self.caption.input_offset,
            "live_caption_commit_offset": self.caption.commit_offset,
            "live_caption_generation": self.caption.generation,
            "live_caption_last_voice_ms": self.caption.last_voice_ms,
            "live_caption_last_commit_ms": self.caption.last_commit_ms,
            "live_caption_committed_text": self.caption.committed_text,
            "live_caption_partial_text": self.caption.partial_text,
            "live_caption_last_text": self.caption.last_text,
            "live_caption_last_emit_ms": self.caption.last_emit_ms,
            "live_caption_active": self.caption.active,
            "last_partial_transcript": self.partial.last_transcript,
            "last_partial_ms": self.partial.last_ms,
            "last_audio_energy_ms": self.audio.last_energy_ms,
            "local_partial_inflight": self.partial.local_inflight,
            "local_partial_last_probe_ms": self.partial.local_last_probe_ms,
            "local_partial_last_text": self.partial.local_last_text,
            "local_partial_last_emit_ms": self.partial.local_last_emit_ms,
            "pending_route_transcript": self.route.pending_transcript,
            "pending_route_ms": self.route.pending_ms,
        }
