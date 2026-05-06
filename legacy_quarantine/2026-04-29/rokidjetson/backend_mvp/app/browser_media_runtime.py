from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class LatestFrame:
    session_id: str
    width: int
    height: int
    sequence: int
    timestamp_ms: int
    bgr_bytes: bytes
    jpeg_bytes: bytes


def _pcm_energy_stats(payload: bytes) -> tuple[int, int, float]:
    if not payload or len(payload) < 2:
        return 0, 0, 0.0
    try:
        import numpy as np  # type: ignore

        samples = np.frombuffer(payload, dtype="<i2")
        if samples.size == 0:
            return 0, 0, 0.0
        abs_samples = np.abs(samples.astype(np.int32))
        avg_abs = int(abs_samples.mean())
        peak_abs = int(abs_samples.max())
        non_silent_ratio = float((abs_samples >= 96).sum() / samples.size)
        return avg_abs, peak_abs, non_silent_ratio
    except Exception:
        sample_count = len(payload) // 2
        if sample_count <= 0:
            return 0, 0, 0.0
        avg_total = 0
        peak_abs = 0
        non_silent = 0
        for index in range(0, sample_count * 2, 2):
            sample = int.from_bytes(payload[index:index + 2], byteorder="little", signed=True)
            value = abs(sample)
            avg_total += value
            if value > peak_abs:
                peak_abs = value
            if value >= 96:
                non_silent += 1
        avg_abs = int(avg_total / max(1, sample_count))
        non_silent_ratio = float(non_silent / max(1, sample_count))
        return avg_abs, peak_abs, non_silent_ratio


class BrowserMediaRuntime:
    def __init__(
        self,
        *,
        append_session_log: Callable[[Any, str, dict[str, Any]], None],
        latest_frames: dict[str, LatestFrame],
        latest_ai_results: dict[str, dict[str, Any]],
        latest_preview_session_id_getter: Callable[[], str | None],
        latest_preview_session_id_setter: Callable[[str | None], None],
        now_ms_provider: Callable[[], int],
        preview_jpeg_quality: int,
        video_sample_log_interval: int,
        audio_sample_log_interval: int,
        browser_audio_sample_rate: int,
        browser_audio_channels: int,
        audio_ring_max_bytes: int,
        audio_archive_writer_provider: Callable[[], Any | None],
    ) -> None:
        self._append_session_log = append_session_log
        self._latest_frames = latest_frames
        self._latest_ai_results = latest_ai_results
        self._latest_preview_session_id_getter = latest_preview_session_id_getter
        self._latest_preview_session_id_setter = latest_preview_session_id_setter
        self._now_ms_provider = now_ms_provider
        self._preview_jpeg_quality = preview_jpeg_quality
        self._video_sample_log_interval = video_sample_log_interval
        self._audio_sample_log_interval = audio_sample_log_interval
        self._browser_audio_sample_rate = browser_audio_sample_rate
        self._browser_audio_channels = browser_audio_channels
        self._audio_ring_max_bytes = audio_ring_max_bytes
        self._audio_archive_writer_provider = audio_archive_writer_provider

    def set_browser_media_state(
        self,
        session: Any,
        *,
        video_active: bool | None = None,
        audio_active: bool | None = None,
        peer_label: str = "browser",
    ) -> None:
        latest_preview_session_id = self._latest_preview_session_id_getter()
        if video_active is not None:
            session.video_connected = bool(video_active)
            session.video_peer = peer_label if video_active else None
            if not video_active:
                self._latest_frames.pop(session.session_id, None)
                self._latest_ai_results.pop(session.session_id, None)
                if latest_preview_session_id == session.session_id:
                    latest_preview_session_id = None
        if audio_active is not None:
            session.audio_connected = bool(audio_active)
            session.audio_peer = peer_label if audio_active else None
        self._latest_preview_session_id_setter(latest_preview_session_id)

    async def ingest_browser_video_bgr_frame(
        self,
        session: Any,
        frame: Any,
        *,
        peer_label: str,
        sequence: int,
        capture_timestamp_ms: int,
        rotation_degrees: int,
        event_name: str,
    ) -> None:
        invalid_event = f"{event_name}_invalid"
        try:
            import cv2  # type: ignore
        except Exception as error:
            self._append_session_log(
                session,
                invalid_event,
                {"peer": peer_label, "reason": f"cv2_unavailable:{error}"},
            )
            return

        height, width = frame.shape[:2]
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), self._preview_jpeg_quality],
        )
        jpeg_bytes = encoded.tobytes() if ok else b""
        if not jpeg_bytes:
            self._append_session_log(
                session,
                invalid_event,
                {"peer": peer_label, "reason": "jpeg_encode_failed"},
            )
            return
        session.rotation_degrees = rotation_degrees
        session.video_connected = True
        session.video_peer = peer_label
        session.video_frames += 1
        session.video_bytes += len(jpeg_bytes)
        session.last_video_seq = max(sequence, session.last_video_seq)
        session.last_video_timestamp_ms = capture_timestamp_ms
        self._latest_preview_session_id_setter(session.session_id)
        self._latest_frames[session.session_id] = LatestFrame(
            session_id=session.session_id,
            width=width,
            height=height,
            sequence=sequence,
            timestamp_ms=capture_timestamp_ms,
            bgr_bytes=frame.tobytes(),
            jpeg_bytes=jpeg_bytes,
        )
        if sequence <= 2 or sequence % self._video_sample_log_interval == 0:
            self._append_session_log(
                session,
                event_name,
                {
                    "peer": peer_label,
                    "sequence": sequence,
                    "width": width,
                    "height": height,
                    "payloadBytes": len(jpeg_bytes),
                    "captureTimestampMs": capture_timestamp_ms,
                    "videoFrames": session.video_frames,
                    "videoBytes": session.video_bytes,
                },
            )

    async def ingest_browser_audio_pcm(
        self,
        session: Any,
        pcm_bytes: bytes,
        *,
        peer_label: str,
        sequence: int,
        capture_timestamp_ms: int,
        sample_rate_hz: int,
        channels: int,
        avg_abs: int,
        peak_abs: int,
        non_silent_ratio: float,
        audio_source: str,
        event_name: str,
    ) -> None:
        if avg_abs <= 0 and peak_abs <= 0 and non_silent_ratio <= 0.0:
            avg_abs, peak_abs, non_silent_ratio = _pcm_energy_stats(pcm_bytes)

        session.audio_connected = True
        session.audio_peer = peer_label
        session.audio_packets += 1
        session.audio_bytes += len(pcm_bytes)
        session.last_audio_timestamp_ms = capture_timestamp_ms
        session.latest_audio_stats = {
            **session.latest_audio_stats,
            "avgAbs": avg_abs,
            "peakAbs": peak_abs,
            "nonSilentRatio": round(non_silent_ratio, 4),
            "audioSource": audio_source,
            "sampleRateHz": sample_rate_hz,
            "channels": channels,
        }
        session.append_audio_payload(pcm_bytes, max_buffer_bytes=self._audio_ring_max_bytes)
        audio_archive_writer = self._audio_archive_writer_provider()
        if audio_archive_writer is not None:
            audio_archive_writer.append(session.audio_path, pcm_bytes)
        if sequence <= 2 or sequence % self._audio_sample_log_interval == 0:
            self._append_session_log(
                session,
                event_name,
                {
                    "peer": peer_label,
                    "sequence": sequence,
                    "captureTimestampMs": capture_timestamp_ms,
                    "payloadBytes": len(pcm_bytes),
                    "audioPackets": session.audio_packets,
                    "audioBytes": session.audio_bytes,
                    "avgAbs": avg_abs,
                    "peakAbs": peak_abs,
                    "nonSilentRatio": round(non_silent_ratio, 4),
                    "audioSource": audio_source,
                    "sampleRateHz": sample_rate_hz,
                    "channels": channels,
                },
            )
