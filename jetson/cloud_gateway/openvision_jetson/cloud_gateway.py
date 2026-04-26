"""Typed cloud escalation gateway for OpenVision v2.

The gateway is intentionally small right now: it packages evidence, enforces
privacy/budget gates, validates schema contracts, and calls an optional verifier
provider. Without a verifier provider it returns a validated fallback result
instead of pretending cloud visual verification happened.
"""

from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import time
from typing import Any, Callable

from .contracts import new_id, utc_now
from .event_store import InMemoryEventStore
from .skill_registry import validate_json_value


CloudVerifierProvider = Callable[[dict[str, Any]], dict[str, Any]]


class CloudGateway:
    def __init__(
        self,
        *,
        events: InMemoryEventStore,
        provider: CloudVerifierProvider | None = None,
        max_requests_per_minute: int = 12,
    ) -> None:
        self._events = events
        self._provider = provider
        self._max_requests_per_minute = max(1, int(max_requests_per_minute))
        self._request_times: deque[float] = deque()
        self._bundle_schema = _load_schema("cloud_evidence_bundle.schema.json")
        self._result_schema = _load_schema("cloud_result.schema.json")

    def build_evidence_bundle(
        self,
        *,
        session_id: str,
        skill_id: str,
        user_query: str,
        local_summary: dict[str, Any],
        candidates: list[dict[str, Any]],
        frame_refs: list[str] | None = None,
        crop_refs: list[str] | None = None,
        contains_face: bool = False,
        allow_cloud: bool = True,
        store_result: bool = False,
        privacy_level: str = "medium",
        max_answer_chars: int = 60,
        hud_allowed: bool = True,
    ) -> dict[str, Any]:
        bundle = {
            "schema_version": "cloud_evidence_bundle.v1",
            "bundle_id": new_id("bundle"),
            "session_id": session_id,
            "skill_id": skill_id,
            "user_query": user_query,
            "created_at": utc_now(),
            "local_summary": local_summary,
            "frame_refs": frame_refs or [],
            "crop_refs": crop_refs or [],
            "candidates": candidates,
            "requested_output": {
                "format": "json",
                "max_answer_chars": max(1, min(500, int(max_answer_chars))),
                "hud_allowed": bool(hud_allowed),
            },
            "privacy": {
                "contains_face": bool(contains_face),
                "allow_cloud": bool(allow_cloud),
                "store_result": bool(store_result),
                "privacy_level": privacy_level,
            },
        }
        self._events.add(
            "cloud_gateway",
            "bundle_created",
            {
                "bundle_id": bundle["bundle_id"],
                "skill_id": skill_id,
                "candidate_count": len(candidates),
                "privacy_level": privacy_level,
            },
            session_id=session_id,
        )
        return bundle

    def request_verification(self, bundle: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        bundle_errors = validate_json_value(self._bundle_schema, bundle, path="bundle")
        if bundle_errors:
            result = _cloud_error(
                answer_short="Lỗi gói cloud",
                code="invalid_evidence_bundle",
                message="Cloud evidence bundle failed schema validation.",
                details=bundle_errors,
            )
            return self._finish(
                bundle=bundle,
                result=result,
                started=started,
                event_type="bundle_rejected",
                severity="error",
            )

        privacy = bundle.get("privacy") if isinstance(bundle.get("privacy"), dict) else {}
        if not privacy.get("allow_cloud"):
            result = _cloud_blocked(
                answer_short="Không gửi cloud",
                code="privacy_blocked",
                message="Privacy policy blocked cloud escalation.",
            )
            return self._finish(
                bundle=bundle,
                result=result,
                started=started,
                event_type="privacy_blocked",
                severity="warning",
            )

        if not self._budget_allows():
            result = _cloud_blocked(
                answer_short="Cloud quá giới hạn",
                code="budget_exceeded",
                message="Cloud request budget exceeded.",
            )
            return self._finish(
                bundle=bundle,
                result=result,
                started=started,
                event_type="budget_blocked",
                severity="warning",
            )

        if self._provider is None:
            result = _cloud_error(
                answer_short="Cloud verifier chưa bật",
                code="cloud_provider_missing",
                message="No cloud verifier provider is configured.",
            )
            return self._finish(
                bundle=bundle,
                result=result,
                started=started,
                event_type="provider_missing",
                severity="warning",
            )

        try:
            result = self._provider(bundle)
        except Exception as exc:
            result = _cloud_error(
                answer_short="Cloud lỗi",
                code=exc.__class__.__name__,
                message=str(exc),
            )
            return self._finish(
                bundle=bundle,
                result=result,
                started=started,
                event_type="provider_error",
                severity="error",
            )

        result_errors = validate_json_value(self._result_schema, result, path="cloud_result")
        if result_errors:
            result = _cloud_error(
                answer_short="Lỗi kết quả cloud",
                code="invalid_cloud_result",
                message="Cloud result failed schema validation.",
                details=result_errors,
            )
            return self._finish(
                bundle=bundle,
                result=result,
                started=started,
                event_type="result_rejected",
                severity="error",
            )

        return self._finish(
            bundle=bundle,
            result=result,
            started=started,
            event_type="result",
            severity="info",
        )

    def _finish(
        self,
        *,
        bundle: dict[str, Any],
        result: dict[str, Any],
        started: float,
        event_type: str,
        severity: str,
    ) -> dict[str, Any]:
        result_errors = validate_json_value(self._result_schema, result, path="cloud_result")
        latency_ms = int((time.perf_counter() - started) * 1000)
        session_id = str(bundle.get("session_id") or "")
        self._events.add(
            "cloud_gateway",
            event_type,
            {
                "bundle_id": bundle.get("bundle_id"),
                "skill_id": bundle.get("skill_id"),
                "status": result.get("status"),
                "latency_ms": latency_ms,
                "validation_errors": result_errors,
            },
            session_id=session_id or None,
            severity=severity if not result_errors else "error",
        )
        return {
            "status": result.get("status", "error"),
            "bundle_id": bundle.get("bundle_id"),
            "latency_ms": latency_ms,
            "cloud_result": result,
            "validation_errors": result_errors,
        }

    def _budget_allows(self) -> bool:
        now = time.monotonic()
        while self._request_times and now - self._request_times[0] >= 60.0:
            self._request_times.popleft()
        if len(self._request_times) >= self._max_requests_per_minute:
            return False
        self._request_times.append(now)
        return True


def _cloud_blocked(*, answer_short: str, code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": "cloud_result.v1",
        "status": "blocked",
        "answer_short": answer_short,
        "answer_long": message,
        "confidence": 0.0,
        "selected_candidate_id": None,
        "hud_scene": None,
        "safety_flags": [code],
        "memory_event": None,
        "error": {"code": code, "message": message},
    }


def _cloud_error(
    *,
    answer_short: str,
    code: str,
    message: str,
    details: list[str] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {
        "schema_version": "cloud_result.v1",
        "status": "error",
        "answer_short": answer_short,
        "answer_long": message,
        "confidence": 0.0,
        "selected_candidate_id": None,
        "hud_scene": None,
        "safety_flags": [code],
        "memory_event": None,
        "error": error,
    }


def _load_schema(name: str) -> dict[str, Any]:
    schema_path = Path(__file__).resolve().parents[3] / "shared" / "schemas" / name
    with schema_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Schema must be an object: {schema_path}")
    return payload
