"""Composable v2 control plane for sessions, skills, events, and settings."""

from __future__ import annotations

import asyncio
from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any
import unicodedata

from .audio_signal import AudioForwardGate, is_voice_like, pcm16_metrics
from .cloud_gateway import CloudGateway, OpenAIResponsesVisionProvider, image_bytes_to_data_url
from .contracts import new_id, utc_now
from .contact_identity import ContactIdentityStore
from .debug_stt import DebugSttRuntime
from .display_command_gateway import DisplayCommandGateway
from .event_store import InMemoryEventStore
from .face_identity_adapter import FaceIdentityAdapter
from .face_identity_worker import build_face_backend, extract_identity_vector_from_image_path, load_face_identity_worker_settings
from .hud_authority import HudAuthority
from .hud import sample_hud_scene
from .media_command_gateway import MediaCommandGateway
from .media_gateway import MediaGateway
from .perception_graph import PerceptionGraph
from .preview_store import PreviewStore
from .preview_routes import (
    BRANCH_FACE_IDENTITY,
    BRANCH_YOLO26_OBJECTS,
    active_live_uses_adapter,
    build_sensor_preview_route,
    skill_preview_route_spec,
)
from .rv101_h264_live import Rv101H264LiveStore
from .people_registry import ImmichClient, PeopleRegistryStore
from .rv101_h264_preview import Rv101H264PreviewDecoder
from .rv101_stream_recorder import Rv101StreamRecorder
from .realtime_manager import RealtimeSessionManager
from .rv101_tcp_ingest import Rv101TcpIngestService
from .session_store import INACTIVE_SESSION_STATUSES, SessionStore
from .session_replay import build_session_replay, build_session_scorecard
from .settings import load_runtime_settings, load_settings
from .simulator_bridge import SimulatorBridge
from .skill_executor import SkillExecutor
from .skill_registry import SkillRegistry
from .voice_output import VoiceOutputBus
from .yolo26_rokid_adapter import Yolo26RokidAdapter
from .yolo26_live_stabilizer import Yolo26LiveStabilizer


RV101_HEALTH_LOG_INTERVAL_S = 30.0
RV101_AUDIO_DRAIN_WAIT_S = 0.8
RV101_AUDIO_DRAIN_POLL_S = 0.02
RV101_REALTIME_RECONNECT_GRACE_S = 90.0
RV101_DEFAULT_VOICE_MODE = "conversation_realtime"
RV101_PTT_VOICE_MODE = "push_to_talk_realtime"
RV101_SERVER_VAD_VOICE_MODES = {"conversation_realtime", "wake_realtime", "mission_realtime"}
PERSON_INFO_SNAPSHOT_RECENT_FRAME_LIMIT = 6
CAMERA_PROFILE_CONTRACT_VERSION = "openvision.camera_profile.v1"
RV101_DEFAULT_LIVE_PROFILE = "rv101_eco_live"
RV101_SKILL_LIVE_PROFILE = "rv101_medium_yolo"
RV101_HIGH_LIVE_PROFILE = "rv101_high_detail"
RV101_DIAGNOSTIC_LIVE_PROFILE = "rv101_diagnostic_30"
RV101_SNAPSHOT_PROFILE = "rv101_snapshot_high"
LIVE_YOLO26_SKILL_UPDATE_INTERVAL_S = 0.10
LIVE_FACE_IDENTITY_SKILL_UPDATE_INTERVAL_S = 0.25

RV101_LIVE_CAMERA_PROFILES: dict[str, dict[str, Any]] = {
    RV101_DEFAULT_LIVE_PROFILE: {
        "media_profile": RV101_DEFAULT_LIVE_PROFILE,
        "resolution": {"width": 640, "height": 360},
        "fps": 8.0,
        "bitrate_hint": "low",
        "preview_profile": "preview_low_latency",
        "description": "Low-power live video for debug and lightweight skills.",
    },
    RV101_SKILL_LIVE_PROFILE: {
        "media_profile": RV101_SKILL_LIVE_PROFILE,
        # V1 MEDIUM requested 720x960 but the stable Camera2 Surface path selected
        # 800x600 in practice. Use that proven HAL-friendly size as the V2 default.
        "resolution": {"width": 800, "height": 600},
        "fps": 15.0,
        "bitrate_hint": "balanced",
        "preview_profile": "preview_yolo_balanced",
        "description": "V1-proven balanced profile for YOLO/person live skills.",
    },
    RV101_HIGH_LIVE_PROFILE: {
        "media_profile": RV101_HIGH_LIVE_PROFILE,
        "resolution": {"width": 1280, "height": 720},
        "fps": 15.0,
        "bitrate_hint": "detail",
        "preview_profile": "preview_high_detail",
        "description": "Higher-detail live video for explicit identity/detail requests.",
    },
    RV101_DIAGNOSTIC_LIVE_PROFILE: {
        "media_profile": RV101_DIAGNOSTIC_LIVE_PROFILE,
        "resolution": {"width": 1280, "height": 720},
        "fps": 30.0,
        "bitrate_hint": "diagnostic",
        "preview_profile": "preview_diagnostic_30",
        "description": "Explicit 30fps validation profile, not the product default.",
    },
}

RV101_LIVE_CAMERA_PROFILE_ALIASES = {
    "eco": RV101_DEFAULT_LIVE_PROFILE,
    "low": RV101_DEFAULT_LIVE_PROFILE,
    "rv101_eco": RV101_DEFAULT_LIVE_PROFILE,
    "rv101_low": RV101_DEFAULT_LIVE_PROFILE,
    "medium": RV101_SKILL_LIVE_PROFILE,
    "balanced": RV101_SKILL_LIVE_PROFILE,
    "yolo": RV101_SKILL_LIVE_PROFILE,
    "rv101_medium": RV101_SKILL_LIVE_PROFILE,
    "rv101_balanced": RV101_SKILL_LIVE_PROFILE,
    "rv101_medium_yolo": RV101_SKILL_LIVE_PROFILE,
    "high": RV101_HIGH_LIVE_PROFILE,
    "detail": RV101_HIGH_LIVE_PROFILE,
    "rv101_high": RV101_HIGH_LIVE_PROFILE,
    "rv101_high_detail": RV101_HIGH_LIVE_PROFILE,
    "diagnostic": RV101_DIAGNOSTIC_LIVE_PROFILE,
    "diagnostic_30": RV101_DIAGNOSTIC_LIVE_PROFILE,
    "rv101_diagnostic": RV101_DIAGNOSTIC_LIVE_PROFILE,
    "rv101_diagnostic_30": RV101_DIAGNOSTIC_LIVE_PROFILE,
}


class OpenVisionControlPlane:
    def __init__(self) -> None:
        self._runtime_started_at = utc_now()
        self._runtime_started_monotonic_s = time.monotonic()
        self._runtime_process_id = os.getpid()
        self._runtime_boot_id = _read_host_boot_id()
        self._runtime_epoch = f"{self._runtime_process_id}:{self._runtime_started_at}"
        self.events = InMemoryEventStore()
        self.sessions = SessionStore()
        self.hud = HudAuthority(events=self.events)
        settings = load_settings()
        environment = str(settings.get("environment") or "dev").lower()
        self.display_commands = DisplayCommandGateway(
            events=self.events,
            hud=self.hud,
            session_validator=self._session_is_active,
            debug_overlay_allowed=environment in {"dev", "development", "local", "test"},
        )
        self.media = MediaGateway(events=self.events)
        self.preview = PreviewStore(events=self.events)
        self.stream_recorder = Rv101StreamRecorder(events=self.events)
        self.perception = PerceptionGraph(events=self.events)
        self.rv101_h264_live = Rv101H264LiveStore(events=self.events)
        self.deepstream_h264_live = Rv101H264LiveStore(events=self.events)
        self.rv101_h264_preview = Rv101H264PreviewDecoder(
            preview=self.preview,
            events=self.events,
            preview_frame_recorder=self._record_review_preview_frame,
        )
        self.media_commands = MediaCommandGateway(
            events=self.events,
            session_validator=self._session_is_active,
            preview_status_provider=self.preview.status,
        )
        self.voice_output = VoiceOutputBus()
        self.yolo26 = Yolo26RokidAdapter(events=self.events)
        self.yolo26_stabilizer = Yolo26LiveStabilizer(events=self.events)
        self.face_identity = FaceIdentityAdapter(events=self.events)
        self.identity = ContactIdentityStore(events=self.events)
        self.people = PeopleRegistryStore(events=self.events)
        runtime_settings = load_runtime_settings()
        self._realtime_audio_gate_mode = runtime_settings.realtime_audio_gate_mode
        self.cloud_gateway = CloudGateway(
            events=self.events,
            provider=self._build_cloud_verifier_provider(runtime_settings),
        )
        self.debug_stt = DebugSttRuntime(events=self.events)
        self.skills = SkillRegistry()
        self.skill_executor = SkillExecutor(
            perception=self.perception,
            events=self.events,
            registry=self.skills,
            cloud_gateway=self.cloud_gateway,
            preview_status_provider=self.preview.status,
            detector_status_provider=self._detector_status_for_skills,
            identity_match_provider=self.identity.match_candidates,
            person_memory_provider=self.remember_person_from_latest_preview,
            person_profile_provider=self.people.profile_for_identity_match,
        )
        self._continued_live_media_commands: set[str] = set()
        self._stopped_live_media_commands: set[str] = set()
        self._last_stream_skill_update_s: dict[str, float] = {}
        self._last_h264_preview_decode_skip_s: dict[str, float] = {}
        self._person_info_snapshot_analyzed: dict[str, str] = {}
        self._rv101_health_log_s: dict[str, float] = {}
        self._rv101_health_signature: dict[str, tuple[Any, ...]] = {}
        self._rv101_audio_gates: dict[str, AudioForwardGate] = {}
        self._rv101_stale_audio_logged: set[str] = set()
        self._rv101_ptt_started_s: dict[str, float] = {}
        self._rv101_audio_last_chunk_s: dict[str, float] = {}
        self._rv101_audio_closed_s: dict[str, float] = {}
        self._rv101_reconnect_grace_tasks: dict[str, asyncio.Task[None]] = {}
        self._rv101_recording_close_requested_sessions: set[str] = set()
        self._simulator_audio_gates: dict[str, AudioForwardGate] = {}
        self.realtime = RealtimeSessionManager(
            events=self.events,
            skills=self.skills,
            skill_handler=self._execute_skill_for_realtime,
            session_validator=self._session_is_active,
            response_text_handler=self._update_hud_from_realtime_text,
            response_audio_handler=self._publish_realtime_voice_output,
            response_audio_done_handler=self._publish_realtime_voice_done,
        )
        self.rv101_ingest = Rv101TcpIngestService(
            media=self.media,
            events=self.events,
            audio_pcm_handler=self._forward_rv101_audio_to_realtime,
            audio_close_handler=self._close_rv101_audio,
            video_h264_handler=self._handle_rv101_h264_sample,
            video_close_handler=self._close_rv101_video_stream,
            video_frame_allowed=self._rv101_video_ingest_allowed,
            video_frame_recorder=lambda session_id, header, payload, message_type: self.stream_recorder.record_video_frame(
                session_id=session_id,
                header=header,
                payload=payload,
                message_type=message_type,
            ),
            audio_frame_recorder=lambda session_id, header, payload, message_type: self.stream_recorder.record_audio_frame(
                session_id=session_id,
                header=header,
                payload=payload,
                message_type=message_type,
            ),
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
            {
                "message": "OpenVision Rokid v2 control plane initialized",
                "runtime_epoch": self._runtime_epoch,
                "process_id": self._runtime_process_id,
                "runtime_started_at": self._runtime_started_at,
            },
        )

    def health(self) -> dict[str, Any]:
        settings = load_settings()
        yolo26 = self.yolo26.status()
        face_identity = self.face_identity.status()
        debug_stt = self.debug_stt.status()
        identity = self.identity.status()
        people = self.people.status()
        session_statuses = self.list_sessions()
        realtime_statuses = self.realtime.statuses()
        media_statuses = self.media.statuses()
        preview_statuses = self.preview.list_statuses()
        media_commands = self.media_commands.statuses()
        rv101_h264_live = self.rv101_h264_live.list_statuses()
        deepstream_h264_live = self.deepstream_h264_live.list_statuses()
        rv101_h264_preview = self.rv101_h264_preview.status()
        stream_recorder = self.stream_recorder.status()
        active_live = [item for item in media_commands if item.get("active")]
        active_sessions = [item for item in session_statuses if _session_active(item)]
        active_realtime = [item for item in realtime_statuses if _realtime_active(item)]
        active_media = [item for item in media_statuses if _media_active(item)]
        return {
            "ok": True,
            "service": "openvision-jetson-agent",
            "version": "0.1.0",
            "process_id": self._runtime_process_id,
            "runtime_epoch": self._runtime_epoch,
            "runtime_started_at": self._runtime_started_at,
            "runtime_uptime_ms": int(max(0.0, time.monotonic() - self._runtime_started_monotonic_s) * 1000),
            "runtime_boot_id": self._runtime_boot_id,
            "environment": settings["environment"],
            "realtime_model": settings["realtime_model"],
            "openai_key_present": settings["openai_key_present"],
            "openai_key_source": settings["openai_key_source"],
            "debug_stt_enabled": debug_stt["enabled"],
            "debug_stt_status": debug_stt["status"],
            "sessions": len(active_sessions),
            "total_sessions": len(self.sessions.list()),
            "skills": len(self.skills.list_definitions()),
            "realtime_sessions": len(active_realtime),
            "total_realtime_sessions": len(realtime_statuses),
            "rv101_realtime_parked_sessions": len(
                [task for task in self._rv101_reconnect_grace_tasks.values() if not task.done()]
            ),
            "media_sessions": len(active_media),
            "total_media_sessions": len(media_statuses),
            "preview_sessions": len(preview_statuses),
            "media_commands": len(media_commands),
            "active_live_count": len(active_live),
            "voice_output": settings["realtime_voice_output_enabled"],
            "realtime_audio_gate_mode": settings["realtime_audio_gate_mode"],
            "cloud_verify_enabled": settings["cloud_verify_enabled"],
            "cloud_verify_model": settings["cloud_verify_model"],
            "cloud_verify_image_detail": settings["cloud_verify_image_detail"],
            "yolo26_adapter_status": yolo26["status"],
            "face_identity_adapter_status": face_identity["status"],
            "identity_status": identity["status"],
            "identity_contacts": identity["contact_count"],
            "identity_samples": identity["sample_count"],
            "people_registry_status": people["status"],
            "people_count": people["people_count"],
            "people_remembered_captures": people.get("remembered_capture_count", 0),
            "people_pending_face_sync": people.get("pending_face_sync_count", 0),
            "people_immich_configured": people["immich"]["configured"],
            "rv101_tcp_ingest": self.rv101_ingest.status()["status"],
            "rv101_h264_live": {
                "status": "ready",
                "session_count": len(rv101_h264_live),
                "sample_count": sum(int(item.get("sample_count") or 0) for item in rv101_h264_live),
                "subscriber_count": sum(int(item.get("subscriber_count") or 0) for item in rv101_h264_live),
            },
            "deepstream_h264_live": {
                "status": "ready",
                "session_count": len(deepstream_h264_live),
                "sample_count": sum(int(item.get("sample_count") or 0) for item in deepstream_h264_live),
                "subscriber_count": sum(int(item.get("subscriber_count") or 0) for item in deepstream_h264_live),
            },
            "rv101_h264_preview": rv101_h264_preview,
            "rv101_stream_recorder": stream_recorder,
        }

    def _build_cloud_verifier_provider(self, runtime_settings: Any) -> OpenAIResponsesVisionProvider | None:
        if not runtime_settings.cloud_verify_enabled or not runtime_settings.openai_api_key:
            return None
        return OpenAIResponsesVisionProvider(
            api_key=runtime_settings.openai_api_key,
            model=runtime_settings.cloud_verify_model,
            responses_url=runtime_settings.cloud_verify_responses_url,
            timeout_s=runtime_settings.cloud_verify_timeout_s,
            max_output_tokens=runtime_settings.cloud_verify_max_output_tokens,
            image_detail=runtime_settings.cloud_verify_image_detail,
            image_ref_resolver=self._resolve_cloud_image_ref,
        )

    def _detector_status_for_skills(self) -> dict[str, Any]:
        yolo26 = self.yolo26.status()
        return {
            **yolo26,
            "face_identity_status": self.face_identity.status(),
        }

    def _resolve_cloud_image_ref(self, ref: str, bundle: dict[str, Any]) -> str | None:
        if not ref.startswith("/api/preview/") or not ref.endswith("/frame.jpg"):
            return None
        session_id = str(bundle.get("session_id") or "").strip()
        if not session_id:
            return None
        image = self.preview.latest_image(session_id)
        if not image:
            return None
        image_bytes, content_type = image
        return image_bytes_to_data_url(image_bytes, content_type)

    def _session_exists(self, session_id: str) -> bool:
        return any(session.get("session_id") == session_id for session in self.sessions.list())

    def _session_is_active(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        if not session or not _session_active(session):
            return False
        realtime = self.realtime.status(session_id)
        if realtime and _realtime_terminal(realtime):
            return False
        return True

    def _session_client_kind(self, session_id: str) -> str | None:
        session = self.sessions.get(session_id)
        if not session:
            return None
        return str(session.get("client_kind") or "").strip() or None

    async def start_background_services(self) -> None:
        await self.rv101_ingest.start()

    async def stop_background_services(self) -> None:
        await self.rv101_ingest.stop()
        self.rv101_h264_live.close_all()
        self.deepstream_h264_live.close_all()
        self.rv101_h264_preview.close_all()
        self.stream_recorder.close_all()

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

    async def close_session(self, session_id: str, *, reason: str = "operator_requested") -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return {
                "status": "error",
                "error": {
                    "code": "missing_session",
                    "message": "Session id is required.",
                },
            }
        session = self.sessions.mark_inactive(normalized_session_id, status="closed")
        if not session:
            return {
                "status": "error",
                "error": {
                    "code": "unknown_session",
                    "message": f"Unknown session: {normalized_session_id}",
                },
            }
        self.events.add(
            "sessions",
            "closed",
            {"reason": reason, "status": session.get("status")},
            session_id=normalized_session_id,
        )
        await self._cleanup_closed_session_runtime(
            normalized_session_id,
            reason=reason,
            stop_failure_event="session_close_stop_failed",
        )
        return {"status": "closed", "session": session}

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

    def session_replay(self, *, session_id: str | None = None, limit: int = 1000) -> dict[str, Any]:
        return build_session_replay(
            session_id=session_id,
            sessions=self.list_sessions(),
            events=self.events.list(session_id=session_id, limit=limit),
            media=self.media.statuses(),
            perception=self.perception.list_latest(),
            hud_scenes=self.hud.list_latest(),
            realtime=self.realtime.statuses(),
            debug_stt=self.debug_stt.transcripts(session_id=session_id, limit=limit),
            debug_stt_status=self.debug_stt.status(),
            limit=limit,
        )

    def session_scorecard(self, *, session_id: str | None = None, limit: int = 1000) -> dict[str, Any]:
        replay = self.session_replay(session_id=session_id, limit=limit)
        return build_session_scorecard(replay)

    def list_sessions(self) -> list[dict[str, Any]]:
        return [self._materialize_session_status(session) for session in self.sessions.list()]

    def _materialize_session_status(self, session: dict[str, Any]) -> dict[str, Any]:
        materialized = dict(session)
        if not _session_active(materialized):
            return materialized
        realtime = self.realtime.status(str(materialized.get("session_id") or ""))
        if realtime and _realtime_terminal(realtime):
            materialized["status"] = str(realtime.get("status") or materialized.get("status"))
            materialized["updated_at"] = realtime.get("updated_at") or materialized.get("updated_at")
        return materialized

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
        force_media_capture: bool = False,
    ) -> dict[str, Any]:
        media_request = self._request_skill_media_if_needed(
            name=name,
            args=args or {},
            session_id=session_id,
            force_media_capture=force_media_capture,
        )
        if media_request:
            self.hud.update_from_skill_result(media_request)
            return media_request
        if name == "person_info" and session_id and _person_info_prefers_snapshot(args or {}):
            self._ensure_person_info_snapshot_from_preview(session_id=session_id)
        result = self.skill_executor.execute(name=name, args=args or {}, session_id=session_id)
        self.hud.update_from_skill_result(result)
        return result

    def _request_skill_media_if_needed(
        self,
        *,
        name: str,
        args: dict[str, Any],
        session_id: str | None,
        force_media_capture: bool = False,
    ) -> dict[str, Any] | None:
        definition = self.skills.get(name)
        if not definition or not session_id or not self._session_exists(session_id):
            return None
        media_requirements = definition.media_requirements
        if not _should_request_visual_media(definition):
            return None
        pending = self._pending_skill_media_command(skill_id=definition.name, session_id=session_id)
        has_existing_evidence = bool(self.perception.latest(session_id) or self.preview.status(session_id))
        if _pending_live_video_has_evidence(pending, has_existing_evidence=has_existing_evidence):
            return None
        wants_live_name_reminder = definition.name == "person_info" and _person_info_wants_live_name_reminder(args)
        if not pending and not force_media_capture and has_existing_evidence and not wants_live_name_reminder:
            return None
        media_mode = _visual_media_mode(media_requirements, args=args, skill_id=definition.name)
        media_params = _skill_media_command_params(mode=media_mode, args=args, skill_id=definition.name)
        media_budget = _skill_media_command_budget(mode=media_mode, args=args, skill_id=definition.name)
        media_result = pending or self.media_commands.request_command(
            mode=media_mode,
            session_id=session_id,
            skill_id=definition.name,
            reason=f"{definition.name} needs fresh camera evidence",
            params=media_params,
            **media_budget,
        )
        if media_result.get("status") == "error":
            return {
                "skill_call_id": new_id("skill"),
                "name": definition.name,
                "args": args,
                "session_id": session_id,
                "status": "error",
                "result": None,
                "error": media_result.get("error"),
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
        command = media_result.get("command") if isinstance(media_result.get("command"), dict) else {}
        event = media_result.get("event") if isinstance(media_result.get("event"), dict) else {}
        payload = {
            "skill_call_id": new_id("skill"),
            "name": definition.name,
            "args": args,
            "session_id": session_id,
            "status": "no_evidence",
            "result": {
                "message": "Fresh camera evidence has been requested from the client.",
                "user_message": _media_request_user_message(media_mode, skill_id=definition.name),
                "media_command": command,
                "media_event": event,
                "hud": {
                    "answer_strip": _media_request_answer_strip(media_mode, skill_id=definition.name),
                    "edge_chips": ["camera", definition.name],
                    "ttl_ms": 3000,
                },
            },
            "error": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self.events.add(
            "skills",
            "media_requested",
            {
                "name": definition.name,
                "mode": command.get("mode"),
                "media_command_id": command.get("command_id"),
                "media_status": media_result.get("status"),
            },
            session_id=session_id,
        )
        return payload

    def _pending_skill_media_command(self, *, skill_id: str, session_id: str) -> dict[str, Any] | None:
        for item in reversed(self.media_commands.statuses()):
            command = item.get("command") if isinstance(item, dict) else None
            event = item.get("event") if isinstance(item, dict) else None
            if not isinstance(command, dict) or not isinstance(event, dict):
                continue
            if command.get("session_id") != session_id or command.get("skill_id") != skill_id:
                continue
            if event.get("status") in {"queued", "running"}:
                return {
                    "status": event.get("status"),
                    "command": command,
                    "event": event,
                    "active_live_video": bool(item.get("active")),
                }
        return None

    def _ensure_person_info_snapshot_from_preview(self, *, session_id: str) -> dict[str, Any] | None:
        preview = self.preview.status(session_id)
        frames = self.preview.recent_frames(session_id, limit=PERSON_INFO_SNAPSHOT_RECENT_FRAME_LIMIT)
        if not preview or not frames:
            return None
        signature = "|".join(
            ":".join(str(part) for part in (frame.frame_count, frame.updated_at, len(frame.image_bytes)))
            for frame in frames
        )
        if self._person_info_snapshot_analyzed.get(session_id) == signature:
            return self.perception.latest(session_id)
        settings = load_face_identity_worker_settings()
        backend = build_face_backend(settings)
        backend_status = backend.status()
        if backend_status.get("status") != "ready":
            self.events.add(
                "adapter.face_identity",
                "snapshot_analysis_unavailable",
                {
                    "skill_id": "person_info",
                    "backend_status": backend_status.get("status"),
                    "reason": backend_status.get("reason"),
                    "message": backend_status.get("message"),
                },
                session_id=session_id,
                severity="warning",
            )
            return None
        candidates: list[dict[str, Any]] = []
        frame_errors: list[dict[str, Any]] = []
        try:
            from PIL import Image  # type: ignore
        except Exception as exc:
            self.events.add(
                "adapter.face_identity",
                "snapshot_analysis_failed",
                {"skill_id": "person_info", "message": f"{exc.__class__.__name__}: {exc}"},
                session_id=session_id,
                severity="error",
            )
            return None
        for frame in frames:
            try:
                pil_image = Image.open(BytesIO(frame.image_bytes)).convert("RGB")
                raw_detections = backend.detect_and_embed(pil_image)
                if not isinstance(raw_detections, list):
                    raw_detections = []
                metrics = _snapshot_image_quality_metrics(pil_image)
                candidates.append(
                    {
                        "frame": frame,
                        "image": pil_image,
                        "detections": raw_detections,
                        "metrics": metrics,
                        "score": _snapshot_candidate_score(detections=raw_detections, image_metrics=metrics),
                    }
                )
            except Exception as exc:
                frame_errors.append(
                    {
                        "frame_count": frame.frame_count,
                        "message": f"{exc.__class__.__name__}: {exc}",
                    }
                )
        if not candidates:
            self.events.add(
                "adapter.face_identity",
                "snapshot_analysis_failed",
                {
                    "skill_id": "person_info",
                    "message": "No preview frame could be decoded for snapshot analysis.",
                    "frame_error_count": len(frame_errors),
                    "frame_errors": frame_errors[-3:],
                },
                session_id=session_id,
                severity="error",
            )
            return None
        selected = max(
            candidates,
            key=lambda item: (
                float(item.get("score") or 0.0),
                int(getattr(item.get("frame"), "frame_count", 0) or 0),
            ),
        )
        selected_frame = selected["frame"]
        pil_image = selected["image"]
        detections = _prepare_snapshot_face_detections(
            detections=selected["detections"],
            image=pil_image,
            session_id=session_id,
            runtime_dir=settings.runtime_dir,
            crop_quality=settings.crop_quality,
        )
        snapshot = self.perception.update_snapshot(
            session_id=session_id,
            detections=detections,
            source="face_identity_snapshot:person_info",
            frame_id=f"preview_{selected_frame.frame_count or 0}",
            width=int(getattr(pil_image, "width", 0) or selected_frame.width or preview.get("width") or 0) or None,
            height=int(getattr(pil_image, "height", 0) or selected_frame.height or preview.get("height") or 0) or None,
        )
        self._record_processed_perception_preview(session_id=session_id, snapshot=snapshot)
        self._person_info_snapshot_analyzed[session_id] = signature
        self.events.add(
            "adapter.face_identity",
            "snapshot_analysis_completed",
            {
                "skill_id": "person_info",
                "source": "face_identity_snapshot:person_info",
                "content_type": selected_frame.content_type,
                "detection_count": len(detections),
                "frame_count": selected_frame.frame_count,
                "quality_gate": {
                    "mode": "best_of_recent_preview",
                    "candidate_frame_count": len(candidates),
                    "selected_frame_count": selected_frame.frame_count,
                    "selected_score": round(float(selected.get("score") or 0.0), 2),
                    "selected_metrics": selected.get("metrics"),
                    "frame_error_count": len(frame_errors),
                    "frames": [_snapshot_candidate_event_summary(candidate) for candidate in candidates],
                },
            },
            session_id=session_id,
            severity="info" if detections else "warning",
        )
        return snapshot

    def settings_snapshot(self) -> dict[str, object]:
        return load_settings()

    def sample_hud(self, session_id: str | None = None) -> dict[str, object]:
        return sample_hud_scene(session_id)

    def test_hud(self, session_id: str) -> dict[str, Any]:
        return self.hud.update_test_scene(session_id=session_id)

    def latest_hud(self, session_id: str) -> dict[str, Any] | None:
        return self.hud.latest(session_id)

    def list_hud(self) -> list[dict[str, Any]]:
        return self.hud.list_latest()

    def subscribe_hud(self, session_id: str) -> Any:
        return self.hud.subscribe(session_id)

    def unsubscribe_hud(self, session_id: str, queue: Any) -> None:
        self.hud.unsubscribe(session_id, queue)

    def list_display_commands(self) -> list[dict[str, Any]]:
        return self.display_commands.statuses()

    def request_display_command(
        self,
        *,
        kind: str,
        session_id: str,
        payload: dict[str, Any] | None = None,
        command_id: str | None = None,
        skill_id: str | None = None,
        priority: str = "normal",
        ttl_ms: int | None = None,
    ) -> dict[str, Any]:
        return self.display_commands.request_command(
            kind=kind,
            session_id=session_id,
            payload=payload,
            command_id=command_id,
            skill_id=skill_id,
            priority=priority,
            ttl_ms=ttl_ms,
        )

    def list_realtime(self) -> list[dict[str, Any]]:
        return self.realtime.statuses()

    def list_voice_output(self) -> list[dict[str, Any]]:
        return self.voice_output.statuses()

    async def debug_stt_status(self, *, probe: bool = False) -> dict[str, Any]:
        if probe:
            return await self.debug_stt.check_health()
        return self.debug_stt.status()

    def list_debug_stt_transcripts(self, *, session_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        return self.debug_stt.transcripts(session_id=session_id, limit=limit)

    async def warm_debug_stt(self) -> dict[str, Any]:
        return await self.debug_stt.warm()

    def list_simulator(self) -> list[dict[str, Any]]:
        return self.simulator.statuses()

    def list_media(self) -> list[dict[str, Any]]:
        return [status for status in self.media.statuses() if _media_active(status)]

    def list_media_commands(self) -> dict[str, Any]:
        self._sync_stopped_live_media()
        return {
            "commands": self.media_commands.statuses(),
            "active_live": self.media_commands.active_live_statuses(),
        }

    def request_media_command(
        self,
        *,
        mode: str,
        session_id: str,
        command_id: str | None = None,
        skill_id: str | None = None,
        reason: str | None = None,
        timeout_ms: int | None = None,
        fps: float | None = None,
        resolution: dict[str, Any] | None = None,
        auto_stop: bool = True,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.media_commands.request_command(
            mode=mode,
            session_id=session_id,
            command_id=command_id,
            skill_id=skill_id,
            reason=reason,
            timeout_ms=timeout_ms,
            fps=fps,
            resolution=resolution,
            auto_stop=auto_stop,
            params=params,
        )
        self._sync_stopped_live_media()
        return result

    def record_media_command_event(
        self,
        *,
        command_id: str,
        session_id: str,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.media_commands.client_event(
            command_id=command_id,
            session_id=session_id,
            status=status,
            payload=payload,
        )
        if result.get("ignored"):
            self._sync_stopped_live_media()
            return result
        self._stop_video_stream_for_final_live_event(result)
        continuation = self._continue_skill_after_media_event(result)
        if continuation:
            result = {**result, "continuation": continuation}
            self._notify_realtime_after_media_continuation(continuation)
        self._sync_stopped_live_media()
        return result

    def _sync_stopped_live_media(self) -> None:
        statuses = self.media_commands.statuses()
        self._prune_stream_runtime_caches(statuses=statuses)
        for item in statuses:
            self._stop_video_stream_for_final_live_event(item)

    def _stop_video_stream_for_final_live_event(self, result: dict[str, Any]) -> None:
        command = result.get("command") if isinstance(result.get("command"), dict) else {}
        event = result.get("event") if isinstance(result.get("event"), dict) else {}
        if command.get("mode") != "live_video":
            return
        status = str(event.get("status") or "").strip().lower()
        if status not in {"ok", "timeout", "cancelled", "error"}:
            return
        session_id = str(command.get("session_id") or "").strip()
        if not session_id:
            return
        command_id = str(command.get("command_id") or event.get("command_id") or "").strip()
        if command_id and command_id in self._stopped_live_media_commands:
            return
        if command_id:
            active_live = [
                item
                for item in self.media_commands.active_live_statuses()
                if str(item.get("session_id") or "").strip() == session_id
            ]
            if any(str(item.get("command_id") or "").strip() != command_id for item in active_live):
                self._stopped_live_media_commands.add(command_id)
                return
            self._stopped_live_media_commands.add(command_id)
        self.media.stop_video_stream(session_id=session_id, reason=f"live_video_{status}")
        self.rv101_h264_live.close_session(session_id)
        self.deepstream_h264_live.close_session(session_id)
        self.rv101_h264_preview.close_session(session_id)
        self._clear_live_perception_sources_for_command(command, reason=f"live_video_{status}")
        preview = self.preview.status(session_id)
        if preview and preview.get("source") == "rv101_live_h264":
            self.preview.mark_session_stale(session_id, reason=f"live_video_{status}")
        self._close_rv101_recording_if_media_idle(session_id, reason=f"live_video_{status}")

    def _clear_live_perception_sources_for_command(self, command: dict[str, Any], *, reason: str) -> None:
        session_id = str(command.get("session_id") or "").strip()
        if not session_id:
            return
        params = command.get("params") if isinstance(command.get("params"), dict) else {}
        branches = {str(item or "").strip() for item in (params.get("perception_branches") or [])}
        markers: set[str] = set()
        if BRANCH_YOLO26_OBJECTS in branches:
            markers.add("yolo26")
        if BRANCH_FACE_IDENTITY in branches:
            markers.add("face_identity")
        if not markers:
            return
        self.perception.clear_sources(session_id=session_id, source_markers=markers, reason=reason)
        if "yolo26" in markers:
            self.yolo26_stabilizer.clear_session(session_id, reason=reason)

    def _prune_stream_runtime_caches(self, *, statuses: list[dict[str, Any]] | None = None) -> None:
        _ = statuses
        active_command_ids = {
            str(item.get("command_id") or "")
            for item in self.media_commands.active_live_statuses()
            if str(item.get("command_id") or "").strip()
        }
        known_command_ids = {
            str(item.get("command", {}).get("command_id") or "")
            for item in (statuses or [])
            if isinstance(item.get("command"), dict)
        }
        if known_command_ids:
            self._stopped_live_media_commands.intersection_update(known_command_ids)
        self._continued_live_media_commands.intersection_update(active_command_ids)
        if not active_command_ids:
            self._last_stream_skill_update_s.clear()
            return
        self._last_stream_skill_update_s = {
            key: value
            for key, value in self._last_stream_skill_update_s.items()
            if any(f":{command_id}:" in key for command_id in active_command_ids)
        }

    def _continue_skill_after_media_event(self, media_result: dict[str, Any]) -> dict[str, Any] | None:
        context = _skill_media_continuation_context(media_result)
        if not context:
            return None
        command = context["command"]
        event = context["event"]
        skill_id = context["skill_id"]
        session_id = context["session_id"]
        args = context["args"]
        media_status = str(media_result.get("status") or "").strip().lower()
        if command.get("mode") == "live_video" and media_status == "running":
            command_id = str(command.get("command_id") or "").strip()
            if command_id and command_id in self._continued_live_media_commands:
                return None
            if command_id:
                self._continued_live_media_commands.add(command_id)
            continuation = self.skill_executor.execute(name=skill_id, args=args, session_id=session_id)
            self.hud.update_from_skill_result(continuation)
            self.events.add(
                "skills",
                "media_continuation_completed",
                {
                    "name": skill_id,
                    "status": continuation.get("status"),
                    "media_command_id": command.get("command_id"),
                    "media_event_id": event.get("event_id"),
                },
                session_id=session_id,
                severity="error" if continuation.get("status") == "error" else "info",
            )
            return continuation
        if media_status != "ok":
            if command.get("mode") == "live_video" and media_status in {"timeout", "cancelled"}:
                return self._live_media_continuation_stopped(
                    skill_id=skill_id,
                    args=args,
                    session_id=session_id,
                    command=command,
                    event=event,
                    media_status=media_status,
                )
            if media_status not in {"timeout", "cancelled", "error"}:
                return None
            return self._media_continuation_failed(
                skill_id=skill_id,
                args=args,
                session_id=session_id,
                command=command,
                event=event,
                media_status=media_status,
            )
        if event.get("status") != "ok":
            return None
        if not self.perception.latest(session_id) and not self.preview.status(session_id):
            continuation = self._media_continuation_missing_preview(
                skill_id=skill_id,
                args=args,
                session_id=session_id,
                command=command,
                event=event,
            )
        else:
            continuation = self.execute_skill(skill_id, args, session_id=session_id)
        self.events.add(
            "skills",
            "media_continuation_completed",
            {
                "name": skill_id,
                "status": continuation.get("status"),
                "media_command_id": command.get("command_id"),
                "media_event_id": event.get("event_id"),
            },
            session_id=session_id,
            severity="error" if continuation.get("status") == "error" else "info",
        )
        return continuation

    def _live_media_continuation_stopped(
        self,
        *,
        skill_id: str,
        args: dict[str, Any],
        session_id: str,
        command: dict[str, Any],
        event: dict[str, Any],
        media_status: str,
    ) -> dict[str, Any]:
        command_id = str(command.get("command_id") or "").strip()
        if command_id:
            self._continued_live_media_commands.discard(command_id)
        if skill_id == "person_info":
            user_message = "Đã dừng quét người quen." if media_status == "timeout" else "Đã hủy quét người quen."
        else:
            user_message = "Đã dừng live target." if media_status == "timeout" else "Đã hủy live target."
        payload = {
            "skill_call_id": new_id("skill"),
            "name": skill_id,
            "args": args,
            "session_id": session_id,
            "status": "cancelled" if media_status == "cancelled" else "ok",
            "result": {
                "message": "Live media session stopped.",
                "user_message": user_message,
                "media_status": media_status,
                "media_command": command,
                "media_event": event,
                "hud": {
                    "answer_strip": user_message,
                    "edge_chips": ["camera", "live_stopped", skill_id],
                    "ttl_ms": 2500,
                },
            },
            "error": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self.hud.update_from_skill_result(payload)
        self.events.add(
            "skills",
            "media_live_continuation_stopped",
            {
                "name": skill_id,
                "status": media_status,
                "media_command_id": command.get("command_id"),
                "media_event_id": event.get("event_id"),
            },
            session_id=session_id,
            severity="info",
        )
        return payload

    def _media_continuation_failed(
        self,
        *,
        skill_id: str,
        args: dict[str, Any],
        session_id: str,
        command: dict[str, Any],
        event: dict[str, Any],
        media_status: str,
    ) -> dict[str, Any]:
        adapter_status = _media_event_adapter_status(event)
        user_message = _media_failure_user_message(media_status)
        payload = {
            "skill_call_id": new_id("skill"),
            "name": skill_id,
            "args": args,
            "session_id": session_id,
            "status": "no_evidence",
            "result": {
                "message": "Client media capture did not produce fresh usable evidence.",
                "user_message": user_message,
                "media_status": media_status,
                "adapter_status": adapter_status,
                "media_command": command,
                "media_event": event,
                "hud": {
                    "answer_strip": user_message,
                    "edge_chips": ["camera", f"capture_{media_status}", skill_id],
                    "ttl_ms": 5000,
                },
            },
            "error": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self.hud.update_from_skill_result(payload)
        self.events.add(
            "skills",
            "media_continuation_failed",
            {
                "name": skill_id,
                "status": media_status,
                "adapter_status": adapter_status,
                "media_command_id": command.get("command_id"),
                "media_event_id": event.get("event_id"),
            },
            session_id=session_id,
            severity="warning" if media_status in {"timeout", "cancelled"} else "error",
        )
        return payload

    def _media_continuation_missing_preview(
        self,
        *,
        skill_id: str,
        args: dict[str, Any],
        session_id: str,
        command: dict[str, Any],
        event: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "skill_call_id": new_id("skill"),
            "name": skill_id,
            "args": args,
            "session_id": session_id,
            "status": "no_evidence",
            "result": {
                "message": "Client reported media capture ok, but Jetson has no decoded preview frame yet.",
                "user_message": "Ảnh báo xong; Jetson chưa nhận frame.",
                "media_command": command,
                "media_event": event,
                "hud": {
                    "answer_strip": "Jetson chưa nhận frame ảnh",
                    "edge_chips": ["camera", "preview_wait", skill_id],
                    "ttl_ms": 4000,
                },
            },
            "error": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self.hud.update_from_skill_result(payload)
        self.events.add(
            "skills",
            "media_continuation_waiting_preview",
            {"name": skill_id, "media_command_id": command.get("command_id")},
            session_id=session_id,
            severity="warning",
        )
        return payload

    def _notify_realtime_after_media_continuation(self, continuation: dict[str, Any]) -> None:
        prompt = _media_continuation_realtime_prompt(continuation)
        session_id = str(continuation.get("session_id") or "").strip()
        if not prompt or not session_id:
            return
        if _is_live_media_stop_continuation(continuation):
            self.events.add(
                "realtime",
                "media_continuation_prompt_suppressed",
                {
                    "name": continuation.get("name"),
                    "status": continuation.get("status"),
                    "reason": "live_media_stopped_hud_only",
                },
                session_id=session_id,
            )
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(
            self._send_realtime_media_continuation_prompt(
                session_id=session_id,
                prompt=prompt,
                continuation=continuation,
            )
        )

    async def _send_realtime_media_continuation_prompt(
        self,
        *,
        session_id: str,
        prompt: str,
        continuation: dict[str, Any],
    ) -> None:
        try:
            await self.realtime.send_text(session_id=session_id, text=prompt)
        except Exception as exc:
            self.events.add(
                "realtime",
                "media_continuation_prompt_dropped",
                {
                    "name": continuation.get("name"),
                    "status": continuation.get("status"),
                    "error": exc.__class__.__name__,
                    "message": str(exc),
                },
                session_id=session_id,
                severity="warning",
            )
            return
        self.events.add(
            "realtime",
            "media_continuation_prompt_queued",
            {
                "name": continuation.get("name"),
                "status": continuation.get("status"),
            },
            session_id=session_id,
        )

    def list_preview(self) -> list[dict[str, Any]]:
        h264_by_session = {
            str(item.get("session_id") or ""): item
            for item in self.rv101_h264_live.list_statuses()
            if str(item.get("session_id") or "").strip()
        }
        deepstream_h264_by_session = {
            str(item.get("session_id") or ""): item
            for item in self.deepstream_h264_live.list_statuses()
            if str(item.get("session_id") or "").strip()
        }
        active_live_by_session = {
            str(item.get("session_id") or ""): item
            for item in self.media_commands.active_live_statuses()
            if str(item.get("session_id") or "").strip()
        }
        statuses = self.preview.list_statuses()
        seen_sessions = {str(status.get("session_id") or "") for status in statuses}
        for session_id in active_live_by_session:
            if session_id in seen_sessions:
                continue
            statuses.append(
                {
                    "session_id": session_id,
                    "source": "active_live_video",
                    "width": None,
                    "height": None,
                    "frame_count": 0,
                    "updated_at": utc_now(),
                    "metadata": {"preview_source": "active_live_route"},
                    "has_frame": False,
                    "image_url": "",
                    "mjpeg_url": "",
                }
            )
            seen_sessions.add(session_id)
        for session_id, deepstream_live in deepstream_h264_by_session.items():
            if session_id in seen_sessions:
                continue
            statuses.append(
                {
                    "session_id": session_id,
                    "source": "deepstream_yolo26_osd",
                    "width": deepstream_live.get("width"),
                    "height": deepstream_live.get("height"),
                    "frame_count": deepstream_live.get("sample_count") or 0,
                    "updated_at": deepstream_live.get("updated_at"),
                    "metadata": {
                        **(deepstream_live.get("metadata") if isinstance(deepstream_live.get("metadata"), dict) else {}),
                        "preview_source": "deepstream_yolo26_osd_h264",
                        "annotated": True,
                        "osd_burned_in": True,
                    },
                    "has_frame": False,
                    "image_url": "",
                    "mjpeg_url": "",
                }
            )
            seen_sessions.add(session_id)
        for session_id, live in h264_by_session.items():
            if session_id in seen_sessions:
                continue
            statuses.append(
                {
                    "session_id": session_id,
                    "source": live.get("transport") or "rv101_tcp",
                    "width": live.get("width"),
                    "height": live.get("height"),
                    "frame_count": live.get("sample_count") or 0,
                    "updated_at": live.get("updated_at"),
                    "metadata": live.get("metadata") if isinstance(live.get("metadata"), dict) else {},
                    "has_frame": False,
                    "image_url": "",
                    "mjpeg_url": "",
                }
            )
            seen_sessions.add(session_id)
        for status in statuses:
            session_id = str(status.get("session_id") or "")
            deepstream_live = deepstream_h264_by_session.get(session_id)
            if deepstream_live:
                deepstream_live = dict(deepstream_live)
                deepstream_live["h264_ws_url"] = f"/ws/preview/{session_id}/deepstream-h264"
                deepstream_live["source"] = "deepstream_yolo26_osd"
                status["has_deepstream_h264_live"] = True
                status["deepstream_h264_ws_url"] = deepstream_live["h264_ws_url"]
                status["deepstream_h264_live"] = deepstream_live
            live = h264_by_session.get(session_id)
            if live:
                status["has_h264_live"] = True
                status["h264_ws_url"] = live.get("h264_ws_url")
                status["h264_live"] = live
            processed = self.stream_recorder.active_processed_preview(session_id)
            if processed:
                status["review_preview"] = {
                    "available": True,
                    "image_url": f"/api/preview/{session_id}/processed/frame.jpg",
                    "kind": "jetson_recording_annotation",
                    "recording_id": processed.get("recording_id"),
                    "live_sensor_preview": False,
                }
                status["has_processed_preview"] = True
                status["processed_image_url"] = f"/api/preview/{session_id}/processed/frame.jpg"
                status["processed_preview_kind"] = "jetson_annotated"
                status["processed_recording_id"] = processed.get("recording_id")
            route = build_sensor_preview_route(
                session_id=session_id,
                active_live=active_live_by_session.get(session_id),
                raw_h264=live,
                deepstream_h264=deepstream_live,
                snapshot=status if status.get("has_frame") else None,
            )
            status["sensor_preview"] = route
            status["active_route"] = route
            status["sensor_preview_route_kind"] = route.get("route_kind")
            status["sensor_preview_status"] = route.get("status")
            if route.get("media_mode") == "live_video":
                status["live_sensor_preview_uses_jpeg"] = False
        return statuses

    def list_preview_routes(self) -> list[dict[str, Any]]:
        return [item["sensor_preview"] for item in self.list_preview() if isinstance(item.get("sensor_preview"), dict)]

    def latest_preview_image(self, session_id: str) -> tuple[bytes, str] | None:
        return self.preview.latest_image(session_id)

    def preview_image_frame(self, session_id: str, *, frame_count: int | None = None) -> Any | None:
        return self.preview.image_frame(session_id, frame_count=frame_count)

    def preview_status(self, session_id: str) -> dict[str, Any] | None:
        return self.preview.status(session_id)

    def h264_live_status(self, session_id: str) -> dict[str, Any] | None:
        return self.rv101_h264_live.status(session_id)

    def deepstream_h264_live_status(self, session_id: str) -> dict[str, Any] | None:
        status = self.deepstream_h264_live.status(session_id)
        if not status:
            return None
        status = dict(status)
        status["h264_ws_url"] = f"/ws/preview/{session_id}/deepstream-h264"
        status["source"] = "deepstream_yolo26_osd"
        return status

    def active_processed_preview(self, session_id: str) -> dict[str, Any] | None:
        return self.stream_recorder.active_processed_preview(session_id)

    def subscribe_h264_live(self, session_id: str) -> Any:
        return self.rv101_h264_live.subscribe(session_id)

    def unsubscribe_h264_live(self, session_id: str, queue: Any) -> None:
        self.rv101_h264_live.unsubscribe(session_id, queue)

    def subscribe_deepstream_h264_live(self, session_id: str) -> Any:
        return self.deepstream_h264_live.subscribe(session_id)

    def unsubscribe_deepstream_h264_live(self, session_id: str, queue: Any) -> None:
        self.deepstream_h264_live.unsubscribe(session_id, queue)

    def list_recordings(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.stream_recorder.list_recordings(limit=limit)

    def finalize_recording(self, recording_id: str) -> dict[str, Any]:
        return self.stream_recorder.finalize_recording(recording_id)

    def record_preview_frame(
        self,
        *,
        session_id: str,
        image_bytes: bytes,
        source: str = "rv101_snapshot",
        width: int | None = None,
        height: int | None = None,
        frame_count: int = 1,
        content_type: str = "image/jpeg",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id or not self._session_exists(normalized_session_id):
            return {
                "status": "error",
                "error": {
                    "code": "unknown_session",
                    "message": f"Preview frame references an unknown session: {normalized_session_id}",
                },
            }
        if not image_bytes:
            return {
                "status": "error",
                "error": {
                    "code": "empty_preview_frame",
                    "message": "Preview frame upload body is empty.",
                },
            }
        if content_type not in {"image/jpeg", "image/png"}:
            return {
                "status": "error",
                "error": {
                    "code": "unsupported_preview_content_type",
                    "message": "Preview frame uploads must use image/jpeg or image/png.",
                    "details": {"content_type": content_type},
                },
            }
        clean_metadata = _clean_sensor_metadata(
            metadata,
            client_kind=self._session_client_kind(normalized_session_id),
            preview_width=width,
            preview_height=height,
        )
        preview = self.preview.record_frame(
            session_id=normalized_session_id,
            source=str(source or "rv101_snapshot"),
            image_bytes=image_bytes,
            width=width,
            height=height,
            frame_count=frame_count,
            content_type=content_type,
            metadata=clean_metadata,
        )
        self.media.record_video_sample(
            session_id=normalized_session_id,
            transport="rv101_snapshot",
            codec=content_type,
            payload_bytes=len(image_bytes),
            is_keyframe=True,
            width=width,
            height=height,
            metadata=clean_metadata,
        )
        if _preview_upload_is_still_capture(source):
            self.media.stop_video_stream(session_id=normalized_session_id, reason="preview_frame_uploaded")
        return {"status": "ok", "preview": preview}

    def identity_status(self) -> dict[str, Any]:
        return self.identity.status()

    def list_identity_contacts(self) -> list[dict[str, Any]]:
        return self.identity.list_contacts()

    def create_identity_contact(
        self,
        *,
        display_name: str,
        aliases: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self.identity.create_contact(display_name=display_name, aliases=aliases, notes=notes)

    def enroll_identity_sample(
        self,
        *,
        display_name: str | None = None,
        contact_id: str | None = None,
        aliases: list[str] | None = None,
        notes: str | None = None,
        image_ref: str | None = None,
        image_path: str | None = None,
        vector: list[float] | None = None,
        source_note: str | None = None,
    ) -> dict[str, Any]:
        return self.identity.enroll_sample(
            display_name=display_name,
            contact_id=contact_id,
            aliases=aliases,
            notes=notes,
            image_ref=image_ref,
            image_path=image_path,
            vector=vector,
            source_note=source_note,
        )

    def match_identity_candidates(
        self,
        *,
        candidates: list[dict[str, Any]],
        query: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self.identity.match_candidates(candidates=candidates, query=query, session_id=session_id)

    def people_status(self) -> dict[str, Any]:
        return self.people.status()

    def list_people(self) -> list[dict[str, Any]]:
        return self.people.list_people()

    def sync_people_from_immich(self, *, push_names: bool = False) -> dict[str, Any]:
        return self.people.sync_from_immich(push_names=push_names)

    def update_person_profile(
        self,
        *,
        person_id: str,
        display_name: str | None = None,
        aliases: list[str] | None = None,
        phone: str | None = None,
        address: str | None = None,
        age: str | None = None,
        where_lives: str | None = None,
        relationship: str | None = None,
        first_met: str | None = None,
        links: dict[str, Any] | None = None,
        facts: dict[str, Any] | None = None,
        notes: str | None = None,
        sync_name_to_immich: bool = False,
    ) -> dict[str, Any]:
        return self.people.update_person_profile(
            person_id=person_id,
            display_name=display_name,
            aliases=aliases,
            phone=phone,
            address=address,
            age=age,
            where_lives=where_lives,
            relationship=relationship,
            first_met=first_met,
            links=links,
            facts=facts,
            notes=notes,
            sync_name_to_immich=sync_name_to_immich,
        )

    def sync_person_name_to_immich(self, *, person_id: str) -> dict[str, Any]:
        return self.people.sync_person_name_to_immich(person_id)

    def person_thumbnail(self, *, person_id: str) -> tuple[bytes, str]:
        person = self.people.get_person(person_id)
        if person is None:
            raise ValueError("person_id was not found")
        thumbnail_ref = str(person.get("immich_thumbnail_ref") or person.get("thumbnail_ref") or "").strip()
        if not thumbnail_ref:
            raise ValueError("person has no Immich thumbnail_ref")
        return ImmichClient(self.people.immich_settings).fetch_bytes(thumbnail_ref)

    def enroll_person_identity_from_immich(
        self,
        *,
        person_id: str,
        display_name: str | None = None,
        aliases: list[str] | None = None,
        max_assets: int | None = None,
    ) -> dict[str, Any]:
        if display_name is not None or aliases is not None:
            self.people.update_person_profile(person_id=person_id, display_name=display_name, aliases=aliases)
        person = self.people.get_person(person_id)
        if person is None:
            raise ValueError("person_id was not found")
        name = str(person.get("display_name") or "").strip()
        if not name:
            raise ValueError("display_name is required before identity enrollment")
        thumbnail_ref = str(person.get("immich_thumbnail_ref") or person.get("thumbnail_ref") or "").strip()
        if not thumbnail_ref:
            raise ValueError("Immich thumbnail_ref is required before identity enrollment")
        client = ImmichClient(self.people.immich_settings)
        resolved_aliases = (
            aliases
            if aliases is not None
            else person.get("aliases")
            if isinstance(person.get("aliases"), list)
            else []
        )
        settings = load_face_identity_worker_settings()
        immich_person_id = str(person.get("immich_person_id") or "").strip()
        sample_results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        if immich_person_id and hasattr(client, "search_person_assets"):
            asset_samples, asset_failures = _enroll_identity_samples_from_immich_assets(
                client=client,
                identity=self.identity,
                settings=settings,
                display_name=name,
                aliases=resolved_aliases,
                immich_person_id=immich_person_id,
                max_assets=_people_identity_max_assets(max_assets),
            )
            sample_results.extend(asset_samples)
            failures.extend(asset_failures)

        try:
            image_bytes, content_type = client.fetch_bytes(thumbnail_ref)
            if not image_bytes:
                raise RuntimeError("Immich thumbnail was empty")
            vector = _extract_identity_vector_from_image_bytes(
                settings=settings,
                image_bytes=image_bytes,
                content_type=content_type,
            )
            sample_results.append(
                self.identity.enroll_sample(
                    display_name=name,
                    aliases=resolved_aliases,
                    vector=vector,
                    source_note=f"opencv_sface:immich_person:{immich_person_id or person_id}:thumbnail",
                )
            )
        except Exception as exc:
            failures.append(
                {
                    "source": "immich_person_thumbnail",
                    "reason": exc.__class__.__name__,
                    "message": str(exc),
                }
            )

        if not sample_results:
            reason = failures[-1]["message"] if failures else "No Immich face samples could be enrolled."
            raise RuntimeError(reason)

        latest_enrolled = sample_results[-1]
        contact = latest_enrolled.get("contact") if isinstance(latest_enrolled.get("contact"), dict) else {}
        result = {
            "status": "enrolled",
            "person_id": person_id,
            "immich_person_id": immich_person_id,
            "display_name": name,
            "identity": latest_enrolled,
            "sample_count_added_or_updated": len(sample_results),
            "contact_sample_count": contact.get("sample_count"),
            "failed_sample_count": len(failures),
            "failures": failures[:8],
            "image_storage": "temporary_immich_previews_deleted_after_embedding",
        }
        self.events.add(
            "people_registry",
            "identity_sample_enrolled_from_immich",
            {
                "person_id": person_id,
                "immich_person_id": immich_person_id,
                "display_name": name,
                "sample_count_added_or_updated": len(sample_results),
                "contact_sample_count": contact.get("sample_count"),
                "failed_sample_count": len(failures),
            },
        )
        return result

    def remember_person_from_latest_preview(
        self,
        *,
        session_id: str,
        display_name: str | None = None,
        aliases: list[str] | None = None,
        notes: str | None = None,
        enroll_identity: bool = False,
    ) -> dict[str, Any]:
        latest = self.preview.latest_image(session_id)
        if latest is None:
            raise ValueError("latest preview frame is required")
        image_bytes, content_type = latest
        preview = self.preview.status(session_id) or {}
        memory = self.people.remember_capture(
            image_bytes=image_bytes,
            content_type=content_type,
            session_id=session_id,
            display_name=display_name,
            aliases=aliases,
            notes=notes,
            source=str(preview.get("source") or "openvision_snapshot"),
        )
        identity_enrollment: dict[str, Any] = {
            "status": "skipped",
            "reason": "display_name_required" if not display_name else "not_requested",
        }
        if enroll_identity and display_name and memory.get("status") == "uploaded":
            suffix = ".png" if "png" in content_type.lower() else ".jpg"
            try:
                with tempfile.NamedTemporaryFile(prefix="openvision_memory_face_", suffix=suffix, delete=True) as temp_file:
                    temp_file.write(image_bytes)
                    temp_file.flush()
                    vector = extract_identity_vector_from_image_path(load_face_identity_worker_settings(), temp_file.name)
                identity_enrollment = self.identity.enroll_sample(
                    display_name=display_name,
                    aliases=aliases or [],
                    notes=notes,
                    vector=vector,
                    source_note=f"opencv_sface:remember_person:{memory.get('capture', {}).get('capture_id')}",
                )
            except Exception as exc:
                identity_enrollment = {
                    "status": "skipped",
                    "reason": "identity_provider_unavailable",
                    "message": str(exc),
                }
        result = {
            **memory,
            "identity_enrollment": identity_enrollment,
            "preview": preview,
        }
        self.events.add(
            "people_registry",
            "remember_person_completed",
            {
                "session_id": session_id,
                "status": result.get("status"),
                "capture_id": result.get("capture", {}).get("capture_id") if isinstance(result.get("capture"), dict) else None,
                "display_name": display_name,
                "identity_status": identity_enrollment.get("status"),
            },
            session_id=session_id,
            severity="warning" if result.get("status") != "uploaded" else "info",
        )
        return result

    def rv101_ingest_status(self) -> dict[str, Any]:
        return self.rv101_ingest.status()

    async def create_rv101_control_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = str(payload.get("deviceId") or "rv101")
        voice_output_enabled = _payload_bool(
            payload,
            "voiceOutput",
            "voice_output",
            default=bool(load_settings()["realtime_voice_output_enabled"]),
        )
        voice_mode = _rv101_voice_mode_from_payload(payload)
        turn_policy = _rv101_turn_policy_for_voice_mode(voice_mode)
        output_modalities = ["audio"] if voice_output_enabled else ["text"]
        session = self._resume_parked_rv101_device_session(
            device_id=device_id,
            turn_policy=turn_policy,
            output_modalities=output_modalities,
        )
        resumed = session is not None
        if not session:
            await self._stop_parked_rv101_device_sessions(
                device_id=device_id,
                reason="rv101_device_reconnected_new_realtime_required",
            )
            await self._supersede_existing_rv101_device_sessions(device_id=device_id)
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
            realtime = await self.realtime.start(
                session_id=str(session["session_id"]),
                turn_policy=turn_policy,
                output_modalities=output_modalities,
                voice_output=voice_output_enabled,
            )
        else:
            realtime = self.realtime.status(str(session["session_id"])) or {"status": "connected"}
            self.stream_recorder.allow_session_reopen(str(session["session_id"]))
            self._rv101_recording_close_requested_sessions.discard(str(session["session_id"]))
        voice_output_contract = _rv101_voice_output_contract(
            session_id=str(session["session_id"]),
            enabled=voice_output_enabled,
            output_modalities=output_modalities,
        )
        accept = {
            "type": "session_accept",
            "sessionId": session["session_id"],
            "voiceMode": voice_mode,
            "voice_mode": voice_mode,
            "turnPolicy": turn_policy,
            "turn_policy": turn_policy,
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
            "voiceOutput": voice_output_contract,
            "voice_output": voice_output_contract,
        }
        self.events.add(
            "rv101_control",
            "session_resumed" if resumed else "session_accept",
            {
                "device_id": device_id,
                "realtime_status": realtime["status"],
                "media": accept["media"],
                "audio": accept["audio"],
                "voice_output": voice_output_contract,
                "voice_mode": voice_mode,
                "turn_policy": turn_policy,
                "reused_realtime_session": resumed,
            },
            session_id=str(session["session_id"]),
        )
        return {
            "session": session,
            "accept": accept,
            "hud_scene": self._rv101_ready_hud(session_id=str(session["session_id"])),
        }

    async def _supersede_existing_rv101_device_sessions(self, *, device_id: str) -> None:
        superseded_sessions = self.sessions.supersede_active_device_sessions(
            client_kind="rv101_glasses",
            device_id=device_id,
        )
        for superseded in superseded_sessions:
            old_session_id = str(superseded.get("session_id") or "").strip()
            if not old_session_id:
                continue
            self._cancel_rv101_reconnect_grace(old_session_id)
            self.events.add(
                "sessions",
                "superseded",
                {
                    "device_id": device_id,
                    "client_kind": "rv101_glasses",
                    "reason": "rv101_device_reconnected",
                },
                session_id=old_session_id,
                severity="warning",
            )
            await self._cleanup_rv101_session_runtime(
                old_session_id,
                reason="rv101_device_reconnected",
                stop_failure_event="supersede_stop_failed",
            )

    def _rv101_realtime_turn_policy(self, session_id: str) -> str:
        status = self.realtime.status(session_id) or {}
        return str(status.get("turn_policy") or "").strip().lower()

    async def close_rv101_control_session(
        self,
        session_id: str,
        *,
        reason: str = "rv101_websocket_disconnected",
    ) -> None:
        session = self.sessions.mark_inactive(session_id, status="disconnected")
        previous_status = str((session or {}).get("status") or "").lower()
        self.events.add(
            "rv101_control",
            "disconnected",
            {"reason": reason, "session_status": previous_status or None},
            session_id=session_id,
        )
        if session:
            self.events.add(
                "sessions",
                "disconnected",
                {"reason": reason, "status": session.get("status")},
                session_id=session_id,
            )
        await self._park_rv101_session_runtime(
            session_id,
            reason=reason,
            stop_failure_event="disconnect_stop_failed",
        )

    async def close_rv101_app_session(
        self,
        session_id: str,
        *,
        reason: str = "rv101_app_exit",
    ) -> None:
        session = self.sessions.mark_inactive(session_id, status="closed")
        self.events.add(
            "rv101_control",
            "app_session_closed",
            {"reason": reason, "session_status": (session or {}).get("status")},
            session_id=session_id,
        )
        if session:
            self.events.add(
                "sessions",
                "closed",
                {"reason": reason, "status": session.get("status")},
                session_id=session_id,
            )
        await self._cleanup_rv101_session_runtime(
            session_id,
            reason=reason,
            stop_failure_event="app_exit_stop_failed",
        )

    def _resume_parked_rv101_device_session(
        self,
        *,
        device_id: str,
        turn_policy: str,
        output_modalities: list[str],
    ) -> dict[str, Any] | None:
        clean_device_id = str(device_id or "").strip()
        if not clean_device_id:
            return None
        wanted_output = list(output_modalities or [])
        for session in reversed(self.sessions.list()):
            session_id = str(session.get("session_id") or "").strip()
            if not session_id or session_id not in self._rv101_reconnect_grace_tasks:
                continue
            capabilities = session.get("capabilities") if isinstance(session.get("capabilities"), dict) else {}
            if str(capabilities.get("device_id") or "").strip() != clean_device_id:
                continue
            realtime = self.realtime.status(session_id) or {}
            if not _realtime_active(realtime):
                continue
            if str(realtime.get("turn_policy") or "").strip().lower() != turn_policy:
                continue
            if list(realtime.get("output_modalities") or []) != wanted_output:
                continue
            self._cancel_rv101_reconnect_grace(session_id)
            resumed = self.sessions.touch(session_id, status="connected") or session
            self.events.add(
                "sessions",
                "resumed",
                {
                    "device_id": clean_device_id,
                    "client_kind": "rv101_glasses",
                    "reason": "rv101_device_reconnected_within_grace",
                },
                session_id=session_id,
            )
            return resumed
        return None

    async def _stop_parked_rv101_device_sessions(self, *, device_id: str, reason: str) -> None:
        clean_device_id = str(device_id or "").strip()
        if not clean_device_id:
            return
        for session in reversed(self.sessions.list()):
            session_id = str(session.get("session_id") or "").strip()
            if not session_id or session_id not in self._rv101_reconnect_grace_tasks:
                continue
            capabilities = session.get("capabilities") if isinstance(session.get("capabilities"), dict) else {}
            if str(capabilities.get("device_id") or "").strip() != clean_device_id:
                continue
            self._cancel_rv101_reconnect_grace(session_id)
            await self._stop_parked_rv101_realtime(
                session_id,
                reason=reason,
                event_type="reconnect_replaced_parked_realtime",
                stop_failure_event="replace_parked_stop_failed",
            )

    async def _park_rv101_session_runtime(
        self,
        session_id: str,
        *,
        reason: str,
        stop_failure_event: str,
    ) -> None:
        self.debug_stt.flush_session(session_id, reason=reason)
        self.stream_recorder.close_session(session_id, reason=reason)
        self.media.close_session(session_id)
        self.preview.remove_session(session_id)
        self.perception.clear_session(session_id, reason=reason)
        self.yolo26_stabilizer.clear_session(session_id, reason=reason)
        self.rv101_h264_live.close_session(session_id)
        self.deepstream_h264_live.close_session(session_id)
        self.rv101_h264_preview.close_session(session_id)
        self._rv101_audio_gates.pop(session_id, None)
        self._rv101_stale_audio_logged.discard(session_id)
        self._rv101_ptt_started_s.pop(session_id, None)
        self._rv101_audio_last_chunk_s.pop(session_id, None)
        self._rv101_audio_closed_s.pop(session_id, None)
        realtime = self.realtime.status(session_id) or {}
        if not _realtime_active(realtime):
            return
        grace_s = _rv101_realtime_reconnect_grace_s()
        if grace_s <= 0:
            await self._stop_parked_rv101_realtime(
                session_id,
                reason=reason,
                event_type="reconnect_grace_disabled",
                stop_failure_event=stop_failure_event,
            )
            return
        self._cancel_rv101_reconnect_grace(session_id)
        self.events.add(
            "rv101_control",
            "realtime_parked",
            {"reason": reason, "grace_s": grace_s},
            session_id=session_id,
        )
        self._rv101_reconnect_grace_tasks[session_id] = asyncio.create_task(
            self._expire_rv101_reconnect_grace(
                session_id,
                grace_s=grace_s,
                reason=reason,
                stop_failure_event=stop_failure_event,
            )
        )

    async def _expire_rv101_reconnect_grace(
        self,
        session_id: str,
        *,
        grace_s: float,
        reason: str,
        stop_failure_event: str,
    ) -> None:
        try:
            await asyncio.sleep(grace_s)
            session = self.sessions.get(session_id) or {}
            if _session_active(session):
                return
            await self._stop_parked_rv101_realtime(
                session_id,
                reason=reason,
                event_type="reconnect_grace_expired",
                stop_failure_event=stop_failure_event,
            )
        except asyncio.CancelledError:
            raise
        finally:
            task = self._rv101_reconnect_grace_tasks.get(session_id)
            if task is asyncio.current_task():
                self._rv101_reconnect_grace_tasks.pop(session_id, None)

    async def _stop_parked_rv101_realtime(
        self,
        session_id: str,
        *,
        reason: str,
        event_type: str,
        stop_failure_event: str,
    ) -> None:
        self.events.add(
            "rv101_control",
            event_type,
            {"reason": reason},
            session_id=session_id,
        )
        try:
            await self.realtime.stop(session_id)
        except RuntimeError as exc:
            self.events.add(
                "realtime",
                stop_failure_event,
                {"message": f"{exc.__class__.__name__}: {exc}"},
                session_id=session_id,
                severity="warning",
            )

    def _cancel_rv101_reconnect_grace(self, session_id: str) -> None:
        task = self._rv101_reconnect_grace_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()

    async def _cleanup_rv101_session_runtime(
        self,
        session_id: str,
        *,
        reason: str,
        stop_failure_event: str,
    ) -> None:
        self._cancel_rv101_reconnect_grace(session_id)
        self.debug_stt.flush_session(session_id, reason=reason)
        self.media_commands.close_session(session_id, reason=reason)
        self.stream_recorder.close_session(session_id, reason=reason)
        self.media.close_session(session_id)
        self.preview.remove_session(session_id)
        self.perception.clear_session(session_id, reason=reason)
        self.yolo26_stabilizer.clear_session(session_id, reason=reason)
        self.rv101_h264_live.close_session(session_id)
        self.deepstream_h264_live.close_session(session_id)
        self.rv101_h264_preview.close_session(session_id)
        self._rv101_audio_gates.pop(session_id, None)
        self._rv101_stale_audio_logged.discard(session_id)
        self._rv101_ptt_started_s.pop(session_id, None)
        self._rv101_audio_last_chunk_s.pop(session_id, None)
        self._rv101_audio_closed_s.pop(session_id, None)
        try:
            await self.realtime.stop(session_id)
        except RuntimeError as exc:
            self.events.add(
                "realtime",
                stop_failure_event,
                {"message": f"{exc.__class__.__name__}: {exc}"},
                session_id=session_id,
                severity="warning",
            )

    def _rv101_video_ingest_allowed(self, session_id: str, header: dict[str, Any], message_type: int) -> bool:
        _ = header, message_type
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id or not self._session_is_active(normalized_session_id):
            return False
        return any(
            item.get("session_id") == normalized_session_id
            for item in self.media_commands.active_live_statuses()
        )

    def _handle_rv101_h264_sample(
        self,
        *,
        session_id: str,
        header: dict[str, Any],
        payload: bytes,
        media_status: dict[str, Any],
    ) -> None:
        self.rv101_h264_live.publish_sample(
            session_id=session_id,
            header=header,
            payload=payload,
            media_status=media_status,
        )
        if self._rv101_h264_preview_decode_allowed(session_id=session_id):
            self.rv101_h264_preview.enqueue_sample(
                session_id=session_id,
                header=header,
                payload=payload,
                media_status=media_status,
            )
        else:
            self._record_rv101_h264_preview_decode_skipped(session_id=session_id)

    def ingest_deepstream_h264_sample(
        self,
        *,
        session_id: str,
        header: dict[str, Any],
        payload: bytes,
    ) -> dict[str, Any]:
        sample_header = dict(header or {})
        if not self._active_live_context_for_adapter(session_id=session_id, adapter="yolo26"):
            self._sync_stopped_live_media()
            stale_status = self.deepstream_h264_live.status(session_id)
            self.deepstream_h264_live.close_session(session_id)
            if stale_status:
                self.events.add(
                    "deepstream_h264_live",
                    "sample_ignored",
                    {
                        "reason": "inactive_live_skill",
                        "sequence": sample_header.get("sequence"),
                        "payload_bytes": len(payload or b""),
                        "closed_stale_sample_count": stale_status.get("sample_count"),
                    },
                    session_id=session_id,
                    severity="info",
                )
            return {
                "status": "ignored",
                "published": False,
                "reason": "inactive_live_skill",
                "session_id": session_id,
            }
        media_status = self.media.status(session_id) or {}
        result = self.deepstream_h264_live.publish_sample(
            session_id=session_id,
            header={
                **sample_header,
                "source": "deepstream_yolo26_osd",
                "transport": "deepstream_rtsp_h264",
            },
            payload=payload,
            media_status=media_status,
        )
        if result.get("sample_count") in {1, 30} or bool(
            sample_header.get("isKeyframe") or sample_header.get("is_keyframe")
        ):
            self.events.add(
                "deepstream_h264_live",
                "sample_published",
                {
                    "sequence": sample_header.get("sequence"),
                    "is_keyframe": bool(sample_header.get("isKeyframe") or sample_header.get("is_keyframe")),
                    "payload_bytes": len(payload or b""),
                    "width": sample_header.get("width"),
                    "height": sample_header.get("height"),
                },
                session_id=session_id,
            )
        return result

    def _close_rv101_video_stream(self, session_id: str) -> None:
        self.media.stop_video_stream(session_id=session_id, reason="rv101_tcp_video_disconnected")
        self.rv101_h264_live.close_session(session_id)
        self.deepstream_h264_live.close_session(session_id)
        self.rv101_h264_preview.close_session(session_id)
        self.perception.clear_sources(
            session_id=session_id,
            source_markers={"yolo26", "face_identity"},
            reason="rv101_tcp_video_disconnected",
        )
        self.yolo26_stabilizer.clear_session(session_id, reason="rv101_tcp_video_disconnected")
        self._close_rv101_recording_if_media_idle(session_id, reason="rv101_tcp_video_disconnected")

    async def _cleanup_closed_session_runtime(
        self,
        session_id: str,
        *,
        reason: str,
        stop_failure_event: str,
    ) -> None:
        self._cancel_rv101_reconnect_grace(session_id)
        self.debug_stt.flush_session(session_id, reason=reason)
        self.media_commands.close_session(session_id, reason=reason)
        self.stream_recorder.close_session(session_id, reason=reason)
        self.media.close_session(session_id)
        self.preview.remove_session(session_id)
        self.perception.clear_session(session_id, reason=reason)
        self.yolo26_stabilizer.clear_session(session_id, reason=reason)
        self.rv101_h264_live.close_session(session_id)
        self.deepstream_h264_live.close_session(session_id)
        self.rv101_h264_preview.close_session(session_id)
        self._simulator_audio_gates.pop(session_id, None)
        self._rv101_audio_gates.pop(session_id, None)
        self._rv101_stale_audio_logged.discard(session_id)
        self._rv101_ptt_started_s.pop(session_id, None)
        self._rv101_audio_last_chunk_s.pop(session_id, None)
        self._rv101_audio_closed_s.pop(session_id, None)
        try:
            await self.realtime.stop(session_id)
        except RuntimeError as exc:
            self.events.add(
                "realtime",
                stop_failure_event,
                {"message": f"{exc.__class__.__name__}: {exc}"},
                session_id=session_id,
                severity="warning",
            )

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
        if not self._session_is_active(session_id):
            self.events.add(
                "rv101_control",
                "stale_session_message_ignored",
                {"type": message_type},
                session_id=session_id,
                severity="warning",
            )
            return []
        if _rv101_client_goodbye_message(payload):
            reason = _rv101_client_goodbye_reason(payload, default=message_type)
            await self.close_rv101_app_session(session_id, reason=reason)
            return [{"type": "session_closed", "sessionId": session_id, "reason": reason}]
        if message_type == "encoder_stats":
            self.media.record_video_heartbeat(
                session_id=session_id,
                transport="rv101_tcp",
                codec="video/avc",
                width=_to_int(payload.get("width")),
                height=_to_int(payload.get("height")),
                fps=_to_float(payload.get("encodeFps") or payload.get("targetFps")),
                metadata=_sensor_metadata_from_payload(
                    payload,
                    client_kind=self._session_client_kind(session_id),
                    preview_width=_to_int(payload.get("width")),
                    preview_height=_to_int(payload.get("height")),
                ),
            )
        elif message_type == "audio_stats":
            self.events.add(
                "rv101_control",
                "audio_stats",
                {
                    "sentChunks": payload.get("sentChunks"),
                    "sentBytes": payload.get("sentBytes"),
                    "avgAbs": payload.get("avgAbs"),
                    "peakAbs": payload.get("peakAbs"),
                    "nonSilentRatio": payload.get("nonSilentRatio"),
                    "captureSampleRateHz": payload.get("captureSampleRateHz"),
                    "wireSampleRateHz": payload.get("wireSampleRateHz"),
                    "audioSource": payload.get("audioSource"),
                },
                session_id=session_id,
            )
        elif message_type == "ptt_down":
            self._rv101_ptt_started_s[session_id] = time.monotonic()
            self._rv101_audio_last_chunk_s.pop(session_id, None)
            self._rv101_audio_closed_s.pop(session_id, None)
            turn_policy = self._rv101_realtime_turn_policy(session_id)
            if turn_policy == "server_vad":
                self.events.add(
                    "rv101_control",
                    "ptt_down_observed_server_vad",
                    {"turn_policy": turn_policy, "action": "no_manual_clear"},
                    session_id=session_id,
                )
            else:
                try:
                    await self.realtime.clear_audio(session_id=session_id)
                except RuntimeError:
                    pass
                self.events.add("rv101_control", "ptt_down", {"turn_policy": turn_policy or "unknown"}, session_id=session_id)
        elif message_type == "ptt_up":
            turn_policy = self._rv101_realtime_turn_policy(session_id)
            if turn_policy == "server_vad":
                self.events.add(
                    "rv101_control",
                    "ptt_up_observed_server_vad",
                    {"turn_policy": turn_policy, "action": "no_manual_commit"},
                    session_id=session_id,
                )
            else:
                await self._wait_for_rv101_audio_drain(session_id=session_id)
                try:
                    await self.realtime.commit_audio(session_id=session_id)
                except RuntimeError:
                    pass
                self.events.add("rv101_control", "ptt_up", {"turn_policy": turn_policy or "unknown"}, session_id=session_id)
        elif message_type == "glasses_health":
            self._record_rv101_health_if_needed(session_id=session_id, payload=payload)
            if _rv101_health_indicates_app_exit(payload):
                reason = _rv101_client_goodbye_reason(payload, default="glasses_health_app_exit")
                await self.close_rv101_app_session(session_id, reason=reason)
                return [{"type": "session_closed", "sessionId": session_id, "reason": reason}]
        else:
            self.events.add(
                "rv101_control",
                message_type,
                {"payload": _compact_payload(payload)},
                session_id=session_id,
            )
        return []

    def _record_rv101_health_if_needed(self, *, session_id: str, payload: dict[str, Any]) -> None:
        summary = _rv101_health_summary(payload)
        signature = _rv101_health_signature(summary)
        now_s = time.monotonic()
        last_signature = self._rv101_health_signature.get(session_id)
        last_log_s = self._rv101_health_log_s.get(session_id)
        changed = signature != last_signature
        due_summary = last_log_s is None or now_s - last_log_s >= RV101_HEALTH_LOG_INTERVAL_S
        if not changed and not due_summary:
            return
        self._rv101_health_signature[session_id] = signature
        self._rv101_health_log_s[session_id] = now_s
        self.events.add(
            "rv101_control",
            "glasses_health",
            {
                **summary,
                "log_reason": "changed" if changed else "periodic_summary",
            },
            session_id=session_id,
        )

    def update_perception(
        self,
        *,
        session_id: str,
        detections: list[dict[str, Any]],
        source: str,
        frame_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = self.perception.update_snapshot(
            session_id=session_id,
            detections=detections,
            source=source,
            frame_id=frame_id,
            width=width,
            height=height,
            metadata=_clean_sensor_metadata(
                metadata,
                client_kind=self._session_client_kind(session_id),
                preview_width=width,
                preview_height=height,
            ),
        )
        self._record_processed_perception_preview(session_id=session_id, snapshot=snapshot)
        return snapshot

    def ingest_debug_perception_snapshot(
        self,
        *,
        session_id: str,
        detections: list[dict[str, Any]],
        source: str,
        frame_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_session_id = str(session_id or "").strip()
        clean_source = str(source or "").strip() or "debug_perception"
        if not clean_session_id or not self._session_is_active(clean_session_id):
            self.events.add(
                "perception",
                "debug_snapshot_rejected",
                {"reason": "inactive_or_unknown_session", "source": clean_source, "frame_id": frame_id},
                session_id=clean_session_id or None,
                severity="warning",
            )
            return {
                "status": "error",
                "error": {
                    "code": "inactive_or_unknown_session",
                    "message": "Debug perception ingestion requires an active Jetson session.",
                },
            }
        snapshot = self.update_perception(
            session_id=clean_session_id,
            detections=detections,
            source=clean_source,
            frame_id=frame_id,
            width=width,
            height=height,
            metadata={**dict(metadata or {}), "debug_ingest": True},
        )
        return {"status": "accepted", "perception": snapshot}

    def list_perception(self) -> list[dict[str, Any]]:
        return self.perception.list_latest()

    def subscribe_perception(self, session_id: str | None = None) -> Any:
        return self.perception.subscribe(session_id)

    def unsubscribe_perception(self, queue: Any, session_id: str | None = None) -> None:
        self.perception.unsubscribe(queue, session_id)

    def perception_history(self, session_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return self.perception.recent_snapshots(session_id=session_id, limit=limit)

    def _record_processed_perception_preview(self, *, session_id: str, snapshot: dict[str, Any]) -> None:
        frame_count = _frame_count_from_perception_snapshot(snapshot)
        frame = self.preview.image_frame(session_id, frame_count=frame_count) if frame_count is not None else None
        if frame is None:
            frame = self.preview.image_frame(session_id)
        if frame is None:
            return
        self.stream_recorder.record_processed_preview(
            session_id=session_id,
            image_bytes=frame.image_bytes,
            frame_count=int(frame.frame_count or frame_count or 0),
            width=frame.width,
            height=frame.height,
            perception=snapshot,
        )

    def _record_review_preview_frame(
        self,
        *,
        session_id: str,
        image_bytes: bytes,
        frame_count: int,
        metadata: dict[str, Any],
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        snapshot = self.perception.latest(session_id) or {
            "source": "rv101_live_h264_preview",
            "objects": [],
            "frame_id": f"preview_{frame_count}",
            "width": width,
            "height": height,
            "metadata": dict(metadata or {}),
        }
        snapshot = _snapshot_with_preview_alignment(snapshot, preview_frame_count=frame_count)
        self.stream_recorder.record_processed_preview(
            session_id=session_id,
            image_bytes=image_bytes,
            frame_count=int(frame_count or 0),
            width=width,
            height=height,
            perception=snapshot,
        )

    def yolo26_status(self) -> dict[str, Any]:
        return self.yolo26.status()

    def face_identity_status(self) -> dict[str, Any]:
        return self.face_identity.status()

    def ingest_yolo26_snapshot(
        self,
        *,
        session_id: str,
        detections: list[dict[str, Any]],
        source: str,
        frame_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_source = str(source or "")
        normalized_source = _normalize_yolo26_source_for_session(
            raw_source,
            client_kind=self._session_client_kind(session_id),
        )
        accepted = self.yolo26.validate_external_snapshot(source=normalized_source)
        if accepted["status"] != "accepted":
            return accepted
        session_error = self._validate_adapter_ingress_session(
            adapter="yolo26",
            ingress_kind="snapshot",
            session_id=session_id,
            source=normalized_source,
            frame_id=frame_id,
        )
        if session_error:
            return session_error
        filtered_detections = self.yolo26.filter_detections(
            detections,
            min_confidence=float(accepted["min_confidence"]),
        )
        snapshot = self.perception.update_snapshot(
            session_id=session_id,
            detections=filtered_detections,
            source=str(accepted["source"]),
            frame_id=frame_id,
            width=width,
            height=height,
            metadata=_clean_sensor_metadata(
                metadata,
                client_kind=self._session_client_kind(session_id),
                detector_width=width,
                detector_height=height,
                raw_source=raw_source if raw_source != normalized_source else None,
                normalized_source=normalized_source,
            ),
        )
        self._record_processed_perception_preview(session_id=session_id, snapshot=snapshot)
        self.events.add(
            "adapter.yolo26",
            "snapshot_accepted",
            {
                "objects": len(filtered_detections),
                "rejected_low_confidence": len(detections) - len(filtered_detections),
                "frame_id": frame_id,
                "source": normalized_source,
                "raw_source": raw_source if raw_source != normalized_source else None,
                "min_confidence": accepted["min_confidence"],
            },
            session_id=session_id,
        )
        return {
            "status": "accepted",
            "adapter": accepted["adapter"],
            "source": accepted["source"],
            "min_confidence": accepted["min_confidence"],
            "accepted_detection_count": len(filtered_detections),
            "rejected_detection_count": len(detections) - len(filtered_detections),
            "perception": snapshot,
        }

    def ingest_yolo26_stream_frame(
        self,
        *,
        session_id: str,
        detections: list[dict[str, Any]],
        source: str,
        frame_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
        sequence: int | None = None,
        latency_ms: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_source = str(source or "")
        normalized_source = _normalize_yolo26_source_for_session(
            raw_source,
            client_kind=self._session_client_kind(session_id),
        )
        accepted = self.yolo26.validate_external_stream(source=normalized_source)
        if accepted["status"] != "accepted":
            return accepted
        session_error = self._validate_adapter_ingress_session(
            adapter="yolo26",
            ingress_kind="stream",
            session_id=session_id,
            source=normalized_source,
            frame_id=frame_id,
        )
        if session_error:
            return session_error
        live_error = self._validate_adapter_stream_live_context(
            adapter="yolo26",
            session_id=session_id,
            source=normalized_source,
            frame_id=frame_id,
        )
        if live_error:
            return live_error
        filtered_detections = self.yolo26.filter_detections(
            detections,
            min_confidence=float(accepted["min_confidence"]),
        )
        stable_detections, stable_metrics = self.yolo26_stabilizer.stabilize(
            session_id=session_id,
            source=str(accepted["source"]),
            detections=filtered_detections,
            frame_id=frame_id,
            width=width,
            height=height,
            sequence=sequence,
        )
        snapshot = self.perception.update_snapshot(
            session_id=session_id,
            detections=stable_detections,
            source=str(accepted["source"]),
            frame_id=frame_id,
            width=width,
            height=height,
            metadata=_clean_sensor_metadata(
                metadata,
                client_kind=self._session_client_kind(session_id),
                detector_width=width,
                detector_height=height,
                bbox_coordinate_space="yolo26_detector_frame",
                perception_branch=BRANCH_YOLO26_OBJECTS,
                preview_route_kind="stable_overlay_h264",
                bbox_authority="perception_graph_stable",
                overlay_policy="stable_perception_overlay",
                yolo26_stabilizer=stable_metrics,
                source_frame_id=frame_id,
                video_sequence=sequence,
                detection_latency_ms=latency_ms,
                raw_source=raw_source if raw_source != normalized_source else None,
                normalized_source=normalized_source,
            ),
        )
        self.events.add(
            "adapter.yolo26",
            "stream_frame_accepted",
            {
                "objects": len(stable_detections),
                "raw_accepted_objects": len(filtered_detections),
                "rejected_low_confidence": len(detections) - len(filtered_detections),
                "stable_metrics": stable_metrics,
                "frame_id": frame_id,
                "sequence": sequence,
                "latency_ms": latency_ms,
                "source": normalized_source,
                "raw_source": raw_source if raw_source != normalized_source else None,
                "min_confidence": accepted["min_confidence"],
            },
            session_id=session_id,
        )
        response = {
            "status": "accepted",
            "adapter": accepted["adapter"],
            "source": accepted["source"],
            "min_confidence": accepted["min_confidence"],
            "accepted_detection_count": len(stable_detections),
            "raw_accepted_detection_count": len(filtered_detections),
            "rejected_detection_count": len(detections) - len(filtered_detections),
            "stabilizer": stable_metrics,
            "frame_id": frame_id,
            "sequence": sequence,
            "latency_ms": latency_ms,
            "perception": snapshot,
        }
        continuation = self._continue_live_skill_after_yolo26_stream(
            session_id=session_id,
            source=str(accepted["source"]),
            frame_id=frame_id,
        )
        if continuation:
            response["continuation"] = continuation
        return response

    def ingest_face_identity_stream_frame(
        self,
        *,
        session_id: str,
        detections: list[dict[str, Any]],
        source: str,
        frame_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
        sequence: int | None = None,
        latency_ms: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_source = str(source or "")
        normalized_source = _normalize_face_identity_source_for_session(
            raw_source,
            client_kind=self._session_client_kind(session_id),
        )
        accepted = self.face_identity.validate_external_stream(source=normalized_source)
        if accepted["status"] != "accepted":
            return accepted
        session_error = self._validate_adapter_ingress_session(
            adapter="face_identity",
            ingress_kind="stream",
            session_id=session_id,
            source=normalized_source,
            frame_id=frame_id,
        )
        if session_error:
            return session_error
        live_error = self._validate_adapter_stream_live_context(
            adapter="face_identity",
            session_id=session_id,
            source=normalized_source,
            frame_id=frame_id,
        )
        if live_error:
            return live_error
        filtered_detections = self.face_identity.filter_detections(
            detections,
            min_confidence=float(accepted["min_confidence"]),
        )
        snapshot = self.perception.update_snapshot(
            session_id=session_id,
            detections=filtered_detections,
            source=str(accepted["source"]),
            frame_id=frame_id,
            width=width,
            height=height,
            metadata=_clean_sensor_metadata(
                metadata,
                client_kind=self._session_client_kind(session_id),
                detector_width=width,
                detector_height=height,
                bbox_coordinate_space="face_identity_frame",
                perception_branch=BRANCH_FACE_IDENTITY,
                preview_route_kind="raw_h264",
                source_frame_id=frame_id,
                video_sequence=sequence,
                detection_latency_ms=latency_ms,
                raw_source=raw_source if raw_source != normalized_source else None,
                normalized_source=normalized_source,
            ),
        )
        self.events.add(
            "adapter.face_identity",
            "stream_frame_accepted",
            {
                "objects": len(filtered_detections),
                "rejected_low_confidence": len(detections) - len(filtered_detections),
                "frame_id": frame_id,
                "sequence": sequence,
                "latency_ms": latency_ms,
                "source": normalized_source,
                "raw_source": raw_source if raw_source != normalized_source else None,
                "min_confidence": accepted["min_confidence"],
            },
            session_id=session_id,
        )
        response = {
            "status": "accepted",
            "adapter": accepted["adapter"],
            "source": accepted["source"],
            "min_confidence": accepted["min_confidence"],
            "accepted_detection_count": len(filtered_detections),
            "rejected_detection_count": len(detections) - len(filtered_detections),
            "frame_id": frame_id,
            "sequence": sequence,
            "latency_ms": latency_ms,
            "perception": snapshot,
        }
        continuation = self._continue_live_skill_after_face_identity_stream(
            session_id=session_id,
            source=str(accepted["source"]),
            frame_id=frame_id,
        )
        if continuation:
            response["continuation"] = continuation
        return response

    def _continue_live_skill_after_yolo26_stream(
        self,
        *,
        session_id: str,
        source: str,
        frame_id: str | None,
    ) -> dict[str, Any] | None:
        context = self._active_live_skill_context(session_id=session_id, skill_id="target_finder")
        if not context:
            return None
        command = context["command"]
        command_id = str(command.get("command_id") or "").strip()
        throttle_key = f"{session_id}:{command_id}:target_finder"
        now_s = time.monotonic()
        last_s = self._last_stream_skill_update_s.get(throttle_key)
        if last_s is not None and now_s - last_s < LIVE_YOLO26_SKILL_UPDATE_INTERVAL_S:
            return None
        self._last_stream_skill_update_s[throttle_key] = now_s
        args = context["args"]
        continuation = self.skill_executor.execute(name="target_finder", args=args, session_id=session_id)
        self.hud.update_from_skill_result(continuation)
        self.events.add(
            "skills",
            "yolo26_stream_continuation_completed",
            {
                "name": "target_finder",
                "status": continuation.get("status"),
                "media_command_id": command_id,
                "frame_id": frame_id,
                "source": source,
            },
            session_id=session_id,
            severity="error" if continuation.get("status") == "error" else "info",
        )
        return continuation

    def _continue_live_skill_after_face_identity_stream(
        self,
        *,
        session_id: str,
        source: str,
        frame_id: str | None,
    ) -> dict[str, Any] | None:
        context = self._active_live_skill_context(session_id=session_id, skill_id="target_finder")
        skill_id = "target_finder"
        if not context:
            context = self._active_live_skill_context(session_id=session_id, skill_id="person_info")
            skill_id = "person_info" if context else skill_id
        if not context:
            return None
        command = context["command"]
        command_id = str(command.get("command_id") or "").strip()
        throttle_key = f"{session_id}:{command_id}:{skill_id}:face_identity"
        now_s = time.monotonic()
        last_s = self._last_stream_skill_update_s.get(throttle_key)
        if last_s is not None and now_s - last_s < LIVE_FACE_IDENTITY_SKILL_UPDATE_INTERVAL_S:
            return None
        self._last_stream_skill_update_s[throttle_key] = now_s
        args = context["args"]
        continuation = self.skill_executor.execute(name=skill_id, args=args, session_id=session_id)
        self.hud.update_from_skill_result(continuation)
        self.events.add(
            "skills",
            "face_identity_stream_continuation_completed",
            {
                "name": skill_id,
                "status": continuation.get("status"),
                "media_command_id": command_id,
                "frame_id": frame_id,
                "source": source,
            },
            session_id=session_id,
            severity="error" if continuation.get("status") == "error" else "info",
        )
        return continuation

    def _validate_adapter_ingress_session(
        self,
        *,
        adapter: str,
        ingress_kind: str,
        session_id: str,
        source: str,
        frame_id: str | None,
    ) -> dict[str, Any] | None:
        clean_session_id = str(session_id or "").strip()
        if clean_session_id and self._session_exists(clean_session_id):
            return None
        return self._adapter_ingress_error(
            adapter=adapter,
            ingress_kind=ingress_kind,
            code="unknown_session",
            message="Adapter ingress requires an existing Jetson session.",
            session_id=clean_session_id or None,
            source=source,
            frame_id=frame_id,
        )

    def _validate_adapter_stream_live_context(
        self,
        *,
        adapter: str,
        session_id: str,
        source: str,
        frame_id: str | None,
    ) -> dict[str, Any] | None:
        if self._active_live_context_for_adapter(session_id=session_id, adapter=adapter):
            return None
        return self._adapter_ingress_error(
            adapter=adapter,
            ingress_kind="stream",
            code="inactive_live_skill",
            message=f"Stream adapter frames are accepted only while an active live_video command declares the {adapter} perception branch.",
            session_id=session_id,
            source=source,
            frame_id=frame_id,
        )

    def _adapter_ingress_error(
        self,
        *,
        adapter: str,
        ingress_kind: str,
        code: str,
        message: str,
        session_id: str | None,
        source: str,
        frame_id: str | None,
    ) -> dict[str, Any]:
        self.events.add(
            f"adapter.{adapter}",
            f"{ingress_kind}_rejected",
            {
                "reason": code,
                "source": source,
                "frame_id": frame_id,
            },
            session_id=session_id,
            severity="info" if code == "inactive_live_skill" else "warning",
        )
        return {
            "status": "error",
            "adapter": adapter,
            "error": {
                "code": code,
                "message": message,
            },
        }

    def _active_live_skill_context(self, *, session_id: str, skill_id: str) -> dict[str, Any] | None:
        for item in reversed(self.media_commands.statuses()):
            if not item.get("active"):
                continue
            command = item.get("command") if isinstance(item.get("command"), dict) else {}
            event = item.get("event") if isinstance(item.get("event"), dict) else {}
            if command.get("session_id") != session_id or command.get("skill_id") != skill_id:
                continue
            if command.get("mode") != "live_video" or event.get("status") != "running":
                continue
            params = command.get("params") if isinstance(command.get("params"), dict) else {}
            if params.get("requested_by") != "skill_runtime" or not params.get("continue_after_capture"):
                continue
            args = params.get("skill_args") if isinstance(params.get("skill_args"), dict) else {}
            if not args:
                continue
            return {"command": command, "event": event, "args": args}
        return None

    def _active_live_context_for_adapter(self, *, session_id: str, adapter: str) -> dict[str, Any] | None:
        for item in reversed(self.media_commands.statuses()):
            if not item.get("active"):
                continue
            command = item.get("command") if isinstance(item.get("command"), dict) else {}
            event = item.get("event") if isinstance(item.get("event"), dict) else {}
            if command.get("session_id") != session_id:
                continue
            if command.get("mode") != "live_video" or event.get("status") != "running":
                continue
            params = command.get("params") if isinstance(command.get("params"), dict) else {}
            if params.get("requested_by") != "skill_runtime" or not params.get("continue_after_capture"):
                continue
            active_live = {
                "session_id": session_id,
                "command_id": command.get("command_id"),
                "skill_id": command.get("skill_id"),
                "params": params,
            }
            if active_live_uses_adapter(active_live, adapter=adapter):
                args = params.get("skill_args") if isinstance(params.get("skill_args"), dict) else {}
                return {"command": command, "event": event, "args": args, "active_live": active_live}
        return None

    def _rv101_h264_preview_decode_allowed(self, *, session_id: str) -> bool:
        """Keep JPEG preview decode off the live YOLO26 object-only hot path."""

        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return False
        for item in self.media_commands.active_live_statuses():
            if str(item.get("session_id") or "") != normalized_session_id:
                continue
            if active_live_uses_adapter(item, adapter="face_identity"):
                return True
        return False

    def _record_rv101_h264_preview_decode_skipped(self, *, session_id: str) -> None:
        now_s = time.monotonic()
        last_s = self._last_h264_preview_decode_skip_s.get(session_id)
        if last_s is not None and now_s - last_s < 10.0:
            return
        self._last_h264_preview_decode_skip_s[session_id] = now_s
        active_live = [
            item
            for item in self.media_commands.active_live_statuses()
            if str(item.get("session_id") or "") == str(session_id or "")
        ]
        branches: list[str] = []
        route_kind = ""
        skill_id = ""
        if active_live:
            live = active_live[-1]
            branches = [
                str(value)
                for value in (live.get("perception_branches") or [])
                if str(value or "").strip()
            ]
            route = live.get("preview_route") if isinstance(live.get("preview_route"), dict) else {}
            route_kind = str(route.get("route_kind") or "")
            skill_id = str(live.get("skill_id") or "")
        self.events.add(
            "rv101_h264_preview",
            "decode_skipped",
            {
                "reason": "active_live_route_does_not_require_jpeg_preview",
                "skill_id": skill_id or None,
                "route_kind": route_kind or None,
                "perception_branches": branches,
                "sensor_preview_live_source": "routed_h264",
            },
            session_id=session_id,
        )

    def record_video_heartbeat(
        self,
        *,
        session_id: str,
        transport: str,
        codec: str,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.media.record_video_heartbeat(
            session_id=session_id,
            transport=transport,
            codec=codec,
            width=width,
            height=height,
            fps=fps,
            metadata=_clean_sensor_metadata(
                metadata,
                client_kind=self._session_client_kind(session_id),
                preview_width=width,
                preview_height=height,
            ),
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
        avg_abs: float | None = None,
        peak_abs: int | None = None,
        non_silent_ratio: float | None = None,
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
            avg_abs=avg_abs,
            peak_abs=peak_abs,
            non_silent_ratio=non_silent_ratio,
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
            metadata=_sensor_metadata_from_payload(
                frame,
                client_kind=self._session_client_kind(session_id),
                preview_width=_to_int(frame.get("width")),
                preview_height=_to_int(frame.get("height")),
            ),
        )

    def _record_simulator_preview_frame(self, session_id: str, image_bytes: bytes, frame: dict[str, Any]) -> None:
        metadata = _sensor_metadata_from_payload(
            frame,
            client_kind=self._session_client_kind(session_id),
            preview_width=_to_int(frame.get("width")),
            preview_height=_to_int(frame.get("height")),
        )
        self.preview.record_frame(
            session_id=session_id,
            source=str(frame.get("source") or "iphone_webrtc"),
            image_bytes=image_bytes,
            width=_to_int(frame.get("width")),
            height=_to_int(frame.get("height")),
            frame_count=_to_int(frame.get("frame_count")) or 0,
            metadata=metadata,
        )

    def _close_simulator_media(self, session_id: str) -> None:
        self.debug_stt.flush_session(session_id, reason="simulator_stream_closed")
        self.media.close_session(session_id)
        self.preview.remove_session(session_id)
        self._simulator_audio_gates.pop(session_id, None)
        self.sessions.touch(session_id, status="closed")
        self.events.add(
            "sessions",
            "closed",
            {"reason": "simulator_stream_closed"},
            session_id=session_id,
        )
        self._stop_realtime_after_transport_close(session_id)

    def _stop_realtime_after_transport_close(self, session_id: str) -> None:
        async def stop_realtime() -> None:
            try:
                await self.realtime.stop(session_id)
            except Exception as exc:
                self.events.add(
                    "realtime",
                    "transport_close_stop_failed",
                    {"message": f"{exc.__class__.__name__}: {exc}"},
                    session_id=session_id,
                    severity="warning",
                )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(stop_realtime())

    def _close_rv101_audio(self, session_id: str) -> None:
        self._rv101_audio_closed_s[session_id] = time.monotonic()
        self.debug_stt.flush_session(session_id, reason="rv101_audio_stream_closed")
        self.media.stop_audio_stream(session_id=session_id, reason="rv101_tcp_audio_disconnected")
        self._rv101_audio_gates.pop(session_id, None)
        self._close_rv101_recording_if_media_idle(session_id, reason="rv101_tcp_audio_disconnected")

    def _close_rv101_recording_if_media_idle(self, session_id: str, *, reason: str) -> None:
        media = self.media.status(session_id)
        if _media_active(media):
            return
        has_active_live = any(
            item.get("session_id") == session_id
            for item in self.media_commands.active_live_statuses()
        )
        if has_active_live:
            return
        if session_id in self._rv101_recording_close_requested_sessions:
            return
        self._rv101_recording_close_requested_sessions.add(session_id)
        self.stream_recorder.close_session(session_id, reason=reason)
        self.events.add(
            "rv101_stream_recorder",
            "recording_close_requested",
            {"reason": reason, "media_idle": True},
            session_id=session_id,
        )

    def _execute_skill_for_realtime(
        self,
        name: str,
        args: dict[str, Any],
        session_id: str | None,
    ) -> dict[str, Any]:
        return self.execute_skill(
            name,
            args,
            session_id=session_id,
            force_media_capture=_should_force_realtime_media_capture(name, args=args),
        )

    def _update_hud_from_realtime_text(self, session_id: str, text: str) -> None:
        if not self._session_is_active(session_id):
            self.events.add(
                "realtime",
                "output_text_ignored",
                {"reason": "inactive_session", "chars": len(text or "")},
                session_id=session_id,
                severity="warning",
            )
            return
        self.hud.update_realtime_text(
            session_id=session_id,
            text=text,
            edge_chips=["realtime"],
            ttl_ms=5000,
        )

    def _publish_realtime_voice_output(self, session_id: str, audio_base64: str, byte_count: int) -> None:
        if not self._session_is_active(session_id):
            self.events.add(
                "realtime",
                "output_audio_ignored",
                {"reason": "inactive_session", "bytes": byte_count},
                session_id=session_id,
                severity="warning",
            )
            return
        self.voice_output.publish_delta(
            session_id=session_id,
            audio_base64=audio_base64,
            byte_count=byte_count,
        )

    def _publish_realtime_voice_done(self, session_id: str) -> None:
        if not self._session_is_active(session_id):
            return
        self.voice_output.publish_done(session_id=session_id)

    async def _forward_rv101_audio_to_realtime(self, session_id: str, pcm_bytes: bytes) -> None:
        if not self._session_is_active(session_id):
            if session_id not in self._rv101_stale_audio_logged:
                self._rv101_stale_audio_logged.add(session_id)
                self.events.add(
                    "rv101_audio",
                    "stale_session_audio_ignored",
                    {"reason": "session is no longer active"},
                    session_id=session_id,
                    severity="info",
                )
            return
        metrics = pcm16_metrics(pcm_bytes)
        self._rv101_audio_last_chunk_s[session_id] = time.monotonic()
        await self._forward_gated_audio(
            session_id=session_id,
            pcm_bytes=pcm_bytes,
            metrics=metrics,
            source="rv101",
            gates=self._rv101_audio_gates,
        )

    async def _wait_for_rv101_audio_drain(self, *, session_id: str) -> None:
        ptt_started_s = self._rv101_ptt_started_s.get(session_id)
        if ptt_started_s is None:
            return
        deadline_s = time.monotonic() + RV101_AUDIO_DRAIN_WAIT_S
        while time.monotonic() < deadline_s:
            last_chunk_s = self._rv101_audio_last_chunk_s.get(session_id, 0.0)
            closed_s = self._rv101_audio_closed_s.get(session_id, 0.0)
            if last_chunk_s >= ptt_started_s and closed_s >= last_chunk_s:
                return
            await asyncio.sleep(RV101_AUDIO_DRAIN_POLL_S)
        self.events.add(
            "rv101_control",
            "audio_drain_timeout_before_ptt_up",
            {
                "wait_s": RV101_AUDIO_DRAIN_WAIT_S,
                "saw_audio_chunk": self._rv101_audio_last_chunk_s.get(session_id, 0.0) >= ptt_started_s,
                "saw_audio_close": self._rv101_audio_closed_s.get(session_id, 0.0) >= ptt_started_s,
            },
            session_id=session_id,
            severity="warning",
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
            strong=is_voice_like(metrics),
            avg_abs=float(metrics.get("avg_abs") or 0.0),
            peak_abs=int(metrics.get("peak_abs") or 0),
            non_silent_ratio=float(metrics.get("non_silent_ratio") or 0.0),
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
        realtime_chunks = (
            decision.chunks
            if self._realtime_audio_gate_mode == "suppress_idle_noise"
            else [pcm_bytes]
        )
        self.media.record_audio_gate_decision(
            session_id=session_id,
            source=source,
            state=decision.state,
            transition=decision.transition,
            strong=decision.strong,
            forwarded_chunks=len(realtime_chunks),
            buffered_chunks=decision.buffered_chunks,
            avg_abs=float(metrics.get("avg_abs") or 0.0),
            peak_abs=int(metrics.get("peak_abs") or 0),
            non_silent_ratio=float(metrics.get("non_silent_ratio") or 0.0),
            mode=self._realtime_audio_gate_mode,
        )
        if decision.transition:
            self.events.add(
                "audio_gate",
                decision.transition,
                {
                    "source": source,
                    "mode": self._realtime_audio_gate_mode,
                    "state": decision.state,
                    "strong": decision.strong,
                    "gate_forwarded_chunks": len(decision.chunks),
                    "realtime_forwarded_chunks": len(realtime_chunks),
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
        for chunk in realtime_chunks:
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


def _rv101_health_summary(payload: dict[str, Any]) -> dict[str, Any]:
    battery_pct = _to_int(payload.get("battery_pct") or payload.get("batteryPct"))
    return {
        "sessionId": payload.get("sessionId") or payload.get("session_id"),
        "app_state": payload.get("app_state") or payload.get("appState"),
        "battery_pct": battery_pct,
        "thermal_state": payload.get("thermal_state") or payload.get("thermalState"),
        "active_media": payload.get("active_media") or payload.get("activeMedia"),
    }


def _rv101_health_signature(summary: dict[str, Any]) -> tuple[Any, ...]:
    battery_pct = summary.get("battery_pct")
    battery_bucket = None
    if isinstance(battery_pct, int):
        battery_bucket = max(0, min(100, battery_pct)) // 5
    return (
        summary.get("app_state"),
        summary.get("thermal_state"),
        summary.get("active_media"),
        battery_bucket,
    )


def _skill_media_continuation_context(media_result: dict[str, Any]) -> dict[str, Any] | None:
    command = media_result.get("command") if isinstance(media_result.get("command"), dict) else {}
    event = media_result.get("event") if isinstance(media_result.get("event"), dict) else {}
    if command.get("mode") not in {"snapshot", "burst_clip", "live_video"}:
        return None
    params = command.get("params") if isinstance(command.get("params"), dict) else {}
    if params.get("requested_by") != "skill_runtime" or not params.get("continue_after_capture"):
        return None
    skill_id = str(command.get("skill_id") or "").strip()
    session_id = str(command.get("session_id") or "").strip()
    if not skill_id or not session_id:
        return None
    return {
        "command": command,
        "event": event,
        "skill_id": skill_id,
        "session_id": session_id,
        "args": params.get("skill_args") if isinstance(params.get("skill_args"), dict) else {},
    }


def _pending_live_video_has_evidence(pending: dict[str, Any] | None, *, has_existing_evidence: bool) -> bool:
    if not pending or not has_existing_evidence:
        return False
    command = pending.get("command") if isinstance(pending.get("command"), dict) else {}
    event = pending.get("event") if isinstance(pending.get("event"), dict) else {}
    return command.get("mode") == "live_video" and event.get("status") == "running"


def _skill_live_camera_profile(*, args: dict[str, Any], skill_id: str | None = None) -> dict[str, Any]:
    requested = _first_nonempty_text(
        args.get("media_profile"),
        args.get("camera_profile"),
        args.get("profile"),
        args.get("video_profile"),
    )
    if requested:
        profile_id = RV101_LIVE_CAMERA_PROFILE_ALIASES.get(_normalize_profile_key(requested), "")
    elif _to_float(args.get("fps")) is not None and (_to_float(args.get("fps")) or 0) >= 25.0:
        profile_id = RV101_DIAGNOSTIC_LIVE_PROFILE
    elif _skill_live_needs_high_detail_identity(args=args, skill_id=skill_id):
        profile_id = RV101_HIGH_LIVE_PROFILE
    elif skill_id in {"target_finder", "person_info"}:
        profile_id = RV101_SKILL_LIVE_PROFILE
    else:
        profile_id = RV101_DEFAULT_LIVE_PROFILE
    if not profile_id:
        profile_id = RV101_SKILL_LIVE_PROFILE if skill_id in {"target_finder", "person_info"} else RV101_DEFAULT_LIVE_PROFILE
    profile = RV101_LIVE_CAMERA_PROFILES.get(profile_id, RV101_LIVE_CAMERA_PROFILES[RV101_DEFAULT_LIVE_PROFILE])
    return {
        **profile,
        "requested_media_profile": requested or profile["media_profile"],
        "resolved_media_profile": profile["media_profile"],
    }


def _skill_live_needs_high_detail_identity(*, args: dict[str, Any], skill_id: str | None = None) -> bool:
    if skill_id == "person_info":
        return _person_info_wants_live_name_reminder(args)
    if skill_id != "target_finder":
        return False
    target_type = str(args.get("target_type") or "person").strip().lower()
    if target_type != "person":
        return False
    if bool(args.get("identity_query")) or str(args.get("target_name") or "").strip():
        return True
    query = _normalize_vietnamese_text(str(args.get("question") or args.get("query") or ""))
    return any(
        phrase in query
        for phrase in (
            "nguoi quen",
            "nguoi nha",
            "ten rieng",
            "nhan dien nguoi",
            "nhac ten",
            "name reminder",
            "known person",
            "contact",
        )
    )


def _skill_live_camera_resolution(args: dict[str, Any], *, default: dict[str, int]) -> dict[str, int]:
    value = args.get("resolution")
    if isinstance(value, dict):
        width = _budget_int(value.get("width"), default=default["width"], minimum=240, maximum=1280)
        height = _budget_int(value.get("height"), default=default["height"], minimum=240, maximum=720)
        return {"width": width, "height": height}
    width = _budget_int(args.get("resolution_width"), default=default["width"], minimum=240, maximum=1280)
    height = _budget_int(args.get("resolution_height"), default=default["height"], minimum=240, maximum=720)
    return {"width": width, "height": height}


def _camera_profile_authority_params(profile: dict[str, Any], *, mode: str) -> dict[str, Any]:
    media_profile = str(profile.get("media_profile") or profile.get("resolved_media_profile") or "").strip()
    return {
        "camera_contract_version": CAMERA_PROFILE_CONTRACT_VERSION,
        "profile_authority": "jetson",
        "profile_source": "skill_media_command",
        "media_profile": media_profile or RV101_DEFAULT_LIVE_PROFILE,
        "camera_profile": media_profile or RV101_DEFAULT_LIVE_PROFILE,
        "requested_media_profile": profile.get("requested_media_profile") or media_profile,
        "resolved_media_profile": profile.get("resolved_media_profile") or media_profile,
        "preview_profile": profile.get("preview_profile"),
        "pipeline_preference": "camera2_surface_h264",
        "bitrate_hint": profile.get("bitrate_hint"),
        "fov_mode": "wide",
        "crop_policy": "no_crop",
        "camera_preference": "widest_back",
        "digital_zoom": 1.0,
        "preserve_resolution": True,
        "full_fov": True,
        "video_stabilization": False,
        "app_fallback_policy": "nearest_supported_same_fov_report_selected",
        "app_auto_quality": False,
        "media_mode": mode,
    }


def _skill_media_command_params(*, mode: str, args: dict[str, Any], skill_id: str | None = None) -> dict[str, Any]:
    action = "start" if mode == "live_video" else "capture"
    preview_route = skill_preview_route_spec(skill_id=skill_id, mode=mode, args=args)
    profile = (
        _skill_live_camera_profile(args=args, skill_id=skill_id)
        if mode == "live_video"
        else {
            "media_profile": RV101_SNAPSHOT_PROFILE,
            "requested_media_profile": args.get("media_profile") or RV101_SNAPSHOT_PROFILE,
            "resolved_media_profile": RV101_SNAPSHOT_PROFILE,
            "preview_profile": "snapshot_high_quality",
            "bitrate_hint": "still_quality",
        }
    )
    params: dict[str, Any] = {
        "action": action,
        "requested_by": "skill_runtime",
        "continue_after_capture": True,
        "skill_args": args,
        "preview_route": preview_route,
        "perception_branches": list(preview_route.get("perception_branches") or []),
        "primary_perception_branch": preview_route.get("primary_branch"),
        **_camera_profile_authority_params(profile, mode=mode),
    }
    if skill_id == "person_info" and mode == "snapshot":
        sample_count = _budget_int(args.get("snapshot_sample_count"), default=4, minimum=2, maximum=6)
        params["quality_gate"] = {
            "mode": "best_of_burst",
            "sample_count": sample_count,
            "min_new_frames": _budget_int(args.get("snapshot_min_new_frames"), default=sample_count, minimum=2, maximum=8),
            "settle_ms": _budget_int(args.get("snapshot_settle_ms"), default=850, minimum=450, maximum=1500),
            "score": "face_quality_then_sharpness",
            "server_recent_frame_limit": PERSON_INFO_SNAPSHOT_RECENT_FRAME_LIMIT,
        }
    return params


def _skill_media_command_budget(*, mode: str, args: dict[str, Any], skill_id: str | None = None) -> dict[str, Any]:
    if mode != "live_video":
        return {}
    profile = _skill_live_camera_profile(args=args, skill_id=skill_id)
    default_timeout_ms = 60000 if skill_id in {"target_finder", "person_info"} else 15000
    timeout_ms = _budget_int(args.get("timeout_ms"), default=default_timeout_ms, minimum=3000, maximum=60000)
    fps = _budget_float(args.get("fps"), default=float(profile["fps"]), minimum=1.0, maximum=30.0)
    resolution = _skill_live_camera_resolution(args, default=dict(profile["resolution"]))
    return {
        "timeout_ms": timeout_ms,
        "fps": fps,
        "resolution": resolution,
        "auto_stop": True,
    }


def _media_request_user_message(mode: str, *, skill_id: str | None = None) -> str:
    if mode == "live_video":
        if skill_id == "person_info":
            return "Đang bật live camera để nhắc tên realtime."
        return "Đang bật live camera để tìm mục tiêu."
    if skill_id == "person_info":
        return "Đang chụp ảnh để kiểm tra người quen."
    return "Đang bật camera để lấy ảnh."


def _media_request_answer_strip(mode: str, *, skill_id: str | None = None) -> str:
    if mode == "live_video":
        if skill_id == "person_info":
            return "Đang nhắc tên"
        return "Đang bật live target"
    if skill_id == "person_info":
        return "Đang check người quen"
    return "Đang bật camera"


def _media_event_adapter_status(event: dict[str, Any]) -> str | None:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    adapter_status = payload.get("adapter_status")
    return str(adapter_status) if adapter_status is not None else None


def _media_failure_user_message(media_status: str) -> str:
    if media_status == "timeout":
        return "Không lấy được ảnh mới; thử hỏi lại."
    if media_status == "cancelled":
        return "Đã hủy chụp ảnh."
    return "Camera báo lỗi khi chụp ảnh."


def _media_continuation_realtime_prompt(continuation: dict[str, Any]) -> str | None:
    spoken = _media_continuation_spoken_text(continuation)
    if not spoken:
        return None
    return f"Nội bộ Jetson: kết quả skill sau khi chụp ảnh đã sẵn sàng. Không gọi tool. Nói ngắn: {spoken}"


def _is_live_media_stop_continuation(continuation: dict[str, Any]) -> bool:
    result = continuation.get("result") if isinstance(continuation.get("result"), dict) else {}
    command = result.get("media_command") if isinstance(result.get("media_command"), dict) else {}
    media_status = str(result.get("media_status") or "").strip().lower()
    return command.get("mode") == "live_video" and media_status in {"timeout", "cancelled"}


def _media_continuation_spoken_text(continuation: dict[str, Any]) -> str | None:
    result = continuation.get("result") if isinstance(continuation.get("result"), dict) else {}
    for key in ("user_message", "answer", "message"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    cloud_result = result.get("cloud_result") if isinstance(result.get("cloud_result"), dict) else {}
    answer = cloud_result.get("answer_short")
    if isinstance(answer, str) and answer.strip():
        return answer.strip()
    hud = result.get("hud") if isinstance(result.get("hud"), dict) else {}
    answer_strip = hud.get("answer_strip")
    if isinstance(answer_strip, str) and answer_strip.strip():
        return answer_strip.strip()
    error = continuation.get("error") if isinstance(continuation.get("error"), dict) else {}
    message = error.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return None


def _should_request_visual_media(definition: Any) -> bool:
    media_requirements = definition.media_requirements if hasattr(definition, "media_requirements") else {}
    if bool(media_requirements.get("requires_camera")):
        return True
    allowed_modes = media_requirements.get("allowed_modes")
    local_resources = definition.local_resources if hasattr(definition, "local_resources") else []
    return (
        isinstance(allowed_modes, list)
        and "snapshot" in {str(mode) for mode in allowed_modes}
        and "perception_graph" in {str(resource) for resource in local_resources}
    )


def _should_force_realtime_media_capture(name: str, *, args: dict[str, Any] | None = None) -> bool:
    if name == "person_info":
        return not _person_info_followup_query(args or {})
    return name in {"query_scene", "scene_describe", "text_reader", "object_counter", "target_finder", "remember_person"}


def _visual_media_mode(
    media_requirements: dict[str, Any],
    *,
    args: dict[str, Any] | None = None,
    skill_id: str | None = None,
) -> str:
    requested = str((args or {}).get("media_mode") or (args or {}).get("scan_mode") or "").strip().lower()
    allowed_modes = media_requirements.get("allowed_modes")
    allowed = {str(mode) for mode in allowed_modes} if isinstance(allowed_modes, list) else set()
    if skill_id == "person_info" and _person_info_wants_live_name_reminder(args or {}) and "live_video" in allowed:
        return "live_video"
    if requested in {"live", "live_video", "realtime", "realtime_names", "name_reminder", "nhac_ten"} and "live_video" in allowed:
        return "live_video"
    if requested in {"snapshot", "photo", "image", "anh", "chup_anh"} and "snapshot" in allowed:
        return "snapshot"
    default_mode = str(media_requirements.get("default_mode") or "").strip()
    if default_mode and default_mode != "none":
        return default_mode
    if "snapshot" in allowed:
        return "snapshot"
    if "burst_clip" in allowed:
        return "burst_clip"
    return "snapshot"


def _session_active(session: dict[str, Any]) -> bool:
    return str(session.get("status") or "").lower() not in INACTIVE_SESSION_STATUSES


def _rv101_client_goodbye_message(payload: dict[str, Any]) -> bool:
    message_type = str(payload.get("type") or "").strip().lower()
    if message_type in {"client_goodbye", "app_exit", "app_closing", "app_shutdown", "session_close"}:
        return True
    if message_type != "app_lifecycle":
        return False
    state = str(payload.get("state") or payload.get("app_state") or payload.get("appState") or "").strip().lower()
    return state in {"closing", "stopping", "stopped", "destroyed", "exiting", "exit"}


def _rv101_health_indicates_app_exit(payload: dict[str, Any]) -> bool:
    app_state = str(payload.get("app_state") or payload.get("appState") or "").strip().lower()
    lifecycle = str(payload.get("lifecycle") or payload.get("lifecycle_state") or payload.get("lifecycleState") or "").strip().lower()
    return app_state in {"app_closing", "app_stopping", "app_stopped", "app_destroyed"} or lifecycle in {
        "closing",
        "stopping",
        "stopped",
        "destroyed",
        "exiting",
        "exit",
    }


def _rv101_client_goodbye_reason(payload: dict[str, Any], *, default: str) -> str:
    reason = str(payload.get("reason") or payload.get("closeReason") or default or "rv101_app_exit").strip().lower()
    reason = re.sub(r"[^a-z0-9_.:-]+", "_", reason)
    return reason[:80] or "rv101_app_exit"


def _rv101_realtime_reconnect_grace_s() -> float:
    raw = os.getenv("OPENVISION_RV101_REALTIME_RECONNECT_GRACE_S")
    if raw is None:
        return RV101_REALTIME_RECONNECT_GRACE_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return RV101_REALTIME_RECONNECT_GRACE_S


def _normalize_face_identity_source_for_session(source: str, *, client_kind: str | None) -> str:
    clean_source = str(source or "").strip().lower().replace(" ", "_")
    if str(client_kind or "").strip().lower() == "rv101_glasses":
        if not clean_source:
            return "openvision_rv101_face_identity"
        if "iphone" in clean_source and "face_identity" in clean_source:
            return clean_source.replace("iphone", "rv101")
    return clean_source or "openvision_rokid_face_identity"


def _normalize_yolo26_source_for_session(source: str, *, client_kind: str | None) -> str:
    clean_source = str(source or "").strip().lower().replace(" ", "_")
    if str(client_kind or "").strip().lower() == "rv101_glasses":
        if not clean_source:
            return "openvision_rv101_yolo26"
        if "iphone" in clean_source and "yolo26" in clean_source:
            return clean_source.replace("iphone", "rv101")
    return clean_source or "openvision_rokid_yolo26"


def _rv101_voice_output_contract(
    *,
    session_id: str,
    enabled: bool,
    output_modalities: list[str],
) -> dict[str, Any]:
    websocket_path = f"/ws/realtime/{session_id}/audio"
    return {
        "supported": True,
        "enabled": enabled,
        "transport": "ws_pcm",
        "path": websocket_path,
        "websocketPath": websocket_path,
        "websocket_path": websocket_path,
        "format": "pcm_s16le",
        "sampleRateHz": 24000,
        "sample_rate_hz": 24000,
        "channels": 1,
        "outputModalities": list(output_modalities),
        "output_modalities": list(output_modalities),
        "requiresRestBootstrap": False,
        "requires_rest_bootstrap": False,
    }


def _rv101_voice_mode_from_payload(payload: dict[str, Any]) -> str:
    raw = (
        payload.get("voiceMode")
        or payload.get("voice_mode")
        or payload.get("voice_mode_id")
        or payload.get("voiceModeId")
        or ""
    )
    mode = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if mode in {"", "auto", "default", "conversation", "server_vad", "open_mic", "openmic"}:
        return RV101_DEFAULT_VOICE_MODE
    if mode in {"ptt", "push_to_talk", "push_to_talk_realtime", "touch_to_talk", "manual"}:
        return RV101_PTT_VOICE_MODE
    if mode in {"wake", "wake_realtime", "hey_vision"}:
        return "wake_realtime"
    if mode in {"mission", "mission_realtime"}:
        return "mission_realtime"
    return RV101_DEFAULT_VOICE_MODE


def _rv101_turn_policy_for_voice_mode(voice_mode: str) -> str:
    if str(voice_mode or "").strip().lower() in RV101_SERVER_VAD_VOICE_MODES:
        return "server_vad"
    return "manual"


def _payload_bool(payload: dict[str, Any], *keys: str, default: bool = False) -> bool:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on", "enabled"}:
                return True
            if lowered in {"0", "false", "no", "off", "disabled"}:
                return False
    return default


def _sensor_metadata_from_payload(
    payload: dict[str, Any],
    *,
    client_kind: str | None = None,
    preview_width: int | None = None,
    preview_height: int | None = None,
) -> dict[str, Any]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return _clean_sensor_metadata(
        metadata,
        client_kind=client_kind,
        orientation=_first_present(payload, "orientation", "sensorOrientation", "sensor_orientation"),
        sensor_orientation_degrees=_first_present(
            payload,
            "sensorOrientationDegrees",
            "sensor_orientation_degrees",
        ),
        profile=_first_present(payload, "profile", "cameraProfile", "camera_profile", "videoProfile", "video_profile"),
        rotation_degrees=_first_present(payload, "rotation_degrees", "rotationDegrees", "displayRotation", "display_rotation"),
        mirrored=_first_present(payload, "mirrored", "isMirrored", "is_mirrored"),
        source_width=_first_present(payload, "source_width", "sourceWidth", "captureWidth", "capture_width", "sensorWidth", "sensor_width"),
        source_height=_first_present(payload, "source_height", "sourceHeight", "captureHeight", "capture_height", "sensorHeight", "sensor_height"),
        requested_width=_first_present(payload, "requestedWidth", "requested_width"),
        requested_height=_first_present(payload, "requestedHeight", "requested_height"),
        capture_fps_min=_first_present(payload, "captureFpsMin", "capture_fps_min"),
        capture_fps_max=_first_present(payload, "captureFpsMax", "capture_fps_max"),
        sent_fps_estimate=_first_present(payload, "sentFpsEstimate", "sent_fps_estimate"),
        dropped_frames=_first_present(payload, "droppedFrames", "dropped_frames"),
        camera_id=_first_present(payload, "cameraId", "camera_id"),
        camera_preference=_first_present(payload, "cameraPreference", "camera_preference"),
        fov_mode=_first_present(payload, "fovMode", "fov_mode"),
        crop_policy=_first_present(payload, "cropPolicy", "crop_policy"),
        full_fov=_first_present(payload, "fullFov", "full_fov"),
        video_stabilization=_first_present(payload, "videoStabilization", "video_stabilization"),
        digital_zoom=_first_present(payload, "digitalZoom", "digital_zoom"),
        zoom_ratio=_first_present(payload, "zoomRatio", "zoom_ratio"),
        preview_width=preview_width,
        preview_height=preview_height,
    )


def _clean_sensor_metadata(metadata: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    if isinstance(metadata, dict):
        for key, value in list(metadata.items())[:64]:
            clean_key = _metadata_key(key)
            if not clean_key:
                continue
            clean_value = _metadata_value(value)
            if clean_value is not None:
                clean[clean_key] = clean_value
    for key, value in overrides.items():
        clean_key = _metadata_key(key)
        clean_value = _metadata_value(value)
        if clean_key and clean_value is not None:
            clean[clean_key] = clean_value
    _add_canonical_metadata_aliases(clean)
    source_width = _to_int(clean.get("source_width"))
    source_height = _to_int(clean.get("source_height"))
    preview_width = _to_int(clean.get("preview_width"))
    preview_height = _to_int(clean.get("preview_height"))
    if source_width and source_height and preview_width and preview_height:
        downscaled = source_width != preview_width or source_height != preview_height
        clean.setdefault("preview_downscaled", downscaled)
        clean.setdefault("preview_profile", "downscaled" if downscaled else "full_res")
        clean.setdefault("downscaled_to", f"{preview_width}x{preview_height}")
        if downscaled:
            clean.setdefault("downscaled_from", f"{source_width}x{source_height}")
    return clean


def _add_canonical_metadata_aliases(metadata: dict[str, Any]) -> None:
    aliases = {
        "sourceWidth": "source_width",
        "sourceHeight": "source_height",
        "captureWidth": "source_width",
        "captureHeight": "source_height",
        "sensorWidth": "source_width",
        "sensorHeight": "source_height",
        "previewWidth": "preview_width",
        "previewHeight": "preview_height",
        "displayWidth": "display_width",
        "displayHeight": "display_height",
        "rotationDegrees": "rotation_degrees",
        "displayRotation": "rotation_degrees",
        "cameraProfile": "profile",
        "videoProfile": "profile",
        "sensorOrientation": "orientation",
        "sensorOrientationDegrees": "sensor_orientation_degrees",
        "requestedWidth": "requested_width",
        "requestedHeight": "requested_height",
        "captureFpsMin": "capture_fps_min",
        "captureFpsMax": "capture_fps_max",
        "sentFpsEstimate": "sent_fps_estimate",
        "droppedFrames": "dropped_frames",
        "cameraId": "camera_id",
        "cameraPreference": "camera_preference",
        "fovMode": "fov_mode",
        "cropPolicy": "crop_policy",
        "fullFov": "full_fov",
        "videoStabilization": "video_stabilization",
        "digitalZoom": "digital_zoom",
        "zoomRatio": "zoom_ratio",
    }
    for source_key, target_key in aliases.items():
        if source_key in metadata and target_key not in metadata:
            metadata[target_key] = metadata[source_key]


def _metadata_key(value: Any) -> str | None:
    key = str(value or "").strip()
    if not key or len(key) > 64:
        return None
    return key


def _metadata_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned[:240] if cleaned else None
    if isinstance(value, list):
        output = []
        for item in value[:16]:
            clean_item = _metadata_value(item)
            if clean_item is not None:
                output.append(clean_item)
        return output
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in list(value.items())[:24]:
            clean_key = _metadata_key(key)
            clean_value = _metadata_value(item)
            if clean_key and clean_value is not None:
                output[clean_key] = clean_value
        return output or None
    return None


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return None


def _realtime_active(status: dict[str, Any]) -> bool:
    return str(status.get("status") or "").lower() in {"connecting", "connected"}


def _realtime_terminal(status: dict[str, Any]) -> bool:
    return str(status.get("status") or "").lower() in INACTIVE_SESSION_STATUSES


def _media_active(status: dict[str, Any]) -> bool:
    video = status.get("video") if isinstance(status.get("video"), dict) else {}
    audio = status.get("audio") if isinstance(status.get("audio"), dict) else {}
    return str(video.get("state") or "").lower() == "receiving" or str(audio.get("state") or "").lower() == "receiving"


def _preview_upload_is_still_capture(source: str | None) -> bool:
    normalized = str(source or "").strip().lower()
    if not normalized:
        return True
    return "live" not in normalized and "stream" not in normalized


def _person_info_prefers_snapshot(args: dict[str, Any]) -> bool:
    return not _person_info_wants_live_name_reminder(args)


def _person_info_wants_live_name_reminder(args: dict[str, Any]) -> bool:
    requested = str(args.get("media_mode") or args.get("scan_mode") or "").strip().lower()
    if requested in {"live", "live_video", "realtime", "realtime_names", "name_reminder", "nhac_ten"}:
        return True
    query = str(args.get("question") or args.get("query") or "").strip()
    normalized = _normalize_vietnamese_text(query)
    return any(
        phrase in normalized
        for phrase in (
            "nhac ten",
            "goi ten",
            "nho ten",
            "ten nguoi nay",
            "nhan dien lien tuc",
            "nhan dien realtime",
            "nhan dien live",
            "realtime name",
            "name reminder",
        )
    )


def _person_info_followup_query(args: dict[str, Any]) -> bool:
    query = str(args.get("question") or args.get("query") or "").strip()
    normalized = _normalize_vietnamese_text(query)
    return any(
        phrase in normalized
        for phrase in (
            "con thong tin",
            "them thong tin",
            "thong tin gi",
            "so dien thoai",
            "sdt",
            "dia chi",
            "facebook",
            "link",
            "vi sao quen",
            "tai sao quen",
            "gap lan dau",
            "lan dau gap",
            "noi o",
            "nha o",
        )
    )


def _people_identity_max_assets(value: int | None) -> int:
    if value is not None:
        return max(0, min(int(value), 50))
    raw = os.getenv("OPENVISION_PEOPLE_IDENTITY_MAX_ASSETS", "8")
    try:
        return max(0, min(int(raw), 50))
    except ValueError:
        return 8


def _enroll_identity_samples_from_immich_assets(
    *,
    client: Any,
    identity: ContactIdentityStore,
    settings: Any,
    display_name: str,
    aliases: list[str],
    immich_person_id: str,
    max_assets: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if max_assets <= 0:
        return [], []
    samples: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    try:
        assets = client.search_person_assets(immich_person_id, limit=max_assets)
    except Exception as exc:
        return [], [
            {
                "source": "immich_person_assets",
                "reason": exc.__class__.__name__,
                "message": str(exc),
            }
        ]
    for asset in assets[:max_assets]:
        asset_id = str(asset.get("id") or asset.get("assetId") or "").strip()
        if not asset_id:
            continue
        try:
            details = client.get_asset(asset_id) if hasattr(client, "get_asset") else asset
            face = _first_immich_person_face(details, immich_person_id)
            if not face:
                raise RuntimeError("Asset has no face bbox for the requested Immich person.")
            image_bytes, _content_type = client.fetch_asset_thumbnail(asset_id, size="preview")
            crop_bytes = _crop_immich_face_bytes(image_bytes=image_bytes, face=face)
            vector = _extract_identity_vector_from_image_bytes(
                settings=settings,
                image_bytes=crop_bytes,
                content_type="image/jpeg",
            )
            face_id = str(face.get("id") or "face").strip() or "face"
            samples.append(
                identity.enroll_sample(
                    display_name=display_name,
                    aliases=aliases,
                    vector=vector,
                    source_note=f"opencv_sface:immich_person:{immich_person_id}:asset:{asset_id}:face:{face_id}",
                )
            )
        except Exception as exc:
            failures.append(
                {
                    "source": f"immich_asset:{asset_id}",
                    "reason": exc.__class__.__name__,
                    "message": str(exc),
                }
            )
    return samples, failures


def _first_immich_person_face(asset: dict[str, Any], immich_person_id: str) -> dict[str, Any] | None:
    people = asset.get("people") if isinstance(asset.get("people"), list) else []
    for person in people:
        if not isinstance(person, dict):
            continue
        if str(person.get("id") or person.get("personId") or "") != immich_person_id:
            continue
        faces = person.get("faces") if isinstance(person.get("faces"), list) else []
        for face in faces:
            if isinstance(face, dict) and _immich_face_bbox(face):
                return face
    return None


def _crop_immich_face_bytes(*, image_bytes: bytes, face: dict[str, Any]) -> bytes:
    from PIL import Image  # type: ignore

    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    crop = _crop_immich_face_image(image, face)
    output = BytesIO()
    crop.save(output, format="JPEG", quality=92)
    return output.getvalue()


def _crop_immich_face_image(image: Any, face: dict[str, Any]) -> Any:
    bbox = _immich_face_bbox(face)
    if not bbox:
        raise RuntimeError("Immich face bbox is missing.")
    x1, y1, x2, y2 = bbox
    source_width = _safe_positive_float(face.get("imageWidth")) or float(getattr(image, "width", 0) or 0)
    source_height = _safe_positive_float(face.get("imageHeight")) or float(getattr(image, "height", 0) or 0)
    image_width = float(getattr(image, "width", 0) or 0)
    image_height = float(getattr(image, "height", 0) or 0)
    if image_width <= 0 or image_height <= 0 or source_width <= 0 or source_height <= 0:
        raise RuntimeError("Immich face image dimensions are invalid.")
    scale_x = image_width / source_width
    scale_y = image_height / source_height
    x1 *= scale_x
    x2 *= scale_x
    y1 *= scale_y
    y2 *= scale_y
    padding_x = max(24, int((x2 - x1) * 0.65))
    padding_y = max(24, int((y2 - y1) * 0.75))
    left = max(0, int(x1) - padding_x)
    top = max(0, int(y1) - padding_y)
    right = min(int(image_width), int(x2) + padding_x)
    bottom = min(int(image_height), int(y2) + padding_y)
    if right <= left or bottom <= top:
        raise RuntimeError("Immich face crop is empty.")
    return image.crop((left, top, right, bottom))


def _immich_face_bbox(face: dict[str, Any]) -> tuple[float, float, float, float] | None:
    values = [
        face.get("boundingBoxX1"),
        face.get("boundingBoxY1"),
        face.get("boundingBoxX2"),
        face.get("boundingBoxY2"),
    ]
    try:
        x1, y1, x2, y2 = [float(value) for value in values]
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _extract_identity_vector_from_image_bytes(*, settings: Any, image_bytes: bytes, content_type: str) -> list[float]:
    if not image_bytes:
        raise RuntimeError("Identity source image was empty.")
    suffix = ".jpg"
    lowered = str(content_type or "").lower()
    if "png" in lowered:
        suffix = ".png"
    elif "webp" in lowered:
        suffix = ".webp"
    with tempfile.NamedTemporaryFile(prefix="openvision_immich_face_", suffix=suffix, delete=True) as temp_file:
        temp_file.write(image_bytes)
        temp_file.flush()
        return extract_identity_vector_from_image_path(settings, temp_file.name)


def _safe_positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _snapshot_image_quality_metrics(image: Any) -> dict[str, Any]:
    try:
        from PIL import ImageFilter, ImageStat  # type: ignore

        gray = image.convert("L")
        stats = ImageStat.Stat(gray)
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_stats = ImageStat.Stat(edges)
        return {
            "status": "ok",
            "brightness": round(float(stats.mean[0]), 2),
            "contrast": round(float(stats.stddev[0]), 2),
            "edge_sharpness": round(float(edge_stats.mean[0]), 2),
        }
    except Exception:
        return {"status": "unknown"}


def _snapshot_candidate_score(*, detections: list[dict[str, Any]], image_metrics: dict[str, Any]) -> float:
    detection_count = len([item for item in detections if isinstance(item, dict)])
    score = 420.0 + min(detection_count, 6) * 35.0 if detection_count else -120.0
    best_face_score = 0.0
    for detection in detections:
        if not isinstance(detection, dict):
            continue
        attributes = detection.get("attributes") if isinstance(detection.get("attributes"), dict) else {}
        face_min_side = (
            _safe_positive_float(attributes.get("face_min_side_px"))
            or _safe_positive_float(attributes.get("face_width_px"))
            or _snapshot_bbox_min_side(detection.get("bbox"))
            or 0.0
        )
        confidence = _to_float(attributes.get("face_confidence")) or _to_float(detection.get("confidence")) or 0.0
        quality_reasons = _snapshot_identity_quality_reasons(attributes)
        face_score = min(face_min_side, 260.0) * 1.25 + min(max(confidence, 0.0), 1.0) * 95.0
        if not quality_reasons or str(attributes.get("identity_quality") or "").lower() == "ok":
            face_score += 90.0
        else:
            face_score -= 45.0 * len(quality_reasons)
            if "too_soft_for_identity" in quality_reasons:
                face_score -= 80.0
            if "too_dark_for_identity" in quality_reasons:
                face_score -= 55.0
            if "too_small_for_identity" in quality_reasons:
                face_score -= 70.0
        best_face_score = max(best_face_score, face_score)
    score += min(best_face_score, 520.0)
    if image_metrics.get("status") == "ok":
        brightness = _to_float(image_metrics.get("brightness")) or 0.0
        contrast = _to_float(image_metrics.get("contrast")) or 0.0
        sharpness = _to_float(image_metrics.get("edge_sharpness")) or 0.0
        if brightness < 45.0:
            score -= 90.0
        elif brightness < 70.0:
            score -= 35.0
        elif brightness <= 210.0:
            score += 35.0
        else:
            score -= 20.0
        score += min(max(contrast - 10.0, 0.0), 80.0) * 1.1
        score += min(sharpness, 90.0) * 1.6
    return round(score, 3)


def _snapshot_candidate_event_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    frame = candidate.get("frame")
    detections = candidate.get("detections") if isinstance(candidate.get("detections"), list) else []
    return {
        "frame_count": int(getattr(frame, "frame_count", 0) or 0),
        "score": round(float(candidate.get("score") or 0.0), 2),
        "detection_count": len([item for item in detections if isinstance(item, dict)]),
        "metrics": candidate.get("metrics"),
    }


def _snapshot_identity_quality_reasons(attributes: dict[str, Any]) -> list[str]:
    reasons = attributes.get("identity_quality_reasons")
    if not isinstance(reasons, list):
        reasons = attributes.get("face_quality_flags")
    if not isinstance(reasons, list):
        return []
    return [str(reason).strip() for reason in reasons if str(reason).strip()]


def _snapshot_bbox_min_side(bbox: Any) -> float | None:
    if not isinstance(bbox, list) or len(bbox) < 4:
        return None
    try:
        x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
    except (TypeError, ValueError):
        return None
    width = abs(x2 - x1)
    height = abs(y2 - y1)
    if width <= 0 or height <= 0:
        return None
    return min(width, height)


def _prepare_snapshot_face_detections(
    *,
    detections: list[dict[str, Any]],
    image: Any,
    session_id: str,
    runtime_dir: Path,
    crop_quality: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    crop_dir = runtime_dir / "crops" / _safe_local_segment(session_id)
    crop_dir.mkdir(parents=True, exist_ok=True)
    for index, detection in enumerate(detections, start=1):
        if not isinstance(detection, dict):
            continue
        track_id = _safe_local_segment(str(detection.get("track_id") or f"snap_f{index}"))
        attributes = detection.get("attributes") if isinstance(detection.get("attributes"), dict) else {}
        item = {
            **detection,
            "label": "person",
            "track_id": track_id,
            "attributes": {
                **attributes,
                "face_track_id": track_id,
                "snapshot_identity": True,
                "snapshot_source": "person_info",
            },
        }
        crop = _crop_snapshot_image(image, item.get("bbox") if isinstance(item.get("bbox"), list) else None)
        if crop is not None:
            file_name = f"face_{track_id}_snapshot.jpg"
            crop.save(crop_dir / file_name, format="JPEG", quality=max(40, min(int(crop_quality or 88), 95)))
            item["crop_ref"] = f"/api/crops/{_safe_local_segment(session_id)}/{file_name}"
        output.append(item)
    return output


def _crop_snapshot_image(image: Any, bbox: list[float] | None) -> Any | None:
    if not bbox or len(bbox) < 4:
        return None
    x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
    width = int(getattr(image, "width", 0) or 0)
    height = int(getattr(image, "height", 0) or 0)
    if width <= 0 or height <= 0:
        return None
    if max(x1, y1, x2, y2) <= 1.5:
        x1 *= width
        x2 *= width
        y1 *= height
        y2 *= height
    padding_x = max(8, int((x2 - x1) * 0.45))
    padding_y = max(8, int((y2 - y1) * 0.55))
    left = max(0, int(x1) - padding_x)
    top = max(0, int(y1) - padding_y)
    right = min(width, int(x2) + padding_x)
    bottom = min(height, int(y2) + padding_y)
    if right <= left or bottom <= top:
        return None
    return image.crop((left, top, right, bottom))


def _read_host_boot_id() -> str | None:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _safe_local_segment(value: str) -> str:
    cleaned = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in {"_", "-"})
    return cleaned or "unknown"


def _normalize_vietnamese_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", str(value or "").lower())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("đ", "d")
    return " ".join("".join(char if char.isalnum() else " " for char in normalized).split())


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


def _first_nonempty_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _normalize_profile_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _frame_count_from_perception_snapshot(snapshot: dict[str, Any]) -> int | None:
    metadata = snapshot.get("metadata") if isinstance(snapshot.get("metadata"), dict) else {}
    for value in (
        metadata.get("frame_count"),
        metadata.get("preview_frame_count"),
        snapshot.get("frame_count"),
    ):
        parsed = _to_int(value)
        if parsed is not None:
            return parsed
    frame_id = str(snapshot.get("frame_id") or "").strip()
    match = re.search(r"(\d+)$", frame_id)
    if match:
        return _to_int(match.group(1))
    return None


def _snapshot_with_preview_alignment(snapshot: dict[str, Any], *, preview_frame_count: int) -> dict[str, Any]:
    output = dict(snapshot)
    metadata = dict(output.get("metadata") if isinstance(output.get("metadata"), dict) else {})
    perception_frame_count = _frame_count_from_perception_snapshot(output)
    preview_count = _to_int(preview_frame_count) or 0
    frame_delta: int | None = None
    if perception_frame_count is not None:
        frame_delta = max(0, preview_count - perception_frame_count)
    metadata["recorded_preview_frame_count"] = preview_count
    metadata["perception_frame_count"] = perception_frame_count
    metadata["perception_frame_delta"] = frame_delta
    metadata["perception_bbox_stale"] = bool(frame_delta is not None and frame_delta > 2)
    output["metadata"] = metadata
    return output


def _budget_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(maximum, max(minimum, number))


def _budget_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return round(min(maximum, max(minimum, number)), 2)
