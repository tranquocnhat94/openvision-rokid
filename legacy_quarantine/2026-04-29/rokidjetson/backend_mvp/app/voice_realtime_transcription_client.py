from __future__ import annotations

import audioop
import base64
import json
import threading
import time
import urllib.parse
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable

import websocket


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True)
class RealtimeCommitState:
    item_id: str
    commit_index: int
    committed_ms: int
    previous_item_id: str | None = None


@dataclass(frozen=True, slots=True)
class QueuedTranscriptionEvent:
    payload: str
    phase: str
    is_audio: bool
    byte_count: int = 0


class RealtimeTranscriptionSendQueue:
    """FIFO single-writer queue for transcription events."""

    def __init__(self, max_items: int = 512) -> None:
        self.max_items = max(8, int(max_items))
        self._lock = threading.Lock()
        self._items: deque[QueuedTranscriptionEvent] = deque()
        self.dropped_audio = 0
        self.dropped_control = 0

    def enqueue(
        self,
        payload: str,
        *,
        phase: str,
        is_audio: bool,
        byte_count: int = 0,
    ) -> tuple[bool, dict[str, int]]:
        dropped_audio = 0
        dropped_control = 0
        event = QueuedTranscriptionEvent(
            payload=payload,
            phase=phase,
            is_audio=is_audio,
            byte_count=max(0, int(byte_count)),
        )
        with self._lock:
            if len(self._items) >= self.max_items:
                drop_index = None
                if is_audio and any(not queued.is_audio for queued in self._items):
                    self.dropped_audio += 1
                    dropped_audio += 1
                    return False, self._snapshot_unlocked(
                        dropped_audio=dropped_audio,
                        dropped_control=dropped_control,
                    )
                drop_index = next(
                    (index for index, queued in enumerate(self._items) if queued.is_audio),
                    None,
                )
                if drop_index is not None:
                    del self._items[drop_index]
                    self.dropped_audio += 1
                    dropped_audio += 1
                elif is_audio:
                    self.dropped_audio += 1
                    dropped_audio += 1
                    return False, self._snapshot_unlocked(
                        dropped_audio=dropped_audio,
                        dropped_control=dropped_control,
                    )
                else:
                    self._items.popleft()
                    self.dropped_control += 1
                    dropped_control += 1
            self._items.append(event)
            return True, self._snapshot_unlocked(
                dropped_audio=dropped_audio,
                dropped_control=dropped_control,
            )

    def pop_many(self, limit: int) -> list[QueuedTranscriptionEvent]:
        events: list[QueuedTranscriptionEvent] = []
        remaining = max(1, int(limit))
        with self._lock:
            while self._items and remaining > 0:
                events.append(self._items.popleft())
                remaining -= 1
        return events

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return self._snapshot_unlocked(dropped_audio=0, dropped_control=0)

    def _snapshot_unlocked(self, *, dropped_audio: int, dropped_control: int) -> dict[str, int]:
        return {
            "queued": len(self._items),
            "droppedAudio": dropped_audio,
            "droppedControl": dropped_control,
            "totalDroppedAudio": self.dropped_audio,
            "totalDroppedControl": self.dropped_control,
        }


def build_realtime_ws_url(config: dict[str, Any]) -> str:
    explicit = str(config.get("openaiRealtimeWsUrl") or "").strip()
    if explicit:
        return explicit
    base_url = str(config.get("openaiBaseUrl") or "https://api.openai.com/v1").strip()
    parsed = urllib.parse.urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1"
    query = urllib.parse.urlencode({"intent": "transcription"})
    return urllib.parse.urlunparse((scheme, parsed.netloc, f"{path}/realtime", "", query, ""))


def build_realtime_session_update_event(
    *,
    config: dict[str, Any],
    turn_detection_mode: str,
    model_config_key: str,
    prompt_config_key: str,
) -> dict[str, Any]:
    transcription: dict[str, Any] = {
        "model": str(
            config.get(model_config_key)
            or config.get("transcriptionModel")
            or "gpt-4o-mini-transcribe"
        ).strip(),
        "language": str(config.get("languageHint") or "vi").strip() or "vi",
    }
    prompt = str(
        config.get(prompt_config_key)
        or config.get("openaiTranscriptionPrompt")
        or ""
    ).strip()
    if prompt:
        transcription["prompt"] = prompt
    session: dict[str, Any] = {
        "type": "transcription",
        "audio": {
            "input": {
                "format": {
                    "type": "audio/pcm",
                    "rate": 24000,
                },
                "transcription": transcription,
            },
        },
    }
    if turn_detection_mode == "server_vad":
        session["audio"]["input"]["turn_detection"] = {
            "type": "server_vad",
            "threshold": float(config.get("realtimeVadThreshold") or 0.5),
            "prefix_padding_ms": int(config.get("realtimeVadPrefixPaddingMs") or 300),
            "silence_duration_ms": int(config.get("realtimeVadSilenceDurationMs") or 500),
            "create_response": False,
            "interrupt_response": False,
        }
    else:
        session["audio"]["input"]["turn_detection"] = None
    noise_reduction = str(config.get("realtimeNoiseReduction") or "").strip()
    if noise_reduction:
        session["audio"]["input"]["noise_reduction"] = {"type": noise_reduction}
    event: dict[str, Any] = {
        "type": "session.update",
        "session": session,
    }
    if bool(config.get("realtimeIncludeLogprobs")):
        event["session"]["include"] = ["item.input_audio_transcription.logprobs"]
    return event


class OpenAIRealtimeTranscriptionClient:
    def __init__(
        self,
        *,
        session_id: str,
        config_provider: Callable[[], dict[str, Any]],
        log_handler: Callable[[str, str, dict[str, Any]], None],
        partial_handler: Callable[[str, str, dict[str, Any]], None],
        final_handler: Callable[[str, str, dict[str, Any]], None],
        status_handler: Callable[[str, dict[str, Any]], None],
        source_label: str = "openai_realtime",
        task_label: str = "voice live",
        turn_detection_mode: str = "server_vad",
        model_config_key: str = "transcriptionModel",
        prompt_config_key: str = "openaiTranscriptionPrompt",
    ) -> None:
        self.session_id = session_id
        self._config_provider = config_provider
        self._log_handler = log_handler
        self._partial_handler = partial_handler
        self._final_handler = final_handler
        self._status_handler = status_handler
        self._source_label = source_label
        self._task_label = task_label
        self._turn_detection_mode = turn_detection_mode
        self._model_config_key = model_config_key
        self._prompt_config_key = prompt_config_key
        self._shutdown = threading.Event()
        self._connected = threading.Event()
        self._ready = threading.Event()
        self._socket_lock = threading.Lock()
        self._socket: websocket.WebSocket | None = None
        self._resample_state: Any = None
        self._partials_by_item: dict[str, str] = {}
        self._pending_completed_by_item: dict[str, str] = {}
        self._commits_by_item: dict[str, RealtimeCommitState] = {}
        self._completed_by_index: dict[int, tuple[str, str]] = {}
        self._send_queue = RealtimeTranscriptionSendQueue()
        self._next_commit_index = 0
        self._next_emit_index = 0
        self._last_partial_emit_ms = 0
        self._last_send_phase = ""
        self._last_recv_event_type = ""
        self._last_queue_drop_log_ms = 0
        self._sent_audio_events = 0
        self._sent_audio_bytes = 0
        self._ready_generation = 0
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"rokid-openai-realtime-{session_id[:8]}",
        )
        self._thread.start()

    def is_ready(self) -> bool:
        return self._ready.is_set()

    def ready_generation(self) -> int:
        return self._ready_generation

    def append_pcm(self, payload: bytes) -> bool:
        if not payload or not self._ready.is_set() or self._shutdown.is_set():
            return False
        pcm = self._resample_to_24khz(payload)
        if not pcm:
            return True
        event = {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm).decode("ascii"),
        }
        accepted, stats = self._send_queue.enqueue(
            json.dumps(event),
            phase="input_audio_buffer.append",
            is_audio=True,
            byte_count=len(pcm),
        )
        self._maybe_log_queue_drop(stats)
        return accepted

    def commit_audio(self) -> bool:
        if not self._ready.is_set() or self._shutdown.is_set():
            return False
        accepted, stats = self._send_queue.enqueue(
            json.dumps({"type": "input_audio_buffer.commit"}),
            phase="input_audio_buffer.commit",
            is_audio=False,
        )
        self._maybe_log_queue_drop(stats)
        return accepted

    def clear_audio(self) -> bool:
        if not self._ready.is_set() or self._shutdown.is_set():
            return False
        accepted, stats = self._send_queue.enqueue(
            json.dumps({"type": "input_audio_buffer.clear"}),
            phase="input_audio_buffer.clear",
            is_audio=False,
        )
        self._maybe_log_queue_drop(stats)
        return accepted

    def close(self, reason: str) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        self._close_socket()
        self._thread.join(timeout=2.0)
        self._log_handler(
            self.session_id,
            "voice_realtime_closed",
            {"reason": reason, "source": self._source_label},
        )

    def _reset_transcript_state(self) -> None:
        self._partials_by_item.clear()
        self._pending_completed_by_item.clear()
        self._commits_by_item.clear()
        self._completed_by_index.clear()
        self._next_commit_index = 0
        self._next_emit_index = 0
        self._last_partial_emit_ms = 0

    def _run(self) -> None:
        retry_backoff_s = 1.0
        while not self._shutdown.is_set():
            config = self._config_provider()
            api_key = str(config.get("openaiApiKey") or "").strip()
            if not api_key:
                self._ready.clear()
                self._connected.clear()
                if self._shutdown.wait(1.0):
                    return
                continue

            ws: websocket.WebSocket | None = None
            try:
                ws = websocket.create_connection(
                    build_realtime_ws_url(config),
                    header=[f"Authorization: Bearer {api_key}"],
                    timeout=5,
                    enable_multithread=True,
                )
                ws.settimeout(0.25)
                with self._socket_lock:
                    self._socket = ws
                self._connected.set()
                self._log_handler(
                    self.session_id,
                    "voice_realtime_connected",
                    {"url": build_realtime_ws_url(config), "source": self._source_label},
                )
                self._send_session_update(ws, config)
                retry_backoff_s = 1.0
                last_ping_ms = _now_ms()

                while not self._shutdown.is_set():
                    now_ms = _now_ms()
                    self._drain_send_queue(ws)
                    if now_ms - last_ping_ms >= 15000:
                        self._last_send_phase = "ping"
                        ws.ping("keepalive")
                        last_ping_ms = now_ms
                    try:
                        message = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not message:
                        raise websocket.WebSocketConnectionClosedException("empty websocket message")
                    if isinstance(message, bytes):
                        message = message.decode("utf-8", errors="ignore")
                    payload = json.loads(message)
                    self._handle_server_event(payload)
            except Exception as error:
                if not self._shutdown.is_set():
                    self._ready.clear()
                    self._connected.clear()
                    self._log_handler(
                        self.session_id,
                        "voice_realtime_error",
                        {
                            "error": str(error),
                            "source": self._source_label,
                            "lastSendPhase": self._last_send_phase,
                            "lastRecvEventType": self._last_recv_event_type,
                            "sendQueue": self._send_queue.snapshot(),
                            "sentAudioEvents": self._sent_audio_events,
                            "sentAudioBytes": self._sent_audio_bytes,
                        },
                    )
                    self._status_handler(
                        self.session_id,
                        {
                            "stateLabel": "reconnecting",
                            "taskLabel": self._task_label,
                            "transcriptHint": None,
                            "source": self._source_label,
                        },
                    )
                    if self._shutdown.wait(retry_backoff_s):
                        break
                    retry_backoff_s = min(8.0, retry_backoff_s * 2.0)
            finally:
                self._ready.clear()
                self._connected.clear()
                if ws is not None:
                    with suppress(Exception):
                        ws.close()
                with self._socket_lock:
                    if self._socket is ws:
                        self._socket = None
                self._send_queue.clear()

    def _send_session_update(self, ws: websocket.WebSocket, config: dict[str, Any]) -> None:
        event = build_realtime_session_update_event(
            config=config,
            turn_detection_mode=self._turn_detection_mode,
            model_config_key=self._model_config_key,
            prompt_config_key=self._prompt_config_key,
        )
        self._last_send_phase = "session.update"
        ws.send(json.dumps(event))

    def _drain_send_queue(self, ws: websocket.WebSocket) -> None:
        for event in self._send_queue.pop_many(64):
            self._last_send_phase = event.phase
            ws.send(event.payload)
            if event.is_audio:
                self._sent_audio_events += 1
                self._sent_audio_bytes += event.byte_count

    def _maybe_log_queue_drop(self, stats: dict[str, int]) -> None:
        if not (stats.get("droppedAudio") or stats.get("droppedControl")):
            return
        now_ms = _now_ms()
        if now_ms - self._last_queue_drop_log_ms < 1000:
            return
        self._last_queue_drop_log_ms = now_ms
        self._log_handler(
            self.session_id,
            "voice_realtime_send_queue_drop",
            {"source": self._source_label, **stats},
        )

    def _handle_server_event(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type") or "")
        self._last_recv_event_type = event_type
        if event_type == "session.updated":
            self._reset_transcript_state()
            self._ready_generation += 1
            self._ready.set()
            self._status_handler(
                self.session_id,
                {
                    "stateLabel": "listening",
                    "taskLabel": self._task_label,
                    "transcriptHint": None,
                    "source": self._source_label,
                },
            )
            self._log_handler(
                self.session_id,
                "voice_realtime_session_updated",
                {"source": self._source_label},
            )
            return
        if event_type == "session.created":
            self._log_handler(
                self.session_id,
                "voice_realtime_session_created",
                {"source": self._source_label},
            )
            return
        if event_type == "input_audio_buffer.speech_started":
            self._status_handler(
                self.session_id,
                {
                    "stateLabel": "capturing",
                    "taskLabel": self._task_label,
                    "transcriptHint": None,
                    "source": self._source_label,
                },
            )
            self._log_handler(
                self.session_id,
                "voice_realtime_speech_started",
                {"source": self._source_label},
            )
            return
        if event_type == "input_audio_buffer.speech_stopped":
            self._status_handler(
                self.session_id,
                {
                    "stateLabel": "transcribing",
                    "taskLabel": self._task_label,
                    "transcriptHint": None,
                    "source": self._source_label,
                },
            )
            self._log_handler(
                self.session_id,
                "voice_realtime_speech_stopped",
                {"source": self._source_label},
            )
            return
        if event_type == "input_audio_buffer.committed":
            item_id = str(payload.get("item_id") or "").strip()
            if not item_id:
                return
            commit = RealtimeCommitState(
                item_id=item_id,
                commit_index=self._next_commit_index,
                committed_ms=_now_ms(),
                previous_item_id=str(payload.get("previous_item_id") or "").strip() or None,
            )
            self._next_commit_index += 1
            self._commits_by_item[item_id] = commit
            self._log_handler(
                self.session_id,
                "voice_realtime_committed",
                {
                    "itemId": item_id,
                    "commitIndex": commit.commit_index,
                    "previousItemId": commit.previous_item_id,
                    "source": self._source_label,
                },
            )
            pending = self._pending_completed_by_item.pop(item_id, "")
            if pending:
                self._completed_by_index[commit.commit_index] = (item_id, pending)
                self._drain_completed()
            return
        if event_type == "input_audio_buffer.cleared":
            self._partials_by_item.clear()
            self._pending_completed_by_item.clear()
            self._commits_by_item.clear()
            self._completed_by_index.clear()
            self._next_commit_index = 0
            self._next_emit_index = 0
            self._log_handler(
                self.session_id,
                "voice_realtime_buffer_cleared",
                {"source": self._source_label},
            )
            return
        if event_type == "conversation.item.input_audio_transcription.delta":
            item_id = str(payload.get("item_id") or "").strip()
            delta = str(payload.get("delta") or "")
            if not item_id or not delta:
                return
            next_partial = f"{self._partials_by_item.get(item_id, '')}{delta}"
            self._partials_by_item[item_id] = next_partial
            now_ms = _now_ms()
            debounce_ms = max(40, int(self._config_provider().get("realtimePartialDebounceMs") or 120))
            if now_ms - self._last_partial_emit_ms >= debounce_ms:
                self._last_partial_emit_ms = now_ms
                self._partial_handler(
                    self.session_id,
                    next_partial,
                    {
                        "itemId": item_id,
                        "source": self._source_label,
                    },
                )
            return
        if event_type == "conversation.item.input_audio_transcription.completed":
            item_id = str(payload.get("item_id") or "").strip()
            transcript = str(payload.get("transcript") or "").strip()
            if not item_id:
                return
            final_text = transcript or self._partials_by_item.get(item_id, "")
            self._partials_by_item.pop(item_id, None)
            commit = self._commits_by_item.get(item_id)
            if commit is None:
                self._pending_completed_by_item[item_id] = final_text
            else:
                self._completed_by_index[commit.commit_index] = (item_id, final_text)
                self._drain_completed()
            return
        if event_type == "error":
            self._log_handler(
                self.session_id,
                "voice_realtime_error",
                {"error": payload, "source": self._source_label},
            )

    def _drain_completed(self) -> None:
        while self._next_emit_index in self._completed_by_index:
            item_id, transcript = self._completed_by_index.pop(self._next_emit_index)
            commit = self._commits_by_item.pop(item_id, None)
            meta = {
                "itemId": item_id,
                "commitIndex": self._next_emit_index,
                "source": self._source_label,
                "transcribeMs": max(0, _now_ms() - commit.committed_ms) if commit is not None else 0,
                "committedMs": commit.committed_ms if commit is not None else 0,
            }
            self._final_handler(self.session_id, transcript, meta)
            self._next_emit_index += 1

    def _close_socket(self) -> None:
        with self._socket_lock:
            ws = self._socket
            self._socket = None
        if ws is not None:
            with suppress(Exception):
                ws.close()

    def _resample_to_24khz(self, payload: bytes) -> bytes:
        trimmed = payload[: len(payload) - (len(payload) % 2)]
        if not trimmed:
            return b""
        converted, self._resample_state = audioop.ratecv(
            trimmed,
            2,
            1,
            16000,
            24000,
            self._resample_state,
        )
        return converted
