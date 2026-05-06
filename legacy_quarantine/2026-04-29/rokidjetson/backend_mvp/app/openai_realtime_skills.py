from __future__ import annotations

import audioop
import base64
import json
import re
import threading
import time
import urllib.parse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable

import websocket


def _now_ms() -> int:
    return int(time.time() * 1000)


DEFAULT_REALTIME_SKILL_INSTRUCTIONS = (
    "You are the voice command layer for Rokid smart glasses running with Jetson skills. "
    "You are not a general chat assistant. Never greet first. Never offer help. Never apologize. "
    "Never switch to English or any non-Vietnamese language. Never add commentary after a successful tool call. "
    "The user speaks Vietnamese naturally. Prefer calling one of the provided tools when the user asks "
    "Jetson to do something. Use search_target for concrete people or object descriptions. That tool can first "
    "narrow local YOLO26 candidates, then use deeper visual reasoning only when needed. Use query_scene for scene "
    "understanding requests. Use set_jetson_mode only for explicit mode switches. Never call set_jetson_mode with "
    "standby unless the user clearly says to stop, return to standby, or go back to waiting. Use analyze_selected_target when the "
    "user asks a follow-up question about the currently selected person or object, such as glasses, clothing, "
    "gender presentation, or carried items. Use "
    "clear_target_search when the user asks to stop finding something. If audio is too unclear, do nothing and "
    "avoid guessing. Prefer tool calls over free-form replies. If no tool is needed and the speech is unclear, return no message. "
    "After a successful tool call, do not add extra text unless a short clarification question is truly needed. Do not chat casually. Do not explain tool schemas. "
    "Keep all behavior grounded in the provided tools."
)

DEFAULT_HANDLED_CALL_CACHE_SIZE = 512
DEFAULT_SEND_QUEUE_MAX_ITEMS = 512
DEFAULT_SEND_DRAIN_LIMIT = 64

_VIETNAMESE_MESSAGE_HINTS = (
    "ao",
    "áo",
    "canh",
    "cảnh",
    "che do",
    "chế độ",
    "dang",
    "đang",
    "da",
    "đã",
    "doi tuong",
    "đối tượng",
    "nguoi",
    "người",
    "nhin",
    "nhìn",
    "phia",
    "phía",
    "tim",
    "tìm",
    "xe",
)

_BLOCKED_MESSAGE_PHRASES = (
    "xin chào",
    "tôi có thể hỗ trợ",
    "bạn cần gì thêm",
    "hãy cho tôi biết",
    "sẵn sàng hỗ trợ",
    "giúp gì cho bạn",
    "hôm nay",
    "chưa nghe rõ",
    "có thể nói lại",
    "please clarify",
    "please repeat",
    "speak clearly",
    "sorry",
    "i am only able",
    "i have switched",
    "explain rõ hơn",
    "中国",
)


def remember_handled_call_id(
    handled_ids: set[str],
    handled_order: deque[str],
    call_id: str,
    *,
    max_size: int = DEFAULT_HANDLED_CALL_CACHE_SIZE,
) -> bool:
    normalized = str(call_id or "").strip()
    if not normalized or normalized in handled_ids:
        return False
    handled_ids.add(normalized)
    handled_order.append(normalized)
    trim_target = max(1, int(max_size))
    while len(handled_order) > trim_target:
        evicted = handled_order.popleft()
        handled_ids.discard(evicted)
    return True


def should_surface_realtime_skill_message(text: str, *, had_tool_call: bool) -> bool:
    normalized = str(text or "").strip()
    if not normalized or had_tool_call:
        return False
    lowered = normalized.casefold()
    if any(phrase in lowered for phrase in _BLOCKED_MESSAGE_PHRASES):
        return False
    if re.fullmatch(r"[\d\s.,:%+-]+", normalized):
        return False
    has_hint = any(hint in lowered for hint in _VIETNAMESE_MESSAGE_HINTS)
    if re.fullmatch(r"[A-Z0-9_. -]{2,}", normalized) and not has_hint:
        return False
    if len(normalized) <= 5 and not has_hint:
        return False
    if not has_hint:
        return False
    return len(normalized) <= 140


@dataclass(frozen=True)
class QueuedRealtimeEvent:
    payload: str
    phase: str
    is_audio: bool
    byte_count: int = 0


class RealtimeSkillSendQueue:
    """Single-writer queue for Realtime WebSocket events.

    Audio is disposable when the socket falls behind; control events are not.
    Keeping two FIFO lanes lets function outputs and response requests jump
    ahead of stale audio without reversing control-event order.
    """

    def __init__(self, max_items: int = DEFAULT_SEND_QUEUE_MAX_ITEMS) -> None:
        self.max_items = max(8, int(max_items))
        self._lock = threading.Lock()
        self._control: deque[QueuedRealtimeEvent] = deque()
        self._audio: deque[QueuedRealtimeEvent] = deque()
        self.dropped_audio = 0
        self.dropped_control = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._control) + len(self._audio)

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
        event = QueuedRealtimeEvent(
            payload=payload,
            phase=phase,
            is_audio=is_audio,
            byte_count=max(0, int(byte_count)),
        )
        with self._lock:
            total = len(self._control) + len(self._audio)
            if total >= self.max_items:
                if self._audio:
                    self._audio.popleft()
                    self.dropped_audio += 1
                    dropped_audio += 1
                elif is_audio:
                    self.dropped_audio += 1
                    dropped_audio += 1
                    return False, {
                        "droppedAudio": dropped_audio,
                        "droppedControl": dropped_control,
                        "queuedAudio": len(self._audio),
                        "queuedControl": len(self._control),
                    }
                else:
                    self._control.popleft()
                    self.dropped_control += 1
                    dropped_control += 1
            if is_audio:
                self._audio.append(event)
            else:
                self._control.append(event)
            return True, {
                "droppedAudio": dropped_audio,
                "droppedControl": dropped_control,
                "queuedAudio": len(self._audio),
                "queuedControl": len(self._control),
            }

    def pop_many(self, limit: int) -> list[QueuedRealtimeEvent]:
        events: list[QueuedRealtimeEvent] = []
        remaining = max(1, int(limit))
        with self._lock:
            while self._control and remaining > 0:
                events.append(self._control.popleft())
                remaining -= 1
            while self._audio and remaining > 0:
                events.append(self._audio.popleft())
                remaining -= 1
        return events

    def clear(self) -> None:
        with self._lock:
            self._control.clear()
            self._audio.clear()

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "queuedAudio": len(self._audio),
                "queuedControl": len(self._control),
                "droppedAudio": self.dropped_audio,
                "droppedControl": self.dropped_control,
            }


class OpenAIRealtimeSkillClient:
    def __init__(
        self,
        *,
        session_id: str,
        config_provider: Callable[[], dict[str, Any]],
        log_handler: Callable[[str, str, dict[str, Any]], None],
        status_handler: Callable[[str, dict[str, Any]], None],
        tool_schemas_provider: Callable[[], list[dict[str, Any]]],
        tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]],
    ) -> None:
        self.session_id = session_id
        self._config_provider = config_provider
        self._log_handler = log_handler
        self._status_handler = status_handler
        self._tool_schemas_provider = tool_schemas_provider
        self._tool_executor = tool_executor
        self._shutdown = threading.Event()
        self._connected = threading.Event()
        self._ready = threading.Event()
        self._socket_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._socket: websocket.WebSocket | None = None
        self._resample_state: Any = None
        self._ready_generation = 0
        self._connection_generation = 0
        self._last_response_request_ms = 0
        self._response_in_flight = False
        self._suppress_next_response_message = False
        self._last_send_phase = ""
        self._last_recv_event_type = ""
        self._last_queue_drop_log_ms = 0
        self._last_audio_send_log_ms = 0
        self._audio_events_enqueued = 0
        self._audio_events_sent = 0
        self._audio_bytes_enqueued = 0
        self._audio_bytes_sent = 0
        self._handled_call_ids: set[str] = set()
        self._handled_call_order: deque[str] = deque()
        self._send_queue = RealtimeSkillSendQueue(DEFAULT_SEND_QUEUE_MAX_ITEMS)
        self._tool_pool = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix=f"rokid-skill-tool-{session_id[:8]}",
        )
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"rokid-openai-skill-{session_id[:8]}",
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
        return self._enqueue_event(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm).decode("ascii"),
            },
            phase="input_audio_buffer.append",
            is_audio=True,
            byte_count=len(pcm),
        )

    def close(self, reason: str) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        self._close_socket()
        self._thread.join(timeout=2.0)
        self._tool_pool.shutdown(wait=False, cancel_futures=True)
        self._log_handler(
            self.session_id,
            "voice_realtime_skill_closed",
            {"reason": reason, "source": "openai_realtime_skills"},
        )

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
                    self._ws_url(config),
                    header=[f"Authorization: Bearer {api_key}"],
                    timeout=5,
                    enable_multithread=True,
                )
                ws.settimeout(0.05)
                with self._state_lock:
                    self._connection_generation += 1
                    connection_generation = self._connection_generation
                    self._response_in_flight = False
                    self._suppress_next_response_message = False
                    self._last_send_phase = ""
                    self._last_recv_event_type = ""
                with self._socket_lock:
                    self._socket = ws
                self._send_queue.clear()
                self._connected.set()
                self._log_handler(
                    self.session_id,
                    "voice_realtime_skill_connected",
                    {
                        "url": self._ws_url(config),
                        "model": str(config.get("openaiRealtimeVoiceModel") or "gpt-realtime-1.5"),
                        "generation": connection_generation,
                    },
                )
                self._send_session_update(ws, config)
                retry_backoff_s = 1.0
                last_ping_ms = _now_ms()
                try:
                    ping_interval_ms = max(3000, int(config.get("realtimeSkillPingMs") or 8000))
                except Exception:
                    ping_interval_ms = 8000
                while not self._shutdown.is_set():
                    self._drain_send_queue(ws, connection_generation)
                    now_ms = _now_ms()
                    if now_ms - last_ping_ms >= ping_interval_ms:
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
                    self._last_recv_event_type = str(payload.get("type") or "")
                    self._handle_server_event(payload)
            except Exception as error:
                if not self._shutdown.is_set():
                    self._mark_connection_unready()
                    socket_debug = self._socket_debug(ws)
                    self._log_handler(
                        self.session_id,
                        "voice_realtime_skill_error",
                        {
                            "error": str(error),
                            "errorType": type(error).__name__,
                            "source": "openai_realtime_skills",
                            "lastSendPhase": self._last_send_phase,
                            "lastRecvEventType": self._last_recv_event_type,
                            "audioEventsEnqueued": self._audio_events_enqueued,
                            "audioEventsSent": self._audio_events_sent,
                            "audioBytesEnqueued": self._audio_bytes_enqueued,
                            "audioBytesSent": self._audio_bytes_sent,
                            **socket_debug,
                            **self._send_queue.snapshot(),
                        },
                    )
                    self._status_handler(
                        self.session_id,
                        {
                            "stateLabel": "reconnecting",
                            "taskLabel": "voice agent",
                            "transcriptHint": None,
                            "source": "openai_realtime_skills",
                        },
                    )
                    if self._shutdown.wait(retry_backoff_s):
                        return
                    retry_backoff_s = min(retry_backoff_s * 1.5, 10.0)
            finally:
                self._mark_connection_unready()
                self._close_socket()

    def _close_socket(self) -> None:
        with self._socket_lock:
            ws = self._socket
            self._socket = None
        if ws is None:
            return
        with suppress(Exception):
            ws.close()

    def _mark_connection_unready(self) -> None:
        self._ready.clear()
        self._connected.clear()
        with self._state_lock:
            self._response_in_flight = False
            self._suppress_next_response_message = False

    def _socket_debug(self, ws: websocket.WebSocket | None) -> dict[str, Any]:
        if ws is None:
            return {"closeStatus": None, "socketConnected": False}
        status: Any = None
        with suppress(Exception):
            status = ws.getstatus()
        return {
            "closeStatus": status,
            "socketConnected": bool(getattr(ws, "connected", False)),
        }

    def _enqueue_event(
        self,
        event: dict[str, Any],
        *,
        phase: str,
        is_audio: bool,
        byte_count: int = 0,
    ) -> bool:
        if self._shutdown.is_set():
            return False
        try:
            payload = json.dumps(event, ensure_ascii=False)
        except Exception as error:
            self._log_handler(
                self.session_id,
                "voice_realtime_skill_error",
                {"error": str(error), "phase": f"{phase}:serialize", "source": "openai_realtime_skills"},
            )
            return False
        queued, stats = self._send_queue.enqueue(
            payload,
            phase=phase,
            is_audio=is_audio,
            byte_count=byte_count,
        )
        if queued and is_audio:
            with self._state_lock:
                self._audio_events_enqueued += 1
                self._audio_bytes_enqueued += max(0, int(byte_count))
        if stats.get("droppedAudio") or stats.get("droppedControl") or not queued:
            now_ms = _now_ms()
            if now_ms - self._last_queue_drop_log_ms >= 1000:
                self._last_queue_drop_log_ms = now_ms
                self._log_handler(
                    self.session_id,
                    "voice_realtime_skill_send_queue_drop",
                    {
                        "phase": phase,
                        "queued": queued,
                        "source": "openai_realtime_skills",
                        **stats,
                    },
                )
        return queued

    def _drain_send_queue(self, ws: websocket.WebSocket, connection_generation: int) -> None:
        with self._state_lock:
            if connection_generation != self._connection_generation:
                return
        for item in self._send_queue.pop_many(DEFAULT_SEND_DRAIN_LIMIT):
            if self._shutdown.is_set():
                return
            with self._state_lock:
                if connection_generation != self._connection_generation:
                    return
                self._last_send_phase = item.phase
            ws.send(item.payload)
            if item.is_audio:
                should_log = False
                with self._state_lock:
                    self._audio_events_sent += 1
                    self._audio_bytes_sent += item.byte_count
                    now_ms = _now_ms()
                    if now_ms - self._last_audio_send_log_ms >= 3000:
                        self._last_audio_send_log_ms = now_ms
                        should_log = True
                        audio_stats = {
                            "generation": connection_generation,
                            "eventsEnqueued": self._audio_events_enqueued,
                            "eventsSent": self._audio_events_sent,
                            "bytesEnqueued": self._audio_bytes_enqueued,
                            "bytesSent": self._audio_bytes_sent,
                        }
                if should_log:
                    self._log_handler(
                        self.session_id,
                        "voice_realtime_skill_audio_stream",
                        {
                            "source": "openai_realtime_skills",
                            **audio_stats,
                            **self._send_queue.snapshot(),
                        },
                    )

    def _send_session_update(self, ws: websocket.WebSocket, config: dict[str, Any]) -> None:
        instructions = str(config.get("openaiRealtimeSkillInstructions") or DEFAULT_REALTIME_SKILL_INSTRUCTIONS).strip()
        turn_detection_mode = str(config.get("realtimeSkillTurnDetection") or "semantic_vad").strip() or "semantic_vad"
        session: dict[str, Any] = {
            "type": "realtime",
            "model": str(config.get("openaiRealtimeVoiceModel") or "gpt-realtime-1.5").strip() or "gpt-realtime-1.5",
            "instructions": instructions,
            "output_modalities": ["text"],
            "tools": self._tool_schemas_provider(),
            "tool_choice": "auto",
            "audio": {
                "input": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": 24000,
                    }
                }
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
            session["audio"]["input"]["turn_detection"] = {
                "type": "semantic_vad",
                "eagerness": str(config.get("realtimeSkillSemanticEagerness") or "medium").strip() or "medium",
                "create_response": False,
                "interrupt_response": False,
            }
        noise_reduction = str(config.get("realtimeNoiseReduction") or "").strip()
        if noise_reduction:
            session["audio"]["input"]["noise_reduction"] = {"type": noise_reduction}
        ws.send(json.dumps({"type": "session.update", "session": session}))

    def _request_response(self, *, reason: str, suppress_message: bool = False) -> bool:
        if not self._ready.is_set() or self._shutdown.is_set():
            return False
        with self._state_lock:
            if self._response_in_flight:
                self._log_handler(
                    self.session_id,
                    "voice_realtime_skill_response_skipped",
                    {
                        "reason": reason,
                        "skipReason": "response_in_flight",
                        "source": "openai_realtime_skills",
                    },
                )
                return False
            self._response_in_flight = True
            if suppress_message:
                self._suppress_next_response_message = True
        queued = self._enqueue_event({"type": "response.create"}, phase=f"response.create:{reason}", is_audio=False)
        if queued:
            self._last_response_request_ms = _now_ms()
            self._log_handler(
                self.session_id,
                "voice_realtime_skill_response_create",
                {
                    "reason": reason,
                    "suppressMessage": suppress_message,
                    "source": "openai_realtime_skills",
                },
            )
            return True
        with self._state_lock:
            self._response_in_flight = False
            if suppress_message:
                self._suppress_next_response_message = False
        return False

    def _handle_server_event(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type") or "")
        if event_type == "session.created":
            self._log_handler(self.session_id, "voice_realtime_skill_session_created", {})
            return
        if event_type == "session.updated":
            self._handled_call_ids.clear()
            self._handled_call_order.clear()
            self._ready_generation += 1
            self._ready.set()
            self._status_handler(
                self.session_id,
                {
                    "stateLabel": "listening",
                    "taskLabel": "voice agent",
                    "transcriptHint": None,
                    "source": "openai_realtime_skills",
                },
            )
            self._log_handler(self.session_id, "voice_realtime_skill_session_updated", {})
            return
        if event_type == "input_audio_buffer.speech_started":
            self._status_handler(
                self.session_id,
                {
                    "stateLabel": "capturing",
                    "taskLabel": "voice agent",
                    "transcriptHint": None,
                    "source": "openai_realtime_skills",
                },
            )
            self._log_handler(self.session_id, "voice_realtime_skill_speech_started", {})
            return
        if event_type == "input_audio_buffer.speech_stopped":
            self._status_handler(
                self.session_id,
                {
                    "stateLabel": "thinking",
                    "taskLabel": "voice agent",
                    "transcriptHint": None,
                    "source": "openai_realtime_skills",
                },
            )
            config = self._config_provider()
            try:
                response_debounce_ms = max(250, int(config.get("realtimeSkillResponseDebounceMs") or 700))
            except Exception:
                response_debounce_ms = 700
            if _now_ms() - self._last_response_request_ms >= response_debounce_ms:
                self._request_response(reason="speech_stopped")
            self._log_handler(
                self.session_id,
                "voice_realtime_skill_speech_stopped",
                {"responseDebounceMs": response_debounce_ms},
            )
            return
        if event_type == "response.function_call_arguments.delta":
            self._log_handler(
                self.session_id,
                "voice_realtime_skill_args_delta",
                {
                    "callId": payload.get("call_id"),
                    "name": payload.get("name"),
                },
            )
            return
        if event_type == "response.done":
            self._handle_response_done(payload)
            return
        if event_type == "error":
            error_payload = payload.get("error") if isinstance(payload.get("error"), dict) else payload
            self._log_handler(
                self.session_id,
                "voice_realtime_skill_error",
                {
                    "error": error_payload.get("message") if isinstance(error_payload, dict) else payload,
                    "errorCode": error_payload.get("code") if isinstance(error_payload, dict) else None,
                    "errorType": error_payload.get("type") if isinstance(error_payload, dict) else None,
                    "source": "openai_realtime_skills",
                },
            )

    def _handle_response_done(self, payload: dict[str, Any]) -> None:
        with self._state_lock:
            suppress_this_response = self._suppress_next_response_message
            self._suppress_next_response_message = False
            self._response_in_flight = False
        response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
        outputs = response.get("output") if isinstance(response.get("output"), list) else []
        output_types = [
            str(item.get("type") or "")
            for item in outputs
            if isinstance(item, dict)
        ]
        self._log_handler(
            self.session_id,
            "voice_realtime_skill_response_done",
            {
                "status": response.get("status"),
                "outputTypes": output_types,
                "suppressMessage": suppress_this_response,
                "source": "openai_realtime_skills",
            },
        )
        if not outputs:
            self._status_handler(
                self.session_id,
                {
                    "stateLabel": "listening",
                    "taskLabel": "voice agent",
                    "transcriptHint": None,
                    "source": "openai_realtime_skills",
                },
            )
            return
        handled_function_call = False
        for item in outputs:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type == "function_call":
                handled_function_call = True
                self._handle_function_call(item)
                continue
            if item_type == "message":
                text = self._extract_message_text(item)
                if (
                    text
                    and not suppress_this_response
                    and self._should_surface_message(text, had_tool_call=handled_function_call)
                ):
                    self._log_handler(
                        self.session_id,
                        "voice_realtime_skill_message",
                        {"text": text, "source": "openai_realtime_skills"},
                    )
                    self._status_handler(
                        self.session_id,
                        {
                            "stateLabel": "heard",
                            "taskLabel": "voice agent",
                            "transcriptHint": text,
                            "source": "openai_realtime_skills",
                        },
                    )
                elif text:
                    self._log_handler(
                        self.session_id,
                        "voice_realtime_skill_message_suppressed",
                        {
                            "text": text,
                            "reason": "tool_followup" if suppress_this_response else "message_policy",
                            "source": "openai_realtime_skills",
                        },
                    )
        self._status_handler(
            self.session_id,
            {
                "stateLabel": "listening",
                "taskLabel": "voice agent",
                "transcriptHint": None,
                "source": "openai_realtime_skills",
            },
        )

    def _handle_function_call(self, item: dict[str, Any]) -> None:
        call_id = str(item.get("call_id") or "").strip()
        if not remember_handled_call_id(self._handled_call_ids, self._handled_call_order, call_id):
            return
        name = str(item.get("name") or "").strip()
        raw_arguments = str(item.get("arguments") or "").strip()
        try:
            arguments = json.loads(raw_arguments) if raw_arguments else {}
        except Exception:
            arguments = {}
        self._log_handler(
            self.session_id,
            "voice_realtime_skill_call",
            {
                "callId": call_id,
                "tool": name,
                "arguments": arguments,
                "source": "openai_realtime_skills",
            },
        )
        with self._state_lock:
            connection_generation = self._connection_generation
        try:
            self._tool_pool.submit(
                self._execute_tool_call,
                connection_generation,
                call_id,
                name,
                arguments,
            )
        except RuntimeError as error:
            self._log_handler(
                self.session_id,
                "voice_realtime_skill_error",
                {
                    "error": str(error),
                    "phase": "tool_submit",
                    "tool": name,
                    "callId": call_id,
                    "source": "openai_realtime_skills",
                },
            )

    def _execute_tool_call(
        self,
        connection_generation: int,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        started_ms = _now_ms()
        try:
            output = self._tool_executor(tool_name, arguments)
            if not isinstance(output, dict):
                output = {"ok": True, "result": output}
        except Exception as error:
            output = {"ok": False, "error": str(error)}
            self._log_handler(
                self.session_id,
                "voice_realtime_skill_tool_error",
                {
                    "callId": call_id,
                    "tool": tool_name,
                    "error": str(error),
                    "source": "openai_realtime_skills",
                },
            )
        with self._state_lock:
            current_generation = self._connection_generation
        if self._shutdown.is_set() or current_generation != connection_generation:
            self._log_handler(
                self.session_id,
                "voice_realtime_skill_tool_output_dropped",
                {
                    "callId": call_id,
                    "tool": tool_name,
                    "reason": "connection_generation_changed",
                    "callGeneration": connection_generation,
                    "currentGeneration": current_generation,
                    "latencyMs": _now_ms() - started_ms,
                    "source": "openai_realtime_skills",
                },
            )
            return
        self._send_function_output(
            call_id=call_id,
            tool_name=tool_name,
            output=output,
            latency_ms=_now_ms() - started_ms,
        )

    def _send_function_output(
        self,
        *,
        call_id: str,
        tool_name: str,
        output: dict[str, Any],
        latency_ms: int,
    ) -> None:
        self._log_handler(
            self.session_id,
            "voice_realtime_skill_tool_output",
            {
                "callId": call_id,
                "tool": tool_name,
                "output": output,
                "latencyMs": latency_ms,
                "source": "openai_realtime_skills",
            },
        )
        queued = self._enqueue_event(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(output, ensure_ascii=False),
                },
            },
            phase="conversation.item.create:function_call_output",
            is_audio=False,
        )
        if not queued:
            self._log_handler(
                self.session_id,
                "voice_realtime_skill_tool_output_dropped",
                {
                    "callId": call_id,
                    "tool": tool_name,
                    "reason": "send_queue_rejected",
                    "source": "openai_realtime_skills",
                },
            )
            return
        config = self._config_provider()
        complete_tool_turn = bool(config.get("realtimeSkillCompleteToolTurn", True))
        if complete_tool_turn:
            self._request_response(
                reason="tool_output",
                suppress_message=not bool(config.get("realtimeSkillRespondAfterTool", False)),
            )

    def _extract_message_text(self, item: dict[str, Any]) -> str:
        pieces: list[str] = []
        for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
            if not isinstance(content, dict):
                continue
            text = str(content.get("text") or content.get("transcript") or "").strip()
            if text:
                pieces.append(text)
        return " ".join(piece for piece in pieces if piece).strip()

    def _should_surface_message(self, text: str, *, had_tool_call: bool) -> bool:
        return should_surface_realtime_skill_message(text, had_tool_call=had_tool_call)

    def _ws_url(self, config: dict[str, Any]) -> str:
        explicit = str(config.get("openaiRealtimeWsUrl") or "").strip()
        if explicit:
            parsed = urllib.parse.urlparse(explicit)
            if urllib.parse.parse_qs(parsed.query).get("model"):
                return explicit
            model = urllib.parse.quote(str(config.get("openaiRealtimeVoiceModel") or "gpt-realtime-1.5").strip())
            separator = "&" if parsed.query else "?"
            return f"{explicit}{separator}model={model}"
        base_url = str(config.get("openaiBaseUrl") or "https://api.openai.com/v1").strip()
        parsed = urllib.parse.urlparse(base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = parsed.path.rstrip("/")
        if not path:
            path = "/v1"
        query = urllib.parse.urlencode(
            {"model": str(config.get("openaiRealtimeVoiceModel") or "gpt-realtime-1.5").strip()}
        )
        return urllib.parse.urlunparse((scheme, parsed.netloc, f"{path}/realtime", "", query, ""))

    def _resample_to_24khz(self, payload: bytes) -> bytes:
        if not payload:
            return b""
        converted, self._resample_state = audioop.ratecv(payload, 2, 1, 16000, 24000, self._resample_state)
        return converted
