#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import gc
import io
import json
import threading
import time
import wave
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import numpy as np
from faster_whisper import WhisperModel


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class WorkerStats:
    started_ms: int
    request_count: int = 0
    transcribe_count: int = 0
    model_load_count: int = 0
    ndarray_decode_count: int = 0
    binary_io_fallback_count: int = 0
    tempfile_fallback_count: int = 0
    last_request_ms: int = 0
    last_transcribe_ms: int = 0
    last_error: str = ""


class PhoWhisperWorker:
    def __init__(
        self,
        *,
        model_dir: Path,
        language: str,
        cpu_threads: int,
        compute_type: str,
        beam_size: int,
        vad_filter: bool,
        idle_unload_ms: int,
        hotwords: str,
    ) -> None:
        self.model_dir = model_dir
        self.language = language
        self.cpu_threads = cpu_threads
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.idle_unload_ms = max(0, idle_unload_ms)
        self.hotwords = hotwords.strip()
        self._model: WhisperModel | None = None
        self._model_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self.stats = WorkerStats(started_ms=_now_ms())
        self._reaper_stop = threading.Event()
        self._reaper = threading.Thread(target=self._reaper_loop, daemon=True, name="phowhisper-idle-reaper")
        self._reaper.start()

    def close(self) -> None:
        self._reaper_stop.set()
        self._reaper.join(timeout=1.0)
        self._unload_model()

    def mark_request(self) -> None:
        with self._stats_lock:
            self.stats.request_count += 1
            self.stats.last_request_ms = _now_ms()

    def health(self) -> dict[str, Any]:
        with self._stats_lock:
            stats = WorkerStats(**self.stats.__dict__)
        return {
            "ok": True,
            "backend": "phowhisper_http",
            "modelDir": str(self.model_dir),
            "modelLoaded": self._model is not None,
            "language": self.language,
            "cpuThreads": self.cpu_threads,
            "computeType": self.compute_type,
            "beamSize": self.beam_size,
            "vadFilter": self.vad_filter,
            "idleUnloadMs": self.idle_unload_ms,
            "hotwords": self.hotwords,
            "startedMs": stats.started_ms,
            "requestCount": stats.request_count,
            "transcribeCount": stats.transcribe_count,
            "modelLoadCount": stats.model_load_count,
            "ndarrayDecodeCount": stats.ndarray_decode_count,
            "binaryIoFallbackCount": stats.binary_io_fallback_count,
            "tempfileFallbackCount": stats.tempfile_fallback_count,
            "lastRequestMs": stats.last_request_ms,
            "lastTranscribeMs": stats.last_transcribe_ms,
            "lastError": stats.last_error,
        }

    def warm(self) -> dict[str, Any]:
        self.mark_request()
        self._ensure_model_loaded()
        return self.health()

    def unload(self) -> dict[str, Any]:
        self.mark_request()
        self._unload_model()
        return self.health()

    def transcribe(
        self,
        *,
        wav_bytes: bytes,
        language: str | None = None,
        session_id: str = "",
        profile: str = "",
        beam_size: int | None = None,
        vad_filter: bool | None = None,
        hotwords: str | None = None,
    ) -> dict[str, Any]:
        started_ms = _now_ms()
        model = self._ensure_model_loaded()
        transcript = ""
        effective_beam_size = max(1, int(beam_size or self.beam_size))
        effective_vad_filter = self.vad_filter if vad_filter is None else bool(vad_filter)
        effective_hotwords = (hotwords or self.hotwords or "").strip()
        try:
            segments, info, input_mode = self._transcribe_best_effort(
                model=model,
                wav_bytes=wav_bytes,
                language=(language or self.language or "vi").strip() or "vi",
                beam_size=effective_beam_size,
                vad_filter=effective_vad_filter,
                hotwords=effective_hotwords,
            )
            transcript = " ".join(segment.text.strip() for segment in segments if segment.text).strip()
            elapsed_ms = max(0, _now_ms() - started_ms)
            with self._stats_lock:
                self.stats.transcribe_count += 1
                self.stats.last_transcribe_ms = _now_ms()
                self.stats.last_error = ""
            return {
                "text": transcript,
                "backend": "phowhisper_http",
                "sessionId": session_id,
                "profile": profile,
                "language": getattr(info, "language", language or self.language),
                "languageProbability": getattr(info, "language_probability", None),
                "transcribeMs": elapsed_ms,
                "modelLoaded": True,
                "beamSize": effective_beam_size,
                "vadFilter": effective_vad_filter,
                "audioInputMode": input_mode,
                "hotwords": effective_hotwords,
            }
        except Exception as error:
            with self._stats_lock:
                self.stats.last_error = str(error)
            raise

    def _ensure_model_loaded(self) -> WhisperModel:
        with self._model_lock:
            if self._model is None:
                self._model = WhisperModel(
                    str(self.model_dir),
                    device="cpu",
                    compute_type=self.compute_type,
                    cpu_threads=self.cpu_threads,
                )
                with self._stats_lock:
                    self.stats.model_load_count += 1
                    self.stats.last_request_ms = _now_ms()
            return self._model

    def _unload_model(self) -> None:
        with self._model_lock:
            if self._model is None:
                return
            self._model = None
        gc.collect()

    def _reaper_loop(self) -> None:
        while not self._reaper_stop.wait(1.0):
            if self.idle_unload_ms <= 0 or self._model is None:
                continue
            with self._stats_lock:
                last_touch_ms = max(self.stats.last_request_ms, self.stats.last_transcribe_ms, self.stats.started_ms)
            if _now_ms() - last_touch_ms >= self.idle_unload_ms:
                self._unload_model()

    def _transcribe_best_effort(
        self,
        *,
        model: WhisperModel,
        wav_bytes: bytes,
        language: str,
        beam_size: int,
        vad_filter: bool,
        hotwords: str,
    ) -> tuple[Any, Any, str]:
        last_error: Exception | None = None

        ndarray_audio = self._decode_pcm_wav(wav_bytes)
        if ndarray_audio is not None and ndarray_audio.size > 0:
            try:
                segments, info = model.transcribe(
                    ndarray_audio,
                    language=language,
                    beam_size=beam_size,
                    condition_on_previous_text=False,
                    vad_filter=vad_filter,
                    temperature=0.0,
                    hotwords=hotwords or None,
                )
                with self._stats_lock:
                    self.stats.ndarray_decode_count += 1
                return segments, info, "ndarray_wav"
            except Exception as error:
                last_error = error

        try:
            segments, info = model.transcribe(
                io.BytesIO(wav_bytes),
                language=language,
                beam_size=beam_size,
                condition_on_previous_text=False,
                vad_filter=vad_filter,
                temperature=0.0,
                hotwords=hotwords or None,
            )
            with self._stats_lock:
                self.stats.binary_io_fallback_count += 1
            return segments, info, "binary_io"
        except Exception as error:
            last_error = error

        temp_path = self.model_dir / f".tmp_request_{threading.get_ident()}_{_now_ms()}.wav"
        try:
            temp_path.write_bytes(wav_bytes)
            segments, info = model.transcribe(
                str(temp_path),
                language=language,
                beam_size=beam_size,
                condition_on_previous_text=False,
                vad_filter=vad_filter,
                temperature=0.0,
                hotwords=hotwords or None,
            )
            with self._stats_lock:
                self.stats.tempfile_fallback_count += 1
            return segments, info, "tempfile"
        finally:
            try:
                temp_path.unlink()
            except Exception:
                pass

    def _decode_pcm_wav(self, wav_bytes: bytes) -> np.ndarray | None:
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
                channels = wav_file.getnchannels()
                width = wav_file.getsampwidth()
                rate = wav_file.getframerate()
                frame_count = wav_file.getnframes()
                if frame_count <= 0 or width != 2 or rate != 16_000:
                    return None
                raw = wav_file.readframes(frame_count)
        except Exception:
            return None

        pcm = np.frombuffer(raw, dtype=np.int16)
        if pcm.size == 0:
            return None
        if channels > 1:
            usable = (pcm.size // channels) * channels
            if usable <= 0:
                return None
            pcm = pcm[:usable].reshape(-1, channels).mean(axis=1).astype(np.int16)
        return pcm.astype(np.float32) / 32768.0


class PhoWhisperHandler(BaseHTTPRequestHandler):
    server: "PhoWhisperHTTPServer"

    def do_GET(self) -> None:  # noqa: N802
        self.server.worker.mark_request()
        route = urlsplit(self.path).path
        if route in {"/", "/health"}:
            self._write_json(HTTPStatus.OK, self.server.worker.health())
            return
        if route == "/warm":
            self._write_json(HTTPStatus.OK, self.server.worker.warm())
            return
        if route == "/unload":
            self._write_json(HTTPStatus.OK, self.server.worker.unload())
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        self.server.worker.mark_request()
        route = urlsplit(self.path).path
        if route not in {"/inference", "/transcribe"}:
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return

        content_type = str(self.headers.get("Content-Type") or "")
        content_length = int(self.headers.get("Content-Length") or "0")
        if content_length <= 0 or content_length > self.server.max_body_bytes:
            self._write_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "body_too_large"})
            return

        try:
            raw = self.rfile.read(content_length)
            if "application/json" in content_type:
                payload = json.loads(raw.decode("utf-8"))
                audio_base64 = str(payload.get("audioBase64") or "").strip()
                if not audio_base64:
                    raise ValueError("audioBase64 is required")
                wav_bytes = base64.b64decode(audio_base64, validate=True)
                response = self.server.worker.transcribe(
                    wav_bytes=wav_bytes,
                    language=str(payload.get("language") or "").strip() or None,
                    session_id=str(payload.get("sessionId") or "").strip(),
                    profile=str(payload.get("profile") or "").strip(),
                    beam_size=int(payload.get("beamSize")) if payload.get("beamSize") is not None else None,
                    vad_filter=bool(payload.get("vadFilter")) if payload.get("vadFilter") is not None else None,
                    hotwords=str(payload.get("hotwords") or "").strip() or None,
                )
            elif "audio/wav" in content_type or "application/octet-stream" in content_type:
                response = self.server.worker.transcribe(
                    wav_bytes=raw,
                    language=str(self.headers.get("X-Rokid-Language") or "").strip() or None,
                    session_id=str(self.headers.get("X-Rokid-Session-Id") or "").strip(),
                    profile=str(self.headers.get("X-Rokid-Profile") or "").strip(),
                    beam_size=self._parse_optional_int(self.headers.get("X-Rokid-Beam-Size")),
                    vad_filter=self._parse_optional_bool(self.headers.get("X-Rokid-Vad-Filter")),
                    hotwords=(
                        self._parse_optional_utf8_base64(self.headers.get("X-Rokid-Hotwords-Base64"))
                        or str(self.headers.get("X-Rokid-Hotwords") or "").strip()
                        or None
                    ),
                )
            else:
                self._write_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "unsupported_media_type"})
                return
        except Exception as error:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
            return

        self._write_json(HTTPStatus.OK, response)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _parse_optional_bool(self, value: str | None) -> bool | None:
        if value is None:
            return None
        norm = value.strip().lower()
        if norm in {"1", "true", "yes", "on"}:
            return True
        if norm in {"0", "false", "no", "off"}:
            return False
        return None

    def _parse_optional_int(self, value: str | None) -> int | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return int(text)

    def _parse_optional_utf8_base64(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return base64.b64decode(text.encode("ascii"), validate=True).decode("utf-8").strip() or None

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class PhoWhisperHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], *, worker: PhoWhisperWorker, max_body_bytes: int) -> None:
        super().__init__(server_address, handler_class)
        self.worker = worker
        self.max_body_bytes = max_body_bytes


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve PhoWhisper over a tiny HTTP API for Jetson local_http ASR.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9460)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--language", default="vi")
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--idle-unload-ms", type=int, default=120000)
    parser.add_argument("--max-body-mb", type=int, default=25)
    parser.add_argument("--no-vad-filter", action="store_true")
    parser.add_argument("--hotwords", default="")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    model_dir = Path(args.model_dir).expanduser().resolve()
    if not model_dir.is_dir():
        raise SystemExit(f"missing model dir: {model_dir}")
    if not (model_dir / "model.bin").is_file():
        raise SystemExit(f"missing model.bin in: {model_dir}")

    worker = PhoWhisperWorker(
        model_dir=model_dir,
        language=args.language,
        cpu_threads=max(1, args.cpu_threads),
        compute_type=args.compute_type,
        beam_size=max(1, args.beam_size),
        vad_filter=not bool(args.no_vad_filter),
        idle_unload_ms=max(0, args.idle_unload_ms),
        hotwords=str(args.hotwords or ""),
    )
    server = PhoWhisperHTTPServer(
        (args.host, args.port),
        PhoWhisperHandler,
        worker=worker,
        max_body_bytes=max(1, args.max_body_mb) * 1024 * 1024,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        worker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
