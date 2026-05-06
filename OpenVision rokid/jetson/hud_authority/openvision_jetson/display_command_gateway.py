"""Typed DisplayCommand adapter into the HUD scene protocol."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from .contracts import DisplayCommand, new_id, to_jsonable
from .event_store import InMemoryEventStore
from .hud_authority import HudAuthority


SessionValidator = Callable[[str], bool]

DISPLAY_KINDS = {
    "text_hud",
    "object_card",
    "thumbnail_card",
    "full_image",
    "live_overlay",
    "debug_overlay",
    "clear",
}
DISPLAY_PRIORITIES = {"low", "normal", "high", "critical"}
HUD_PRIORITY_BY_DISPLAY = {
    "low": "low",
    "normal": "normal",
    "high": "high",
    "critical": "urgent",
}


@dataclass(frozen=True, slots=True)
class _DisplayBudget:
    default_ttl_ms: int
    max_ttl_ms: int


class DisplayCommandValidationError(RuntimeError):
    def __init__(self, *, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        payload = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class DisplayCommandGateway:
    """Validate display commands and render their Rokid-safe HUD equivalent."""

    _BUDGETS = {
        "text_hud": _DisplayBudget(default_ttl_ms=2500, max_ttl_ms=5000),
        "object_card": _DisplayBudget(default_ttl_ms=3000, max_ttl_ms=5000),
        "thumbnail_card": _DisplayBudget(default_ttl_ms=3000, max_ttl_ms=5000),
        "full_image": _DisplayBudget(default_ttl_ms=5000, max_ttl_ms=8000),
        "live_overlay": _DisplayBudget(default_ttl_ms=1000, max_ttl_ms=5000),
        "debug_overlay": _DisplayBudget(default_ttl_ms=1000, max_ttl_ms=1000),
        "clear": _DisplayBudget(default_ttl_ms=0, max_ttl_ms=0),
    }

    def __init__(
        self,
        *,
        events: InMemoryEventStore,
        hud: HudAuthority,
        session_validator: SessionValidator | None = None,
        debug_overlay_allowed: bool = True,
    ) -> None:
        self._events = events
        self._hud = hud
        self._session_validator = session_validator
        self._debug_overlay_allowed = debug_overlay_allowed
        self._commands: dict[str, DisplayCommand] = {}
        self._latest_scenes: dict[str, dict[str, Any]] = {}

    def request_command(
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
        started = perf_counter()
        try:
            normalized_kind = self._normalize_kind(kind)
            normalized_session_id = self._validate_session_id(session_id)
            normalized_priority = self._normalize_priority(priority)
            normalized_payload = payload if isinstance(payload, dict) else {}
            command = DisplayCommand(
                command_id=self._normalize_command_id(command_id),
                kind=normalized_kind,
                session_id=normalized_session_id,
                skill_id=self._optional_text(skill_id),
                payload=normalized_payload,
                priority=normalized_priority,
                ttl_ms=self._normalize_ttl_ms(normalized_kind, ttl_ms),
            )
            scene_args = self._scene_args(command)
            scene = self._hud.update_display_scene(**scene_args)
            duration_ms = _duration_ms(started)
            self._commands[command.command_id] = command
            self._latest_scenes[command.command_id] = scene
            self._events.add(
                "display_command",
                "command_completed",
                {
                    "command_id": command.command_id,
                    "kind": command.kind,
                    "status": "ok",
                    "skill_id": command.skill_id,
                    "hud_scene_id": scene["scene_id"],
                    "duration_ms": duration_ms,
                },
                session_id=command.session_id,
            )
            return {
                "status": "ok",
                "command": to_jsonable(command),
                "hud_scene": scene,
                "duration_ms": duration_ms,
            }
        except DisplayCommandValidationError as exc:
            duration_ms = _duration_ms(started)
            error = exc.to_payload()
            self._events.add(
                "display_command",
                "command_failed",
                {
                    "kind": kind,
                    "status": "error",
                    "duration_ms": duration_ms,
                    "error": error,
                },
                session_id=session_id or None,
                severity="error",
            )
            return {
                "status": "error",
                "error": error,
                "duration_ms": duration_ms,
            }

    def statuses(self) -> list[dict[str, Any]]:
        return [
            {
                "command": to_jsonable(command),
                "hud_scene": self._latest_scenes.get(command_id),
            }
            for command_id, command in self._commands.items()
        ]

    def _scene_args(self, command: DisplayCommand) -> dict[str, Any]:
        payload = command.payload
        hud_priority = HUD_PRIORITY_BY_DISPLAY[command.priority]
        if command.kind == "text_hud":
            text = _required_text(payload.get("text") or payload.get("answer_strip"), "payload.text")
            return {
                "session_id": command.session_id,
                "answer_strip": _short_text(text, 80),
                "edge_chips": _chips(payload, default=["display"]),
                "priority": hud_priority,
                "ttl_ms": command.ttl_ms,
            }
        if command.kind == "object_card":
            target_id = _optional_text(payload.get("target_id") or payload.get("track_id"))
            title = _required_text(payload.get("title") or payload.get("label") or target_id, "payload.title")
            subtitle = _optional_text(payload.get("subtitle") or payload.get("description"))
            thumbnail = _thumbnail_payload(
                payload,
                kind="object_card",
                title=title,
                caption=subtitle,
                target_id=target_id,
            )
            return {
                "session_id": command.session_id,
                "answer_strip": _short_text(_join_text(title, subtitle), 80),
                "edge_chips": _chips(payload, default=["object"]),
                "thumbnails": [thumbnail],
                "target_hint": _target_hint(payload, target_id=target_id, title=title),
                "priority": hud_priority,
                "ttl_ms": command.ttl_ms,
            }
        if command.kind == "thumbnail_card":
            image_uri = _required_text(payload.get("thumbnail_uri") or payload.get("image_url"), "payload.thumbnail_uri")
            title = _optional_text(payload.get("title") or payload.get("caption")) or "Thumbnail"
            thumbnail = _thumbnail_payload(
                {**payload, "thumbnail_uri": image_uri},
                kind="thumbnail_card",
                title=title,
                caption=_optional_text(payload.get("caption")),
                target_id=_optional_text(payload.get("target_id") or payload.get("track_id")),
            )
            return {
                "session_id": command.session_id,
                "answer_strip": _short_text(title, 80),
                "edge_chips": _chips(payload, default=["thumbnail"]),
                "thumbnails": [thumbnail],
                "priority": hud_priority,
                "ttl_ms": command.ttl_ms,
            }
        if command.kind == "full_image":
            image_uri = _required_text(payload.get("image_uri") or payload.get("image_url"), "payload.image_uri")
            title = _optional_text(payload.get("title") or payload.get("caption")) or "Full image"
            thumbnail = _thumbnail_payload(
                {**payload, "image_uri": image_uri},
                kind="full_image",
                title=title,
                caption=_optional_text(payload.get("caption")),
                target_id=_optional_text(payload.get("target_id") or payload.get("track_id")),
            )
            thumbnail["full_image"] = True
            return {
                "session_id": command.session_id,
                "answer_strip": _short_text(title, 80),
                "edge_chips": _chips(payload, default=["image"]),
                "thumbnails": [thumbnail],
                "priority": hud_priority,
                "ttl_ms": command.ttl_ms,
            }
        if command.kind == "live_overlay":
            target = _first_target(payload)
            title = _optional_text(payload.get("text") or payload.get("title") or payload.get("overlay_mode")) or "Live overlay"
            target_id = _optional_text(target.get("target_id") or target.get("track_id"))
            return {
                "session_id": command.session_id,
                "answer_strip": _short_text(title, 80),
                "edge_chips": _chips(payload, default=["live"]),
                "target_hint": _target_hint(target, target_id=target_id, title=title) if target else None,
                "priority": hud_priority,
                "ttl_ms": command.ttl_ms,
            }
        if command.kind == "debug_overlay":
            if not self._debug_overlay_allowed:
                raise DisplayCommandValidationError(
                    code="debug_overlay_disabled",
                    message="debug_overlay display commands are allowed only when debug display is enabled.",
                )
            text = _optional_text(payload.get("text")) or _debug_text(command.session_id, payload)
            return {
                "session_id": command.session_id,
                "answer_strip": _short_text(text, 80),
                "edge_chips": _chips(payload, default=["debug"]),
                "priority": hud_priority,
                "ttl_ms": command.ttl_ms,
            }
        if command.kind == "clear":
            return {
                "session_id": command.session_id,
                "answer_strip": None,
                "edge_chips": _chips(payload, default=["clear"]),
                "thumbnails": [],
                "target_hint": None,
                "priority": "low",
                "ttl_ms": 0,
            }
        raise DisplayCommandValidationError(
            code="invalid_display_kind",
            message=f"Unsupported display command kind: {command.kind}",
        )

    def _normalize_kind(self, kind: str) -> str:
        normalized = str(kind or "").strip()
        if normalized not in DISPLAY_KINDS:
            raise DisplayCommandValidationError(
                code="invalid_display_kind",
                message=f"Display kind must be one of: {', '.join(sorted(DISPLAY_KINDS))}.",
                details={"kind": kind},
            )
        return normalized

    def _validate_session_id(self, session_id: str) -> str:
        normalized = str(session_id or "").strip()
        if not normalized:
            raise DisplayCommandValidationError(
                code="missing_session",
                message="Display commands must be attached to a Jetson session.",
            )
        if self._session_validator and not self._session_validator(normalized):
            raise DisplayCommandValidationError(
                code="unknown_session",
                message=f"Display command references an unknown session: {normalized}",
            )
        return normalized

    def _normalize_priority(self, priority: str) -> str:
        normalized = str(priority or "normal").strip()
        if normalized not in DISPLAY_PRIORITIES:
            raise DisplayCommandValidationError(
                code="invalid_display_priority",
                message=f"Display priority must be one of: {', '.join(sorted(DISPLAY_PRIORITIES))}.",
                details={"priority": priority},
            )
        return normalized

    def _normalize_ttl_ms(self, kind: str, ttl_ms: int | None) -> int:
        budget = self._BUDGETS[kind]
        if ttl_ms is None:
            return budget.default_ttl_ms
        try:
            normalized = int(ttl_ms)
        except (TypeError, ValueError) as exc:
            raise DisplayCommandValidationError(
                code="invalid_display_ttl",
                message="ttl_ms must be a non-negative integer.",
                details={"ttl_ms": ttl_ms},
            ) from exc
        if normalized < 0:
            raise DisplayCommandValidationError(
                code="invalid_display_ttl",
                message="ttl_ms must be a non-negative integer.",
                details={"ttl_ms": ttl_ms},
            )
        return min(normalized, budget.max_ttl_ms)

    def _normalize_command_id(self, command_id: str | None) -> str:
        normalized = str(command_id or "").strip()
        return normalized or new_id("display_cmd")

    def _optional_text(self, value: Any) -> str | None:
        return _optional_text(value)


def _required_text(value: Any, field: str) -> str:
    normalized = _optional_text(value)
    if not normalized:
        raise DisplayCommandValidationError(
            code="missing_display_payload_field",
            message=f"{field} is required for this display command.",
            details={"field": field},
        )
    return normalized


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _short_text(value: str, max_chars: int) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _chips(payload: dict[str, Any], *, default: list[str]) -> list[str]:
    raw = payload.get("edge_chips")
    chips = raw if isinstance(raw, list) else default
    result: list[str] = []
    for chip in chips:
        text = str(chip).strip()
        if text and text not in result:
            result.append(text)
    return result[:4]


def _thumbnail_payload(
    payload: dict[str, Any],
    *,
    kind: str,
    title: str,
    caption: str | None,
    target_id: str | None,
) -> dict[str, Any]:
    thumbnail: dict[str, Any] = {
        "kind": kind,
        "title": title,
        "caption": caption,
    }
    if target_id:
        thumbnail["target_id"] = target_id
    for source, target in (
        ("thumbnail_uri", "thumbnail_uri"),
        ("image_uri", "image_uri"),
        ("image_url", "image_url"),
        ("bbox", "bbox"),
        ("zone", "zone"),
        ("confidence", "confidence"),
    ):
        if source in payload:
            thumbnail[target] = payload[source]
    return {key: value for key, value in thumbnail.items() if value is not None}


def _target_hint(payload: dict[str, Any], *, target_id: str | None, title: str) -> dict[str, Any] | None:
    if not target_id and not payload.get("anchor") and not payload.get("zone"):
        return None
    hint: dict[str, Any] = {
        "target_id": target_id,
        "status": _optional_text(payload.get("status")) or "displayed",
        "label": title,
        "anchor": _optional_text(payload.get("anchor") or payload.get("zone")),
    }
    return {key: value for key, value in hint.items() if value is not None}


def _first_target(payload: dict[str, Any]) -> dict[str, Any]:
    target_hint = payload.get("target_hint")
    if isinstance(target_hint, dict):
        return target_hint
    targets = payload.get("targets")
    if isinstance(targets, list):
        for target in targets:
            if isinstance(target, dict):
                return target
    return {}


def _join_text(title: str, subtitle: str | None) -> str:
    return f"{title} - {subtitle}" if subtitle else title


def _debug_text(session_id: str, payload: dict[str, Any]) -> str:
    parts = [f"debug {session_id}"]
    for key in ("fps", "latency_ms", "cloud", "skill", "media_mode"):
        if key in payload and payload[key] is not None:
            parts.append(f"{key}={payload[key]}")
    return " - ".join(parts)


def _duration_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))
