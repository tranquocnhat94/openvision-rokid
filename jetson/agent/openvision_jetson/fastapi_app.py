"""FastAPI entrypoint for the OpenVision Rokid v2 Jetson service."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .control_plane import OpenVisionControlPlane


def default_static_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "web_ui" / "static"


class CreateSessionRequest(BaseModel):
    client_kind: str = Field(..., min_length=1)
    capabilities: dict[str, Any] = Field(default_factory=dict)


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
    turn_policy: str = "manual"
    output_modalities: list[str] | None = None
    voice_output: bool | None = None


class RealtimeTextRequest(BaseModel):
    text: str = Field(..., min_length=1)


class RealtimeAudioRequest(BaseModel):
    audio_base64: str = Field(..., min_length=1)
    commit: bool = False
    create_response: bool = True


class WebRtcOfferRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    sdp: str = Field(..., min_length=1)
    type: str = "offer"


class VideoHeartbeatRequest(BaseModel):
    transport: str = Field(..., min_length=1)
    codec: str = Field(..., min_length=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    fps: float | None = Field(default=None, ge=0)


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


class PerceptionSnapshotRequest(BaseModel):
    source: str = Field(..., min_length=1)
    detections: list[dict[str, Any]] = Field(default_factory=list)
    frame_id: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)


class Yolo26SnapshotRequest(BaseModel):
    source: str = "rokid_yolo26_external"
    detections: list[dict[str, Any]] = Field(default_factory=list)
    frame_id: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)


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
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def no_store_ops_assets(request, call_next):
        response = await call_next(request)
        if request.url.path in {"/", "/app.js", "/style.css"} or request.url.path.startswith("/api/preview/"):
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
        return await control.realtime.start(
            session_id=session_id,
            turn_policy=request.turn_policy,
            output_modalities=request.output_modalities,
            voice_output=request.voice_output,
        )

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

    @app.get("/api/preview")
    async def preview_statuses() -> dict[str, list[dict[str, Any]]]:
        return {"preview": control.list_preview()}

    @app.get("/api/preview/{session_id}/frame.jpg")
    async def preview_frame(session_id: str) -> Response:
        image = control.latest_preview_image(session_id)
        if not image:
            raise HTTPException(status_code=404, detail="No decoded preview frame for session")
        image_bytes, content_type = image
        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={"Cache-Control": "no-store"},
        )

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
        return control.update_perception(
            session_id=session_id,
            detections=request.detections,
            source=request.source,
            frame_id=request.frame_id,
            width=request.width,
            height=request.height,
        )

    @app.get("/api/adapters/yolo26")
    async def yolo26_adapter_status() -> dict[str, Any]:
        return {"adapter": control.yolo26_status()}

    @app.post("/api/adapters/yolo26/{session_id}/detections")
    async def yolo26_adapter_detections(session_id: str, request: Yolo26SnapshotRequest) -> dict[str, Any]:
        result = control.ingest_yolo26_snapshot(
            session_id=session_id,
            detections=request.detections,
            source=request.source,
            frame_id=request.frame_id,
            width=request.width,
            height=request.height,
        )
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result["error"])
        return result

    @app.websocket("/ws/events")
    async def event_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.send_json({"events": control.list_events(limit=80)})
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            return

    @app.websocket("/ws/realtime/{session_id}/audio")
    async def realtime_audio_output_stream(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        queue = control.voice_output.subscribe(session_id)
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
                message = await queue.get()
                await websocket.send_json(message)
        except WebSocketDisconnect:
            return
        finally:
            control.voice_output.unsubscribe(session_id, queue)

    @app.websocket("/ws")
    async def rv101_control(websocket: WebSocket) -> None:
        await websocket.accept()
        session_id: str | None = None
        try:
            while True:
                raw = await websocket.receive_text()
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
                    await websocket.send_json(session["accept"])
                    await websocket.send_json(session["hud_scene"])
                    continue
                for message in await control.handle_rv101_control_message(
                    session_id=session_id,
                    payload=payload,
                ):
                    await websocket.send_json(message)
        except WebSocketDisconnect:
            if session_id:
                control.record_event(
                    module="rv101_control",
                    event_type="disconnected",
                    session_id=session_id,
                    payload={},
                )

    static_dir = default_static_dir()
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="ops_console")
    return app


def _skill_error_status(error: dict[str, Any] | None) -> int:
    if not isinstance(error, dict):
        return 500
    if error.get("code") == "unknown_skill":
        return 404
    if error.get("code") in {"invalid_skill_args", "missing_target_id"}:
        return 400
    return 409


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
