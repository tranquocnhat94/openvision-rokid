from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import unicodedata
from array import array
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .openai_realtime_skills import OpenAIRealtimeSkillClient
from .skills_runtime import JetsonSkillRegistry
from .voice_batch_transport_runtime import (
    pcm_to_wav_bytes,
    run_local_command_transcription,
    request_local_http_transcription,
    request_openai_audio_transcription,
    request_openai_route,
)
from .voice_backend_lifecycle import BackendLifecycleSnapshot, evaluate_backend_lifecycle
from .voice_caption_state_runtime import (
    next_live_final_text,
    next_live_partial_text,
    next_local_partial_text,
    next_route_partial_text,
)
from .voice_caption_text_runtime import (
    build_live_caption_prompt_markers,
    merge_incremental_transcript,
    merge_local_partial_text,
    sanitize_live_caption_transcript,
    should_emit_local_partial_text,
    strip_live_caption_prompt_echo,
    trim_live_caption_hint,
)
from .voice_local_backend_runtime import LocalBackendSupervisor
from .voice_realtime_stream_runtime import (
    PcmPumpResult,
    decide_live_caption_commit,
    plan_generation_replay,
    pump_pcm_chunks,
    resolve_buffer_window,
)
from .voice_realtime_transcription_client import OpenAIRealtimeTranscriptionClient
from .voice_route_runtime import resolve_final_route
from .voice_runtime_config import (
    active_backend_kind,
    is_any_backend_configured,
    load_voice_runtime_config,
    local_backend_configured,
    merge_voice_runtime_config,
    uses_any_realtime_backend,
    uses_local_backend,
    uses_realtime_backend,
    uses_realtime_skill_backend,
)
from .voice_session_state import VoiceSessionState
from .voice_transcript_policy import evaluate_transcript_candidate
from .voice_transcription_dispatch import (
    TranscriptionAttempt,
    build_partial_transcription_plan,
    build_segment_transcription_plan,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _norm_text(value: str) -> str:
    lowered = _strip_accents(value).lower()
    lowered = lowered.replace("đ", "d")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]

VIETNAMESE_COMMAND_HINTS = (
    "scene",
    "monitor",
    "traffic",
    "radar",
    "focus",
    "alert",
    "ao",
    "nguoi",
    "mat",
    "tim",
    "theo doi",
    "xe",
    "dung",
    "tat",
)

COMMON_ENGLISH_TOKENS = {
    "a",
    "all",
    "already",
    "and",
    "are",
    "good",
    "hello",
    "hey",
    "hi",
    "how",
    "i",
    "is",
    "it",
    "people",
    "the",
    "there",
    "they",
    "this",
    "view",
    "we",
    "you",
}


@dataclass
class VoiceCommand:
    timestamp_ms: int
    session_id: str
    transcript: str
    source: str
    intent: str
    mode: str | None
    target_query: str | None
    answer: str
    status_text: str
    scene_summary: str
    confidence: float


@dataclass
class AudioEnergyStats:
    avg_abs: int
    peak_abs: int
    non_silent_ratio: float


class VoiceOrchestrator:
    def __init__(
        self,
        root_dir: Path,
        session_provider: Callable[[], dict[str, Any]],
        scene_context_provider: Callable[[str], dict[str, Any]],
        vision_context_provider: Callable[[str, str | None, str | None], dict[str, Any]],
        command_handler: Callable[[dict[str, Any]], None],
        log_handler: Callable[[str, str, dict[str, Any]], None],
        speech_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.root_dir = root_dir
        self.config_dir = root_dir / "config"
        self.runtime_dir = root_dir / "runtime" / "voice"
        self.segment_dir = self.runtime_dir / "segments"
        self.config_path = self.config_dir / "voice_settings.json"
        self.session_provider = session_provider
        self.scene_context_provider = scene_context_provider
        self.vision_context_provider = vision_context_provider
        self.command_handler = command_handler
        self.log_handler = log_handler
        self.speech_handler = speech_handler
        self.state_lock = threading.Lock()
        self.config_lock = threading.Lock()
        self.session_states: dict[str, VoiceSessionState] = {}
        self.realtime_clients: dict[str, OpenAIRealtimeTranscriptionClient] = {}
        self.realtime_live_clients: dict[str, OpenAIRealtimeTranscriptionClient] = {}
        self.realtime_skill_clients: dict[str, OpenAIRealtimeSkillClient] = {}
        self.recent_commands: list[VoiceCommand] = []
        self.skill_registry = JetsonSkillRegistry(
            config_provider=self._raw_config_snapshot,
            scene_context_provider=self.scene_context_provider,
            vision_context_provider=self.vision_context_provider,
            command_handler=self.command_handler,
            log_handler=self.log_handler,
        )
        self._shutdown = threading.Event()
        self._config = load_voice_runtime_config(self.config_path)
        self._persist_config(self._config)
        self.backend_state = "sleeping"
        self.backend_active = active_backend_kind(self._config)
        self.backend_last_error = ""
        self.backend_last_state_change_ms = _now_ms()
        self.backend_last_activity_ms = 0
        self.local_backend = LocalBackendSupervisor(
            config_provider=self._raw_config_snapshot,
            log_handler=self.log_handler,
            set_backend_state=self._set_backend_state,
            set_backend_error=self._set_backend_error,
            clear_backend_error=self._clear_backend_error,
            now_ms=_now_ms,
        )
        self.segment_executor = ThreadPoolExecutor(
            max_workers=max(2, min(4, os.cpu_count() or 2)),
            thread_name_prefix="rokid-voice-segment",
        )
        self.partial_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="rokid-voice-partial",
        )
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="rokid-voice-orchestrator",
        )
        self._thread.start()

    def close(self) -> None:
        self._shutdown.set()
        self._thread.join(timeout=2.0)
        self.local_backend.stop("shutdown", keep_sleep_state=uses_local_backend(self._config))
        self._close_realtime_clients("shutdown")
        with suppress(Exception):
            self.segment_executor.shutdown(wait=False, cancel_futures=True)
        with suppress(Exception):
            self.partial_executor.shutdown(wait=False, cancel_futures=True)

    def drop_session(self, session_id: str, *, reason: str = "session_removed") -> None:
        normalized = str(session_id or "").strip()
        if not normalized:
            return
        self._close_realtime_client_bucket(self.realtime_clients, normalized, reason)
        self._close_realtime_client_bucket(self.realtime_live_clients, normalized, reason)
        self._close_realtime_client_bucket(self.realtime_skill_clients, normalized, reason)
        with self.state_lock:
            self.session_states.pop(normalized, None)

    def health(self) -> dict[str, Any]:
        config = self.get_config(mask_secrets=True)
        with self.state_lock:
            tracked = len(self.session_states)
            recent = [asdict(item) for item in self.recent_commands[-20:]][::-1]
        return {
            "enabled": True,
            "configured": is_any_backend_configured(self._config, has_api_key=bool(self._api_key())),
            "trackedSessions": tracked,
            "realtimeSessions": len(self.realtime_clients) + len(self.realtime_live_clients),
            "realtimeRouteSessions": len(self.realtime_clients),
            "realtimeLiveSessions": len(self.realtime_live_clients),
            "realtimeSkillSessions": len(self.realtime_skill_clients),
            "recentCommands": recent,
            "config": config,
            "backend": {
                "kind": self.backend_active,
                "state": self.backend_state,
                "localConfigured": local_backend_configured(self._config),
                "openAIConfigured": bool(self._api_key()),
                "pid": self.local_backend.pid,
                "lastError": self.backend_last_error,
                "lastStateChangeMs": self.backend_last_state_change_ms,
                "lastActivityMs": self.backend_last_activity_ms,
            },
        }

    def get_config(self, *, mask_secrets: bool) -> dict[str, Any]:
        with self.config_lock:
            payload = dict(self._config)
        if mask_secrets:
            payload["openaiApiKey"] = _mask_secret(str(payload.get("openaiApiKey") or ""))
        return payload

    def _raw_config_snapshot(self) -> dict[str, Any]:
        with self.config_lock:
            return dict(self._config)

    def update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.config_lock:
            next_config = merge_voice_runtime_config(self._config, payload)
            self._config = next_config
            self._persist_config(next_config)
        self.backend_active = active_backend_kind(self._config)
        self.local_backend.stop("reconfigure", keep_sleep_state=uses_local_backend(self._config))
        self._close_realtime_clients("reconfigure")
        return self.get_config(mask_secrets=True)

    def session_snapshot(self, session_id: str) -> dict[str, Any] | None:
        with self.state_lock:
            state = self.session_states.get(session_id)
            if state is None:
                return None
            return state.snapshot()

    def simulate_command(self, session_id: str, transcript: str) -> dict[str, Any]:
        transcript = transcript.strip()
        if not transcript:
            raise ValueError("Transcript is empty")
        action = self._build_action(
            session_id=session_id,
            transcript=transcript,
            source="manual",
            scene_context=self.scene_context_provider(session_id),
        )
        self._dispatch_action(action)
        return action

    def _persist_config(self, payload: dict[str, Any]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.segment_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _set_backend_error(self, message: str) -> None:
        self.backend_last_error = str(message or "")

    def _clear_backend_error(self) -> None:
        self.backend_last_error = ""

    def _run_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                sessions = list(self.session_provider().values())
                self._prune_session_state_cache(sessions)
                self._prune_realtime_clients(sessions)
                self._maintain_backend_state(sessions)
                for session in sessions:
                    if uses_realtime_skill_backend(self._config):
                        if self._browser_realtime_skill_uses_transcript_route(session):
                            self._maybe_stream_realtime_session(session, browser_skill_route=True)
                        else:
                            self._maybe_stream_realtime_skill_session(session)
                    elif uses_realtime_backend(self._config):
                        self._maybe_stream_realtime_session(session)
                        self._maybe_stream_live_caption_session(session)
                    else:
                        self._maybe_probe_local_partial(session)
                        self._maybe_process_session(session)
            except Exception as error:
                self.backend_last_error = str(error)
            loop_interval_ms = max(40, int(self._config.get("loopIntervalMs") or 180))
            self._shutdown.wait(loop_interval_ms / 1000.0)

    def _maintain_backend_state(self, sessions: list[Any]) -> None:
        now_ms = _now_ms()
        active_sessions = [session for session in sessions if bool(getattr(session, "active", False))]
        uses_realtime = uses_any_realtime_backend(self._config)
        uses_local = uses_local_backend(self._config)
        has_active_sessions = bool(active_sessions)
        local_process_alive = self.local_backend.process_alive() if uses_local and not uses_realtime else False
        local_backend_running = (
            self.local_backend.running()
            if uses_local and not uses_realtime and has_active_sessions
            else False
        )
        decision = evaluate_backend_lifecycle(
            BackendLifecycleSnapshot(
                uses_any_realtime_backend=uses_realtime,
                uses_local_backend=uses_local,
                has_active_sessions=has_active_sessions,
                has_api_key=bool(self._api_key()),
                backend_state=self.backend_state,
                auto_wake_on_session=bool(self._config.get("autoWakeOnSession", True)),
                last_activity_ms=self.backend_last_activity_ms,
                now_ms=now_ms,
                idle_unload_ms=int(self._config.get("backendIdleUnloadMs") or 60000),
                local_backend_running=local_backend_running,
                local_process_alive=local_process_alive,
            )
        )
        if decision.touch_activity:
            self.backend_last_activity_ms = now_ms
        if decision.next_state is not None:
            self._set_backend_state(decision.next_state)
        if decision.stop_local_backend and decision.stop_reason:
            self.local_backend.stop(
                decision.stop_reason,
                keep_sleep_state=uses_local,
            )
            return
        if decision.warm_local_backend:
                    self.local_backend.warm()

    def _prune_session_state_cache(self, sessions: list[Any]) -> None:
        active_ids = {
            str(getattr(session, "session_id", "") or "")
            for session in sessions
            if str(getattr(session, "session_id", "") or "")
        }
        with self.state_lock:
            stale_ids = [
                session_id
                for session_id in list(self.session_states.keys())
                if session_id not in active_ids
            ]
        for session_id in stale_ids:
            self.drop_session(session_id, reason="session_missing")

    def _prune_realtime_clients(self, sessions: list[Any]) -> None:
        if not uses_any_realtime_backend(self._config):
            self._close_realtime_clients("backend_disabled")
            return
        active_ids = {
            str(getattr(session, "session_id", "") or "")
            for session in sessions
            if bool(getattr(session, "active", False))
        }
        for session_id, client in list(self.realtime_clients.items()):
            if session_id in active_ids:
                continue
            client.close("session_inactive")
            self.realtime_clients.pop(session_id, None)
        for session_id, client in list(self.realtime_live_clients.items()):
            if session_id in active_ids:
                continue
            client.close("session_inactive")
            self.realtime_live_clients.pop(session_id, None)
        for session_id, client in list(self.realtime_skill_clients.items()):
            if session_id in active_ids:
                continue
            client.close("session_inactive")
            self.realtime_skill_clients.pop(session_id, None)

    def _close_realtime_client_bucket(
        self,
        clients: dict[str, OpenAIRealtimeTranscriptionClient | OpenAIRealtimeSkillClient],
        session_id: str,
        reason: str,
    ) -> None:
        client = clients.pop(session_id, None)
        if client is None:
            return
        client.close(reason)

    def _audio_energy_stats(self, session: Any) -> AudioEnergyStats:
        stats = getattr(session, "latest_audio_stats", {}) or {}
        try:
            avg_abs = int(stats.get("avgAbs") or 0)
        except Exception:
            avg_abs = 0
        try:
            peak_abs = int(stats.get("peakAbs") or 0)
        except Exception:
            peak_abs = 0
        try:
            non_silent_ratio = float(stats.get("nonSilentRatio") or 0.0)
        except Exception:
            non_silent_ratio = 0.0
        return AudioEnergyStats(
            avg_abs=avg_abs,
            peak_abs=peak_abs,
            non_silent_ratio=non_silent_ratio,
        )

    def _is_browser_harness_session(self, session: Any) -> bool:
        app_version = str(getattr(session, "app_version", "") or "").strip().lower()
        device_id = str(getattr(session, "device_id", "") or "").strip().lower()
        return (
            app_version.startswith("browser-harness/")
            or app_version.startswith("browser-simulator/")
            or device_id.startswith("browser-")
        )

    def _browser_realtime_skill_uses_transcript_route(self, session: Any) -> bool:
        return bool(self._config.get("browserRealtimeSkillUseTranscriptRoute", True)) and self._is_browser_harness_session(session)

    def _realtime_route_turn_detection_mode(self, session: Any, *, browser_skill_route: bool = False) -> str:
        if browser_skill_route and self._is_browser_harness_session(session):
            mode = str(self._config.get("browserRealtimeRouteTurnDetection") or "manual").strip().lower()
            return "server_vad" if mode == "server_vad" else "manual"
        return "server_vad"

    def _has_realtime_route_voice_energy(self, session: Any, stats: AudioEnergyStats) -> bool:
        if self._is_browser_harness_session(session):
            try:
                min_ratio = float(self._config.get("browserRealtimeSkillMinNonSilentRatio") or 0.05)
            except Exception:
                min_ratio = 0.05
            floor = max(16, int(self._config.get("silenceFloor") or 72))
            return stats.avg_abs >= floor and stats.non_silent_ratio >= max(0.0, min_ratio)
        return self._has_voice_energy(stats)

    def _audio_stats_support_realtime(self, session: Any, *, skill_keepalive: bool = False) -> bool:
        stats = self._audio_energy_stats(session)
        if skill_keepalive and self._is_browser_harness_session(session):
            try:
                min_ratio = float(self._config.get("browserRealtimeSkillMinNonSilentRatio") or 0.05)
            except Exception:
                min_ratio = 0.05
            return stats.non_silent_ratio >= max(0.0, min_ratio)
        return stats.avg_abs >= 18 or stats.peak_abs >= 160 or stats.non_silent_ratio >= 0.015

    def _realtime_idle_close_ms(self, session: Any, *, skill_keepalive: bool = False) -> int:
        if skill_keepalive and self._is_browser_harness_session(session):
            try:
                return max(1000, int(self._config.get("browserRealtimeSkillIdleCloseMs") or 15000))
            except Exception:
                return 15000
        try:
            return max(1000, int(self._config.get("realtimeSpeechIdleCloseMs") or 6000))
        except Exception:
            return 6000

    def _realtime_replay_ms(self, session: Any, *, skill_keepalive: bool = False) -> int:
        if skill_keepalive and self._is_browser_harness_session(session):
            try:
                return max(1200, int(self._config.get("browserRealtimeSkillReplayMs") or 4000))
            except Exception:
                return 4000
        try:
            return max(0, int(self._config.get("realtimeReplayMs") or 1200))
        except Exception:
            return 1200

    def _realtime_recent_speech_active(
        self,
        state: VoiceSessionState,
        now_ms: int,
        *,
        idle_close_ms: int,
    ) -> bool:
        recent_activity_ms = max(state.partial.last_ms, state.route.last_transcript_ms)
        if recent_activity_ms <= 0:
            return False
        return now_ms - recent_activity_ms <= idle_close_ms

    def _realtime_recent_audio_active(
        self,
        state: VoiceSessionState,
        now_ms: int,
        *,
        idle_close_ms: int,
    ) -> bool:
        if state.audio.last_energy_ms <= 0:
            return False
        return now_ms - state.audio.last_energy_ms <= idle_close_ms

    def _close_realtime_client_for_session(
        self,
        *,
        session_id: str,
        clients: dict[str, OpenAIRealtimeTranscriptionClient | OpenAIRealtimeSkillClient],
        generation_attr: str,
        reason: str,
        log_event: str | None = None,
        log_payload: dict[str, Any] | None = None,
    ) -> None:
        client = clients.pop(session_id, None)
        if client is None:
            return
        client.close(reason)
        with self.state_lock:
            state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))
            if generation_attr == "realtime_generation":
                state.realtime.generation = 0
            elif generation_attr == "live_caption_generation":
                state.caption.generation = 0
        if log_event is not None:
            self.log_handler(session_id, log_event, log_payload or {"reason": reason})

    def _close_realtime_clients(self, reason: str) -> None:
        for session_id, client in list(self.realtime_clients.items()):
            client.close(reason)
            self.realtime_clients.pop(session_id, None)
        for session_id, client in list(self.realtime_live_clients.items()):
            client.close(reason)
            self.realtime_live_clients.pop(session_id, None)
        for session_id, client in list(self.realtime_skill_clients.items()):
            client.close(reason)
            self.realtime_skill_clients.pop(session_id, None)

    def _live_captions_enabled(self) -> bool:
        return bool(self._config.get("liveCaptionsEnabled", True))

    def _local_partials_enabled(self) -> bool:
        if not bool(self._config.get("localPartialEnabled", True)):
            return False
        if not bool(self._config.get("routeSpeechHudEnabled", False)):
            return False
        if self.speech_handler is None:
            return False
        backend = str(self._config.get("asrBackend") or "").strip()
        return backend in {"local_http", "hybrid_local_openai"}

    def _prepare_realtime_stream_session(
        self,
        session: Any,
        *,
        touch_backend_activity: bool,
        skill_keepalive: bool = False,
    ) -> tuple[str, VoiceSessionState, int, dict[str, Any], bool] | None:
        session_id = str(getattr(session, "session_id", "") or "")
        if not session_id or not bool(getattr(session, "active", False)):
            return None
        if not self._api_key():
            return None

        with self.state_lock:
            state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))

        now_ms = _now_ms()
        state.audio.last_seen_ms = int(getattr(session, "last_audio_timestamp_ms", now_ms) or now_ms)
        if touch_backend_activity:
            self.backend_last_activity_ms = now_ms
        stats = getattr(session, "latest_audio_stats", {}) or {}
        audio_supports_realtime = self._audio_stats_support_realtime(
            session,
            skill_keepalive=skill_keepalive,
        )
        if audio_supports_realtime:
            state.audio.last_energy_ms = now_ms
        idle_close_ms = self._realtime_idle_close_ms(session, skill_keepalive=skill_keepalive)
        should_keep_realtime = (
            audio_supports_realtime
            or self._realtime_recent_audio_active(state, now_ms, idle_close_ms=idle_close_ms)
            or self._realtime_recent_speech_active(state, now_ms, idle_close_ms=idle_close_ms)
        )
        return session_id, state, now_ms, stats, should_keep_realtime

    def _stream_realtime_client_audio(
        self,
        *,
        session: Any,
        session_id: str,
        state: VoiceSessionState,
        client: OpenAIRealtimeTranscriptionClient | OpenAIRealtimeSkillClient,
        replay_ms: int,
        chunk_ms: int,
        replay_event: str,
        buffer_overrun_event: str,
        chunk_has_voice: Callable[[bytes], bool] | None = None,
        reset_realtime_commit_on_generation: bool = False,
    ) -> PcmPumpResult | None:
        if not client.is_ready():
            return None

        window_start, _ = self._session_audio_bounds(session, 0)
        previous_generation = state.realtime.generation
        replay_decision = plan_generation_replay(
            current_input_offset=state.realtime.input_offset,
            current_generation=state.realtime.generation,
            ready_generation=client.ready_generation(),
            window_start=window_start,
            replay_bytes=self._bytes_for_ms(replay_ms),
        )
        if replay_decision.replay_from is not None and replay_decision.replay_to is not None:
            self.log_handler(
                session_id,
                replay_event,
                {
                    "fromOffset": replay_decision.replay_from,
                    "toOffset": replay_decision.replay_to,
                    "generation": replay_decision.next_generation,
                },
            )
        state.realtime.input_offset = replay_decision.next_input_offset
        state.realtime.generation = replay_decision.next_generation
        if (
            reset_realtime_commit_on_generation
            and replay_decision.next_generation > previous_generation
        ):
            state.realtime.commit_offset = state.realtime.input_offset
            state.realtime.active = False
            state.realtime.last_voice_ms = 0
            state.realtime.voice_bytes_since_commit = 0

        chunk_bytes = self._bytes_for_ms(chunk_ms)
        requested_offset = state.realtime.input_offset
        window_start, window_end = self._session_audio_bounds(session, requested_offset)
        window_decision = resolve_buffer_window(
            requested_offset=requested_offset,
            window_start=window_start,
            window_end=window_end,
            now_ms=_now_ms(),
            last_overrun_log_ms=state.segment.last_overrun_log_ms,
        )
        if not window_decision.has_audio:
            return None
        if window_decision.log_overrun:
            state.segment.last_overrun_log_ms = window_decision.next_overrun_log_ms
            self.log_handler(
                session_id,
                buffer_overrun_event,
                {
                    "requestedOffset": window_decision.requested_offset,
                    "bufferStartOffset": window_decision.buffer_start_offset,
                    "bufferedBytes": window_decision.buffered_bytes,
                },
            )
        state.realtime.input_offset = window_decision.next_input_offset
        if reset_realtime_commit_on_generation and window_decision.next_input_offset > requested_offset:
            state.realtime.commit_offset = max(
                state.realtime.commit_offset,
                window_decision.next_input_offset,
            )
            state.realtime.voice_bytes_since_commit = 0

        catch_up_bytes = max(chunk_bytes, chunk_bytes * 8)
        payload_start, _, payload = self._session_audio_window(
            session,
            window_decision.start_offset,
            catch_up_bytes,
        )
        if not payload:
            return None

        pump_result = pump_pcm_chunks(
            payload_start=payload_start,
            payload=payload,
            chunk_bytes=chunk_bytes,
            append_pcm=client.append_pcm,
            chunk_has_voice=chunk_has_voice,
        )
        if pump_result.next_offset > state.realtime.input_offset:
            state.realtime.input_offset = pump_result.next_offset
        return pump_result

    def _ensure_transcription_client(
        self,
        *,
        session_id: str,
        clients: dict[str, OpenAIRealtimeTranscriptionClient],
        partial_handler: Callable[[str, str, dict[str, Any]], None],
        final_handler: Callable[[str, str, dict[str, Any]], None],
        status_handler: Callable[[str, dict[str, Any]], None],
        source_label: str,
        task_label: str,
        turn_detection_mode: str,
        model_config_key: str,
        prompt_config_key: str,
    ) -> OpenAIRealtimeTranscriptionClient:
        client = clients.get(session_id)
        if client is None:
            client = OpenAIRealtimeTranscriptionClient(
                session_id=session_id,
                config_provider=lambda: self.get_config(mask_secrets=False),
                log_handler=self.log_handler,
                partial_handler=partial_handler,
                final_handler=final_handler,
                status_handler=status_handler,
                source_label=source_label,
                task_label=task_label,
                turn_detection_mode=turn_detection_mode,
                model_config_key=model_config_key,
                prompt_config_key=prompt_config_key,
            )
            clients[session_id] = client
        return client

    def _maybe_commit_manual_realtime_route(
        self,
        *,
        session: Any,
        session_id: str,
        state: VoiceSessionState,
        client: OpenAIRealtimeTranscriptionClient,
        pump_result: PcmPumpResult | None,
        now_ms: int,
    ) -> None:
        if pump_result is None:
            return
        if pump_result.saw_voice:
            state.realtime.last_voice_ms = now_ms
            state.realtime.voice_bytes_since_commit += max(0, int(pump_result.voiced_bytes))
            if not state.realtime.active:
                state.realtime.active = True
                self._handle_realtime_route_status_update(
                    session_id,
                    {
                        "stateLabel": "capturing",
                        "taskLabel": "voice final",
                        "transcriptHint": None,
                        "source": "openai_realtime_route",
                    },
                )

        if not state.realtime.active:
            return

        silence_commit_ms = max(
            120,
            int(self._config.get("browserRealtimeRouteSilenceCommitMs") or 420)
            if self._is_browser_harness_session(session)
            else int(self._config.get("idleFlushMs") or 220),
        )
        min_voiced_bytes = self._bytes_for_ms(
            int(self._config.get("browserRealtimeRouteMinVoicedMs") or 320)
            if self._is_browser_harness_session(session)
            else max(160, int(self._config.get("minVoicedSegmentMs") or 640) // 2)
        )
        voice_gap_ms = max(0, now_ms - state.realtime.last_voice_ms) if state.realtime.last_voice_ms else 10_000
        if (
            voice_gap_ms > silence_commit_ms
            and state.realtime.voice_bytes_since_commit < min_voiced_bytes
        ):
            if client.clear_audio():
                self.log_handler(
                    session_id,
                    "voice_realtime_route_segment_dropped",
                    {
                        "reason": "short_voice",
                        "voiceBytes": state.realtime.voice_bytes_since_commit,
                        "minVoiceBytes": min_voiced_bytes,
                        "voiceGapMs": voice_gap_ms,
                        "source": "openai_realtime_route",
                    },
                )
            state.realtime.commit_offset = state.realtime.input_offset
            state.realtime.active = False
            state.realtime.voice_bytes_since_commit = 0
            return

        commit_decision = decide_live_caption_commit(
            active=state.realtime.active,
            now_ms=now_ms,
            last_voice_ms=state.realtime.last_voice_ms,
            input_offset=state.realtime.input_offset,
            commit_offset=state.realtime.commit_offset,
            rolling_commit_bytes=self._bytes_for_ms(
                int(self._config.get("browserRealtimeRouteCommitMs") or 2200)
                if self._is_browser_harness_session(session)
                else int(self._config.get("maxSegmentMs") or 1800)
            ),
            min_commit_bytes=self._bytes_for_ms(
                int(self._config.get("browserRealtimeRouteMinCommitMs") or 640)
                if self._is_browser_harness_session(session)
                else int(self._config.get("minVoicedSegmentMs") or 640)
            ),
            silence_commit_ms=silence_commit_ms,
        )
        if not commit_decision.should_commit:
            return
        if not client.commit_audio():
            return

        state.realtime.commit_offset = state.realtime.input_offset
        state.realtime.last_commit_ms = now_ms
        state.realtime.voice_bytes_since_commit = 0
        if commit_decision.deactivate_after_commit:
            state.realtime.active = False
        self.log_handler(
            session_id,
            "voice_realtime_route_commit",
            {
                "reason": commit_decision.reason,
                "bytesSinceCommit": commit_decision.bytes_since_commit,
                "voiceGapMs": commit_decision.voice_gap_ms,
                "source": "openai_realtime_route",
            },
        )
        self._handle_realtime_route_status_update(
            session_id,
            {
                "stateLabel": commit_decision.next_state_label,
                "taskLabel": "voice final",
                "transcriptHint": None,
                "source": "openai_realtime_route",
            },
        )

    def _maybe_stream_realtime_session(self, session: Any, *, browser_skill_route: bool = False) -> None:
        prepared = self._prepare_realtime_stream_session(
            session,
            touch_backend_activity=True,
            skill_keepalive=browser_skill_route,
        )
        if prepared is None:
            return
        session_id, state, now_ms, stats, should_keep_realtime = prepared
        if not should_keep_realtime:
            self._close_realtime_client_for_session(
                session_id=session_id,
                clients=self.realtime_clients,
                generation_attr="realtime_generation",
                reason="idle_silence",
                log_event="voice_realtime_idle_close",
                log_payload={
                    "source": "openai_realtime_route",
                    "avgAbs": int(stats.get("avgAbs") or 0),
                    "peakAbs": int(stats.get("peakAbs") or 0),
                    "nonSilentRatio": float(stats.get("nonSilentRatio") or 0.0),
                    "idleCloseMs": self._realtime_idle_close_ms(session, skill_keepalive=browser_skill_route),
                    "browserHarness": self._is_browser_harness_session(session),
                    "browserSkillRoute": browser_skill_route,
                },
            )
            return

        turn_detection_mode = self._realtime_route_turn_detection_mode(
            session,
            browser_skill_route=browser_skill_route,
        )
        client = self._ensure_transcription_client(
            session_id=session_id,
            clients=self.realtime_clients,
            partial_handler=self._handle_realtime_route_partial_transcript,
            final_handler=self._handle_realtime_final_transcript,
            status_handler=self._handle_realtime_route_status_update,
            source_label="openai_realtime_route",
            task_label="voice final",
            turn_detection_mode=turn_detection_mode,
            model_config_key="transcriptionModel",
            prompt_config_key="openaiTranscriptionPrompt",
        )
        pump_result = self._stream_realtime_client_audio(
            session=session,
            session_id=session_id,
            state=state,
            client=client,
            replay_ms=self._realtime_replay_ms(session, skill_keepalive=browser_skill_route),
            chunk_ms=int(self._config.get("realtimeChunkMs") or 120),
            replay_event="voice_realtime_replay",
            buffer_overrun_event="voice_realtime_buffer_overrun",
            chunk_has_voice=(
                lambda chunk: self._has_realtime_route_voice_energy(
                    session,
                    self._analyze_audio_energy(chunk),
                )
            )
            if turn_detection_mode == "manual"
            else None,
            reset_realtime_commit_on_generation=turn_detection_mode == "manual",
        )
        if turn_detection_mode == "manual":
            self._maybe_commit_manual_realtime_route(
                session=session,
                session_id=session_id,
                state=state,
                client=client,
                pump_result=pump_result,
                now_ms=now_ms,
            )

    def _maybe_stream_realtime_skill_session(self, session: Any) -> None:
        prepared = self._prepare_realtime_stream_session(
            session,
            touch_backend_activity=True,
            skill_keepalive=True,
        )
        if prepared is None:
            return
        session_id, state, _, stats, should_keep_realtime = prepared
        if not should_keep_realtime:
            self._close_realtime_client_for_session(
                session_id=session_id,
                clients=self.realtime_skill_clients,
                generation_attr="realtime_generation",
                reason="idle_silence",
                log_event="voice_realtime_skill_idle_close",
                log_payload={
                    "source": "openai_realtime_skills",
                    "avgAbs": int(stats.get("avgAbs") or 0),
                    "peakAbs": int(stats.get("peakAbs") or 0),
                    "nonSilentRatio": float(stats.get("nonSilentRatio") or 0.0),
                    "idleCloseMs": self._realtime_idle_close_ms(session, skill_keepalive=True),
                    "browserHarness": self._is_browser_harness_session(session),
                },
            )
            return

        client = self.realtime_skill_clients.get(session_id)
        if client is None:
            client = OpenAIRealtimeSkillClient(
                session_id=session_id,
                config_provider=lambda: self.get_config(mask_secrets=False),
                log_handler=self.log_handler,
                status_handler=self._handle_realtime_status_update,
                tool_schemas_provider=self.skill_registry.tool_schemas,
                tool_executor=lambda name, arguments: self.skill_registry.execute(
                    session_id=session_id,
                    tool_name=name,
                    arguments=arguments,
                    source="openai_realtime_skills",
                ),
            )
            self.realtime_skill_clients[session_id] = client
        self._stream_realtime_client_audio(
            session=session,
            session_id=session_id,
            state=state,
            client=client,
            replay_ms=self._realtime_replay_ms(session, skill_keepalive=True),
            chunk_ms=int(self._config.get("realtimeChunkMs") or 120),
            replay_event="voice_realtime_skill_replay",
            buffer_overrun_event="voice_realtime_skill_buffer_overrun",
        )

    def _maybe_stream_live_caption_session(self, session: Any) -> None:
        if not self._live_captions_enabled():
            return
        prepared = self._prepare_realtime_stream_session(
            session,
            touch_backend_activity=False,
        )
        if prepared is None:
            return
        session_id, state, now_ms, stats, should_keep_realtime = prepared
        if not should_keep_realtime:
            self._close_realtime_client_for_session(
                session_id=session_id,
                clients=self.realtime_live_clients,
                generation_attr="live_caption_generation",
                reason="idle_silence",
                log_event="voice_realtime_idle_close",
                log_payload={
                    "source": "openai_realtime_live",
                    "avgAbs": int(stats.get("avgAbs") or 0),
                    "peakAbs": int(stats.get("peakAbs") or 0),
                    "nonSilentRatio": float(stats.get("nonSilentRatio") or 0.0),
                },
            )
            return

        client = self._ensure_transcription_client(
            session_id=session_id,
            clients=self.realtime_live_clients,
            partial_handler=self._handle_realtime_partial_transcript,
            final_handler=self._handle_realtime_caption_final_transcript,
            status_handler=self._handle_realtime_status_update,
            source_label="openai_realtime_live",
            task_label="live caption",
            turn_detection_mode="manual",
            model_config_key="liveCaptionModel",
            prompt_config_key="openaiLiveCaptionPrompt",
        )
        if not client.is_ready():
            return

        window_start, _ = self._session_audio_bounds(session, 0)
        replay_decision = plan_generation_replay(
            current_input_offset=state.caption.input_offset,
            current_generation=state.caption.generation,
            ready_generation=client.ready_generation(),
            window_start=window_start,
            replay_bytes=self._bytes_for_ms(int(self._config.get("liveCaptionReplayMs") or 960)),
        )
        if replay_decision.replay_from is not None and replay_decision.replay_to is not None:
            self.log_handler(
                session_id,
                "voice_live_caption_replay",
                {
                    "fromOffset": replay_decision.replay_from,
                    "toOffset": replay_decision.replay_to,
                    "generation": replay_decision.next_generation,
                },
            )
        state.caption.input_offset = replay_decision.next_input_offset
        if replay_decision.next_generation > state.caption.generation:
            state.caption.commit_offset = state.caption.input_offset
        state.caption.generation = replay_decision.next_generation

        chunk_bytes = self._bytes_for_ms(int(self._config.get("realtimeChunkMs") or 80))
        requested_offset = state.caption.input_offset
        window_start, window_end = self._session_audio_bounds(session, requested_offset)
        window_decision = resolve_buffer_window(
            requested_offset=requested_offset,
            window_start=window_start,
            window_end=window_end,
            now_ms=now_ms,
            last_overrun_log_ms=state.segment.last_overrun_log_ms,
        )
        if not window_decision.has_audio:
            return
        if window_decision.next_input_offset > requested_offset:
            state.caption.input_offset = window_decision.next_input_offset
            state.caption.commit_offset = max(window_decision.next_input_offset, state.caption.commit_offset)

        catch_up_bytes = max(chunk_bytes, chunk_bytes * 8)
        payload_start, _, payload = self._session_audio_window(
            session,
            window_decision.start_offset,
            catch_up_bytes,
        )
        if not payload:
            return

        pump_result = pump_pcm_chunks(
            payload_start=payload_start,
            payload=payload,
            chunk_bytes=chunk_bytes,
            append_pcm=client.append_pcm,
            chunk_has_voice=lambda chunk: self._has_voice_energy(self._analyze_audio_energy(chunk)),
        )
        if pump_result.next_offset > state.caption.input_offset:
            state.caption.input_offset = pump_result.next_offset

        if pump_result.saw_voice:
            state.caption.last_voice_ms = now_ms
            if not state.caption.active:
                state.caption.active = True
                self._handle_realtime_status_update(
                    session_id,
                    {
                        "stateLabel": "capturing",
                        "taskLabel": "live caption",
                        "transcriptHint": self._trim_caption_hint(state.caption.last_text),
                        "source": "openai_realtime_live",
                    },
                )

        commit_decision = decide_live_caption_commit(
            active=state.caption.active,
            now_ms=now_ms,
            last_voice_ms=state.caption.last_voice_ms,
            input_offset=state.caption.input_offset,
            commit_offset=state.caption.commit_offset,
            rolling_commit_bytes=self._bytes_for_ms(int(self._config.get("liveCaptionCommitMs") or 480)),
            min_commit_bytes=self._bytes_for_ms(int(self._config.get("liveCaptionMinCommitMs") or 240)),
            silence_commit_ms=max(80, int(self._config.get("liveCaptionSilenceCommitMs") or 180)),
        )
        if not commit_decision.should_commit:
            return
        if not client.commit_audio():
            return

        state.caption.commit_offset = state.caption.input_offset
        state.caption.last_commit_ms = now_ms
        if commit_decision.deactivate_after_commit:
            state.caption.active = False
        self.log_handler(
            session_id,
            "voice_live_caption_commit",
            {
                "reason": commit_decision.reason,
                "bytesSinceCommit": commit_decision.bytes_since_commit,
                "voiceGapMs": commit_decision.voice_gap_ms,
            },
        )
        self._handle_realtime_status_update(
            session_id,
            {
                "stateLabel": commit_decision.next_state_label,
                "taskLabel": "live caption",
                "transcriptHint": self._trim_caption_hint(state.caption.last_text),
                "source": "openai_realtime_live",
            },
        )

    def _maybe_process_session(self, session: Any) -> None:
        session_id = str(getattr(session, "session_id", "") or "")
        if not session_id:
            return

        with self.state_lock:
            state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))
            if state.segment.transcribe_inflight:
                return

        now_ms = _now_ms()
        state.audio.last_seen_ms = int(getattr(session, "last_audio_timestamp_ms", now_ms) or now_ms)
        if self._audio_stats_support_realtime(session):
            state.audio.last_energy_ms = now_ms
        self.backend_last_activity_ms = now_ms

        min_bytes = self._bytes_for_ms(int(self._config["minSegmentMs"]))
        max_bytes = self._bytes_for_ms(int(self._config["maxSegmentMs"]))
        idle_flush_ms = int(self._config["idleFlushMs"])
        fast_min_bytes = self._bytes_for_ms(int(self._config.get("fastMinSegmentMs") or 720))
        rolling_flush_ms = int(self._config.get("rollingFlushMs") or 900)
        effective_min_bytes = max(self._bytes_for_ms(240), min(min_bytes, fast_min_bytes))
        start_offset = state.segment.last_processed_offset
        window_start, window_end, _ = self._session_audio_window(session, start_offset)
        if window_end <= window_start:
            return
        if window_start > start_offset:
            if now_ms - state.segment.last_overrun_log_ms >= 1500:
                state.segment.last_overrun_log_ms = now_ms
                self.log_handler(
                    session_id,
                    "voice_buffer_overrun",
                    {
                        "requestedOffset": start_offset,
                        "bufferStartOffset": window_start,
                        "bufferedBytes": window_end - window_start,
                    },
                )
            state.segment.last_processed_offset = window_start
            start_offset = window_start

        unprocessed = window_end - start_offset
        audio_idle_ms = now_ms - state.audio.last_seen_ms

        if unprocessed < effective_min_bytes:
            return
        should_flush = (
            unprocessed >= max_bytes
            or (unprocessed >= min_bytes and audio_idle_ms >= idle_flush_ms)
            or (
                unprocessed >= effective_min_bytes
                and (
                    audio_idle_ms >= max(100, idle_flush_ms // 2)
                    or now_ms - state.segment.last_segment_queued_ms >= rolling_flush_ms
                )
            )
        )
        if not should_flush:
            return

        read_size = min(unprocessed, max_bytes)
        segment_start, segment_end, segment = self._session_audio_window(session, start_offset, read_size)
        if not segment:
            return

        state.segment.transcribe_inflight = True
        state.segment.inflight_start_offset = segment_start
        state.segment.inflight_end_offset = segment_end
        state.segment.last_segment_queued_ms = now_ms
        last_audio_seen_ms = state.audio.last_seen_ms
        try:
            self.segment_executor.submit(
                self._process_segment_job,
                session_id,
                segment_start,
                segment_end,
                segment,
                audio_idle_ms,
                last_audio_seen_ms,
            )
        except Exception:
            state.segment.transcribe_inflight = False
            state.segment.inflight_start_offset = 0
            state.segment.inflight_end_offset = 0
            raise

    def _maybe_probe_local_partial(self, session: Any) -> None:
        if not self._local_partials_enabled():
            return

        session_id = str(getattr(session, "session_id", "") or "")
        if not session_id or not bool(getattr(session, "active", False)):
            return

        with self.state_lock:
            state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))

        now_ms = _now_ms()
        state.audio.last_seen_ms = int(getattr(session, "last_audio_timestamp_ms", now_ms) or now_ms)
        if self._audio_stats_support_realtime(session):
            state.audio.last_energy_ms = now_ms

        probe_interval_ms = max(120, int(self._config.get("localPartialProbeMs") or 280))
        min_window_bytes = self._bytes_for_ms(int(self._config.get("localPartialMinMs") or 320))
        window_bytes = self._bytes_for_ms(int(self._config.get("localPartialWindowMs") or 1200))
        idle_clear_ms = max(200, int(self._config.get("localPartialIdleClearMs") or 1400))

        if state.partial.local_inflight or state.segment.transcribe_inflight:
            return
        if now_ms - state.partial.local_last_probe_ms < probe_interval_ms:
            return

        if not self._realtime_recent_audio_active(
            state,
            now_ms,
            idle_close_ms=self._realtime_idle_close_ms(session),
        ):
            if state.partial.local_last_text and now_ms - state.partial.local_last_emit_ms > idle_clear_ms:
                self._clear_local_partial(session_id, state_label="heard")
            return

        start_floor = max(0, state.segment.last_processed_offset)
        window_start, window_end, _ = self._session_audio_window(session, start_floor)
        if window_end <= window_start:
            return

        payload_end = window_end
        payload_start = max(window_start, payload_end - window_bytes, start_floor)
        payload_size = payload_end - payload_start
        if payload_size < min_window_bytes:
            return
        _, _, payload = self._session_audio_window(session, payload_start, payload_size)
        if not payload or len(payload) < min_window_bytes:
            return

        energy = self._analyze_audio_energy(payload)
        if not self._has_voice_energy(energy):
            return

        state.partial.local_inflight = True
        state.partial.local_last_probe_ms = now_ms
        try:
            self.partial_executor.submit(
                self._process_local_partial_job,
                session_id,
                payload_start,
                payload_end,
                payload,
            )
        except Exception:
            state.partial.local_inflight = False
            raise

    def _bytes_for_ms(self, duration_ms: int) -> int:
        sample_rate_hz = 16_000
        bytes_per_sample = 2
        channels = 1
        return max(1, int(sample_rate_hz * bytes_per_sample * channels * duration_ms / 1000))

    def _session_audio_bounds(self, session: Any, start_offset: int) -> tuple[int, int]:
        buffer_lock = getattr(session, "_audio_buffer_lock", None)
        audio_buffer = getattr(session, "_audio_buffer", None)
        buffer_start = getattr(session, "_audio_buffer_start_offset", None)
        if buffer_lock is not None and audio_buffer is not None and buffer_start is not None:
            try:
                with buffer_lock:
                    current_start = int(getattr(session, "_audio_buffer_start_offset", 0) or 0)
                    current_end = current_start + len(getattr(session, "_audio_buffer", b""))
                return max(start_offset, current_start), current_end
            except Exception:
                pass

        audio_path = Path(str(getattr(session, "audio_path", "") or ""))
        if audio_path.exists():
            total_bytes = audio_path.stat().st_size
            return min(max(start_offset, 0), total_bytes), total_bytes

        payload_start, payload_end, payload = self._session_audio_window(session, start_offset, 1)
        if payload_end > payload_start or payload:
            return payload_start, payload_end
        return payload_start, payload_start

    def _session_audio_window(
        self,
        session: Any,
        start_offset: int,
        max_bytes: int | None = None,
    ) -> tuple[int, int, bytes]:
        if hasattr(session, "read_audio_window"):
            try:
                payload_start, payload_end, payload = session.read_audio_window(start_offset, max_bytes)
                return int(payload_start), int(payload_end), payload
            except Exception:
                pass

        audio_path = Path(str(getattr(session, "audio_path", "") or ""))
        if not audio_path.exists():
            return start_offset, start_offset, b""

        total_bytes = audio_path.stat().st_size
        if total_bytes <= start_offset:
            return total_bytes, total_bytes, b""
        read_size = total_bytes - start_offset if max_bytes is None else min(max_bytes, total_bytes - start_offset)
        with open(audio_path, "rb") as source:
            source.seek(start_offset)
            payload = source.read(read_size)
        return start_offset, start_offset + len(payload), payload

    def _segment_overlap_bytes(self, segment_bytes: int) -> int:
        configured = self._bytes_for_ms(int(self._config.get("segmentOverlapMs") or 240))
        return min(max(0, configured), max(0, segment_bytes // 2))

    def _process_segment_job(
        self,
        session_id: str,
        segment_start: int,
        segment_end: int,
        segment: bytes,
        audio_idle_ms: int,
        last_audio_seen_ms: int,
    ) -> None:
        overlap_bytes = self._segment_overlap_bytes(len(segment))
        next_offset = segment_end
        try:
            trimmed_segment, trim_meta = self._trim_pcm_silence(segment)
            candidate_segment = trimmed_segment if trimmed_segment else segment

            energy = self._analyze_audio_energy(candidate_segment)
            if not self._has_voice_energy(energy):
                self.log_handler(
                    session_id,
                    "voice_silence_skip",
                    {
                        "bytes": len(candidate_segment),
                        "rawBytes": len(segment),
                        "avgAbs": energy.avg_abs,
                        "peakAbs": energy.peak_abs,
                        "nonSilentRatio": round(energy.non_silent_ratio, 4),
                        "silenceFloor": int(self._config.get("silenceFloor") or 72),
                        "audioIdleMs": audio_idle_ms,
                        "segmentStartOffset": segment_start,
                        "segmentEndOffset": segment_end,
                        **trim_meta,
                    },
                )
                return

            self.log_handler(
                session_id,
                "voice_segment_ready",
                {
                    "bytes": len(candidate_segment),
                    "rawBytes": len(segment),
                    "audioIdleMs": audio_idle_ms,
                    "avgAbs": energy.avg_abs,
                    "peakAbs": energy.peak_abs,
                    "nonSilentRatio": round(energy.non_silent_ratio, 4),
                    "segmentStartOffset": segment_start,
                    "segmentEndOffset": segment_end,
                    **trim_meta,
                },
            )

            min_voiced_bytes = self._bytes_for_ms(int(self._config.get("minVoicedSegmentMs") or 640))
            hold_idle_ms = max(0, int(self._config.get("minVoicedHoldIdleMs") or 260))
            if len(candidate_segment) < min_voiced_bytes and audio_idle_ms < hold_idle_ms:
                next_offset = segment_start
                self.log_handler(
                    session_id,
                    "voice_segment_hold_short_voiced",
                    {
                        "bytes": len(candidate_segment),
                        "rawBytes": len(segment),
                        "audioIdleMs": audio_idle_ms,
                        "minVoicedBytes": min_voiced_bytes,
                        "holdIdleMs": hold_idle_ms,
                        "segmentStartOffset": segment_start,
                        "segmentEndOffset": segment_end,
                    },
                )
                return

            transcribe_started_ms = _now_ms()
            transcript, backend_used = self._transcribe_segment(session_id, candidate_segment)
            transcribe_elapsed_ms = max(0, _now_ms() - transcribe_started_ms)
            if not transcript:
                self.log_handler(
                    session_id,
                    "voice_transcribe_empty",
                    {
                        "backend": backend_used,
                        "transcribeMs": transcribe_elapsed_ms,
                        "segmentStartOffset": segment_start,
                        "segmentEndOffset": segment_end,
                    },
                )
                next_offset = max(segment_start, segment_end - overlap_bytes)
                return

            self._process_final_transcript(
                session_id=session_id,
                transcript=transcript,
                source=backend_used,
                transcribe_elapsed_ms=transcribe_elapsed_ms,
                end_to_end_ms=max(0, _now_ms() - last_audio_seen_ms),
                audio_idle_ms=audio_idle_ms,
                extra_log={
                    "segmentStartOffset": segment_start,
                    "segmentEndOffset": segment_end,
                },
            )
            next_offset = max(segment_start, segment_end - overlap_bytes)
        except Exception as error:
            self.backend_last_error = str(error)
            self.log_handler(
                session_id,
                "voice_segment_error",
                {
                    "error": str(error),
                    "segmentStartOffset": segment_start,
                    "segmentEndOffset": segment_end,
                },
            )
            next_offset = max(segment_start, segment_end - overlap_bytes)
        finally:
            self._complete_segment_job(session_id, next_offset, segment_end)

    def _process_local_partial_job(
        self,
        session_id: str,
        segment_start: int,
        segment_end: int,
        segment: bytes,
    ) -> None:
        try:
            trimmed_segment, trim_meta = self._trim_pcm_silence(segment)
            candidate_segment = trimmed_segment if trimmed_segment else segment
            energy = self._analyze_audio_energy(candidate_segment)
            if not self._has_voice_energy(energy):
                return

            transcribe_started_ms = _now_ms()
            transcript, backend_used = self._transcribe_partial_segment(session_id, candidate_segment)
            transcribe_elapsed_ms = max(0, _now_ms() - transcribe_started_ms)
            if not transcript:
                return

            cleaned = self._sanitize_caption_text(transcript)
            if not cleaned:
                return
            if self._is_language_script_mismatch(cleaned):
                return
            if self._is_spurious_transcript(cleaned):
                return
            if not self._should_emit_local_partial_candidate(cleaned):
                return

            with self.state_lock:
                state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))
                merged = next_local_partial_text(
                    state.partial.local_last_text,
                    cleaned,
                    merge_local_partial_text=self._merge_local_partial_caption,
                )
                if not merged:
                    return
                state.partial.local_last_text = merged
                state.partial.last_transcript = merged
                state.partial.last_ms = _now_ms()
                state.partial.local_last_emit_ms = state.partial.last_ms

            self.log_handler(
                session_id,
                "voice_local_partial",
                {
                    "backend": backend_used,
                    "text": merged,
                    "piece": cleaned,
                    "segmentStartOffset": segment_start,
                    "segmentEndOffset": segment_end,
                    "transcribeMs": transcribe_elapsed_ms,
                    **trim_meta,
                },
            )
            self._handle_realtime_status_update(
                session_id,
                {
                    "stateLabel": "captioning",
                    "taskLabel": "live speech",
                    "transcriptHint": self._trim_caption_hint(merged),
                    "source": backend_used,
                },
            )
        except Exception as error:
            self.log_handler(
                session_id,
                "voice_local_partial_error",
                {
                    "error": str(error),
                    "segmentStartOffset": segment_start,
                    "segmentEndOffset": segment_end,
                },
            )
        finally:
            with self.state_lock:
                state = self.session_states.get(session_id)
                if state is not None:
                    state.partial.local_inflight = False

    def _complete_segment_job(self, session_id: str, next_offset: int, segment_end: int) -> None:
        with self.state_lock:
            state = self.session_states.get(session_id)
            if state is None:
                return
            state.segment.last_processed_offset = min(
                segment_end,
                max(state.segment.last_processed_offset, next_offset),
            )
            state.segment.transcribe_inflight = False
            state.segment.inflight_start_offset = 0
            state.segment.inflight_end_offset = 0

    def _clear_local_partial(self, session_id: str, *, state_label: str) -> None:
        with self.state_lock:
            state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))
            if not state.partial.local_last_text and not state.partial.last_transcript:
                return
            state.partial.clear()
        self._handle_realtime_status_update(
            session_id,
            {
                "stateLabel": state_label,
                "taskLabel": "live speech",
                "transcriptHint": None,
                "source": "local_partial_clear",
            },
        )

    def _handle_realtime_status_update(self, session_id: str, payload: dict[str, Any]) -> None:
        if self.speech_handler is None:
            return
        event = {
            "timestampMs": _now_ms(),
            "sessionId": session_id,
            "listening": True,
            "stateLabel": str(payload.get("stateLabel") or "listening"),
            "taskLabel": str(payload.get("taskLabel") or "voice live"),
            "transcriptHint": payload.get("transcriptHint"),
            "source": str(payload.get("source") or "openai_realtime"),
        }
        self.speech_handler(event)

    def _handle_realtime_route_status_update(self, session_id: str, payload: dict[str, Any]) -> None:
        if not bool(self._config.get("routeSpeechHudEnabled", False)):
            return
        if not self._live_captions_enabled():
            self._handle_realtime_status_update(session_id, payload)

    def _handle_realtime_route_partial_transcript(self, session_id: str, transcript: str, meta: dict[str, Any]) -> None:
        if not bool(self._config.get("routeSpeechHudEnabled", False)):
            return
        cleaned = self._strip_caption_prompt_echo(self._clean_transcript(transcript))
        if not cleaned:
            return
        if self._is_language_script_mismatch(cleaned):
            return
        with self.state_lock:
            state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))
            next_text = next_route_partial_text(state.partial.last_transcript, cleaned)
            if not next_text:
                return
            state.partial.last_transcript = next_text
            state.partial.last_ms = _now_ms()
        self._handle_realtime_status_update(
            session_id,
            {
                "stateLabel": "captioning",
                "taskLabel": "live speech",
                "transcriptHint": self._trim_caption_hint(next_text),
                "source": str(meta.get("source") or "openai_realtime_route"),
            },
        )

    def _handle_realtime_partial_transcript(self, session_id: str, transcript: str, meta: dict[str, Any]) -> None:
        cleaned = self._sanitize_caption_text(transcript)
        if not cleaned:
            return
        if self._is_language_script_mismatch(cleaned):
            return
        if self._is_spurious_transcript(cleaned):
            return
        with self.state_lock:
            state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))
            merged = next_live_partial_text(
                state.caption.committed_text,
                state.caption.last_text,
                cleaned,
                merge_incremental_transcript=self._merge_caption_incremental,
            )
            if not merged:
                return
            state.partial.last_transcript = merged
            state.partial.last_ms = _now_ms()
            state.caption.partial_text = cleaned
            state.caption.last_text = merged
            state.caption.last_emit_ms = state.partial.last_ms
        self.log_handler(
            session_id,
            "voice_live_caption_partial",
            {
                "backend": str(meta.get("source") or "openai_realtime_live"),
                "text": merged,
                "piece": cleaned,
            },
        )
        self._handle_realtime_status_update(
            session_id,
            {
                "stateLabel": "captioning",
                "taskLabel": "live caption",
                "transcriptHint": self._trim_caption_hint(merged),
                "source": str(meta.get("source") or "openai_realtime_live"),
            },
        )

    def _handle_realtime_caption_final_transcript(self, session_id: str, transcript: str, meta: dict[str, Any]) -> None:
        normalized = self._sanitize_caption_text(transcript)
        if not normalized:
            return
        if self._is_language_script_mismatch(normalized):
            return
        if self._is_spurious_transcript(normalized):
            return
        with self.state_lock:
            state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))
            merged = next_live_final_text(
                state.caption.committed_text,
                state.caption.last_text,
                normalized,
                merge_incremental_transcript=self._merge_caption_incremental,
            )
            if not merged:
                return
            state.partial.last_transcript = merged
            state.partial.last_ms = _now_ms()
            state.caption.committed_text = merged
            state.caption.partial_text = ""
            state.caption.last_text = merged
            state.caption.last_emit_ms = state.partial.last_ms
        self.log_handler(
            session_id,
            "voice_live_caption",
            {
                "backend": str(meta.get("source") or "openai_realtime_live"),
                "text": merged,
                "piece": normalized,
                "commitIndex": meta.get("commitIndex"),
            },
        )
        self._handle_realtime_status_update(
            session_id,
            {
                "stateLabel": "captioning",
                "taskLabel": "live caption",
                "transcriptHint": self._trim_caption_hint(merged),
                "source": str(meta.get("source") or "openai_realtime_live"),
            },
        )

    def _handle_realtime_final_transcript(self, session_id: str, transcript: str, meta: dict[str, Any]) -> None:
        normalized = self._accept_backend_transcript(
            session_id,
            backend="openai_realtime_route",
            transcript=transcript,
        )
        if not normalized:
            return
        with self.state_lock:
            state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))
            end_to_end_ms = max(0, _now_ms() - state.audio.last_seen_ms) if state.audio.last_seen_ms else 0
            state.reset_caption_feedback()
        self._process_final_transcript(
            session_id=session_id,
            transcript=normalized,
            source=str(meta.get("source") or "openai_realtime_route"),
            transcribe_elapsed_ms=int(meta.get("transcribeMs") or 0),
            end_to_end_ms=end_to_end_ms,
            extra_log={
                "itemId": meta.get("itemId"),
                "commitIndex": meta.get("commitIndex"),
                "committedMs": meta.get("committedMs"),
            },
        )

    def _caption_prompt_markers(self) -> tuple[str, ...]:
        return build_live_caption_prompt_markers(
            (
                str(self._config.get("openaiLiveCaptionPrompt") or ""),
                str(self._config.get("openaiTranscriptionPrompt") or ""),
            )
        )

    def _merge_caption_incremental(self, stable_text: str, next_piece: str) -> str:
        return merge_incremental_transcript(
            stable_text,
            next_piece,
            cleaner=self._clean_transcript,
            normalizer=_norm_text,
        )

    def _merge_local_partial_caption(self, previous_text: str, next_text: str) -> str:
        return merge_local_partial_text(
            previous_text,
            next_text,
            cleaner=self._clean_transcript,
            normalizer=_norm_text,
        )

    def _trim_caption_hint(self, transcript: str, max_chars: int = 160) -> str:
        return trim_live_caption_hint(
            transcript,
            cleaner=self._clean_transcript,
            max_chars=max_chars,
        )

    def _sanitize_caption_text(self, transcript: str) -> str:
        return sanitize_live_caption_transcript(
            transcript,
            cleaner=self._clean_transcript,
            normalizer=_norm_text,
            has_vietnamese_markers=self._has_vietnamese_markers,
            prompt_markers=self._caption_prompt_markers(),
        )

    def _strip_caption_prompt_echo(self, transcript: str) -> str:
        return strip_live_caption_prompt_echo(
            transcript,
            cleaner=self._clean_transcript,
            prompt_markers=self._caption_prompt_markers(),
        )

    def _should_emit_local_partial_candidate(self, transcript: str) -> bool:
        return should_emit_local_partial_text(
            transcript,
            normalizer=_norm_text,
            command_hints=VIETNAMESE_COMMAND_HINTS,
        )

    def _process_final_transcript(
        self,
        *,
        session_id: str,
        transcript: str,
        source: str,
        transcribe_elapsed_ms: int,
        end_to_end_ms: int,
        audio_idle_ms: int | None = None,
        extra_log: dict[str, Any] | None = None,
    ) -> None:
        now_ms = _now_ms()
        with self.state_lock:
            state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))
            pending_text = state.route.pending_transcript
            pending_ms = state.route.pending_ms
            last_transcript = state.route.last_transcript
            last_transcript_ms = state.route.last_transcript_ms
        resolution = resolve_final_route(
            transcript=transcript,
            source=source,
            now_ms=now_ms,
            last_transcript=last_transcript,
            last_transcript_ms=last_transcript_ms,
            pending_text=pending_text,
            pending_ms=pending_ms,
            build_action=lambda next_transcript, next_source: self._build_action(
                session_id=session_id,
                transcript=next_transcript,
                source=next_source,
                scene_context=self.scene_context_provider(session_id),
            ),
            merge_transcript=self._merge_caption_incremental,
            is_action_more_specific=self._is_action_more_specific,
            is_incomplete_command_prefix=self._is_incomplete_command_prefix,
        )
        if resolution.duplicate:
            self.log_handler(session_id, "voice_duplicate_skip", {"transcript": transcript})
            return
        if resolution.clear_pending:
            with self.state_lock:
                state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))
                state.route.clear_pending()
        if resolution.hold_transcript:
            hold_transcript = resolution.hold_transcript
            effective_action = resolution.effective_action or {}
            with self.state_lock:
                state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))
                state.route.pending_transcript = hold_transcript
                state.route.pending_ms = now_ms
            self.log_handler(
                session_id,
                "voice_route_hold",
                {
                    "transcript": hold_transcript,
                    "reason": resolution.hold_reason or "await_followup",
                    "source": source,
                },
            )
            return
        effective_transcript = resolution.effective_transcript
        effective_action = resolution.effective_action or {}

        payload = {
            "backend": source,
            "transcribeMs": max(0, transcribe_elapsed_ms),
            "endToEndMs": max(0, end_to_end_ms),
            "transcript": effective_transcript,
            "intent": effective_action.get("intent"),
            "mode": effective_action.get("mode"),
        }
        if audio_idle_ms is not None:
            payload["audioIdleMs"] = audio_idle_ms
        if extra_log:
            payload.update({key: value for key, value in extra_log.items() if value not in (None, "")})
        self.log_handler(session_id, "voice_action_ready", payload)
        self._dispatch_action(effective_action)

        with self.state_lock:
            state = self.session_states.setdefault(session_id, VoiceSessionState(session_id=session_id))
            state.partial.clear()
            state.route.record_action(
                now_ms=now_ms,
                transcript=effective_transcript,
                answer=str(effective_action.get("answer") or ""),
                intent=str(effective_action.get("intent") or "idle"),
                mode=effective_action.get("mode"),
                target_query=effective_action.get("targetQuery"),
            )

    def _analyze_audio_energy(self, payload: bytes) -> AudioEnergyStats:
        samples = array("h")
        samples.frombytes(payload[: len(payload) - (len(payload) % 2)])
        if not samples:
            return AudioEnergyStats(avg_abs=0, peak_abs=0, non_silent_ratio=0.0)
        floor = max(16, int(self._config.get("silenceFloor") or 72))
        voiced_threshold = max(24, floor // 2)
        total = sum(abs(int(item)) for item in samples)
        peak = max(abs(int(item)) for item in samples)
        non_silent = sum(1 for item in samples if abs(int(item)) >= voiced_threshold)
        average = int(total / max(1, len(samples)))
        ratio = non_silent / max(1, len(samples))
        return AudioEnergyStats(avg_abs=average, peak_abs=int(peak), non_silent_ratio=float(ratio))

    def _has_voice_energy(self, stats: AudioEnergyStats) -> bool:
        floor = max(16, int(self._config.get("silenceFloor") or 72))
        if stats.avg_abs >= floor:
            return True
        if stats.non_silent_ratio >= 0.02 and stats.peak_abs >= max(192, floor * 3):
            return True
        if stats.peak_abs >= 2048 and stats.non_silent_ratio >= 0.002:
            return True
        return False

    def _trim_pcm_silence(self, payload: bytes) -> tuple[bytes, dict[str, int]]:
        frame_size = self._bytes_for_ms(80)
        if len(payload) <= frame_size * 2:
            return payload, {
                "trimFrontBytes": 0,
                "trimBackBytes": 0,
                "trimmedBytes": len(payload),
            }

        frames: list[tuple[int, AudioEnergyStats]] = []
        for offset in range(0, len(payload), frame_size):
            chunk = payload[offset : offset + frame_size]
            if len(chunk) < frame_size:
                break
            frames.append((offset, self._analyze_audio_energy(chunk)))
        if not frames:
            return payload, {
                "trimFrontBytes": 0,
                "trimBackBytes": 0,
                "trimmedBytes": len(payload),
            }

        start_offset = 0
        end_offset = len(payload)

        for offset, stats in frames:
            if self._has_voice_energy(stats):
                start_offset = max(0, offset - frame_size)
                break

        for offset, stats in reversed(frames):
            if self._has_voice_energy(stats):
                end_offset = min(len(payload), offset + (frame_size * 2))
                break

        if end_offset <= start_offset:
            return payload, {
                "trimFrontBytes": 0,
                "trimBackBytes": 0,
                "trimmedBytes": len(payload),
            }

        trimmed = payload[start_offset:end_offset]
        return trimmed, {
            "trimFrontBytes": start_offset,
            "trimBackBytes": max(0, len(payload) - end_offset),
            "trimmedBytes": len(trimmed),
        }

    def _transcribe_segment(self, session_id: str, segment: bytes) -> tuple[str, str]:
        wav_bytes = pcm_to_wav_bytes(segment)
        plan = build_segment_transcription_plan(self._config)
        if plan.skip_reason:
            log_payload = {"reason": plan.skip_reason}
            if plan.skip_backend:
                log_payload["backend"] = plan.skip_backend
            self.log_handler(session_id, "voice_transcribe_skipped", log_payload)
            return "", plan.terminal_source
        for attempt in plan.attempts:
            transcript = self._execute_transcription_attempt(
                session_id=session_id,
                wav_bytes=wav_bytes,
                attempt=attempt,
            )
            if transcript:
                return transcript, attempt.result_source
        return "", plan.terminal_source

    def _transcribe_partial_segment(self, session_id: str, segment: bytes) -> tuple[str, str]:
        wav_bytes = pcm_to_wav_bytes(segment)
        plan = build_partial_transcription_plan(self._config)
        for attempt in plan.attempts:
            transcript = self._execute_transcription_attempt(
                session_id=session_id,
                wav_bytes=wav_bytes,
                attempt=attempt,
            )
            if transcript:
                return transcript, attempt.result_source
        return "", plan.terminal_source

    def _execute_transcription_attempt(
        self,
        *,
        session_id: str,
        wav_bytes: bytes,
        attempt: TranscriptionAttempt,
    ) -> str:
        if attempt.backend == "local_http":
            return self._transcribe_local_http(session_id, wav_bytes, partial_mode=attempt.partial_mode)
        if attempt.backend == "local_command":
            return self._transcribe_local_command(session_id, wav_bytes)
        if attempt.backend == "openai":
            return self._transcribe_openai(session_id, wav_bytes)
        return ""

    def _accept_backend_transcript(
        self,
        session_id: str,
        *,
        backend: str,
        transcript: str,
        mark_backend_active: bool = False,
    ) -> str:
        decision = evaluate_transcript_candidate(
            transcript,
            cleaner=self._clean_transcript,
            is_spurious=self._is_spurious_transcript,
            is_language_script_mismatch=self._is_language_script_mismatch,
        )
        if decision.discard_reason == "spurious":
            self.log_handler(
                session_id,
                "voice_transcript_discarded",
                {"backend": backend, "text": decision.cleaned_text},
            )
            return ""
        if decision.discard_reason == "language_script_mismatch":
            self.log_handler(
                session_id,
                "voice_transcript_discarded",
                {
                    "backend": backend,
                    "text": decision.cleaned_text,
                    "reason": "language_script_mismatch",
                },
            )
            return ""
        if not decision.accepted_text:
            return ""
        if mark_backend_active:
            self._set_backend_state("active")
        self.log_handler(
            session_id,
            "voice_transcript",
            {"backend": backend, "text": decision.accepted_text},
        )
        return decision.accepted_text

    def _transcribe_openai(self, session_id: str, wav_bytes: bytes) -> str:
        if not self._config.get("enableOpenAI", True) or not self._api_key():
            self.log_handler(session_id, "voice_transcribe_skipped", {"reason": "openai_not_configured"})
            return ""
        try:
            payload = request_openai_audio_transcription(
                config=self._config,
                api_key=self._api_key(),
                wav_bytes=wav_bytes,
                now_ms=_now_ms,
            )
        except Exception as error:
            self.log_handler(session_id, "voice_transcribe_error", {"backend": "openai", "error": str(error)})
            return ""
        return self._accept_backend_transcript(
            session_id,
            backend="openai",
            transcript=str(payload.get("text") or "").strip(),
        )

    def _clean_transcript(self, transcript: str) -> str:
        text = transcript.strip()
        text = re.sub(r"\s+", " ", text)
        text = text.strip(" .,!?:;-_")
        if len(text) <= 1:
            return text
        return text

    def _has_vietnamese_markers(self, transcript: str) -> bool:
        lowered = transcript.lower()
        return lowered != _strip_accents(lowered) or "đ" in lowered

    def _looks_non_vietnamese_latin_transcript(self, transcript: str) -> bool:
        norm = _norm_text(transcript)
        if not norm or self._has_vietnamese_markers(transcript):
            return False
        if any(hint in norm for hint in VIETNAMESE_COMMAND_HINTS):
            return False
        tokens = [token for token in re.findall(r"[a-z']+", norm) if token]
        if not tokens:
            return False
        english_hits = sum(1 for token in tokens if token in COMMON_ENGLISH_TOKENS)
        if len(tokens) == 1 and tokens[0] in {"hello", "hey", "hi", "hallo", "people", "there", "view"}:
            return True
        if english_hits >= 3:
            return True
        return english_hits >= 2 and (english_hits * 2) >= len(tokens)

    def _is_language_script_mismatch(self, transcript: str) -> bool:
        language = str(self._config.get("languageHint") or "").strip().lower()
        if not language.startswith("vi"):
            return False

        latin_letters = 0
        foreign_counts = {
            "hangul": 0,
            "cjk": 0,
            "cyrillic": 0,
            "thai": 0,
        }
        for char in transcript:
            if not char.isalpha():
                continue
            name = unicodedata.name(char, "")
            if "LATIN" in name:
                latin_letters += 1
            elif "HANGUL" in name:
                foreign_counts["hangul"] += 1
            elif "CJK UNIFIED" in name:
                foreign_counts["cjk"] += 1
            elif "CYRILLIC" in name:
                foreign_counts["cyrillic"] += 1
            elif "THAI" in name:
                foreign_counts["thai"] += 1

        dominant_foreign = max(foreign_counts.values()) if foreign_counts else 0
        if dominant_foreign == 0:
            return self._looks_non_vietnamese_latin_transcript(transcript)
        if latin_letters == 0:
            return True
        return dominant_foreign >= 2 and dominant_foreign >= (latin_letters * 2)

    def _is_spurious_transcript(self, transcript: str) -> bool:
        norm = _norm_text(transcript)
        if not norm:
            return True
        prompt_echo_markers = self._caption_prompt_markers()
        if any(marker in norm for marker in prompt_echo_markers):
            return True
        filler_tokens = {
            "a",
            "ah",
            "bye",
            "ha",
            "hallo",
            "hello",
            "hi",
            "hmm",
            "huh",
            "ok",
            "oke",
            "uh",
            "um",
            "xin",
            "yo",
            "à",
            "á",
            "ờ",
            "ừ",
            "ừm",
        }
        if not any(char.isalnum() for char in norm):
            return True
        if norm in filler_tokens:
            return True
        tokens = [token for token in norm.split(" ") if token]
        if not tokens:
            return True
        if any(hint in norm for hint in VIETNAMESE_COMMAND_HINTS):
            return False
        if len(tokens) == 1 and (tokens[0] in filler_tokens or len(tokens[0]) <= 2):
            return True
        if len(tokens) <= 2 and all(len(token) <= 2 for token in tokens):
            return True
        return False

    def _transcribe_local_http(self, session_id: str, wav_bytes: bytes, *, partial_mode: bool = False) -> str:
        url = str(self._config.get("localTranscribeUrl") or "").strip()
        if not url:
            return ""
        self.backend_last_activity_ms = _now_ms()
        if not self.local_backend.ensure_running(session_id):
            return ""

        try:
            transcript = request_local_http_transcription(
                config=self._config,
                session_id=session_id,
                wav_bytes=wav_bytes,
                partial_mode=partial_mode,
                now_ms=_now_ms,
            )
        except Exception as error:
            self.backend_last_error = str(error)
            self.log_handler(session_id, "voice_transcribe_error", {"backend": "local_http", "error": str(error)})
            return ""

        return self._accept_backend_transcript(
            session_id,
            backend="local_http",
            transcript=transcript,
            mark_backend_active=True,
        )

    def _transcribe_local_command(self, session_id: str, wav_bytes: bytes) -> str:
        try:
            transcript = run_local_command_transcription(
                config=self._config,
                session_id=session_id,
                wav_bytes=wav_bytes,
                segment_dir=self.segment_dir,
                now_ms=_now_ms,
            )
        except Exception as error:
            self.log_handler(session_id, "voice_transcribe_error", {"backend": "local_command", "error": str(error)})
            return ""

        return self._accept_backend_transcript(
            session_id,
            backend="local_command",
            transcript=transcript,
        )

    def _set_backend_state(self, next_state: str) -> None:
        if self.backend_state == next_state:
            return
        self.backend_state = next_state
        self.backend_last_state_change_ms = _now_ms()

    def _api_key(self) -> str:
        return str(self._config.get("openaiApiKey") or "").strip()

    def _openai_route(self, transcript: str, scene_summary: str) -> dict[str, Any] | None:
        if not self._config.get("enableOpenAI", True) or not self._config.get("allowOpenAIRouterFallback", True):
            return None
        if not self._api_key():
            return None
        return request_openai_route(
            config=self._config,
            api_key=self._api_key(),
            transcript=transcript,
            scene_summary=scene_summary,
        )

    def _build_action(
        self,
        *,
        session_id: str,
        transcript: str,
        source: str,
        scene_context: dict[str, Any],
    ) -> dict[str, Any]:
        transcript_norm = _norm_text(transcript)
        scene_summary = str(scene_context.get("summary") or "No scene summary")
        heuristic = self._heuristic_route(transcript, transcript_norm, scene_context)
        if heuristic["confidence"] < 0.8:
            remote = self._openai_route(transcript, scene_summary)
            if remote:
                heuristic = self._merge_remote_route(heuristic, remote)

        return {
            "timestampMs": _now_ms(),
            "sessionId": session_id,
            "transcript": transcript,
            "source": source,
            "intent": heuristic["intent"],
            "mode": heuristic.get("mode"),
            "targetQuery": heuristic.get("target_query"),
            "answer": heuristic["answer"],
            "statusText": heuristic.get("status_text"),
            "confidence": heuristic["confidence"],
            "sceneSummary": scene_summary,
        }

    def _merge_remote_route(self, heuristic: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
        merged = dict(heuristic)
        for key in ("intent", "mode", "target_query", "answer", "confidence"):
            if key in remote and remote[key] not in (None, ""):
                merged[key] = remote[key]
        try:
            merged["confidence"] = float(merged.get("confidence") or 0.5)
        except Exception:
            merged["confidence"] = heuristic["confidence"]
        return merged

    def _is_incomplete_command_prefix(self, transcript: str, action: dict[str, Any]) -> bool:
        if str(action.get("intent") or "") != "transcript_only":
            return False
        norm = _norm_text(transcript)
        if not norm:
            return False
        command_prefixes = (
            "tim",
            "theo doi",
            "mo ta",
        )
        return any(norm.startswith(prefix) for prefix in command_prefixes)

    def _is_action_more_specific(self, candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
        candidate_intent = str(candidate.get("intent") or "")
        baseline_intent = str(baseline.get("intent") or "")
        if baseline_intent == "transcript_only" and candidate_intent != "transcript_only":
            return True
        if candidate_intent == "target_search" and baseline_intent == "target_search":
            candidate_query = _norm_text(str(candidate.get("target_query") or ""))
            baseline_query = _norm_text(str(baseline.get("target_query") or ""))
            return len(candidate_query) > len(baseline_query)
        return False

    def _heuristic_route(
        self,
        transcript_raw: str,
        transcript_norm: str,
        scene_context: dict[str, Any],
    ) -> dict[str, Any]:
        variants = self._routing_variants(transcript_raw, transcript_norm)
        summary = str(scene_context.get("summary") or "Scene live")
        counts_inline = str(scene_context.get("countsInline") or "")

        if self._is_standby_command(variants):
            return {
                "intent": "mode_change",
                "mode": "standby",
                "target_query": None,
                "answer": "",
                "status_text": "Đã về chế độ chờ.",
                "confidence": 0.98,
            }
        if self._is_traffic_command(variants):
            return {
                "intent": "mode_change",
                "mode": "traffic_count",
                "target_query": None,
                "answer": "",
                "status_text": "Đã bật đếm phương tiện.",
                "confidence": 0.98,
            }
        if self._matches_any_variant(variants, ("radar", "trai phai", "xung quanh", "peripheral", "ar radar")):
            return {
                "intent": "mode_change",
                "mode": "ar_radar",
                "target_query": None,
                "answer": "",
                "status_text": "Đã bật AR radar.",
                "confidence": 0.96,
            }
        if self._matches_any_variant(variants, ("focus", "tap trung", "bubble", "khoa muc tieu")):
            return {
                "intent": "mode_change",
                "mode": "focus_bubble",
                "target_query": None,
                "answer": "",
                "status_text": "Đã bật Focus Bubble.",
                "confidence": 0.96,
            }
        if self._matches_any_variant(variants, ("silent", "im lang", "alert", "canh bao", "burst")):
            return {
                "intent": "mode_change",
                "mode": "alert_burst",
                "target_query": None,
                "answer": "",
                "status_text": "Đã bật Silent Alert Burst.",
                "confidence": 0.95,
            }
        if self._is_scene_command(variants):
            return {
                "intent": "scene_query",
                "mode": "visual_assistant",
                "target_query": None,
                "answer": "",
                "status_text": "Đã bật hỗ trợ hình ảnh.",
                "confidence": 0.94,
            }

        target_query = self._extract_target_query(transcript_raw, transcript_norm)
        if target_query:
            return {
                "intent": "target_search",
                "mode": "visual_assistant",
                "target_query": target_query,
                "answer": "",
                "status_text": f"Đang tìm {target_query}.",
                "confidence": 0.94,
            }

        if self._matches_any_variant(variants, ("co gi", "bao nhieu", "trang thai", "nhin thay")):
            return {
                "intent": "scene_query",
                "mode": "visual_assistant",
                "target_query": None,
                "answer": "",
                "status_text": "Đã chuyển sang hỗ trợ hình ảnh.",
                "confidence": 0.72,
            }

        return {
            "intent": "transcript_only",
            "mode": None,
            "target_query": None,
            "answer": "",
            "status_text": "",
            "confidence": 0.45,
        }

    def _is_standby_command(self, variants: set[str]) -> bool:
        explicit_phrases = (
            "ve che do cho",
            "quay ve che do cho",
            "tro ve che do cho",
            "chuyen ve che do cho",
            "che do cho",
            "standby",
            "stop",
            "dung lai",
            "dung tim",
            "ngung lai",
            "tat di",
            "huy tim",
            "thoat",
        )
        return any(phrase in value for value in variants for phrase in explicit_phrases)

    def _routing_variants(self, transcript_raw: str, transcript_norm: str) -> set[str]:
        variants = {transcript_norm}
        raw_norm = _norm_text(transcript_raw)
        if raw_norm:
            variants.add(raw_norm)
        replacements = (
            ("diem xe", "dem xe"),
            ("diem x e", "dem xe"),
            ("diem", "dem"),
            ("phuong tien", "phuong tien"),
            ("traffic cao", "traffic count"),
            ("traffic cao", "dem xe"),
            ("moniter", "scene monitor"),
            ("monitor", "scene monitor"),
            ("xe", "xe"),
        )
        for value in list(variants):
            for src, dst in replacements:
                if src in value:
                    variants.add(value.replace(src, dst))
        return {item.strip() for item in variants if item.strip()}

    def _matches_any_variant(self, variants: set[str], tokens: tuple[str, ...]) -> bool:
        return any(token in value for value in variants for token in tokens)

    def _is_scene_command(self, variants: set[str]) -> bool:
        return self._matches_any_variant(
            variants,
            (
                "scene monitor",
                "mo ta canh",
                "co gi truoc mat",
                "visual assistant",
                "quan sat",
                "xem canh",
                "nhin canh",
            ),
        )

    def _is_traffic_command(self, variants: set[str]) -> bool:
        if self._matches_any_variant(
            variants,
            (
                "traffic count",
                "traffic",
                "dem xe",
                "dem phuong tien",
                "phuong tien",
                "xe co",
                "traffic cao",
            ),
        ):
            return True
        return any(("xe" in value and ("dem" in value or "phuong tien" in value)) for value in variants)

    def _extract_target_query(self, transcript_raw: str, transcript_norm: str) -> str | None:
        def is_specific(query: str) -> bool:
            norm = _norm_text(query)
            tokens = [token for token in norm.split(" ") if token]
            if not tokens:
                return False
            generic_tokens = {
                "ai",
                "ban",
                "be",
                "chi",
                "co",
                "cu",
                "em",
                "nguoi",
                "ong",
                "person",
            }
            if tokens[0] in generic_tokens:
                return len(tokens) >= 3
            if len(tokens) == 1:
                return len(tokens[0]) > 2 and tokens[0] not in generic_tokens
            return True

        patterns = [
            r"\btim\s+(.+)$",
            r"\btheo doi\s+(.+)$",
            r"\bmo ta\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, transcript_norm)
            if match:
                raw = match.group(1).strip(" .,!?:;")
                if raw and is_specific(raw):
                    return raw
        if "tìm" in transcript_raw.lower():
            suffix = transcript_raw.lower().split("tìm", 1)[1].strip(" .,!?:;")
            return suffix if suffix and is_specific(suffix) else None
        if "theo dõi" in transcript_raw.lower():
            suffix = transcript_raw.lower().split("theo dõi", 1)[1].strip(" .,!?:;")
            return suffix if suffix and is_specific(suffix) else None
        return None

    def _dispatch_action(self, action: dict[str, Any]) -> None:
        command = VoiceCommand(
            timestamp_ms=int(action["timestampMs"]),
            session_id=str(action["sessionId"]),
            transcript=str(action["transcript"]),
            source=str(action["source"]),
            intent=str(action["intent"]),
            mode=str(action["mode"]) if action.get("mode") else None,
            target_query=str(action["targetQuery"]) if action.get("targetQuery") else None,
            answer=str(action["answer"]),
            status_text=str(action.get("statusText") or ""),
            scene_summary=str(action["sceneSummary"]),
            confidence=float(action.get("confidence") or 0.0),
        )
        with self.state_lock:
            self.recent_commands.append(command)
            if len(self.recent_commands) > 120:
                self.recent_commands = self.recent_commands[-120:]
        self.log_handler(
            command.session_id,
            "voice_command",
            {
                "transcript": command.transcript,
                "intent": command.intent,
                "mode": command.mode,
                "targetQuery": command.target_query,
                "answer": command.answer,
                "statusText": command.status_text,
                "confidence": command.confidence,
                "source": command.source,
            },
        )
        self.command_handler(asdict(command))
