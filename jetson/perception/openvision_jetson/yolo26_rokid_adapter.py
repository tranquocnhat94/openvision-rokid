"""Rokid-scoped YOLO26 adapter.

This module is deliberately separate from the existing Ring / security YOLO26
runtime. It only exposes configuration status and a snapshot ingress contract
that a future Rokid-specific detector process can call.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from .contracts import to_jsonable
from .event_store import InMemoryEventStore


VALID_MODES = {"disabled", "external_snapshot"}
ALLOWED_SOURCE_MARKERS = ("rokid", "openvision")
FORBIDDEN_SOURCE_MARKERS = ("ring", "security", "surveillance")


@dataclass(frozen=True, slots=True)
class Yolo26AdapterSettings:
    mode: str
    engine_path: str | None
    labels_path: str | None
    min_confidence: float


@dataclass(slots=True)
class Yolo26AdapterStatus:
    name: str
    mode: str
    status: str
    engine_path_configured: bool
    labels_path_configured: bool
    engine_exists: bool
    labels_exists: bool
    min_confidence: float
    isolation: str
    message: str


class Yolo26RokidAdapter:
    def __init__(self, *, events: InMemoryEventStore) -> None:
        self._events = events

    def status(self) -> dict[str, Any]:
        settings = load_yolo26_adapter_settings()
        return to_jsonable(_build_status(settings))

    def validate_external_snapshot(self, *, source: str) -> dict[str, Any]:
        settings = load_yolo26_adapter_settings()
        status = _build_status(settings)
        clean_source = _clean_source(source)
        if status.status == "disabled":
            self._events.add(
                "adapter.yolo26",
                "snapshot_rejected",
                {"reason": "adapter_disabled", "source": clean_source},
                severity="warning",
            )
            return {
                "status": "error",
                "error": {
                    "code": "adapter_disabled",
                    "message": "Set OPENVISION_YOLO26_MODE=external_snapshot before posting YOLO26 snapshots.",
                },
            }
        if status.status == "invalid":
            self._events.add(
                "adapter.yolo26",
                "snapshot_rejected",
                {"reason": "invalid_config", "mode": settings.mode, "source": clean_source},
                severity="error",
            )
            return {
                "status": "error",
                "error": {
                    "code": "invalid_yolo26_adapter_config",
                    "message": status.message,
                },
            }
        source_error = _validate_external_source(clean_source)
        if source_error:
            self._events.add(
                "adapter.yolo26",
                "snapshot_rejected",
                {"reason": source_error["code"], "source": clean_source},
                severity="warning",
            )
            return {"status": "error", "error": source_error}
        return {
            "status": "accepted",
            "source": f"yolo26_rokid:{clean_source}",
            "min_confidence": settings.min_confidence,
            "adapter": to_jsonable(status),
        }

    def filter_detections(self, detections: list[dict[str, Any]], *, min_confidence: float) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in detections
            if isinstance(item, dict)
            and _detection_confidence(item) >= min_confidence
        ]


def load_yolo26_adapter_settings() -> Yolo26AdapterSettings:
    mode = os.getenv("OPENVISION_YOLO26_MODE", "disabled").strip().lower() or "disabled"
    engine_path = _clean_path(os.getenv("OPENVISION_YOLO26_ENGINE_PATH"))
    labels_path = _clean_path(os.getenv("OPENVISION_YOLO26_LABELS_PATH"))
    return Yolo26AdapterSettings(
        mode=mode,
        engine_path=engine_path,
        labels_path=labels_path,
        min_confidence=_to_float(os.getenv("OPENVISION_YOLO26_MIN_CONFIDENCE"), 0.25),
    )


def _build_status(settings: Yolo26AdapterSettings) -> Yolo26AdapterStatus:
    engine_exists = _exists(settings.engine_path)
    labels_exists = _exists(settings.labels_path)
    if settings.mode not in VALID_MODES:
        status = "invalid"
        message = f"Unsupported OPENVISION_YOLO26_MODE: {settings.mode}"
    elif settings.mode == "disabled":
        status = "disabled"
        message = "YOLO26 adapter is off; v2 will not touch any YOLO26 runtime."
    elif settings.mode == "external_snapshot":
        status = "ready"
        message = "Ready to accept snapshots from a separate Rokid YOLO26 runtime."
    else:
        status = "invalid"
        message = "YOLO26 v2 only supports disabled or external_snapshot mode; it never starts or binds detector processes."

    return Yolo26AdapterStatus(
        name="yolo26_rokid",
        mode=settings.mode,
        status=status,
        engine_path_configured=bool(settings.engine_path),
        labels_path_configured=bool(settings.labels_path),
        engine_exists=engine_exists,
        labels_exists=labels_exists,
        min_confidence=settings.min_confidence,
        isolation="rokid_specific_runtime_only",
        message=message,
    )


def _clean_path(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_source(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower().replace(" ", "_")


def _validate_external_source(source: str) -> dict[str, str] | None:
    if not source:
        return {
            "code": "missing_snapshot_source",
            "message": "YOLO26 snapshot source is required and must identify the separate Rokid runtime.",
        }
    if any(marker in source for marker in FORBIDDEN_SOURCE_MARKERS):
        return {
            "code": "forbidden_snapshot_source",
            "message": "YOLO26 snapshots from Ring/security runtimes are not accepted by OpenVision v2.",
        }
    if not any(marker in source for marker in ALLOWED_SOURCE_MARKERS):
        return {
            "code": "invalid_snapshot_source",
            "message": "YOLO26 snapshot source must identify a separate Rokid/OpenVision runtime.",
        }
    return None


def _exists(path: str | None) -> bool:
    return bool(path and Path(path).expanduser().exists())


def _to_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _detection_confidence(item: dict[str, Any]) -> float:
    value = item.get("confidence", item.get("score", 0.0))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
