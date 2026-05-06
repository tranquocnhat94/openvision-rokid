"""Manifest-driven typed skill registry for v2."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .contracts import SkillCall, SkillDefinition, new_id, to_jsonable, utc_now


DEFAULT_MANIFEST_DIR = Path(__file__).resolve().parents[1] / "manifests"
SKILL_MANIFEST_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "shared" / "schemas" / "skill_manifest.schema.json"
)
VISUAL_MEDIA_MODES = {"snapshot", "burst_clip", "live_video"}
HUD_POLICIES = {"answer_strip", "thumbnail_strip", "target_hint", "clear_target"}


class SkillRegistry:
    def __init__(self, *, manifest_dir: Path | str | None = None) -> None:
        self.manifest_dir = Path(manifest_dir) if manifest_dir else DEFAULT_MANIFEST_DIR
        self._skills = self._load_manifests(self.manifest_dir)
        self._tools = self._tool_lookup(self._skills)

    def list_definitions(self) -> list[dict[str, Any]]:
        return [to_jsonable(skill) for skill in self._skills.values()]

    def realtime_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": skill.tool_name or skill.name,
                "description": _realtime_tool_description(skill),
                "parameters": skill.input_schema,
            }
            for skill in self._skills.values()
        ]

    def get(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name) or self._tools.get(name)

    def validate_args(self, name: str, args: dict[str, Any]) -> list[str]:
        definition = self.get(name)
        if definition is None:
            return [f"unknown skill: {name}"]
        return validate_json_value(definition.input_schema, args, path="args")

    def dry_run(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        definition = self.get(name)
        call = SkillCall(
            skill_call_id=new_id("skill"),
            session_id=session_id,
            name=name,
            args=args or {},
            status="not_implemented",
        )
        call.updated_at = utc_now()
        if definition is None:
            call.status = "error"
            call.error = {"code": "unknown_skill", "message": f"Unknown skill: {name}"}
        else:
            call.result = {
                "planned_skill": definition.name,
                "manifest_id": definition.manifest_id,
                "tool_name": definition.tool_name or definition.name,
                "local_resources": definition.local_resources,
                "media_requirements": definition.media_requirements,
                "display_capabilities": definition.display_capabilities,
                "cloud_allowed": definition.cloud_allowed,
                "cloud_behavior": definition.cloud_behavior,
                "hud_policy": definition.hud_policy,
                "note": "Skill schema is registered; executor is pending runtime adapter wiring.",
            }
        return to_jsonable(call)

    def _load_manifests(self, manifest_dir: Path) -> dict[str, SkillDefinition]:
        if not manifest_dir.is_dir():
            raise FileNotFoundError(f"Missing skill manifest directory: {manifest_dir}")
        definitions: dict[str, SkillDefinition] = {}
        for path in sorted(manifest_dir.glob("*.json")):
            payload = _load_json(path)
            _validate_manifest(payload, source_path=path)
            definition = _definition_from_manifest(payload, source_path=path)
            if definition.name in definitions:
                raise ValueError(f"Duplicate skill manifest name: {definition.name}")
            definitions[definition.name] = definition
        if not definitions:
            raise ValueError(f"No skill manifests found in: {manifest_dir}")
        return definitions

    def _tool_lookup(self, definitions: dict[str, SkillDefinition]) -> dict[str, SkillDefinition]:
        tools: dict[str, SkillDefinition] = {}
        for definition in definitions.values():
            tool_name = definition.tool_name or definition.name
            if tool_name in tools:
                raise ValueError(f"Duplicate skill tool_name: {tool_name}")
            tools[tool_name] = definition
        return tools


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Skill manifest must be an object: {path}")
    return payload


def _validate_manifest(payload: dict[str, Any], *, source_path: Path) -> None:
    errors = validate_json_value(_skill_manifest_schema(), payload, path="manifest")
    errors.extend(_validate_manifest_policy(payload))
    if errors:
        formatted = "; ".join(errors)
        raise ValueError(f"Skill manifest failed validation: {source_path}: {formatted}")


@lru_cache(maxsize=1)
def _skill_manifest_schema() -> dict[str, Any]:
    return _load_json(SKILL_MANIFEST_SCHEMA_PATH)


def _validate_manifest_policy(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    media = payload.get("media_requirements") if isinstance(payload.get("media_requirements"), dict) else {}
    default_mode = str(media.get("default_mode") or "")
    allowed_modes = media.get("allowed_modes") if isinstance(media.get("allowed_modes"), list) else []
    allowed = {str(mode) for mode in allowed_modes}
    if default_mode and default_mode not in allowed:
        errors.append("manifest.media_requirements.default_mode must be present in allowed_modes")
    if default_mode in VISUAL_MEDIA_MODES and media.get("requires_camera") is not True:
        errors.append("manifest.media_requirements.requires_camera must be true for visual default_mode")
    if "live_video" in allowed and media.get("live_video_allowed") is not True:
        errors.append("manifest.media_requirements.live_video_allowed must be true when live_video is allowed")
    if media.get("live_video_allowed") is True and "live_video" not in allowed:
        errors.append("manifest.media_requirements.allowed_modes must include live_video when live_video_allowed is true")
    cloud_behavior = str(payload.get("cloud_behavior") or "")
    cloud_allowed = payload.get("cloud_allowed")
    if cloud_allowed is False and cloud_behavior != "local_only":
        errors.append("manifest.cloud_behavior must be local_only when cloud_allowed is false")
    if cloud_behavior != "local_only" and cloud_allowed is not True:
        errors.append("manifest.cloud_allowed must be true for gateway cloud behavior")
    if payload.get("cloud_allowed") is True and str(payload.get("privacy_level") or "") == "low":
        errors.append("manifest.privacy_level must be medium or higher when cloud is allowed")
    if str(payload.get("hud_policy") or "") not in HUD_POLICIES:
        errors.append(f"manifest.hud_policy must be one of: {', '.join(sorted(HUD_POLICIES))}")
    for key in ("display_capabilities", "activation_phrases_vi", "acceptance_tests", "failure_modes"):
        value = payload.get(key)
        if isinstance(value, list) and not value:
            errors.append(f"manifest.{key} must not be empty")
    return errors


def _definition_from_manifest(payload: dict[str, Any], *, source_path: Path) -> SkillDefinition:
    name = _required_string(payload, "name", source_path)
    description = _required_string(payload, "description", source_path)
    input_schema = _required_object(payload, "input_schema", source_path)
    result_schema = _required_object(payload, "result_schema", source_path)
    return SkillDefinition(
        name=name,
        description=description,
        input_schema=input_schema,
        result_schema=result_schema,
        tool_name=str(payload.get("tool_name") or name),
        local_resources=_string_list(payload.get("local_resources")),
        media_requirements=_optional_object(payload.get("media_requirements")),
        display_capabilities=_string_list(payload.get("display_capabilities")),
        memory_allowed=bool(payload.get("memory_allowed", False)),
        cloud_behavior=str(
            payload.get("cloud_behavior")
            or _default_cloud_behavior(bool(payload.get("cloud_allowed", False)))
        ),
        cloud_allowed=bool(payload.get("cloud_allowed", False)),
        hud_policy=str(payload.get("hud_policy") or "answer_strip"),
        timeout_ms=int(payload.get("timeout_ms") or 2500),
        manifest_id=str(payload.get("id") or f"openvision.skill.{name}"),
        version=str(payload.get("version") or "0.1.0"),
        latency_class=str(payload.get("latency_class") or "interactive"),
        local_first=bool(payload.get("local_first", True)),
        privacy_level=str(payload.get("privacy_level") or "low"),
        activation_phrases_vi=_string_list(payload.get("activation_phrases_vi")),
        activation_phrases_en=_string_list(payload.get("activation_phrases_en")),
        acceptance_tests=_string_list(payload.get("acceptance_tests")),
        failure_modes=_string_list(payload.get("failure_modes")),
    )


def _required_string(payload: dict[str, Any], key: str, source_path: Path) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"Skill manifest {source_path} missing required string: {key}")
    return value


def _required_object(payload: dict[str, Any], key: str, source_path: Path) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Skill manifest {source_path} missing required object: {key}")
    return value


def _optional_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _default_cloud_behavior(cloud_allowed: bool) -> str:
    return "gateway_optional" if cloud_allowed else "local_only"


def _realtime_tool_description(skill: SkillDefinition) -> str:
    parts = [skill.description.strip()]
    parts.append(
        "Route by semantic intent, not exact command text; Vietnamese phrases are examples, "
        "and noisy ASR/paraphrases with the same meaning should still use this tool."
    )
    if skill.activation_phrases_vi:
        parts.append("Vietnamese activation phrases: " + "; ".join(skill.activation_phrases_vi) + ".")
    if skill.activation_phrases_en:
        parts.append("English activation phrases: " + "; ".join(skill.activation_phrases_en) + ".")
    hint = _realtime_routing_hint(skill.name)
    if hint:
        parts.append(hint)
    return " ".join(part for part in parts if part)


def _realtime_routing_hint(name: str) -> str:
    if name == "scene_describe":
        return (
            "Routing: use this for open-ended visual scene description questions such as "
            '"đang có gì trước mặt tôi", "trước mặt tôi có gì", "nhìn xem có gì", '
            '"tôi đang nhìn thấy gì", "nhìn hộ tôi xem có gì", "xem quanh đây có gì", '
            'or "mô tả cảnh trước mặt". If unsure between scene_describe and '
            "count_people, choose scene_describe."
        )
    if name == "query_scene":
        return (
            "Routing: use this for specific visual follow-up questions such as "
            '"vật đó là gì", "cái kia là gì", or "màu gì". For sign/text/OCR '
            'questions such as "biển này ghi gì" or "có chữ gì", use text_reader. '
            "For open-ended scene description requests, use scene_describe instead."
        )
    if name == "text_reader":
        return (
            "Routing: use this for OCR/text-reading questions such as "
            '"biển này ghi gì", "có chữ gì", "đọc giúp tôi dòng này", '
            '"nhãn này ghi gì", or "màn hình ghi gì". Keep the original question '
            "in question, include language_hint when the user specifies a language, "
            "and prefer exact visible text over broad scene description."
        )
    if name == "count_people":
        return (
            "Routing: use only when the user explicitly asks for a person count "
            'such as "có bao nhiêu người", "mấy người", or "đếm người". Do not '
            'use for open-ended scene questions like "đang có gì trước mặt tôi"; '
            'use scene_describe instead. Do not route find-person requests like '
            '"tìm Trâm" or "tìm người quen" to count_people; use target_finder. '
            'Do not route identity/profile questions like "có ai quen không" or '
            '"người này là ai" to count_people; use person_info.'
        )
    if name == "object_counter":
        return (
            "Routing: use when the user asks to count visible non-person objects "
            'or repeated items, such as "có bao nhiêu hạt", "đếm mấy cái", '
            '"bao nhiêu ô", "có mấy ly", or "đếm giúp tôi cái này". '
            "For person counts, use count_people."
        )
    if name == "target_finder":
        return (
            "Routing: use for live target-finding requests such as \"tìm mục tiêu\", "
            '"tìm Trâm", "tìm người tên Trâm", "tìm người trong đám đông", '
            '"tìm người quen", or "người đó ở đâu". If Vietnamese has "tìm" plus '
            'a person/contact/proper name, choose target_finder with target_type="person"; '
            'keep query as the original utterance, include target_name, and set identity_query=true. '
            'Do not simplify "tìm Trâm" to "tìm người". '
            'For name-reminder requests such as "nhắc tên Trâm" or "bật nhắc tên", '
            'use person_info with scan_mode="name_reminder" instead unless the user clearly asks to find/guide. '
            "do not answer that the skill is not enabled unless Jetson returns a "
            "typed tool error. "
            "This tool starts bounded live video and returns anonymous person/object "
            "IDs plus HUD aim-assist. Named-person/contact requests can use the "
            "local OpenVision contact identity DB when enrolled samples exist."
        )
    if name == "person_info":
        return (
            "Routing: use for visible-person identity/profile lookup such as "
            '"có ai quen không", "người này tôi đã gặp chưa", "tôi có biết người này không", '
            '"người này là ai", "đây là ai", "nhắc tên người này", '
            '"cho tôi thông tin về người này", or "còn thông tin gì không". '
            "Default to scan_mode=\"snapshot\" for low power: Jetson captures one image, runs local Face Identity, "
            "checks the local OpenVision contact identity DB, enriches from People Registry, "
            "and returns static thumbnails with names for multiple visible people. Use "
            "scan_mode=\"name_reminder\" only when the user explicitly asks for realtime name reminders, "
            'live name reminder mode, continuous name hints, "nhắc tên Trâm", or "bật nhắc tên". '
            "For commands that ask to "
            'find/guide to a named person, such as "tìm Trâm", use target_finder instead.'
        )
    if name == "remember_person":
        return (
            "Routing: use when the user asks to remember/save the visible person, "
            'such as "ghi nhớ người này", "nhớ người này", or '
            '"ghi nhớ người này là Trâm". This captures a snapshot through Jetson, '
            "uploads it to Immich, and records People Registry metadata for later "
            "face sync and target_finder identity matching."
        )
    return ""


def validate_json_value(schema: dict[str, Any], value: Any, *, path: str = "value") -> list[str]:
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} must equal {schema['const']}")
    expected_type = schema.get("type")
    if expected_type and not _matches_json_type(value, expected_type):
        return [f"{path} must be {_type_label(expected_type)}"]

    if _schema_includes_type(expected_type, "object") and isinstance(value, dict):
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key} is required")
        if schema.get("additionalProperties") is False:
            extra = sorted(str(key) for key in set(value) - set(properties))
            for key in extra:
                errors.append(f"{path}.{key} is not allowed")
        for key, item in value.items():
            if key in properties and isinstance(properties[key], dict):
                errors.extend(validate_json_value(properties[key], item, path=f"{path}.{key}"))

    elif _schema_includes_type(expected_type, "array") and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(validate_json_value(item_schema, item, path=f"{path}[{index}]"))

    elif _schema_includes_type(expected_type, "string") and isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path} must have at least {min_length} characters")
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and len(value) > max_length:
            errors.append(f"{path} must have at most {max_length} characters")

    elif (
        (_schema_includes_type(expected_type, "integer") or _schema_includes_type(expected_type, "number"))
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{path} must be >= {minimum}")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{path} must be <= {maximum}")

    allowed = schema.get("enum")
    if isinstance(allowed, list) and value not in allowed:
        errors.append(f"{path} must be one of {', '.join(str(item) for item in allowed)}")

    return errors


def _schema_includes_type(expected_type: Any, item: str) -> bool:
    if isinstance(expected_type, list):
        return item in expected_type
    return expected_type == item


def _matches_json_type(value: Any, expected_type: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_json_type(value, item) for item in expected_type)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _type_label(expected_type: Any) -> str:
    if isinstance(expected_type, list):
        return " or ".join(str(item) for item in expected_type)
    return str(expected_type)
