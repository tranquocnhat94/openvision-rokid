"""Safe ingress adapter for OpenVision local face identity stream results.

The adapter accepts bbox + embedding frames from an OpenVision-owned worker only.
It does not connect to, mutate, or depend on the protected Ring/security runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any


FORBIDDEN_RUNTIME_MARKERS = ("ring", "security", "surveillance")
ALLOWED_SOURCE_MARKERS = ("openvision", "rokid", "iphone")


@dataclass(frozen=True, slots=True)
class FaceIdentityAdapterSettings:
    mode: str = "external_stream"
    min_confidence: float = 0.75
    worker_detector_model_path: str | None = None
    worker_recognizer_model_path: str | None = None


class FaceIdentityAdapter:
    """Validate and normalize local face identity stream ingress."""

    def __init__(self, *, events: Any | None = None) -> None:
        self._events = events

    def validate_external_stream(self, *, source: str) -> dict[str, Any]:
        settings = load_face_identity_adapter_settings()
        if settings.mode != "external_stream":
            return _error(
                code="adapter_mode_mismatch",
                message="Face identity adapter must be in external_stream mode to accept live frames.",
                mode=settings.mode,
            )
        source_name = _clean_source(source)
        if not source_name:
            return _error(
                code="missing_stream_source",
                message="Face identity stream source is required.",
                mode=settings.mode,
            )
        if marker := _forbidden_marker(source_name):
            return _error(
                code="forbidden_stream_source",
                message=f"Rejected protected source marker: {marker}.",
                mode=settings.mode,
            )
        if not any(marker in source_name for marker in ALLOWED_SOURCE_MARKERS):
            return _error(
                code="untrusted_stream_source",
                message="Face identity stream source must identify an OpenVision/Rokid/iPhone runtime.",
                mode=settings.mode,
            )
        return {
            "status": "accepted",
            "adapter": "face_identity",
            "source": f"face_identity_stream:{source_name}",
            "mode": settings.mode,
            "min_confidence": settings.min_confidence,
        }

    def filter_detections(self, detections: list[dict[str, Any]], *, min_confidence: float) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for item in detections:
            confidence = _confidence(item)
            if confidence < min_confidence:
                continue
            normalized = dict(item)
            normalized["label"] = str(normalized.get("label") or "person").strip().lower() or "person"
            normalized["confidence"] = confidence
            attributes = normalized.get("attributes") if isinstance(normalized.get("attributes"), dict) else {}
            normalized["attributes"] = {
                **attributes,
                "detector_family": "face_identity",
                "primary_region": attributes.get("primary_region") or "face",
            }
            output.append(normalized)
        return output

    def status(self) -> dict[str, Any]:
        settings = load_face_identity_adapter_settings()
        model_status = _model_status(settings)
        if settings.mode == "disabled":
            status = "disabled"
            message = "Face identity stream adapter is disabled."
        elif settings.mode == "external_stream":
            status = "ready"
            message = "Ready to accept live bbox + embedding frames from a separate OpenVision face identity worker."
        else:
            status = "error"
            message = f"Unsupported face identity adapter mode: {settings.mode}."
        return {
            "name": "face_identity",
            "status": status,
            "mode": settings.mode,
            "stream_ingest_enabled": settings.mode == "external_stream",
            "min_confidence": settings.min_confidence,
            "detector_model_configured": bool(settings.worker_detector_model_path),
            "detector_model_exists": model_status["detector_exists"],
            "recognizer_model_configured": bool(settings.worker_recognizer_model_path),
            "recognizer_model_exists": model_status["recognizer_exists"],
            "isolation": "separate_openvision_runtime_only",
            "message": message,
        }


def load_face_identity_adapter_settings() -> FaceIdentityAdapterSettings:
    return FaceIdentityAdapterSettings(
        mode=os.getenv("OPENVISION_FACE_IDENTITY_MODE", "external_stream").strip().lower() or "external_stream",
        min_confidence=_env_float("OPENVISION_FACE_IDENTITY_MIN_CONFIDENCE", 0.75),
        worker_detector_model_path=_clean_path(os.getenv("OPENVISION_FACE_WORKER_DETECTOR_MODEL")),
        worker_recognizer_model_path=_clean_path(os.getenv("OPENVISION_FACE_WORKER_RECOGNIZER_MODEL")),
    )


def _model_status(settings: FaceIdentityAdapterSettings) -> dict[str, bool]:
    detector = settings.worker_detector_model_path or ""
    recognizer = settings.worker_recognizer_model_path or ""
    return {
        "detector_exists": bool(detector and Path(detector).expanduser().exists()),
        "recognizer_exists": bool(recognizer and Path(recognizer).expanduser().exists()),
    }


def _error(*, code: str, message: str, mode: str) -> dict[str, Any]:
    return {
        "status": "error",
        "adapter": "face_identity",
        "mode": mode,
        "error": {"code": code, "message": message},
    }


def _confidence(item: dict[str, Any]) -> float:
    for key in ("confidence", "face_confidence"):
        try:
            return float(item.get(key))
        except (TypeError, ValueError):
            continue
    attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    try:
        return float(attributes.get("face_confidence"))
    except (TypeError, ValueError):
        return 0.0


def _clean_source(value: str) -> str:
    source = str(value or "").strip().lower().replace(" ", "_")
    return source


def _clean_path(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    return cleaned or None


def _forbidden_marker(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower()
    for marker in FORBIDDEN_RUNTIME_MARKERS:
        if marker in lowered:
            return marker
    return None


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default
