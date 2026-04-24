"""Composable v2 control plane for sessions, skills, events, and settings."""

from __future__ import annotations

from typing import Any

from .audio_signal import AudioForwardGate, is_voice_like, pcm16_metrics
from .debug_stt import DebugSttRuntime
from .event_store import InMemoryEventStore
from .hud_authority import HudAuthority
from .hud import sample_hud_scene
from .media_gateway import MediaGateway
from .perception_graph import PerceptionGraph
from .preview_store import PreviewStore
from .realtime_manager import RealtimeSessionManager
from .rv101_tcp_ingest import Rv101TcpIngestService
from .session_store import SessionStore
from .settings import load_settings
from .simulator_bridge import SimulatorBridge
from .skill_executor import SkillExecutor
from .skill_registry import SkillRegistry
from .yolo26_rokid_adapter import Yolo26RokidAdapter


class OpenVisionControlPlane:
    def __init__(self) -> None:
        self.events = InMemoryEventStore()
        self.sessions = SessionStore()
        self.hud = HudAuthority(events=self.events)
        self.media = MediaGateway(events=self.events)
        self.preview = PreviewStore(events=self.events)
        self.perception = PerceptionGraph(events=self.events)
        self.yolo26 = Yolo26RokidAdapter(events=self.events)
        self.debug_stt = DebugSttRuntime(events=self.events)
        self.skills = SkillRegistry()
        self.skill_executor = SkillExecutor(perception=self.perception, events=self.events)
        self._rv101_audio_gates: dict[str, AudioForwardGate] = {}
        self._simulator_audio_gates: dict[str, AudioForwardGate] = {}
        self.realtime = RealtimeSessionManager(
            events=self.events,
            skills=self.skills,
            skill_handler=self._execute_skill_for_realtime,
            response_text_handler=self._update_hud_from_realtime_text,
        )
        self.rv101_ingest = Rv101TcpIngestService(
            media=self.media,
            events=self.events,
            audio_pcm_handler=self._forward_rv101_audio_to_realtime,
        )
        self.simulator = SimulatorBridge(
            events=self.events,
            on_track=self._record_simulator_track,
            on_audio_pcm=self._forward_simulator_audio_to_realtime,
            on_video_frame=self._record_simulator_video_frame,
            on_preview_frame=self._record_simulator_preview_frame,
            on_close=self._close_simulator_media,
        )
        self.events.add(
            "agent",
            "boot",
            {"message": "OpenVision Rokid v2 control plane initialized"},
        )

    def health(self) -> dict[str, Any]:
        settings = load_settings()
        yolo26 = self.yolo26.status()
        debug_stt = self.debug_stt.status()
        return {
            "ok": True,
            "service": "openvision-jetson-agent",
            "version": "0.1.0",
            "environment": settings["environment"],
            "realtime_model": settings["realtime_model"],
            "openai_key_present": settings["openai_key_present"],
            "openai_key_source": settings["openai_key_source"],
            "debug_stt_enabled": debug_stt["enabled"],
            "debug_stt_status": debug_stt["status"],
            "sessions": len(self.sessions.list()),
            "skills": len(self.skills.list_definitions()),
            "realtime_sessions": len(self.realtime.statuses()),
            "yolo26_adapter_status": yolo26["status"],
            "rv101_tcp_ingest": self.rv101_ingest.status()["status"],
        }

    async def start_background_services(self) -> None:
        await self.rv101_ingest.start()

    async def stop_background_services(self) -> None:
        await self.rv101_ingest.stop()

    def create_session(
        self,
        *,
        client_kind: str,
        capabilities: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self.sessions.create(client_kind, capabilities)
        self.events.add(
            "session",
            "created",
            {"client_kind": client_kind, "capabilities": capabilities or {}},
            session_id=str(session["session_id"]),
        )
        return session

    def record_event(
        self,
        *,
        module: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        session_id: str | None = None,
        severity: str = "info",
    ) -> dict[str, Any]:
        event = self.events.add(
            module,
            event_type,
            payload or {},
            session_id=session_id,
            severity=severity,
        )
        return {
            "event_id": event.event_id,
            "recorded": True,
        }

    def list_events(self, *, session_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        return self.events.list(session_id=session_id, limit=limit)

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.sessions.list()

    def list_skills(self) -> list[dict[str, Any]]:
        return self.skills.list_definitions()

    def dry_run_skill(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        result = self.skills.dry_run(name, args, session_id=session_id)
        self.events.add(
            "skills",
            "dry_run",
            {"name": name, "status": result["status"]},
            session_id=session_id,
            severity="warning" if result["status"] != "not_implemented" else "info",
        )
        return result

    def execute_skill(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        result = self.skill_executor.execute(name=name, args=args or {}, session_id=session_id)
        self.hud.update_from_skill_result(result)
        return result

    def settings_snapshot(self) -> dict[str, object]:
        return load_settings()

    def sample_hud(self, session_id: str | None = None) -> dict[str, object]:
        return sample_hud_scene(session_id)

    def latest_hud(self, session_id: str) -> dict[str, Any] | None:
        return self.hud.latest(session_id)

    def list_hud(self) -> list[dict[str, Any]]:
        return self.hud.list_latest()

    def list_realtime(self) -> list[dict[str, Any]]:
        return self.realtime.statuses()

    def debug_stt_status(self) -> dict[str, Any]:
        return self.debug_stt.status()

    def list_debug_stt_transcripts(self, *, session_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        return self.debug_stt.transcripts(session_id=session_id, limit=limit)

    async def warm_debug_stt(self) -> dict[str, Any]:
        return await self.debug_stt.warm()

    def list_simulator(self) -> list[dict[str, Any]]:
        return self.simulator.statuses()

    def list_media(self) -> list[dict[str, Any]]:
        return self.media.statuses()

    def list_preview(self) -> list[dict[str, Any]]:
        return self.preview.list_statuses()

    def latest_preview_image(self, session_id: str) -> tuple[bytes, str] | None:
        return self.preview.latest_image(session_id)

    def preview_status(self, session_id: str) -> dict[str, Any] | None:
        return self.preview.status(session_id)

    def rv101_ingest_status(self) -> dict[str, Any]:
        return self.rv101_ingest.status()

    async def create_rv101_control_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = str(payload.get("deviceId") or "rv101")
        session = self.create_session(
            client_kind="rv101_glasses",
            capabilities={
                "device_id": device_id,
                "app_version": payload.get("appVersion"),
                "video": payload.get("videoCodec", "h264"),
                "audio": "pcm_s16le",
                "hud": "scene_json",
            },
        )
        accept = {
            "type": "session_accept",
            "sessionId": session["session_id"],
            "controlHeartbeatMs": 1000,
            "resultThrottleMs": 500,
            "media": {
                "transport": "tcp_h264",
                "host": self.rv101_ingest.status()["advertised_host"],
                "port": self.rv101_ingest.status()["video_port"],
            },
            "audio": {
                "transport": "tcp_pcm",
                "host": self.rv101_ingest.status()["advertised_host"],
                "port": self.rv101_ingest.status()["audio_port"],
                "codec": "pcm_s16le",
            },
        }
        realtime = await self.realtime.start(
            session_id=str(session["session_id"]),
            turn_policy="server_vad",
            output_modalities=["text"],
        )
        self.events.add(
            "rv101_control",
            "session_accept",
            {
                "device_id": device_id,
                "realtime_status": realtime["status"],
                "media": accept["media"],
                "audio": accept["audio"],
            },
            session_id=str(session["session_id"]),
        )
        return {
            "session": session,
            "accept": accept,
            "hud_scene": self._rv101_ready_hud(session_id=str(session["session_id"])),
        }

    async def handle_rv101_control_message(
        self,
        *,
        session_id: str | None,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        message_type = str(payload.get("type") or "unknown")
        if message_type == "ping":
            return [{"type": "pong", "sessionId": session_id, "timestampMs": payload.get("timestampMs")}]
        if not session_id:
            self.events.add("rv101_control", "orphan_message", {"type": message_type}, severity="warning")
            return []
        if message_type == "encoder_stats":
            self.media.record_video_heartbeat(
                session_id=session_id,
                transport="rv101_tcp",
                codec="video/avc",
                width=_to_int(payload.get("width")),
                height=_to_int(payload.get("height")),
                fps=_to_float(payload.get("encodeFps") or payload.get("targetFps")),
            )
        elif message_type == "audio_stats":
            self.events.add(
                "rv101_control",
                "audio_stats",
                {
                    "sentChunks": payload.get("sentChunks"),
                    "sentBytes": payload.get("sentBytes"),
                    "avgAbs": payload.get("avgAbs"),
                    "nonSilentRatio": payload.get("nonSilentRatio"),
                    "audioSource": payload.get("audioSource"),
                },
                session_id=session_id,
            )
        elif message_type == "ptt_down":
            try:
                await self.realtime.clear_audio(session_id=session_id)
            except RuntimeError:
                pass
            self.events.add("rv101_control", "ptt_down", {}, session_id=session_id)
        elif message_type == "ptt_up":
            try:
                await self.realtime.commit_audio(session_id=session_id)
            except RuntimeError:
                pass
            self.events.add("rv101_control", "ptt_up", {}, session_id=session_id)
        else:
            self.events.add(
                "rv101_control",
                message_type,
                {"payload": _compact_payload(payload)},
                session_id=session_id,
            )
        return []

    def update_perception(
        self,
        *,
        session_id: str,
        detections: list[dict[str, Any]],
        source: str,
        frame_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        return self.perception.update_snapshot(
            session_id=session_id,
            detections=detections,
            source=source,
            frame_id=frame_id,
            width=width,
            height=height,
        )

    def list_perception(self) -> list[dict[str, Any]]:
        return self.perception.list_latest()

    def yolo26_status(self) -> dict[str, Any]:
        return self.yolo26.status()

    def ingest_yolo26_snapshot(
        self,
        *,
        session_id: str,
        detections: list[dict[str, Any]],
        source: str,
        frame_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        accepted = self.yolo26.validate_external_snapshot(source=source)
        if accepted["status"] != "accepted":
            return accepted
        snapshot = self.perception.update_snapshot(
            session_id=session_id,
            detections=detections,
            source=str(accepted["source"]),
            frame_id=frame_id,
            width=width,
            height=height,
        )
        self.events.add(
            "adapter.yolo26",
            "snapshot_accepted",
            {"objects": len(detections), "frame_id": frame_id, "source": source},
            session_id=session_id,
        )
        return {
            "status": "accepted",
            "adapter": accepted["adapter"],
            "perception": snapshot,
        }

    def record_video_heartbeat(
        self,
        *,
        session_id: str,
        transport: str,
        codec: str,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
    ) -> dict[str, Any]:
        return self.media.record_video_heartbeat(
            session_id=session_id,
            transport=transport,
            codec=codec,
            width=width,
            height=height,
            fps=fps,
        )

    def record_audio_metrics(
        self,
        *,
        session_id: str,
        transport: str,
        sample_rate: int,
        channels: int,
        chunk_count: int,
        strong_chunk_count: int,
        rms: float | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        return self.media.record_audio_metrics(
            session_id=session_id,
            transport=transport,
            sample_rate=sample_rate,
            channels=channels,
            chunk_count=chunk_count,
            strong_chunk_count=strong_chunk_count,
            rms=rms,
            source=source,
        )

    def _record_simulator_track(self, session_id: str, kind: str) -> None:
        self.media.record_webrtc_track(session_id=session_id, kind=kind)

    def _record_simulator_video_frame(self, session_id: str, frame: dict[str, Any]) -> None:
        self.media.record_video_sample(
            session_id=session_id,
            transport="webrtc",
            codec="raw_video",
            payload_bytes=0,
            is_keyframe=False,
            width=_to_int(frame.get("width")),
            height=_to_int(frame.get("height")),
        )

    def _record_simulator_preview_frame(self, session_id: str, image_bytes: bytes, frame: dict[str, Any]) -> None:
        self.preview.record_frame(
            session_id=session_id,
            source=str(frame.get("source") or "iphone_webrtc"),
            image_bytes=image_bytes,
            width=_to_int(frame.get("width")),
            height=_to_int(frame.get("height")),
            frame_count=_to_int(frame.get("frame_count")) or 0,
        )

    def _close_simulator_media(self, session_id: str) -> None:
        self.media.close_session(session_id)
        self.preview.remove_session(session_id)
        self._simulator_audio_gates.pop(session_id, None)

    def _execute_skill_for_realtime(
        self,
        name: str,
        args: dict[str, Any],
        session_id: str | None,
    ) -> dict[str, Any]:
        return self.execute_skill(name, args, session_id=session_id)

    def _update_hud_from_realtime_text(self, session_id: str, text: str) -> None:
        self.hud.update_answer(
            session_id=session_id,
            answer_strip=text,
            edge_chips=["realtime"],
            ttl_ms=5000,
        )

    async def _forward_rv101_audio_to_realtime(self, session_id: str, pcm_bytes: bytes) -> None:
        metrics = pcm16_metrics(pcm_bytes)
        await self._forward_gated_audio(
            session_id=session_id,
            pcm_bytes=pcm_bytes,
            metrics=metrics,
            source="rv101",
            gates=self._rv101_audio_gates,
        )

    async def _forward_simulator_audio_to_realtime(
        self,
        session_id: str,
        pcm_bytes: bytes,
        metrics: dict[str, Any],
    ) -> None:
        self.media.record_audio_sample(
            session_id=session_id,
            transport="webrtc",
            sample_rate=24000,
            channels=1,
            payload_bytes=len(pcm_bytes),
            strong=float(metrics.get("avg_abs") or 0.0) >= 120.0
            and float(metrics.get("non_silent_ratio") or 0.0) >= 0.02,
            rms=float(metrics.get("avg_abs") or 0.0),
            source="iphone_webrtc",
        )
        await self._forward_gated_audio(
            session_id=session_id,
            pcm_bytes=pcm_bytes,
            metrics=metrics,
            source="iphone_webrtc",
            gates=self._simulator_audio_gates,
        )

    async def _forward_gated_audio(
        self,
        *,
        session_id: str,
        pcm_bytes: bytes,
        metrics: dict[str, Any],
        source: str,
        gates: dict[str, AudioForwardGate],
    ) -> None:
        gate = gates.setdefault(session_id, AudioForwardGate())
        decision = gate.accept(pcm_bytes, metrics)
        if decision.transition:
            self.events.add(
                "audio_gate",
                decision.transition,
                {
                    "source": source,
                    "state": decision.state,
                    "strong": decision.strong,
                    "forwarded_chunks": len(decision.chunks),
                    "buffered_chunks": decision.buffered_chunks,
                    "avg_abs": metrics.get("avg_abs"),
                    "peak_abs": metrics.get("peak_abs"),
                    "non_silent_ratio": metrics.get("non_silent_ratio"),
                },
                session_id=session_id,
            )
        self.debug_stt.accept_gate_decision(
            session_id=session_id,
            chunks=decision.chunks,
            transition=decision.transition,
            sample_rate=24000,
            channels=1,
            source=source,
        )
        for chunk in decision.chunks:
            try:
                await self.realtime.append_audio(session_id=session_id, pcm_bytes=chunk)
            except RuntimeError:
                return

    def _rv101_ready_hud(self, *, session_id: str) -> dict[str, Any]:
        return {
            "type": "hud_scene",
            "sessionId": session_id,
            "components": [
                {"kind": "chip", "id": "task_chip", "text": "OpenVision"},
                {"kind": "chip", "id": "mic_chip", "text": "Listening"},
                {"kind": "answer_strip", "text": "Sẵn sàng"},
            ],
        }


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "type":
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
    return compact


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
