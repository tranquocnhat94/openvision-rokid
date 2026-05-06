"""FastAPI entrypoint for the OpenVision Rokid v2 Jetson service."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import hmac
import ipaddress
import json
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .control_plane import OpenVisionControlPlane
from .realtime_manager import DEFAULT_REALTIME_TURN_POLICY


def default_static_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "web_ui" / "static"


def default_runtime_dir() -> Path:
    return Path(os.getenv("OPENVISION_RUNTIME_DIR") or Path(__file__).resolve().parents[3] / "runtime")


PUBLIC_HTTP_PATHS = {"/", "/api/health", "/favicon.ico"}
DEFAULT_TRUSTED_CLIENT_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("100.64.0.0/10"),
)
H264_PREVIEW_HEARTBEAT_S = 5.0


def _cors_origins() -> list[str]:
    raw = os.getenv("OPENVISION_API_CORS_ORIGINS")
    if raw is None:
        return ["http://127.0.0.1:8765", "http://localhost:8765"]
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["http://127.0.0.1:8765", "http://localhost:8765"]


def _http_request_allowed(request: Request) -> bool:
    path = request.url.path
    if request.method == "OPTIONS" or path in PUBLIC_HTTP_PATHS:
        return True
    if not path.startswith("/api/") and not path.startswith("/ops/"):
        return True
    token = _configured_api_token()
    if token and _request_has_api_token(request, token):
        return True
    return _trusted_client_host(request.client.host if request.client else "")


def _websocket_request_allowed(websocket: WebSocket) -> bool:
    token = _configured_api_token()
    if token and _websocket_has_api_token(websocket, token):
        return True
    return _trusted_client_host(websocket.client.host if websocket.client else "")


async def _accept_guarded_websocket(websocket: WebSocket) -> bool:
    if not _websocket_request_allowed(websocket):
        await websocket.close(code=1008, reason="openvision_api_forbidden")
        return False
    await websocket.accept()
    return True


def _configured_api_token() -> str:
    token = str(os.getenv("OPENVISION_API_SHARED_TOKEN") or "").strip()
    token_file = str(os.getenv("OPENVISION_API_SHARED_TOKEN_FILE") or "").strip()
    if token or not token_file:
        return token
    try:
        return Path(token_file).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _request_has_api_token(request: Request, expected: str) -> bool:
    return _headers_have_api_token(request.headers, expected)


def _websocket_has_api_token(websocket: WebSocket, expected: str) -> bool:
    if _headers_have_api_token(websocket.headers, expected):
        return True
    query_token = str(
        websocket.query_params.get("openvision_api_token")
        or websocket.query_params.get("api_token")
        or ""
    ).strip()
    return bool(query_token and hmac.compare_digest(query_token, expected))


def _headers_have_api_token(headers: Any, expected: str) -> bool:
    header = str(headers.get("x-openvision-api-token") or "").strip()
    if not header:
        authorization = str(headers.get("authorization") or "").strip()
        if authorization.lower().startswith("bearer "):
            header = authorization[7:].strip()
    return bool(header and hmac.compare_digest(header, expected))


def _trusted_client_host(host: str) -> bool:
    clean_host = str(host or "").strip()
    if clean_host in {"testclient", "localhost"}:
        return True
    try:
        address = ipaddress.ip_address(clean_host)
    except ValueError:
        return False
    if any(address in network for network in DEFAULT_TRUSTED_CLIENT_NETWORKS):
        return True
    for network in _configured_trusted_networks():
        if address in network:
            return True
    return False


def _configured_trusted_networks() -> list[ipaddress._BaseNetwork]:
    raw = os.getenv("OPENVISION_API_TRUSTED_CLIENTS") or ""
    networks: list[ipaddress._BaseNetwork] = []
    for item in raw.split(","):
        clean = item.strip()
        if not clean:
            continue
        try:
            networks.append(ipaddress.ip_network(clean, strict=False))
        except ValueError:
            continue
    return networks


class CreateSessionRequest(BaseModel):
    client_kind: str = Field(..., min_length=1)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class CloseSessionRequest(BaseModel):
    reason: str = "operator_requested"


class RecordEventRequest(BaseModel):
    module: str = Field(..., min_length=1)
    event_type: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    severity: str = "info"


class SkillDryRunRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class SkillExecuteRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class RealtimeStartRequest(BaseModel):
    turn_policy: str = DEFAULT_REALTIME_TURN_POLICY
    output_modalities: list[str] | None = None
    voice_output: bool | None = None


class RealtimeTextRequest(BaseModel):
    text: str = Field(..., min_length=1)


class RealtimeAudioRequest(BaseModel):
    audio_base64: str = Field(..., min_length=1)
    commit: bool = False
    create_response: bool = True


class SensorMetadataModel(BaseModel):
    class Config:
        extra = "allow"


class WebRtcOfferRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    sdp: str = Field(..., min_length=1)
    type: str = "offer"


class VideoHeartbeatRequest(SensorMetadataModel):
    transport: str = Field(..., min_length=1)
    codec: str = Field(..., min_length=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    fps: float | None = Field(default=None, ge=0)
    orientation: str | int | None = None
    profile: str | None = None
    rotation_degrees: int | None = None
    mirrored: bool | None = None
    source_width: int | None = Field(default=None, ge=1)
    source_height: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AudioMetricsRequest(BaseModel):
    transport: str = Field(..., min_length=1)
    sample_rate: int = Field(..., ge=8000)
    channels: int = Field(..., ge=1, le=8)
    chunk_count: int = Field(..., ge=0)
    strong_chunk_count: int = Field(..., ge=0)
    rms: float | None = Field(default=None, ge=0)
    avg_abs: float | None = Field(default=None, ge=0)
    peak_abs: int | None = Field(default=None, ge=0)
    non_silent_ratio: float | None = Field(default=None, ge=0, le=1)
    source: str | None = None


class MediaCommandRequest(BaseModel):
    mode: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    command_id: str | None = None
    skill_id: str | None = None
    reason: str | None = None
    timeout_ms: int | None = Field(default=None, ge=1)
    fps: float | None = Field(default=None, ge=0)
    resolution: dict[str, Any] | None = None
    auto_stop: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class MediaCommandEventRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class DisplayCommandRequest(BaseModel):
    kind: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    command_id: str | None = None
    skill_id: str | None = None
    priority: str = "normal"
    ttl_ms: int | None = Field(default=None, ge=0)


class PerceptionSnapshotRequest(SensorMetadataModel):
    source: str = Field(..., min_length=1)
    detections: list[dict[str, Any]] = Field(default_factory=list)
    frame_id: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    orientation: str | int | None = None
    profile: str | None = None
    rotation_degrees: int | None = None
    source_width: int | None = Field(default=None, ge=1)
    source_height: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Yolo26SnapshotRequest(SensorMetadataModel):
    source: str = "rokid_yolo26_external"
    detections: list[dict[str, Any]] = Field(default_factory=list)
    frame_id: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    orientation: str | int | None = None
    profile: str | None = None
    rotation_degrees: int | None = None
    source_width: int | None = Field(default=None, ge=1)
    source_height: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Yolo26StreamFrameRequest(SensorMetadataModel):
    source: str = "openvision_rokid_yolo26_stream"
    detections: list[dict[str, Any]] = Field(default_factory=list)
    frame_id: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    sequence: int | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    orientation: str | int | None = None
    profile: str | None = None
    rotation_degrees: int | None = None
    source_width: int | None = Field(default=None, ge=1)
    source_height: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FaceIdentityStreamFrameRequest(SensorMetadataModel):
    source: str = "openvision_rokid_face_identity"
    detections: list[dict[str, Any]] = Field(default_factory=list)
    frame_id: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    sequence: int | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    orientation: str | int | None = None
    profile: str | None = None
    rotation_degrees: int | None = None
    source_width: int | None = Field(default=None, ge=1)
    source_height: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IdentityContactRequest(BaseModel):
    display_name: str = Field(..., min_length=1)
    aliases: list[str] = Field(default_factory=list)
    notes: str | None = None


class IdentityEnrollRequest(BaseModel):
    display_name: str | None = None
    contact_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    notes: str | None = None
    image_ref: str | None = None
    image_path: str | None = None
    vector: list[float] | None = None
    source_note: str | None = None


class IdentityMatchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    session_id: str | None = None


class PeopleSyncRequest(BaseModel):
    push_names: bool = False


class PeopleProfileUpdateRequest(BaseModel):
    display_name: str | None = None
    aliases: list[str] | None = None
    phone: str | None = None
    address: str | None = None
    age: str | None = None
    where_lives: str | None = None
    relationship: str | None = None
    first_met: str | None = None
    links: dict[str, Any] | None = None
    facts: dict[str, Any] | None = None
    notes: str | None = None
    sync_name_to_immich: bool = False


class PeopleIdentityEnrollRequest(BaseModel):
    display_name: str | None = None
    aliases: list[str] | None = None
    max_assets: int | None = Field(default=None, ge=0, le=50)


def create_app(control_plane: OpenVisionControlPlane | None = None) -> FastAPI:
    control = control_plane or OpenVisionControlPlane()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await control.start_background_services()
        try:
            yield
        finally:
            await control.stop_background_services()

    app = FastAPI(
        title="OpenVision Rokid Jetson Agent",
        version="0.1.0",
        docs_url="/ops/api",
        redoc_url="/ops/redoc",
        lifespan=lifespan,
    )
    app.state.control_plane = control

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def api_access_guard(request: Request, call_next):
        if _http_request_allowed(request):
            return await call_next(request)
        return Response(
            content=json.dumps(
                {
                    "detail": {
                        "code": "openvision_api_forbidden",
                        "message": "OpenVision Jetson API requires a trusted client network or shared API token.",
                    }
                }
            ),
            status_code=403,
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    @app.middleware("http")
    async def no_store_ops_assets(request, call_next):
        response = await call_next(request)
        if (
            request.url.path
            in {"/", "/app.js", "/people.html", "/people.js", "/recordings.html", "/recordings.js", "/style.css"}
            or request.url.path.startswith("/api/preview/")
            or request.url.path.startswith("/api/crops/")
            or request.url.path.startswith("/api/recordings/")
            or (request.url.path.startswith("/api/people/") and request.url.path.endswith("/thumbnail"))
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return control.health()

    @app.get("/api/settings")
    async def settings() -> dict[str, object]:
        return control.settings_snapshot()

    @app.get("/api/sessions")
    async def list_sessions() -> dict[str, list[dict[str, Any]]]:
        return {"sessions": control.list_sessions()}

    @app.post("/api/sessions", status_code=201)
    async def create_session(request: CreateSessionRequest) -> dict[str, dict[str, Any]]:
        return {
            "session": control.create_session(
                client_kind=request.client_kind,
                capabilities=request.capabilities,
            )
        }

    @app.post("/api/sessions/{session_id}/close")
    async def close_session(session_id: str, request: CloseSessionRequest) -> dict[str, Any]:
        result = await control.close_session(session_id, reason=request.reason)
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result["error"])
        return result

    @app.get("/api/events")
    async def list_events(
        session_id: str | None = None,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, list[dict[str, Any]]]:
        return {"events": control.list_events(session_id=session_id, limit=limit)}

    @app.post("/api/events", status_code=201)
    async def record_event(request: RecordEventRequest) -> dict[str, Any]:
        return control.record_event(
            module=request.module,
            event_type=request.event_type,
            payload=request.payload,
            session_id=request.session_id,
            severity=request.severity,
        )

    @app.get("/api/replay")
    async def replay_all(limit: int = Query(default=1000, ge=1, le=5000)) -> dict[str, Any]:
        return {"replay": control.session_replay(limit=limit)}

    @app.get("/api/replay/{session_id}")
    async def replay_session(session_id: str, limit: int = Query(default=1000, ge=1, le=5000)) -> dict[str, Any]:
        return {"replay": control.session_replay(session_id=session_id, limit=limit)}

    @app.get("/api/scorecard")
    async def scorecard_all(limit: int = Query(default=1000, ge=1, le=5000)) -> dict[str, Any]:
        return {"scorecard": control.session_scorecard(limit=limit)}

    @app.get("/api/scorecard/{session_id}")
    async def scorecard_session(session_id: str, limit: int = Query(default=1000, ge=1, le=5000)) -> dict[str, Any]:
        return {"scorecard": control.session_scorecard(session_id=session_id, limit=limit)}

    @app.get("/api/skills")
    async def list_skills() -> dict[str, list[dict[str, Any]]]:
        return {"skills": control.list_skills()}

    @app.post("/api/skills/{skill_name}/dry-run")
    async def dry_run_skill(skill_name: str, request: SkillDryRunRequest) -> dict[str, Any]:
        result = control.dry_run_skill(
            skill_name,
            request.args,
            session_id=request.session_id,
        )
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result["error"])
        return result

    @app.post("/api/skills/{skill_name}/execute")
    async def execute_skill(skill_name: str, request: SkillExecuteRequest) -> dict[str, Any]:
        result = control.execute_skill(
            skill_name,
            request.args,
            session_id=request.session_id,
        )
        if result["status"] == "error":
            raise HTTPException(status_code=_skill_error_status(result["error"]), detail=result["error"])
        return result

    @app.get("/api/hud/sample")
    async def sample_hud(session_id: str | None = None) -> dict[str, object]:
        return {"hud_scene": control.sample_hud(session_id)}

    @app.post("/api/hud/{session_id}/test-scene")
    async def test_hud_scene(session_id: str) -> dict[str, Any]:
        return {"hud_scene": control.test_hud(session_id)}

    @app.get("/api/hud/latest")
    async def latest_hud_scenes() -> dict[str, list[dict[str, Any]]]:
        return {"hud_scenes": control.list_hud()}

    @app.get("/api/display/commands")
    async def display_command_statuses() -> dict[str, list[dict[str, Any]]]:
        return {"display_commands": control.list_display_commands()}

    @app.post("/api/display/commands")
    async def display_command(request: DisplayCommandRequest) -> dict[str, Any]:
        result = control.request_display_command(
            kind=request.kind,
            session_id=request.session_id,
            payload=request.payload,
            command_id=request.command_id,
            skill_id=request.skill_id,
            priority=request.priority,
            ttl_ms=request.ttl_ms,
        )
        if result["status"] == "error":
            raise HTTPException(
                status_code=_display_command_error_status(result["error"]),
                detail=result["error"],
            )
        return result

    @app.get("/api/hud/{session_id}/latest")
    async def latest_hud_scene(session_id: str) -> dict[str, Any]:
        scene = control.latest_hud(session_id)
        if not scene:
            raise HTTPException(status_code=404, detail="No HUD scene for session")
        return {"hud_scene": scene}

    @app.get("/api/realtime")
    async def realtime_statuses() -> dict[str, list[dict[str, Any]]]:
        return {"realtime": control.list_realtime()}

    @app.get("/api/realtime/voice-output")
    async def realtime_voice_output_statuses() -> dict[str, list[dict[str, Any]]]:
        return {"voice_output": control.list_voice_output()}

    @app.get("/api/debug-stt")
    async def debug_stt(
        session_id: str | None = None,
        limit: int = Query(default=30, ge=1, le=120),
    ) -> dict[str, Any]:
        return {
            "status": await control.debug_stt_status(probe=True),
            "transcripts": control.list_debug_stt_transcripts(session_id=session_id, limit=limit),
        }

    @app.post("/api/debug-stt/warm")
    async def debug_stt_warm() -> dict[str, Any]:
        try:
            return await control.warm_debug_stt()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/realtime/{session_id}/start")
    async def realtime_start(session_id: str, request: RealtimeStartRequest) -> dict[str, Any]:
        try:
            return await control.realtime.start(
                session_id=session_id,
                turn_policy=request.turn_policy,
                output_modalities=request.output_modalities,
                voice_output=request.voice_output,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/realtime/{session_id}/stop")
    async def realtime_stop(session_id: str) -> dict[str, Any]:
        return await control.realtime.stop(session_id)

    @app.post("/api/realtime/{session_id}/text")
    async def realtime_text(session_id: str, request: RealtimeTextRequest) -> dict[str, Any]:
        try:
            return await control.realtime.send_text(session_id=session_id, text=request.text)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/realtime/{session_id}/audio")
    async def realtime_audio(session_id: str, request: RealtimeAudioRequest) -> dict[str, Any]:
        import base64

        try:
            audio = base64.b64decode(request.audio_base64)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid base64 audio") from exc
        try:
            appended = await control.realtime.append_audio(session_id=session_id, pcm_bytes=audio)
            if request.commit:
                committed = await control.realtime.commit_audio(
                    session_id=session_id,
                    create_response=request.create_response,
                )
                return {"audio": appended, "commit": committed}
            return appended
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/realtime/{session_id}/commit-audio")
    async def realtime_commit_audio(session_id: str) -> dict[str, Any]:
        try:
            return await control.realtime.commit_audio(session_id=session_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/realtime/{session_id}/clear-audio")
    async def realtime_clear_audio(session_id: str) -> dict[str, Any]:
        try:
            return await control.realtime.clear_audio(session_id=session_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/simulator/webrtc")
    async def simulator_webrtc_statuses() -> dict[str, list[dict[str, Any]]]:
        return {"peers": control.list_simulator()}

    @app.post("/api/simulator/webrtc/offer")
    async def simulator_webrtc_offer(request: WebRtcOfferRequest) -> dict[str, Any]:
        try:
            return await control.simulator.handle_offer(
                session_id=request.session_id,
                sdp=request.sdp,
                offer_type=request.type,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/simulator/webrtc/{session_id}/close")
    async def simulator_webrtc_close(session_id: str) -> dict[str, Any]:
        return await control.simulator.close(session_id)

    @app.get("/api/media")
    async def media_statuses() -> dict[str, list[dict[str, Any]]]:
        return {"media": control.list_media()}

    @app.get("/api/media/commands")
    async def media_command_statuses() -> dict[str, Any]:
        return {"media_commands": control.list_media_commands()}

    @app.get("/api/recordings")
    async def recordings(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
        return {
            "recorder": control.stream_recorder.status(),
            "recordings": control.list_recordings(limit=limit),
        }

    @app.post("/api/recordings/{recording_id}/finalize")
    async def finalize_recording(recording_id: str) -> dict[str, Any]:
        try:
            result = control.finalize_recording(recording_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Recording not found") from exc
        return {"recording_id": recording_id, "playable_video": result}

    @app.get("/api/recordings/{recording_id}/files/{artifact}")
    async def recording_file(recording_id: str, artifact: str) -> FileResponse:
        path, media_type = _recording_artifact_path(
            root=_recording_root_dir(control),
            recording_id=recording_id,
            artifact=artifact,
        )
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Recording artifact not found")
        return FileResponse(
            path,
            media_type=media_type,
            filename=path.name,
            content_disposition_type=_recording_content_disposition(media_type),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/recordings/{recording_id}/processed/stream.mjpeg")
    async def recording_processed_stream(
        recording_id: str,
        request: Request,
        fps: float = Query(default=8.0, ge=1.0, le=30.0),
        loop: bool = Query(default=True),
    ) -> StreamingResponse:
        path, _media_type = _recording_artifact_path(
            root=_recording_root_dir(control),
            recording_id=recording_id,
            artifact="processed-mjpeg",
        )
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Processed recording preview not found")
        boundary = "openvision-recording-frame"
        interval_s = 1.0 / max(1.0, min(30.0, float(fps or 8.0)))

        async def stream_frames():
            while True:
                emitted = 0
                for frame in _iter_jpeg_frames(path):
                    if await request.is_disconnected():
                        return
                    emitted += 1
                    yield (
                        f"--{boundary}\r\n"
                        "Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(frame)}\r\n"
                        "Cache-Control: no-store\r\n"
                        "\r\n"
                    ).encode("ascii") + frame + b"\r\n"
                    await asyncio.sleep(interval_s)
                if not loop or emitted == 0:
                    return

        return StreamingResponse(
            stream_frames(),
            media_type=f"multipart/x-mixed-replace; boundary={boundary}",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/media/commands")
    async def media_command(request: MediaCommandRequest) -> dict[str, Any]:
        result = control.request_media_command(
            mode=request.mode,
            session_id=request.session_id,
            command_id=request.command_id,
            skill_id=request.skill_id,
            reason=request.reason,
            timeout_ms=request.timeout_ms,
            fps=request.fps,
            resolution=request.resolution,
            auto_stop=request.auto_stop,
            params=request.params,
        )
        if result.get("error"):
            raise HTTPException(
                status_code=_media_command_error_status(result["error"]),
                detail=result["error"],
            )
        return result

    @app.post("/api/media/commands/{command_id}/events")
    async def media_command_event(command_id: str, request: MediaCommandEventRequest) -> dict[str, Any]:
        result = control.record_media_command_event(
            command_id=command_id,
            session_id=request.session_id,
            status=request.status,
            payload=request.payload,
        )
        if result.get("error"):
            raise HTTPException(
                status_code=_media_command_error_status(result["error"]),
                detail=result["error"],
            )
        return result

    @app.get("/api/preview")
    async def preview_statuses() -> dict[str, list[dict[str, Any]]]:
        return {"preview": control.list_preview()}

    @app.get("/api/preview/routes")
    async def preview_routes() -> dict[str, list[dict[str, Any]]]:
        return {"routes": control.list_preview_routes()}

    @app.get("/api/preview/{session_id}/frame.jpg")
    async def preview_frame(
        session_id: str,
        frame_count: int | None = Query(default=None, ge=0),
    ) -> Response:
        frame = control.preview_image_frame(session_id, frame_count=frame_count)
        if not frame:
            detail = "No decoded preview frame for session"
            if frame_count is not None:
                detail = f"No retained decoded preview frame {frame_count} for session"
            raise HTTPException(status_code=404, detail=detail)
        return Response(
            content=frame.image_bytes,
            media_type=frame.content_type,
            headers={
                "Cache-Control": "no-store",
                "X-OpenVision-Frame-Count": str(frame.frame_count),
                "X-OpenVision-Preview-Updated-At": frame.updated_at,
                "X-OpenVision-Preview-Source": frame.source,
            },
        )

    @app.get("/api/preview/{session_id}/processed/frame.jpg")
    async def preview_processed_frame(session_id: str) -> FileResponse:
        processed = control.active_processed_preview(session_id)
        if not processed:
            raise HTTPException(status_code=404, detail="No active processed preview frame for session")
        latest = processed.get("latest_annotated_preview") if isinstance(processed.get("latest_annotated_preview"), dict) else {}
        path = Path(str(latest.get("path") or ""))
        if not path.is_file():
            raise HTTPException(status_code=404, detail="No active processed preview frame for session")
        return FileResponse(
            path,
            media_type="image/jpeg",
            filename=path.name,
            content_disposition_type="inline",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/preview/{session_id}/frame")
    async def preview_frame_upload(
        session_id: str,
        request: Request,
        source: str = Query(default="rv101_snapshot", min_length=1),
        width: int | None = Query(default=None, ge=1),
        height: int | None = Query(default=None, ge=1),
        frame_count: int = Query(default=1, ge=0),
        orientation: str | None = Query(default=None),
        profile: str | None = Query(default=None),
        rotation_degrees: int | None = Query(default=None),
        mirrored: bool | None = Query(default=None),
        source_width: int | None = Query(default=None, ge=1),
        source_height: int | None = Query(default=None, ge=1),
        preview_profile: str | None = Query(default=None),
    ) -> dict[str, Any]:
        content_type = (request.headers.get("content-type") or "image/jpeg").split(";", 1)[0].strip().lower()
        image_bytes = await request.body()
        if len(image_bytes) > 8 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "preview_frame_too_large",
                    "message": "Preview frame uploads are limited to 8 MiB.",
                },
            )
        result = control.record_preview_frame(
            session_id=session_id,
            image_bytes=image_bytes,
            source=source,
            width=width,
            height=height,
            frame_count=frame_count,
            content_type=content_type,
            metadata=_request_sensor_metadata(
                request,
                orientation=orientation,
                profile=profile,
                rotation_degrees=rotation_degrees,
                mirrored=mirrored,
                source_width=source_width,
                source_height=source_height,
                preview_profile=preview_profile,
            ),
        )
        if result["status"] == "error":
            raise HTTPException(
                status_code=_preview_upload_error_status(result["error"]),
                detail=result["error"],
            )
        return result

    @app.get("/api/preview/{session_id}/stream.mjpeg")
    async def preview_mjpeg(session_id: str, request: Request) -> StreamingResponse:
        if not control.preview_status(session_id):
            raise HTTPException(status_code=404, detail="No decoded preview frame for session")
        boundary = "openvision-frame"
        queue = control.preview.subscribe(session_id)

        async def stream_frames():
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        frame = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if frame is None:
                        return
                    content_type = frame.content_type or "image/jpeg"
                    yield (
                        f"--{boundary}\r\n"
                        f"Content-Type: {content_type}\r\n"
                        f"Content-Length: {len(frame.image_bytes)}\r\n"
                        "Cache-Control: no-store\r\n"
                        "\r\n"
                    ).encode("ascii") + frame.image_bytes + b"\r\n"
            finally:
                control.preview.unsubscribe(session_id, queue)

        return StreamingResponse(
            stream_frames(),
            media_type=f"multipart/x-mixed-replace; boundary={boundary}",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/preview/{session_id}/h264")
    async def preview_h264_status(session_id: str) -> dict[str, Any]:
        status = control.h264_live_status(session_id)
        if not status:
            raise HTTPException(status_code=404, detail="No live H.264 stream for session")
        return {"h264_live": status}

    @app.get("/api/preview/{session_id}/deepstream-h264")
    async def preview_deepstream_h264_status(session_id: str) -> dict[str, Any]:
        status = control.deepstream_h264_live_status(session_id)
        if not status:
            raise HTTPException(status_code=404, detail="No DeepStream annotated H.264 stream for session")
        return {"h264_live": status}

    @app.get("/api/crops/{session_id}/{image_name}")
    async def crop_image(session_id: str, image_name: str) -> Response:
        safe_session_id = _safe_runtime_segment(session_id)
        safe_image_name = _safe_runtime_image_name(image_name)
        if not safe_session_id or not safe_image_name:
            raise HTTPException(status_code=404, detail="Crop not found")
        image_path = default_runtime_dir() / "crops" / safe_session_id / safe_image_name
        if not image_path.is_file():
            raise HTTPException(status_code=404, detail="Crop not found")
        return Response(
            content=image_path.read_bytes(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/identity/status")
    async def identity_status() -> dict[str, Any]:
        return {"identity": control.identity_status()}

    @app.get("/api/identity/contacts")
    async def identity_contacts() -> dict[str, Any]:
        return {"contacts": control.list_identity_contacts()}

    @app.post("/api/identity/contacts", status_code=201)
    async def identity_create_contact(request: IdentityContactRequest) -> dict[str, Any]:
        try:
            contact = control.create_identity_contact(
                display_name=request.display_name,
                aliases=request.aliases,
                notes=request.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_identity_contact", "message": str(exc)}) from exc
        return {"contact": contact}

    @app.post("/api/identity/enroll", status_code=201)
    async def identity_enroll(request: IdentityEnrollRequest) -> dict[str, Any]:
        try:
            return control.enroll_identity_sample(
                display_name=request.display_name,
                contact_id=request.contact_id,
                aliases=request.aliases,
                notes=request.notes,
                image_ref=request.image_ref,
                image_path=request.image_path,
                vector=request.vector,
                source_note=request.source_note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_identity_sample", "message": str(exc)}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"code": "identity_provider_unavailable", "message": str(exc)}) from exc

    @app.post("/api/identity/match")
    async def identity_match(request: IdentityMatchRequest) -> dict[str, Any]:
        return {
            "identity_match": control.match_identity_candidates(
                candidates=request.candidates,
                query=request.query,
                session_id=request.session_id,
            )
        }

    @app.get("/api/people/status")
    async def people_status() -> dict[str, Any]:
        return {"people_registry": control.people_status()}

    @app.get("/api/people")
    async def people_list() -> dict[str, Any]:
        return {"people": control.list_people()}

    @app.get("/api/people/{person_id}/thumbnail")
    async def people_thumbnail(person_id: str) -> Response:
        try:
            image_bytes, content_type = control.person_thumbnail(person_id=person_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"code": "people_thumbnail_not_found", "message": str(exc)}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"code": "people_thumbnail_provider_unavailable", "message": str(exc)}) from exc
        return Response(content=image_bytes, media_type=content_type, headers={"Cache-Control": "no-store"})

    @app.post("/api/people/sync")
    async def people_sync(request: PeopleSyncRequest) -> dict[str, Any]:
        result = control.sync_people_from_immich(push_names=request.push_names)
        status_code = result.get("status")
        if status_code == "error":
            raise HTTPException(status_code=503, detail={"code": result.get("reason"), "message": result.get("message")})
        return {"sync": result}

    @app.post("/api/people/{person_id}")
    async def people_update(person_id: str, request: PeopleProfileUpdateRequest) -> dict[str, Any]:
        try:
            person = control.update_person_profile(
                person_id=person_id,
                display_name=request.display_name,
                aliases=request.aliases,
                phone=request.phone,
                address=request.address,
                age=request.age,
                where_lives=request.where_lives,
                relationship=request.relationship,
                first_met=request.first_met,
                links=request.links,
                facts=request.facts,
                notes=request.notes,
                sync_name_to_immich=request.sync_name_to_immich,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_person_profile", "message": str(exc)}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"code": "people_registry_provider_unavailable", "message": str(exc)}) from exc
        return {"person": person}

    @app.post("/api/people/{person_id}/sync-name")
    async def people_sync_name(person_id: str) -> dict[str, Any]:
        try:
            return {"sync": control.sync_person_name_to_immich(person_id=person_id)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_person_profile", "message": str(exc)}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"code": "people_registry_provider_unavailable", "message": str(exc)}) from exc

    @app.post("/api/people/{person_id}/enroll-identity", status_code=201)
    async def people_enroll_identity(person_id: str, request: PeopleIdentityEnrollRequest) -> dict[str, Any]:
        try:
            return {
                "identity_enrollment": control.enroll_person_identity_from_immich(
                    person_id=person_id,
                    display_name=request.display_name,
                    aliases=request.aliases,
                    max_assets=request.max_assets,
                )
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_people_identity_enrollment", "message": str(exc)}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"code": "people_identity_provider_unavailable", "message": str(exc)}) from exc

    @app.get("/api/rv101/ingest")
    async def rv101_ingest_status() -> dict[str, Any]:
        return {"ingest": control.rv101_ingest_status()}

    @app.post("/api/media/{session_id}/video/heartbeat")
    async def media_video_heartbeat(session_id: str, request: VideoHeartbeatRequest) -> dict[str, Any]:
        return control.record_video_heartbeat(
            session_id=session_id,
            transport=request.transport,
            codec=request.codec,
            width=request.width,
            height=request.height,
            fps=request.fps,
            metadata=_model_sensor_metadata(request),
        )

    @app.post("/api/media/{session_id}/audio/metrics")
    async def media_audio_metrics(session_id: str, request: AudioMetricsRequest) -> dict[str, Any]:
        return control.record_audio_metrics(
            session_id=session_id,
            transport=request.transport,
            sample_rate=request.sample_rate,
            channels=request.channels,
            chunk_count=request.chunk_count,
            strong_chunk_count=request.strong_chunk_count,
            rms=request.rms,
            avg_abs=request.avg_abs,
            peak_abs=request.peak_abs,
            non_silent_ratio=request.non_silent_ratio,
            source=request.source,
        )

    @app.get("/api/perception")
    async def perception_statuses() -> dict[str, list[dict[str, Any]]]:
        return {"perception": control.list_perception()}

    @app.get("/api/perception/{session_id}/history")
    async def perception_history(
        session_id: str,
        limit: int = Query(default=10, ge=1, le=100),
    ) -> dict[str, list[dict[str, Any]]]:
        return {"perception": control.perception_history(session_id=session_id, limit=limit)}

    @app.post("/api/perception/{session_id}/detections")
    async def perception_detections(session_id: str, request: PerceptionSnapshotRequest) -> dict[str, Any]:
        result = control.ingest_debug_perception_snapshot(
            session_id=session_id,
            detections=request.detections,
            source=request.source,
            frame_id=request.frame_id,
            width=request.width,
            height=request.height,
            metadata=_model_sensor_metadata(request),
        )
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result["error"])
        return result["perception"]

    @app.get("/api/adapters/yolo26")
    async def yolo26_adapter_status() -> dict[str, Any]:
        return {"adapter": control.yolo26_status()}

    @app.get("/api/adapters/yolo26/worker")
    async def yolo26_worker_status() -> dict[str, Any]:
        return {"worker": _read_yolo26_worker_status(default_runtime_dir())}

    @app.get("/api/adapters/face-identity")
    async def face_identity_adapter_status() -> dict[str, Any]:
        return {"adapter": control.face_identity_status()}

    @app.get("/api/adapters/face-identity/worker")
    async def face_identity_worker_status() -> dict[str, Any]:
        return {"worker": _read_face_identity_worker_status(default_runtime_dir())}

    @app.post("/api/adapters/yolo26/{session_id}/detections")
    async def yolo26_adapter_detections(session_id: str, request: Yolo26SnapshotRequest) -> dict[str, Any]:
        result = control.ingest_yolo26_snapshot(
            session_id=session_id,
            detections=request.detections,
            source=request.source,
            frame_id=request.frame_id,
            width=request.width,
            height=request.height,
            metadata=_model_sensor_metadata(request),
        )
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result["error"])
        return result

    @app.post("/api/adapters/yolo26/{session_id}/stream")
    async def yolo26_adapter_stream_frame(session_id: str, request: Yolo26StreamFrameRequest) -> dict[str, Any]:
        result = control.ingest_yolo26_stream_frame(
            session_id=session_id,
            detections=request.detections,
            source=request.source,
            frame_id=request.frame_id,
            width=request.width,
            height=request.height,
            sequence=request.sequence,
            latency_ms=request.latency_ms,
            metadata=_model_sensor_metadata(request),
        )
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result["error"])
        return result

    @app.post("/api/adapters/face-identity/{session_id}/stream")
    async def face_identity_adapter_stream_frame(
        session_id: str,
        request: FaceIdentityStreamFrameRequest,
    ) -> dict[str, Any]:
        result = control.ingest_face_identity_stream_frame(
            session_id=session_id,
            detections=request.detections,
            source=request.source,
            frame_id=request.frame_id,
            width=request.width,
            height=request.height,
            sequence=request.sequence,
            latency_ms=request.latency_ms,
            metadata=_model_sensor_metadata(request),
        )
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result["error"])
        return result

    @app.websocket("/ws/perception")
    async def perception_stream(websocket: WebSocket) -> None:
        if not await _accept_guarded_websocket(websocket):
            return
        queue = control.subscribe_perception()
        receive_task = asyncio.create_task(websocket.receive_text())
        queue_task: asyncio.Task[Any] | None = None
        try:
            await websocket.send_json({"type": "openvision.perception_stream.v1"})
            while True:
                queue_task = asyncio.create_task(queue.get())
                done, _pending = await asyncio.wait(
                    {queue_task, receive_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if receive_task in done:
                    try:
                        receive_task.result()
                    except WebSocketDisconnect:
                        return
                    except RuntimeError:
                        return
                    return
                snapshot = queue_task.result()
                queue_task = None
                if snapshot is not None:
                    await websocket.send_json({"type": "perception_snapshot", "snapshot": snapshot})
        except asyncio.CancelledError:
            return
        except WebSocketDisconnect:
            return
        finally:
            await _cancel_ws_task(queue_task)
            await _cancel_ws_task(receive_task)
            control.unsubscribe_perception(queue)

    @app.websocket("/ws/events")
    async def event_stream(websocket: WebSocket) -> None:
        if not await _accept_guarded_websocket(websocket):
            return
        try:
            while True:
                await websocket.send_json({"events": control.list_events(limit=80)})
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            return

    @app.websocket("/ws/realtime/{session_id}/audio")
    async def realtime_audio_output_stream(websocket: WebSocket, session_id: str) -> None:
        if not await _accept_guarded_websocket(websocket):
            return
        queue = control.voice_output.subscribe(session_id)
        receive_task = asyncio.create_task(websocket.receive_text())
        queue_task: asyncio.Task[dict[str, Any]] | None = None
        try:
            await websocket.send_json(
                {
                    "type": "voice_config",
                    "format": "pcm_s16le",
                    "sample_rate": 24000,
                    "channels": 1,
                }
            )
            while True:
                queue_task = asyncio.create_task(queue.get())
                done, pending = await asyncio.wait(
                    {queue_task, receive_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if receive_task in done:
                    try:
                        receive_task.result()
                    except WebSocketDisconnect:
                        return
                    except RuntimeError:
                        return
                    return
                message = queue_task.result()
                queue_task = None
                await websocket.send_json(message)
        except asyncio.CancelledError:
            return
        except WebSocketDisconnect:
            return
        finally:
            await _cancel_ws_task(queue_task)
            await _cancel_ws_task(receive_task)
            control.voice_output.unsubscribe(session_id, queue)

    @app.websocket("/ws/preview/{session_id}/h264")
    async def rv101_h264_preview_stream(websocket: WebSocket, session_id: str) -> None:
        if not await _accept_guarded_websocket(websocket):
            return
        queue = control.subscribe_h264_live(session_id)
        try:
            await websocket.send_json(
                {
                    "type": "openvision.h264_preview.v1",
                    "session_id": session_id,
                    "codec": "video/avc",
                    "container": "annexb_h264",
                    "status": control.h264_live_status(session_id) or {"state": "waiting"},
                }
            )
            await _send_h264_preview_samples(
                websocket=websocket,
                queue=queue,
                session_id=session_id,
                status_provider=control.h264_live_status,
            )
        except asyncio.CancelledError:
            return
        except WebSocketDisconnect:
            return
        finally:
            control.unsubscribe_h264_live(session_id, queue)

    @app.websocket("/ws/preview/{session_id}/deepstream-h264")
    async def deepstream_h264_preview_stream(websocket: WebSocket, session_id: str) -> None:
        if not await _accept_guarded_websocket(websocket):
            return
        queue = control.subscribe_deepstream_h264_live(session_id)
        try:
            await websocket.send_json(
                {
                    "type": "openvision.h264_preview.v1",
                    "session_id": session_id,
                    "codec": "video/avc",
                    "container": "annexb_h264",
                    "source": "deepstream_yolo26_osd",
                    "status": control.deepstream_h264_live_status(session_id) or {"state": "waiting"},
                }
            )
            await _send_h264_preview_samples(
                websocket=websocket,
                queue=queue,
                session_id=session_id,
                status_provider=control.deepstream_h264_live_status,
            )
        except asyncio.CancelledError:
            return
        except WebSocketDisconnect:
            return
        finally:
            control.unsubscribe_deepstream_h264_live(session_id, queue)

    @app.websocket("/ws/adapters/deepstream/{session_id}/h264")
    async def deepstream_h264_ingest(websocket: WebSocket, session_id: str) -> None:
        if not await _accept_guarded_websocket(websocket):
            return
        pending_header: dict[str, Any] = {}
        sequence = 0
        try:
            await websocket.send_json({"type": "openvision.deepstream_h264_ingest.v1", "session_id": session_id})
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                text = message.get("text")
                if text is not None:
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        pending_header = {}
                        continue
                    if isinstance(payload, dict):
                        pending_header = dict(payload)
                    continue
                data = message.get("bytes")
                if not data:
                    continue
                sequence += 1
                header = {
                    **pending_header,
                    "sequence": pending_header.get("sequence") or sequence,
                }
                control.ingest_deepstream_h264_sample(
                    session_id=session_id,
                    header=header,
                    payload=data,
                )
                pending_header = {}
        except WebSocketDisconnect:
            return

    @app.websocket("/ws")
    async def rv101_control(websocket: WebSocket) -> None:
        if not await _accept_guarded_websocket(websocket):
            return
        session_id: str | None = None
        last_hud_scene_id: str | None = None
        hud_queue: Any | None = None
        hud_session_id: str | None = None
        receive_task = asyncio.create_task(websocket.receive_text())
        hud_task: asyncio.Task[Any] | None = None

        async def send_latest_hud_if_changed() -> None:
            nonlocal last_hud_scene_id
            if not session_id:
                return
            scene = control.latest_hud(session_id)
            if not scene:
                return
            scene_id = str(scene.get("scene_id") or "").strip()
            if not scene_id or scene_id == last_hud_scene_id:
                return
            await websocket.send_json({"type": "hud_scene", "scene": scene})
            last_hud_scene_id = scene_id

        def subscribe_hud_for_session(new_session_id: str) -> None:
            nonlocal hud_queue, hud_session_id, hud_task
            if hud_queue is not None and hud_session_id:
                control.unsubscribe_hud(hud_session_id, hud_queue)
            if hud_task and not hud_task.done():
                hud_task.cancel()
            hud_queue = control.subscribe_hud(new_session_id)
            hud_session_id = new_session_id
            hud_task = asyncio.create_task(hud_queue.get())

        try:
            while True:
                tasks: set[asyncio.Task[Any]] = {receive_task}
                if hud_task is not None:
                    tasks.add(hud_task)
                done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if hud_task is not None and hud_task in done:
                    scene = hud_task.result()
                    hud_task = asyncio.create_task(hud_queue.get()) if hud_queue is not None else None
                    if scene is not None:
                        scene_id = str(scene.get("scene_id") or "").strip()
                        if scene_id and scene_id != last_hud_scene_id:
                            await websocket.send_json({"type": "hud_scene", "scene": scene})
                            last_hud_scene_id = scene_id
                    continue
                if receive_task in done:
                    try:
                        raw = receive_task.result()
                    except WebSocketDisconnect:
                        return
                    receive_task = asyncio.create_task(websocket.receive_text())
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        await websocket.send_json({"type": "error", "code": "invalid_json"})
                        continue
                    if not isinstance(payload, dict):
                        await websocket.send_json({"type": "error", "code": "invalid_message"})
                        continue
                    if payload.get("type") == "client_hello":
                        session = await control.create_rv101_control_session(payload)
                        session_id = str(session["session"]["session_id"])
                        subscribe_hud_for_session(session_id)
                        await websocket.send_json(session["accept"])
                        await websocket.send_json(session["hud_scene"])
                        continue
                    for message in await control.handle_rv101_control_message(
                        session_id=session_id,
                        payload=payload,
                    ):
                        await websocket.send_json(message)
                        if message.get("type") == "session_closed":
                            await websocket.close()
                            return
                    await send_latest_hud_if_changed()
        except WebSocketDisconnect:
            return
        finally:
            await _cancel_ws_task(receive_task)
            await _cancel_ws_task(hud_task)
            if hud_queue is not None and hud_session_id:
                control.unsubscribe_hud(hud_session_id, hud_queue)
            if session_id:
                await control.close_rv101_control_session(session_id)

    static_dir = default_static_dir()
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="ops_console")
    return app


async def _cancel_ws_task(task: asyncio.Task[Any] | None) -> None:
    if task is None:
        return
    if not task.done():
        task.cancel()
    try:
        await task
    except (asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
        return
    except Exception:
        return


async def _send_h264_preview_samples(
    *,
    websocket: WebSocket,
    queue: Any,
    session_id: str,
    status_provider: Any,
) -> None:
    """Stream server-owned H.264 samples without leaving orphan Queue.get tasks."""

    while True:
        try:
            sample = await asyncio.wait_for(queue.get(), timeout=H264_PREVIEW_HEARTBEAT_S)
        except TimeoutError:
            await websocket.send_json(
                {
                    "type": "heartbeat",
                    "session_id": session_id,
                    "status": status_provider(session_id) or {"state": "waiting"},
                }
            )
            continue
        if sample is None:
            await websocket.send_json({"type": "closed", "session_id": session_id})
            return
        await websocket.send_json(sample.ws_metadata())
        await websocket.send_bytes(sample.payload)


def _skill_error_status(error: dict[str, Any] | None) -> int:
    if not isinstance(error, dict):
        return 500
    if error.get("code") == "unknown_skill":
        return 404
    if error.get("code") in {"invalid_skill_args", "missing_target_id"}:
        return 400
    return 409


def _media_command_error_status(error: dict[str, Any] | None) -> int:
    if not isinstance(error, dict):
        return 500
    if error.get("code") == "unknown_session":
        return 404
    if error.get("code") in {
        "auto_stop_required",
        "invalid_media_action",
        "invalid_media_budget",
        "invalid_media_mode",
        "missing_media_budget",
        "missing_media_command_field",
        "missing_media_command",
        "missing_session",
        "invalid_media_event_payload",
        "invalid_media_event_status",
    }:
        return 400
    if error.get("code") == "unknown_media_command":
        return 404
    return 409


def _preview_upload_error_status(error: dict[str, Any] | None) -> int:
    if not isinstance(error, dict):
        return 500
    if error.get("code") == "unknown_session":
        return 404
    if error.get("code") in {"empty_preview_frame", "unsupported_preview_content_type"}:
        return 400
    return 409


def _model_sensor_metadata(model: BaseModel) -> dict[str, Any]:
    metadata = getattr(model, "metadata", None)
    output = dict(metadata) if isinstance(metadata, dict) else {}
    aliases = {
        "orientation": ("orientation", "sensorOrientation", "sensor_orientation"),
        "sensor_orientation_degrees": ("sensor_orientation_degrees", "sensorOrientationDegrees"),
        "profile": ("profile", "cameraProfile", "camera_profile", "videoProfile", "video_profile"),
        "rotation_degrees": ("rotation_degrees", "rotationDegrees", "displayRotation", "display_rotation"),
        "mirrored": ("mirrored", "isMirrored", "is_mirrored"),
        "source_width": ("source_width", "sourceWidth", "captureWidth", "capture_width", "sensorWidth", "sensor_width"),
        "source_height": ("source_height", "sourceHeight", "captureHeight", "capture_height", "sensorHeight", "sensor_height"),
        "requested_width": ("requested_width", "requestedWidth"),
        "requested_height": ("requested_height", "requestedHeight"),
        "capture_fps_min": ("capture_fps_min", "captureFpsMin"),
        "capture_fps_max": ("capture_fps_max", "captureFpsMax"),
        "sent_fps_estimate": ("sent_fps_estimate", "sentFpsEstimate"),
        "dropped_frames": ("dropped_frames", "droppedFrames"),
        "camera_id": ("camera_id", "cameraId"),
        "preview_profile": ("preview_profile", "previewProfile"),
    }
    for key, names in aliases.items():
        value = _model_sensor_value(model, *names)
        if value is not None:
            output[key] = value
    return output


def _model_sensor_value(model: BaseModel, *names: str) -> Any:
    extra = getattr(model, "model_extra", None)
    if not isinstance(extra, dict):
        extra = getattr(model, "__pydantic_extra__", None)
    if not isinstance(extra, dict):
        extra = {}
    raw = getattr(model, "__dict__", {})
    raw = raw if isinstance(raw, dict) else {}
    for name in names:
        if hasattr(model, name):
            value = getattr(model, name)
            if value is not None:
                return value
        if name in extra and extra.get(name) is not None:
            return extra.get(name)
        if name in raw and raw.get(name) is not None:
            return raw.get(name)
    return None


def _request_sensor_metadata(
    request: Request,
    *,
    orientation: str | None = None,
    profile: str | None = None,
    rotation_degrees: int | None = None,
    mirrored: bool | None = None,
    source_width: int | None = None,
    source_height: int | None = None,
    preview_profile: str | None = None,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    header_map = {
        "orientation": "x-openvision-orientation",
        "sensor_orientation_degrees": "x-openvision-sensor-orientation-degrees",
        "profile": "x-openvision-profile",
        "rotation_degrees": "x-openvision-rotation-degrees",
        "mirrored": "x-openvision-mirrored",
        "source_width": "x-openvision-source-width",
        "source_height": "x-openvision-source-height",
        "requested_width": "x-openvision-requested-width",
        "requested_height": "x-openvision-requested-height",
        "capture_fps_min": "x-openvision-capture-fps-min",
        "capture_fps_max": "x-openvision-capture-fps-max",
        "sent_fps_estimate": "x-openvision-sent-fps-estimate",
        "dropped_frames": "x-openvision-dropped-frames",
        "camera_id": "x-openvision-camera-id",
        "preview_profile": "x-openvision-preview-profile",
    }
    for key, header in header_map.items():
        value = request.headers.get(header)
        if value is not None:
            output[key] = value
    query_aliases = {
        "sensor_orientation_degrees": ("sensorOrientationDegrees", "sensor_orientation_degrees"),
        "requested_width": ("requestedWidth", "requested_width"),
        "requested_height": ("requestedHeight", "requested_height"),
        "capture_fps_min": ("captureFpsMin", "capture_fps_min"),
        "capture_fps_max": ("captureFpsMax", "capture_fps_max"),
        "sent_fps_estimate": ("sentFpsEstimate", "sent_fps_estimate"),
        "dropped_frames": ("droppedFrames", "dropped_frames"),
        "camera_id": ("cameraId", "camera_id"),
    }
    for key, names in query_aliases.items():
        for name in names:
            value = request.query_params.get(name)
            if value is not None:
                output[key] = value
                break
    for key, value in {
        "orientation": orientation,
        "profile": profile,
        "rotation_degrees": rotation_degrees,
        "mirrored": mirrored,
        "source_width": source_width,
        "source_height": source_height,
        "preview_profile": preview_profile,
    }.items():
        if value is not None:
            output[key] = value
    return output


def _display_command_error_status(error: dict[str, Any] | None) -> int:
    if not isinstance(error, dict):
        return 500
    if error.get("code") == "unknown_session":
        return 404
    if error.get("code") in {
        "debug_overlay_disabled",
        "invalid_display_kind",
        "invalid_display_priority",
        "invalid_display_ttl",
        "missing_display_payload_field",
        "missing_session",
    }:
        return 400
    return 409


def _read_yolo26_worker_status(runtime_dir: Path) -> dict[str, Any]:
    status_path = runtime_dir / "status" / "deepstream_yolo26_worker.json"
    if not status_path.is_file():
        return {
            "schema_version": "openvision.deepstream_yolo26_worker_status.v1",
            "status": "not_reported",
            "enabled": False,
            "backend": "deepstream",
            "ring_safety": "separate_openvision_runtime_only",
            "total_posted_frame_count": 0,
            "total_skipped_frame_count": 0,
            "last_posted_frame": None,
            "message": "DeepStream YOLO26 worker has not written a status file yet.",
        }
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema_version": "openvision.deepstream_yolo26_worker_status.v1",
            "status": "error",
            "enabled": False,
            "backend": "deepstream",
            "ring_safety": "separate_openvision_runtime_only",
            "message": f"Could not read DeepStream YOLO26 worker status: {exc.__class__.__name__}",
        }
    if not isinstance(payload, dict):
        return {
            "schema_version": "openvision.deepstream_yolo26_worker_status.v1",
            "status": "error",
            "enabled": False,
            "backend": "deepstream",
            "ring_safety": "separate_openvision_runtime_only",
            "message": "DeepStream YOLO26 worker status file is not a JSON object.",
        }
    return _normalize_worker_status(
        _redact_worker_status(payload),
        schema_version="openvision.deepstream_yolo26_worker_status.v1",
    )


def _read_face_identity_worker_status(runtime_dir: Path) -> dict[str, Any]:
    status_path = runtime_dir / "status" / "face_identity_worker.json"
    if not status_path.is_file():
        return {
            "schema_version": "openvision.face_identity_worker_status.v1",
            "status": "not_reported",
            "enabled": False,
            "ring_safety": "separate_openvision_runtime_only",
            "total_posted_frame_count": 0,
            "total_skipped_frame_count": 0,
            "last_posted_frame": None,
            "message": "Face identity worker has not written a status file yet.",
        }
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema_version": "openvision.face_identity_worker_status.v1",
            "status": "error",
            "enabled": False,
            "ring_safety": "separate_openvision_runtime_only",
            "message": f"Could not read face identity worker status: {exc.__class__.__name__}",
        }
    if not isinstance(payload, dict):
        return {
            "schema_version": "openvision.face_identity_worker_status.v1",
            "status": "error",
            "enabled": False,
            "ring_safety": "separate_openvision_runtime_only",
            "message": "Face identity worker status file is not a JSON object.",
        }
    return _normalize_worker_status(
        _redact_worker_status(payload),
        schema_version="openvision.face_identity_worker_status.v1",
    )


def _normalize_worker_status(payload: Any, *, schema_version: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "schema_version": schema_version,
            "status": "error",
            "enabled": False,
            "ring_safety": "separate_openvision_runtime_only",
            "message": "Worker status payload is not a JSON object.",
        }
    normalized = dict(payload)
    normalized.setdefault("schema_version", schema_version)
    normalized.setdefault("enabled", False)
    normalized.setdefault("ring_safety", "separate_openvision_runtime_only")
    normalized.setdefault("total_posted_frame_count", 0)
    normalized.setdefault("total_skipped_frame_count", 0)
    normalized.setdefault("last_posted_frame", None)
    return normalized


def _redact_worker_status(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _redact_worker_status(item)
            for key, item in value.items()
            if str(key) not in {"model_path", "detector_model_path", "recognizer_model_path"}
        }
    if isinstance(value, list):
        return [_redact_worker_status(item) for item in value]
    return value


def _safe_runtime_segment(value: str) -> str | None:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-"})
    return cleaned or None


def _safe_runtime_image_name(value: str) -> str | None:
    cleaned = _safe_runtime_segment(value.removesuffix(".jpg"))
    if not cleaned:
        return None
    return f"{cleaned}.jpg"


_RECORDING_ARTIFACTS: dict[str, tuple[Path, str]] = {
    "manifest": (Path("manifest.jsonl"), "application/x-ndjson"),
    "raw-video": (Path("raw") / "video.h264", "video/h264"),
    "raw-video-mp4": (Path("raw") / "video.mp4", "video/mp4"),
    "raw-audio": (Path("raw") / "audio.wav", "audio/wav"),
    "processed-mjpeg": (Path("processed") / "preview_annotated.mjpeg", "video/x-motion-jpeg"),
    "processed-preview-mp4": (Path("processed") / "preview_annotated.mp4", "video/mp4"),
    "latest-annotated": (Path("processed") / "latest_annotated.jpg", "image/jpeg"),
    "processed-events": (Path("processed") / "preview_annotated.jsonl", "application/x-ndjson"),
}


def _recording_root_dir(control: OpenVisionControlPlane) -> Path:
    status = control.stream_recorder.status()
    root = status.get("root_dir") if isinstance(status, dict) else None
    return Path(str(root or default_runtime_dir() / "recordings")).expanduser()


def _recording_artifact_path(*, root: Path, recording_id: str, artifact: str) -> tuple[Path, str]:
    safe_recording_id = _safe_runtime_segment(recording_id)
    if not safe_recording_id or safe_recording_id != recording_id:
        raise HTTPException(status_code=404, detail="Recording not found")
    try:
        relative_path, media_type = _RECORDING_ARTIFACTS[artifact]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Recording artifact not found") from exc
    root_path = root.resolve()
    artifact_path = (root_path / safe_recording_id / relative_path).resolve()
    try:
        artifact_path.relative_to(root_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Recording artifact not found") from exc
    return artifact_path, media_type


def _recording_content_disposition(media_type: str) -> str:
    return "inline" if media_type in {"video/mp4", "audio/wav", "image/jpeg"} else "attachment"


def _iter_jpeg_frames(path: Path):
    buffer = bytearray()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(64 * 1024)
            if chunk:
                buffer.extend(chunk)
            while True:
                start = buffer.find(b"\xff\xd8")
                if start < 0:
                    if len(buffer) > 1:
                        del buffer[:-1]
                    break
                end = buffer.find(b"\xff\xd9", start + 2)
                if end < 0:
                    if start:
                        del buffer[:start]
                    break
                end += 2
                yield bytes(buffer[start:end])
                del buffer[:end]
            if not chunk:
                return


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OpenVision Rokid v2 Jetson agent.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    uvicorn.run(
        "openvision_jetson.fastapi_app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=str(Path(__file__).resolve().parents[1]),
    )


if __name__ == "__main__":
    main()
