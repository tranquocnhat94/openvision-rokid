"""Typed cloud escalation gateway for OpenVision v2.

The gateway is intentionally small right now: it packages evidence, enforces
privacy/budget gates, validates schema contracts, and calls an optional verifier
provider. Without a verifier provider it returns a validated fallback result
instead of pretending cloud visual verification happened.
"""

from __future__ import annotations

import base64
from collections import deque
import json
from pathlib import Path
from threading import RLock
import time
from typing import Any, Callable

import httpx

from .contracts import new_id, utc_now
from .event_store import InMemoryEventStore
from .skill_registry import validate_json_value


CloudVerifierProvider = Callable[[dict[str, Any]], dict[str, Any]]
ImageRefResolver = Callable[[str, dict[str, Any]], str | None]
HttpPostJson = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

_MODEL_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "status",
        "answer_short",
        "answer_long",
        "confidence",
        "selected_candidate_id",
        "hud_scene",
        "safety_flags",
        "memory_event",
        "error",
    ],
    "properties": {
        "schema_version": {"type": "string", "enum": ["cloud_result.v1"]},
        "status": {"type": "string", "enum": ["ok", "no_match", "uncertain"]},
        "answer_short": {"type": "string", "maxLength": 80},
        "answer_long": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "selected_candidate_id": {"type": ["string", "null"]},
        "hud_scene": {"type": "null"},
        "safety_flags": {"type": "array", "items": {"type": "string"}},
        "memory_event": {"type": "null"},
        "error": {"type": "null"},
    },
}


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
        self._budget_lock = RLock()
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
        requested_output = bundle["requested_output"]
        privacy = bundle["privacy"]
        self._events.add(
            "cloud_gateway",
            "bundle_created",
            {
                "bundle_id": bundle["bundle_id"],
                "skill_id": skill_id,
                "candidate_count": len(candidates),
                "frame_ref_count": len(bundle["frame_refs"]),
                "crop_ref_count": len(bundle["crop_refs"]),
                "privacy_level": privacy.get("privacy_level"),
                "contains_face": privacy.get("contains_face"),
                "allow_cloud": privacy.get("allow_cloud"),
                "store_result": privacy.get("store_result"),
                "max_answer_chars": requested_output.get("max_answer_chars"),
                "hud_allowed": requested_output.get("hud_allowed"),
            },
            session_id=session_id,
        )
        return bundle

    def request_verification(self, bundle: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        bundle_errors = self.validate_evidence_bundle(bundle, path="bundle")
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
                severity="warning",
            )

        result_errors = self.validate_cloud_result(result, path="cloud_result")
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

    def validate_evidence_bundle(self, bundle: Any, *, path: str = "cloud_evidence_bundle") -> list[str]:
        if not isinstance(bundle, dict):
            return [f"{path} must be object"]
        return validate_json_value(self._bundle_schema, bundle, path=path)

    def validate_cloud_result(self, result: Any, *, path: str = "cloud_result") -> list[str]:
        if not isinstance(result, dict):
            return [f"{path} must be object"]
        return validate_json_value(self._result_schema, result, path=path)

    def validate_gateway_response(
        self,
        response: Any,
        *,
        bundle: dict[str, Any] | None = None,
        path: str = "cloud_gateway",
    ) -> list[str]:
        if not isinstance(response, dict):
            return [f"{path} must be object"]
        errors: list[str] = []
        for key in ("status", "bundle_id", "latency_ms", "cloud_result", "validation_errors"):
            if key not in response:
                errors.append(f"{path}.{key} is required")
        cloud_result = response.get("cloud_result")
        errors.extend(self.validate_cloud_result(cloud_result, path=f"{path}.cloud_result"))
        if isinstance(cloud_result, dict) and response.get("status") != cloud_result.get("status"):
            errors.append(f"{path}.status must match {path}.cloud_result.status")
        if bundle is not None and response.get("bundle_id") != bundle.get("bundle_id"):
            errors.append(f"{path}.bundle_id must match cloud_evidence_bundle.bundle_id")
        latency_ms = response.get("latency_ms")
        if not isinstance(latency_ms, int) or isinstance(latency_ms, bool) or latency_ms < 0:
            errors.append(f"{path}.latency_ms must be integer >= 0")
        validation_errors = response.get("validation_errors")
        if not isinstance(validation_errors, list):
            errors.append(f"{path}.validation_errors must be array")
        elif validation_errors:
            errors.append(f"{path}.validation_errors must be empty before returning needs_cloud")
        return errors

    def validate_needs_cloud_payload(self, payload: Any, *, path: str = "skill_payload") -> list[str]:
        if not isinstance(payload, dict):
            return [f"{path} must be object"]
        if payload.get("status") != "needs_cloud":
            return []
        result = payload.get("result")
        if not isinstance(result, dict):
            return [f"{path}.result must be object when status is needs_cloud"]
        return self.validate_cloud_escalation_result(result, path=f"{path}.result")

    def validate_cloud_escalation_result(self, result: dict[str, Any], *, path: str = "result") -> list[str]:
        errors: list[str] = []
        bundle = result.get("cloud_evidence_bundle")
        gateway_response = result.get("cloud_gateway")
        cloud_result = result.get("cloud_result")
        errors.extend(self.validate_evidence_bundle(bundle, path=f"{path}.cloud_evidence_bundle"))
        errors.extend(
            self.validate_gateway_response(
                gateway_response,
                bundle=bundle if isinstance(bundle, dict) else None,
                path=f"{path}.cloud_gateway",
            )
        )
        errors.extend(self.validate_cloud_result(cloud_result, path=f"{path}.cloud_result"))
        if (
            isinstance(gateway_response, dict)
            and isinstance(gateway_response.get("cloud_result"), dict)
            and isinstance(cloud_result, dict)
            and gateway_response["cloud_result"] != cloud_result
        ):
            errors.append(f"{path}.cloud_result must match {path}.cloud_gateway.cloud_result")
        return errors

    def _finish(
        self,
        *,
        bundle: dict[str, Any],
        result: dict[str, Any],
        started: float,
        event_type: str,
        severity: str,
    ) -> dict[str, Any]:
        result_errors = self.validate_cloud_result(result, path="cloud_result")
        latency_ms = int((time.perf_counter() - started) * 1000)
        session_id = str(bundle.get("session_id") or "")
        privacy = bundle.get("privacy") if isinstance(bundle.get("privacy"), dict) else {}
        requested_output = bundle.get("requested_output") if isinstance(bundle.get("requested_output"), dict) else {}
        error = result.get("error") if isinstance(result.get("error"), dict) else {}
        safety_flags = result.get("safety_flags") if isinstance(result.get("safety_flags"), list) else []
        self._events.add(
            "cloud_gateway",
            event_type,
            {
                "bundle_id": bundle.get("bundle_id"),
                "skill_id": bundle.get("skill_id"),
                "status": result.get("status"),
                "result_status": result.get("status"),
                "confidence": result.get("confidence"),
                "latency_ms": latency_ms,
                "privacy_level": privacy.get("privacy_level"),
                "contains_face": privacy.get("contains_face"),
                "allow_cloud": privacy.get("allow_cloud"),
                "store_result": privacy.get("store_result"),
                "max_answer_chars": requested_output.get("max_answer_chars"),
                "hud_allowed": requested_output.get("hud_allowed"),
                "error_code": error.get("code"),
                "safety_flags": [str(item) for item in safety_flags[:8]],
                "safety_flag_count": len(safety_flags),
                "validation_error_count": len(result_errors),
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
        with self._budget_lock:
            now = time.monotonic()
            while self._request_times and now - self._request_times[0] >= 60.0:
                self._request_times.popleft()
            if len(self._request_times) >= self._max_requests_per_minute:
                return False
            self._request_times.append(now)
            return True


class OpenAIResponsesVisionProvider:
    """OpenAI Responses-backed visual verifier for CloudGateway evidence bundles."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4.1-mini",
        responses_url: str = OPENAI_RESPONSES_URL,
        timeout_s: float = 8.0,
        max_output_tokens: int = 160,
        image_detail: str = "low",
        image_ref_resolver: ImageRefResolver | None = None,
        http_post_json: HttpPostJson | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._responses_url = responses_url
        self._timeout_s = max(1.0, float(timeout_s))
        self._max_output_tokens = max(32, min(800, int(max_output_tokens)))
        self._image_detail = image_detail if image_detail in {"low", "high", "original", "auto"} else "low"
        self._image_ref_resolver = image_ref_resolver
        self._http_post_json = http_post_json or _post_json

    def __call__(self, bundle: dict[str, Any]) -> dict[str, Any]:
        image_inputs = self._image_inputs(bundle)
        if not image_inputs and _bundle_needs_visual_evidence(bundle):
            return _cloud_uncertain(
                answer_short="Thiếu ảnh để xác minh",
                message="Cloud verifier did not receive a usable image reference.",
                safety_flags=["no_image_evidence"],
            )

        body = self._request_body(bundle=bundle, image_inputs=image_inputs)
        response = self._http_post_json(
            self._responses_url,
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            body,
            self._timeout_s,
        )
        result = _extract_cloud_result(response)
        return _normalize_model_result(
            result,
            max_answer_chars=_requested_max_answer_chars(bundle),
        )

    def _request_body(self, *, bundle: dict[str, Any], image_inputs: list[dict[str, Any]]) -> dict[str, Any]:
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": _verification_prompt(bundle),
            }
        ]
        content.extend(image_inputs)
        return {
            "model": self._model,
            "store": False,
            "max_output_tokens": self._max_output_tokens,
            "instructions": (
                "You are OpenVision's cloud visual verifier. Verify only from the provided "
                "evidence bundle and images. Reply in Vietnamese when possible. Do not identify "
                "people, infer sensitive traits, or invent details not visible in evidence."
            ),
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "openvision_cloud_result",
                    "strict": True,
                    "schema": _MODEL_RESULT_SCHEMA,
                }
            },
        }

    def _image_inputs(self, bundle: dict[str, Any]) -> list[dict[str, Any]]:
        refs = _evidence_refs(bundle)
        inputs: list[dict[str, Any]] = []
        for ref in refs[:3]:
            image_url = self._resolve_image_ref(ref, bundle)
            if not image_url:
                continue
            item = {"type": "input_image", "image_url": image_url}
            if self._image_detail:
                item["detail"] = self._image_detail
            inputs.append(item)
        return inputs

    def _resolve_image_ref(self, ref: str, bundle: dict[str, Any]) -> str | None:
        value = str(ref or "").strip()
        if value.startswith(("http://", "https://", "data:image/")):
            return value
        if self._image_ref_resolver:
            return self._image_ref_resolver(value, bundle)
        return None


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


def _cloud_uncertain(*, answer_short: str, message: str, safety_flags: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "cloud_result.v1",
        "status": "uncertain",
        "answer_short": answer_short,
        "answer_long": message,
        "confidence": 0.0,
        "selected_candidate_id": None,
        "hud_scene": None,
        "safety_flags": safety_flags or [],
        "memory_event": None,
        "error": None,
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


def image_bytes_to_data_url(image_bytes: bytes, content_type: str = "image/jpeg") -> str:
    media_type = content_type if content_type.startswith("image/") else "image/jpeg"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _post_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    with httpx.Client(timeout=timeout_s) as client:
        response = client.post(url, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("OpenAI Responses payload must be a JSON object.")
    return payload


def _evidence_refs(bundle: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("frame_refs", "crop_refs"):
        values = bundle.get(key)
        if not isinstance(values, list):
            continue
        refs.extend(str(item).strip() for item in values if str(item).strip())
    return refs


def _bundle_needs_visual_evidence(bundle: dict[str, Any]) -> bool:
    local_summary = bundle.get("local_summary") if isinstance(bundle.get("local_summary"), dict) else {}
    candidates = bundle.get("candidates") if isinstance(bundle.get("candidates"), list) else []
    return bool(_evidence_refs(bundle) or candidates or local_summary)


def _verification_prompt(bundle: dict[str, Any]) -> str:
    redacted_bundle = {
        "bundle_id": bundle.get("bundle_id"),
        "skill_id": bundle.get("skill_id"),
        "user_query": bundle.get("user_query"),
        "local_summary": bundle.get("local_summary"),
        "candidates": bundle.get("candidates"),
        "requested_output": bundle.get("requested_output"),
        "privacy": bundle.get("privacy"),
    }
    count_instruction = ""
    if bundle.get("skill_id") == "object_counter":
        count_instruction = (
            "\nCounting task: count the requested visible object type from the image. "
            "If exact counting is hard because items are small, overlapping, or numerous, "
            "return the best visible approximate count in Vietnamese and use status uncertain; "
            "do not refuse only because the count is approximate."
        )
    text_instruction = ""
    if bundle.get("skill_id") == "text_reader":
        text_instruction = (
            "\nOCR task: read only text that is actually visible in the image. "
            "Preserve exact wording when legible; if text is partially cut off, blurred, "
            "reflective, or too small, return the readable fragment in Vietnamese and use "
            "status uncertain. Do not invent missing words."
        )
    return (
        "Verify this OpenVision evidence bundle. Return cloud_result.v1 JSON only. "
        "Use status ok only when evidence is clear; use no_match when candidates do not match; "
        "use uncertain when image evidence is weak or unavailable."
        f"{count_instruction}{text_instruction}\n\n"
        f"{json.dumps(redacted_bundle, ensure_ascii=False, sort_keys=True)}"
    )


def _extract_cloud_result(response: dict[str, Any]) -> dict[str, Any]:
    text = response.get("output_text") if isinstance(response.get("output_text"), str) else ""
    if not text:
        text = _extract_output_text(response.get("output"))
    if not text:
        raise ValueError("OpenAI Responses payload did not include output text.")
    payload = json.loads(_strip_code_fence(text))
    if not isinstance(payload, dict):
        raise ValueError("OpenAI visual verifier output must be a JSON object.")
    return payload


def _extract_output_text(output: Any) -> str:
    parts: list[str] = []
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _normalize_model_result(result: dict[str, Any], *, max_answer_chars: int) -> dict[str, Any]:
    status = str(result.get("status") or "uncertain")
    if status not in {"ok", "no_match", "uncertain", "blocked", "error"}:
        status = "uncertain"
    answer_short = str(result.get("answer_short") or "Chưa chắc chắn").strip()[: min(80, max_answer_chars)]
    confidence = _clamp_float(result.get("confidence"), default=0.0)
    safety_flags = result.get("safety_flags")
    return {
        "schema_version": "cloud_result.v1",
        "status": status,
        "answer_short": answer_short or "Chưa chắc chắn",
        "answer_long": result.get("answer_long") if isinstance(result.get("answer_long"), str) else None,
        "confidence": confidence,
        "selected_candidate_id": result.get("selected_candidate_id") if isinstance(result.get("selected_candidate_id"), str) else None,
        "hud_scene": None,
        "safety_flags": [str(item) for item in safety_flags] if isinstance(safety_flags, list) else [],
        "memory_event": None,
        "error": result.get("error") if isinstance(result.get("error"), dict) else None,
    }


def _requested_max_answer_chars(bundle: dict[str, Any]) -> int:
    requested = bundle.get("requested_output")
    if not isinstance(requested, dict):
        return 80
    value = requested.get("max_answer_chars")
    if isinstance(value, int) and not isinstance(value, bool):
        return max(1, min(80, value))
    return 80


def _clamp_float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))
