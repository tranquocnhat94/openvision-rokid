"""Typed contracts for the OpenVision Rokid v2 Jetson runtime.

These contracts are intentionally small and dependency-free so they can be
shared by tests, debug tools, and early Jetson services before the production
API stack is installed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


JsonObject = dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value


@dataclass(slots=True)
class ClientSession:
    session_id: str
    client_kind: str
    status: str = "connected"
    capabilities: JsonObject = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class TraceEvent:
    event_id: str
    module: str
    event_type: str
    payload: JsonObject = field(default_factory=dict)
    session_id: str | None = None
    severity: str = "info"
    timestamp: str = field(default_factory=utc_now)


@dataclass(slots=True)
class HudScene:
    scene_id: str
    session_id: str | None = None
    answer_strip: str | None = None
    edge_chips: list[str] = field(default_factory=list)
    thumbnails: list[JsonObject] = field(default_factory=list)
    target_hint: JsonObject | None = None
    priority: str = "normal"
    ttl_ms: int = 2500
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class SkillDefinition:
    name: str
    description: str
    input_schema: JsonObject
    result_schema: JsonObject
    local_resources: list[str] = field(default_factory=list)
    cloud_allowed: bool = False
    hud_policy: str = "answer_strip"
    timeout_ms: int = 2500
    manifest_id: str | None = None
    version: str = "0.1.0"
    latency_class: str = "interactive"
    local_first: bool = True
    privacy_level: str = "low"
    activation_phrases_vi: list[str] = field(default_factory=list)
    activation_phrases_en: list[str] = field(default_factory=list)
    acceptance_tests: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SkillCall:
    skill_call_id: str
    name: str
    args: JsonObject
    session_id: str | None = None
    status: str = "queued"
    result: JsonObject | None = None
    error: JsonObject | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class SettingsSnapshot:
    environment: str
    openai_key_present: bool
    realtime_model: str
    realtime_voice: str
    realtime_url: str
    debug_stt_enabled: bool = False
    debug_stt_transcribe_url: str | None = None
    debug_stt_health_url: str | None = None
    openai_key_source: str = "missing"
    secrets_redacted: bool = True
    secret_load_error: str | None = None


@dataclass(slots=True)
class RealtimeStatus:
    session_id: str
    status: str
    model: str
    turn_policy: str
    output_modalities: list[str] = field(default_factory=lambda: ["text"])
    connected_at: str | None = None
    updated_at: str = field(default_factory=utc_now)
    last_event_type: str | None = None
    event_count: int = 0
    error: JsonObject | None = None
