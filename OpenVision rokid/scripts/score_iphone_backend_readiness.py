#!/usr/bin/env python3
"""Score backend readiness through the iPhone simulator contract.

This harness is for the period where the RV101 app is being built in parallel.
It exercises Jetson HTTP contracts that should already be portable to the thin
glasses client: session creation, preview upload, media command budgets,
perception ingress, typed skill execution, HUD output, replay, scorecard, and
bounded live adapter ingress.

It does not use ADB, root a device, open a real camera, mutate Immich data, or
touch any Ring/security runtime.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
import time
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_OUTPUT = ROOT / "runtime" / "signoff" / "iphone_backend_readiness_latest.json"
FINAL_MEDIA_STATUSES = {"ok", "timeout", "cancelled", "error"}

# 16x16 synthetic PNG. The harness validates transport/contracts, not vision
# accuracy, so the image content is intentionally synthetic and private-data free.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR42mO48+wDSYhhVMOohuGrAQC88LIf9axbSwAAAABJRU5ErkJggg=="
)


class JsonApi(Protocol):
    base_url: str

    def get(self, path: str, *, timeout: float = 8.0) -> dict[str, Any]:
        ...

    def post_json(self, path: str, payload: dict[str, Any], *, timeout: float = 12.0) -> dict[str, Any]:
        ...

    def post_bytes(
        self,
        path: str,
        body: bytes,
        *,
        content_type: str = "image/png",
        timeout: float = 12.0,
    ) -> dict[str, Any]:
        ...


@dataclass(slots=True)
class Check:
    name: str
    status: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        payload = {"name": self.name, "status": self.status, "detail": self.detail}
        if self.data:
            payload["data"] = self.data
        return payload


class Readiness:
    def __init__(self) -> None:
        self.checks: list[Check] = []
        self.artifacts: dict[str, Any] = {}

    def add(self, name: str, status: str, detail: str, **data: Any) -> None:
        self.checks.append(
            Check(
                name=name,
                status=status,
                detail=detail,
                data={key: value for key, value in data.items() if value is not None},
            )
        )

    def status(self) -> str:
        statuses = {check.status for check in self.checks}
        if "fail" in statuses:
            return "fail"
        if "blocked" in statuses:
            return "blocked"
        if "warn" in statuses:
            return "warn"
        return "pass"

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": "openvision.iphone_backend_readiness.v1",
            "status": self.status(),
            "checks": [check.to_json() for check in self.checks],
            "artifacts": self.artifacts,
        }


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = normalize_base_url(base_url)

    def get(self, path: str, *, timeout: float = 8.0) -> dict[str, Any]:
        return self._request_json("GET", path, timeout=timeout)

    def post_json(self, path: str, payload: dict[str, Any], *, timeout: float = 12.0) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._request_json(
            "POST",
            path,
            body=body,
            content_type="application/json",
            timeout=timeout,
        )

    def post_bytes(
        self,
        path: str,
        body: bytes,
        *,
        content_type: str = "image/png",
        timeout: float = 12.0,
    ) -> dict[str, Any]:
        return self._request_json("POST", path, body=body, content_type=content_type, timeout=timeout)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        timeout: float,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(urljoin(self.base_url + "/", path.lstrip("/")), data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-supplied local/tailnet URL.
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} from {request.full_url}: {payload}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"Request failed for {request.full_url}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Jetson FastAPI base URL")
    parser.add_argument("--json-output", default=str(DEFAULT_OUTPUT), help="Path for the JSON readiness report")
    parser.add_argument("--no-write", action="store_true", help="Print report only; do not write json-output")
    parser.add_argument(
        "--exercise-cloud-visual",
        action="store_true",
        help="Complete a scene_describe snapshot and allow the cloud verifier path to run if configured",
    )
    parser.add_argument(
        "--skip-live-adapters",
        action="store_true",
        help="Skip YOLO26/face-identity live adapter ingress checks",
    )
    args = parser.parse_args()

    api = ApiClient(args.base_url)
    readiness = run_backend_readiness(
        api,
        exercise_cloud_visual=args.exercise_cloud_visual,
        exercise_live_adapters=not args.skip_live_adapters,
    )
    report = readiness.to_json()
    if not args.no_write:
        output_path = Path(args.json_output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report["artifacts"]["json_output"] = str(output_path)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1 if report["status"] == "warn" else 2


def run_backend_readiness(
    api: JsonApi,
    *,
    exercise_cloud_visual: bool = False,
    exercise_live_adapters: bool = True,
) -> Readiness:
    readiness = Readiness()
    readiness.artifacts["base_url"] = api.base_url
    started_s = time.monotonic()

    try:
        health = api.get("/api/health")
    except RuntimeError as exc:
        readiness.add("jetson_health", "blocked", "Jetson HTTP health endpoint is not reachable", error=str(exc))
        return readiness
    readiness.artifacts["health_before"] = _health_artifact(health)
    if health.get("ok"):
        readiness.add(
            "jetson_health",
            "pass",
            "Jetson health endpoint reachable",
            runtime_epoch=health.get("runtime_epoch"),
            active_live_count=health.get("active_live_count"),
            yolo26_adapter_status=health.get("yolo26_adapter_status"),
            face_identity_adapter_status=health.get("face_identity_adapter_status"),
        )
    else:
        readiness.add("jetson_health", "fail", "Jetson health endpoint returned ok=false")
        return readiness

    contract_session_id = create_iphone_session(api, readiness, purpose="backend_contract")
    if contract_session_id:
        exercise_contract_session(api, readiness, contract_session_id)
        exercise_local_skills(api, readiness, contract_session_id)
        close_session(api, readiness, session_id=contract_session_id, check_name="backend_contract_cleanup")
        score_contract_session(api, readiness, contract_session_id)

    exercise_snapshot_media_contracts(api, readiness, exercise_cloud_visual=exercise_cloud_visual)
    if exercise_live_adapters:
        exercise_live_target_contract(api, readiness, health)
    else:
        readiness.add("live_adapters", "skip", "Live adapter checks skipped by operator")

    try:
        after_health = api.get("/api/health")
        readiness.artifacts["health_after"] = _health_artifact(after_health)
        if health.get("runtime_epoch") == after_health.get("runtime_epoch"):
            readiness.add("runtime_epoch", "pass", "Jetson runtime epoch stayed stable", runtime_epoch=after_health.get("runtime_epoch"))
        else:
            readiness.add(
                "runtime_epoch",
                "fail",
                "Jetson runtime restarted during backend readiness check",
                before=health.get("runtime_epoch"),
                after=after_health.get("runtime_epoch"),
            )
    except RuntimeError as exc:
        readiness.add("runtime_epoch", "fail", "Could not fetch final health after checks", error=str(exc))

    readiness.artifacts["duration_ms"] = int((time.monotonic() - started_s) * 1000)
    return readiness


def create_iphone_session(api: JsonApi, readiness: Readiness, *, purpose: str) -> str | None:
    try:
        payload = api.post_json(
            "/api/sessions",
            {
                "client_kind": "iphone_simulator",
                "capabilities": {
                    "video": "webrtc",
                    "audio": "webrtc",
                    "hud": "scene_json",
                    "purpose": purpose,
                },
            },
        )
    except RuntimeError as exc:
        readiness.add(f"{purpose}_session", "blocked", "Could not create iPhone simulator session", error=str(exc))
        return None
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    session_id = str(session.get("session_id") or "").strip()
    if not session_id:
        readiness.add(f"{purpose}_session", "fail", "Session creation did not return session_id", payload=_redact(payload))
        return None
    readiness.artifacts.setdefault("sessions", {})[purpose] = session_id
    readiness.add(f"{purpose}_session", "pass", "Created iPhone simulator session", session_id=session_id)
    return session_id


def exercise_contract_session(api: JsonApi, readiness: Readiness, session_id: str) -> None:
    try:
        video = api.post_json(
            f"/api/media/{quote(session_id)}/video/heartbeat",
            {"transport": "webrtc", "codec": "raw_video", "width": 640, "height": 480, "fps": 24},
        )
        readiness.add("video_heartbeat", "pass", "Video heartbeat accepted", video=_compact_media(video, "video"))
    except RuntimeError as exc:
        readiness.add("video_heartbeat", "fail", "Video heartbeat was rejected", error=str(exc))

    try:
        audio = api.post_json(
            f"/api/media/{quote(session_id)}/audio/metrics",
            {
                "transport": "webrtc",
                "sample_rate": 24000,
                "channels": 1,
                "chunk_count": 4,
                "strong_chunk_count": 3,
                "avg_abs": 180.0,
                "peak_abs": 420,
                "non_silent_ratio": 0.06,
                "source": "iphone_backend_readiness",
            },
        )
        readiness.add(
            "audio_metrics",
            "pass",
            "Audio metrics accepted; real WebRTC sessions should additionally open the realtime forward gate",
            audio=_compact_media(audio, "audio"),
        )
    except RuntimeError as exc:
        readiness.add("audio_metrics", "fail", "Audio metrics were rejected", error=str(exc))

    try:
        preview = upload_preview(api, session_id=session_id, frame_count=1, source="iphone_backend_readiness")
        readiness.add("preview_upload", "pass", "Preview frame upload accepted", preview=_compact_preview(preview))
    except RuntimeError as exc:
        readiness.add("preview_upload", "fail", "Preview frame upload was rejected", error=str(exc))

    detections = [
        {"label": "person", "confidence": 0.92, "bbox": [32, 96, 180, 420], "track_id": "p1"},
        {"label": "person", "confidence": 0.88, "bbox": [300, 110, 430, 430], "track_id": "p2"},
        {"label": "cup", "confidence": 0.81, "bbox": [440, 250, 500, 390], "track_id": "cup1"},
    ]
    try:
        perception = api.post_json(
            f"/api/perception/{quote(session_id)}/detections",
            {
                "source": "iphone_backend_readiness",
                "frame_id": "contract_frame_1",
                "width": 640,
                "height": 480,
                "detections": detections,
            },
        )
        readiness.add(
            "perception_ingress",
            "pass",
            "Perception snapshot accepted",
            object_count=len(perception.get("objects") or []),
            source=perception.get("source"),
        )
    except RuntimeError as exc:
        readiness.add("perception_ingress", "fail", "Perception snapshot was rejected", error=str(exc))


def exercise_local_skills(api: JsonApi, readiness: Readiness, session_id: str) -> None:
    try:
        count_people = api.post_json(
            "/api/skills/count_people/execute",
            {"session_id": session_id, "args": {"min_confidence": 0.25}},
        )
        count = ((count_people.get("result") or {}) if isinstance(count_people.get("result"), dict) else {}).get("count")
        if count == 2:
            readiness.add("skill_count_people", "pass", "count_people used local perception and returned two people", count=count)
        else:
            readiness.add("skill_count_people", "fail", "count_people did not return the expected local perception count", count=count)
    except RuntimeError as exc:
        readiness.add("skill_count_people", "fail", "count_people execution failed", error=str(exc))

    try:
        object_counter = api.post_json(
            "/api/skills/object_counter/execute",
            {"session_id": session_id, "args": {"question": "có mấy cup", "target": "cup"}},
        )
        result = object_counter.get("result") if isinstance(object_counter.get("result"), dict) else {}
        if result.get("count") == 1:
            readiness.add("skill_object_counter", "pass", "object_counter used local detections for count", count=result.get("count"))
        else:
            readiness.add(
                "skill_object_counter",
                "fail",
                "object_counter did not count the expected local cup detection",
                skill_status=object_counter.get("status"),
                count=result.get("count"),
            )
    except RuntimeError as exc:
        readiness.add("skill_object_counter", "fail", "object_counter execution failed", error=str(exc))


def score_contract_session(api: JsonApi, readiness: Readiness, session_id: str) -> None:
    try:
        scorecard = api.get(f"/api/scorecard/{quote(session_id)}")
        score = scorecard.get("scorecard") if isinstance(scorecard.get("scorecard"), dict) else scorecard
        readiness.artifacts["contract_scorecard"] = {
            "session_id": score.get("session_id"),
            "status": score.get("status"),
            "score": score.get("score"),
            "skill_eval_status": (score.get("metrics") or {}).get("skill_eval_status") if isinstance(score.get("metrics"), dict) else None,
        }
        status = str(score.get("status") or "fail")
        metrics = score.get("metrics") if isinstance(score.get("metrics"), dict) else {}
        required_fail_count = int(metrics.get("required_gate_fail_count") or 0)
        if status == "pass":
            readiness.add("session_scorecard", "pass", "Contract session scorecard passed", score=score.get("score"))
        elif status == "warn" and required_fail_count == 0:
            readiness.add(
                "session_scorecard",
                "pass",
                "Contract session required gates passed; non-device warnings are expected in HTTP-only mode",
                score=score.get("score"),
                skill_eval_status=metrics.get("skill_eval_status"),
                audio_gate=((score.get("gates") or {}).get("audio_signal") if isinstance(score.get("gates"), dict) else None),
            )
        elif status == "warn":
            readiness.add(
                "session_scorecard",
                "warn",
                "Contract session scorecard warned on a required gate",
                score=score.get("score"),
                required_gate_fail_count=required_fail_count,
            )
        elif status == "fail" and required_fail_count == 0:
            readiness.add(
                "session_scorecard",
                "warn",
                "Contract session scorecard failed only on optional/non-device gates",
                score=score.get("score"),
                top_failures=score.get("top_failures"),
            )
        else:
            readiness.add(
                "session_scorecard",
                "fail",
                "Contract session scorecard failed",
                score=score.get("score"),
                top_failures=score.get("top_failures"),
            )
    except RuntimeError as exc:
        readiness.add("session_scorecard", "fail", "Could not fetch contract session scorecard", error=str(exc))

    try:
        replay = api.get(f"/api/replay/{quote(session_id)}")
        replay_payload = replay.get("replay") if isinstance(replay.get("replay"), dict) else replay
        readiness.add(
            "session_replay",
            "pass",
            "Session replay exported",
            event_count=len(replay_payload.get("events") or []),
            redacted=replay_payload.get("redacted"),
        )
    except RuntimeError as exc:
            readiness.add("session_replay", "fail", "Could not fetch contract session replay", error=str(exc))


def exercise_snapshot_media_contracts(api: JsonApi, readiness: Readiness, *, exercise_cloud_visual: bool) -> None:
    person_session_id = create_iphone_session(api, readiness, purpose="person_info_snapshot")
    if person_session_id:
        try:
            response = api.post_json(
                "/api/skills/person_info/execute",
                {"session_id": person_session_id, "args": {"query": "có ai quen không", "scan_mode": "snapshot"}},
            )
            command = _skill_media_command(response)
            quality_gate = ((command.get("params") or {}) if isinstance(command.get("params"), dict) else {}).get("quality_gate")
            if command.get("mode") == "snapshot" and isinstance(quality_gate, dict):
                readiness.add(
                    "person_info_snapshot_command",
                    "pass",
                    "person_info requests snapshot with best-of-burst quality gate",
                    command_id=command.get("command_id"),
                    sample_count=quality_gate.get("sample_count"),
                    settle_ms=quality_gate.get("settle_ms"),
                )
            else:
                readiness.add(
                    "person_info_snapshot_command",
                    "fail",
                    "person_info did not request the expected snapshot quality gate",
                    response=_redact(response),
                )
            cancel_media_command(api, readiness, session_id=person_session_id, command=command, check_name="person_info_snapshot_cleanup")
            close_session(api, readiness, session_id=person_session_id, check_name="person_info_snapshot_session_cleanup")
        except RuntimeError as exc:
            readiness.add("person_info_snapshot_command", "fail", "person_info snapshot command failed", error=str(exc))

    scene_session_id = create_iphone_session(api, readiness, purpose="scene_snapshot")
    if scene_session_id:
        try:
            response = api.post_json(
                "/api/skills/scene_describe/execute",
                {"session_id": scene_session_id, "args": {"focus": "đang có gì trước mặt tôi"}},
            )
            command = _skill_media_command(response)
            if command.get("mode") == "snapshot":
                readiness.add(
                    "scene_describe_snapshot_command",
                    "pass",
                    "scene_describe requests fresh snapshot evidence when none exists",
                    command_id=command.get("command_id"),
                )
            else:
                readiness.add(
                    "scene_describe_snapshot_command",
                    "fail",
                    "scene_describe did not request snapshot evidence",
                    response=_redact(response),
                )
            if exercise_cloud_visual and command.get("command_id"):
                upload_preview(api, session_id=scene_session_id, frame_count=2, source="iphone_backend_readiness_scene")
                completed = api.post_json(
                    f"/api/media/commands/{quote(str(command['command_id']))}/events",
                    {
                        "session_id": scene_session_id,
                        "status": "ok",
                        "payload": {
                            "adapter_status": "simulator_snapshot_ready",
                            "preview": {"image_url": f"/api/preview/{scene_session_id}/frame.jpg"},
                        },
                    },
                    timeout=30.0,
                )
                continuation = completed.get("continuation") if isinstance(completed.get("continuation"), dict) else {}
                if continuation.get("status") in {"needs_cloud", "ok", "no_evidence"}:
                    readiness.add(
                        "scene_describe_continuation",
                        "pass",
                        "scene_describe media continuation completed through the cloud gateway contract",
                        continuation_status=continuation.get("status"),
                    )
                else:
                    readiness.add(
                        "scene_describe_continuation",
                        "fail",
                        "scene_describe media continuation returned an unexpected status",
                        continuation=_redact(continuation),
                    )
            else:
                cancel_media_command(api, readiness, session_id=scene_session_id, command=command, check_name="scene_describe_snapshot_cleanup")
            close_session(api, readiness, session_id=scene_session_id, check_name="scene_snapshot_session_cleanup")
        except RuntimeError as exc:
            readiness.add("scene_describe_snapshot_command", "fail", "scene_describe snapshot command failed", error=str(exc))


def exercise_live_target_contract(api: JsonApi, readiness: Readiness, health: dict[str, Any]) -> None:
    session_id = create_iphone_session(api, readiness, purpose="target_finder_live")
    if not session_id:
        return
    command: dict[str, Any] = {}
    try:
        queued = api.post_json(
            "/api/skills/target_finder/execute",
            {"session_id": session_id, "args": {"query": "tìm người trong đám đông", "target_type": "person", "fps": 8}},
        )
        command = _skill_media_command(queued)
        if command.get("mode") == "live_video" and command.get("timeout_ms"):
            readiness.add(
                "target_finder_live_command",
                "pass",
                "target_finder requests bounded live_video through MediaCommand",
                command_id=command.get("command_id"),
                timeout_ms=command.get("timeout_ms"),
                fps=command.get("fps"),
            )
        else:
            readiness.add(
                "target_finder_live_command",
                "fail",
                "target_finder did not request bounded live_video",
                response=_redact(queued),
            )
            return
        api.post_json(
            f"/api/media/commands/{quote(str(command['command_id']))}/events",
            {
                "session_id": session_id,
                "status": "running",
                "payload": {
                    "adapter_status": "simulator_live_video_running",
                    "preview": {"image_url": f"/api/preview/{session_id}/frame.jpg"},
                },
            },
        )
        readiness.add("target_finder_live_running", "pass", "Live media command accepted running state")
    except RuntimeError as exc:
        readiness.add("target_finder_live_command", "fail", "target_finder live command setup failed", error=str(exc))
        return

    if _adapter_ready(health, "yolo26_adapter_status"):
        exercise_yolo26_stream(api, readiness, session_id)
    else:
        readiness.add(
            "yolo26_stream_ingress",
            "skip",
            "YOLO26 OpenVision adapter is not ready; skipping stream ingress without touching protected Ring runtime",
            yolo26_adapter_status=health.get("yolo26_adapter_status"),
        )

    if _adapter_ready(health, "face_identity_adapter_status"):
        exercise_face_identity_stream(api, readiness, session_id)
    else:
        readiness.add(
            "face_identity_stream_ingress",
            "skip",
            "Face identity adapter is not ready; skipping stream ingress",
            face_identity_adapter_status=health.get("face_identity_adapter_status"),
        )

    if command.get("command_id"):
        try:
            api.post_json(
                f"/api/media/commands/{quote(str(command['command_id']))}/events",
                {
                    "session_id": session_id,
                    "status": "timeout",
                    "payload": {"adapter_status": "simulator_live_video_stopped"},
                },
            )
            commands = api.get("/api/media/commands")
            active = [
                item
                for item in (commands.get("media_commands") or {}).get("active_live", [])
                if isinstance(item, dict) and (item.get("command") or {}).get("session_id") == session_id
            ]
            if not active:
                readiness.add("target_finder_live_cleanup", "pass", "Live command final event cleared active live state")
            else:
                readiness.add("target_finder_live_cleanup", "fail", "Live command remained active after timeout", active_live_count=len(active))
            close_session(api, readiness, session_id=session_id, check_name="target_finder_live_session_cleanup")
        except RuntimeError as exc:
            readiness.add("target_finder_live_cleanup", "fail", "Could not stop target_finder live command", error=str(exc))


def exercise_yolo26_stream(api: JsonApi, readiness: Readiness, session_id: str) -> None:
    try:
        response = api.post_json(
            f"/api/adapters/yolo26/{quote(session_id)}/stream",
            {
                "source": "openvision_iphone_yolo26",
                "frame_id": "readiness_yolo_1",
                "sequence": 1,
                "latency_ms": 18.0,
                "width": 640,
                "height": 480,
                "detections": [
                    {"label": "person", "confidence": 0.92, "bbox": [32, 96, 180, 420], "track_id": "p1"},
                    {"label": "bottle", "confidence": 0.31, "bbox": [420, 240, 470, 390], "track_id": "b1"},
                    {"label": "bag", "confidence": 0.08, "bbox": [240, 100, 360, 260]},
                ],
            },
        )
        if response.get("status") == "accepted" and response.get("accepted_detection_count", 0) >= 1:
            readiness.add(
                "yolo26_stream_ingress",
                "pass",
                "YOLO26 stream ingress accepted OpenVision/iPhone source and updated perception",
                accepted_detection_count=response.get("accepted_detection_count"),
                source=response.get("source"),
                continuation_status=(response.get("continuation") or {}).get("status")
                if isinstance(response.get("continuation"), dict)
                else None,
            )
        else:
            readiness.add("yolo26_stream_ingress", "fail", "YOLO26 stream ingress returned unexpected payload", response=_redact(response))
    except RuntimeError as exc:
        readiness.add("yolo26_stream_ingress", "fail", "YOLO26 stream ingress failed", error=str(exc))


def exercise_face_identity_stream(api: JsonApi, readiness: Readiness, session_id: str) -> None:
    try:
        response = api.post_json(
            f"/api/adapters/face-identity/{quote(session_id)}/stream",
            {
                "source": "openvision_iphone_face_identity",
                "frame_id": "readiness_face_1",
                "sequence": 1,
                "latency_ms": 9.0,
                "width": 640,
                "height": 480,
                "detections": [
                    {
                        "label": "person",
                        "confidence": 0.91,
                        "bbox": [220, 80, 340, 250],
                        "track_id": "f1",
                        "attributes": {"identity_vector": [1.0, 0.0, 0.0], "face_confidence": 0.91},
                    }
                ],
            },
        )
        if response.get("status") == "accepted" and response.get("accepted_detection_count", 0) >= 1:
            readiness.add(
                "face_identity_stream_ingress",
                "pass",
                "Face identity stream ingress accepted OpenVision/iPhone source and updated perception",
                accepted_detection_count=response.get("accepted_detection_count"),
                source=response.get("source"),
                continuation_status=(response.get("continuation") or {}).get("status")
                if isinstance(response.get("continuation"), dict)
                else None,
            )
        else:
            readiness.add("face_identity_stream_ingress", "fail", "Face identity stream ingress returned unexpected payload", response=_redact(response))
    except RuntimeError as exc:
        readiness.add("face_identity_stream_ingress", "fail", "Face identity stream ingress failed", error=str(exc))


def upload_preview(api: JsonApi, *, session_id: str, frame_count: int, source: str) -> dict[str, Any]:
    return api.post_bytes(
        (
            f"/api/preview/{quote(session_id)}/frame"
            f"?source={quote(source)}&width=640&height=480&frame_count={frame_count}"
        ),
        TINY_PNG,
        content_type="image/png",
    )


def cancel_media_command(api: JsonApi, readiness: Readiness, *, session_id: str, command: dict[str, Any], check_name: str) -> None:
    command_id = str(command.get("command_id") or "").strip()
    if not command_id:
        readiness.add(check_name, "skip", "No media command id to clean up")
        return
    try:
        response = api.post_json(
            f"/api/media/commands/{quote(command_id)}/events",
            {"session_id": session_id, "status": "cancelled", "payload": {"adapter_status": "simulator_cancelled_by_readiness"}},
        )
        status = ((response.get("event") or {}) if isinstance(response.get("event"), dict) else {}).get("status")
        if status in FINAL_MEDIA_STATUSES:
            readiness.add(check_name, "pass", "Queued media command cancelled after contract inspection", command_id=command_id)
        else:
            readiness.add(check_name, "warn", "Media command cleanup returned non-final status", command_id=command_id, event_status=status)
    except RuntimeError as exc:
        readiness.add(check_name, "warn", "Could not cancel queued media command after inspection", command_id=command_id, error=str(exc))


def close_session(api: JsonApi, readiness: Readiness, *, session_id: str, check_name: str) -> None:
    try:
        response = api.post_json(
            f"/api/sessions/{quote(session_id)}/close",
            {"reason": "iphone_backend_readiness_complete"},
        )
    except RuntimeError as exc:
        readiness.add(check_name, "warn", "Could not close synthetic iPhone simulator session", session_id=session_id, error=str(exc))
        return
    if response.get("status") == "closed":
        readiness.add(check_name, "pass", "Synthetic iPhone simulator session closed", session_id=session_id)
    else:
        readiness.add(check_name, "warn", "Session close returned unexpected status", session_id=session_id, response=_redact(response))


def _skill_media_command(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    command = result.get("media_command") if isinstance(result.get("media_command"), dict) else {}
    return command


def _adapter_ready(health: dict[str, Any], key: str) -> bool:
    return str(health.get(key) or "").strip().lower() == "ready"


def _compact_media(payload: dict[str, Any], kind: str) -> dict[str, Any]:
    section = payload.get(kind) if isinstance(payload.get(kind), dict) else {}
    return {
        "state": section.get("state"),
        "transport": section.get("transport"),
        "fps": section.get("fps"),
        "frame_count": section.get("frame_count"),
        "chunk_count": section.get("chunk_count"),
        "strong_chunk_count": section.get("strong_chunk_count"),
        "strong_chunk_ratio": section.get("strong_chunk_ratio"),
    }


def _compact_preview(payload: dict[str, Any]) -> dict[str, Any]:
    preview = payload.get("preview") if isinstance(payload.get("preview"), dict) else payload
    return {
        "source": preview.get("source"),
        "width": preview.get("width"),
        "height": preview.get("height"),
        "frame_count": preview.get("frame_count"),
        "image_url": preview.get("image_url"),
    }


def _health_artifact(health: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": health.get("ok"),
        "runtime_epoch": health.get("runtime_epoch"),
        "sessions": health.get("sessions"),
        "total_sessions": health.get("total_sessions"),
        "realtime_sessions": health.get("realtime_sessions"),
        "media_sessions": health.get("media_sessions"),
        "active_live_count": health.get("active_live_count"),
        "voice_output": health.get("voice_output"),
        "cloud_verify_enabled": health.get("cloud_verify_enabled"),
        "yolo26_adapter_status": health.get("yolo26_adapter_status"),
        "face_identity_adapter_status": health.get("face_identity_adapter_status"),
        "people_registry_status": health.get("people_registry_status"),
        "identity_status": health.get("identity_status"),
        "rv101_tcp_ingest": health.get("rv101_tcp_ingest"),
        "rv101_h264_preview": health.get("rv101_h264_preview"),
    }


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("key", "token", "secret", "password", "authorization")):
                redacted[str(key)] = "***"
            else:
                redacted[str(key)] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value[:10]]
    return value


def normalize_base_url(value: str) -> str:
    base_url = str(value or "").strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise SystemExit("--base-url must start with http:// or https://")
    return base_url


if __name__ == "__main__":
    raise SystemExit(main())
