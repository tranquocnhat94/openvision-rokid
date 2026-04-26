"""Manifest-driven typed skill registry for v2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import SkillCall, SkillDefinition, new_id, to_jsonable, utc_now


DEFAULT_MANIFEST_DIR = Path(__file__).resolve().parents[1] / "manifests"


class SkillRegistry:
    def __init__(self, *, manifest_dir: Path | str | None = None) -> None:
        self.manifest_dir = Path(manifest_dir) if manifest_dir else DEFAULT_MANIFEST_DIR
        self._skills = self._load_manifests(self.manifest_dir)

    def list_definitions(self) -> list[dict[str, Any]]:
        return [to_jsonable(skill) for skill in self._skills.values()]

    def realtime_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": skill.name,
                "description": skill.description,
                "parameters": skill.input_schema,
            }
            for skill in self._skills.values()
        ]

    def get(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

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
                "local_resources": definition.local_resources,
                "cloud_allowed": definition.cloud_allowed,
                "hud_policy": definition.hud_policy,
                "note": "Skill schema is registered; executor is pending runtime adapter wiring.",
            }
        return to_jsonable(call)

    def _load_manifests(self, manifest_dir: Path) -> dict[str, SkillDefinition]:
        if not manifest_dir.is_dir():
            raise FileNotFoundError(f"Missing skill manifest directory: {manifest_dir}")
        definitions: dict[str, SkillDefinition] = {}
        for path in sorted(manifest_dir.glob("*.json")):
            definition = _definition_from_manifest(_load_json(path), source_path=path)
            if definition.name in definitions:
                raise ValueError(f"Duplicate skill manifest name: {definition.name}")
            definitions[definition.name] = definition
        if not definitions:
            raise ValueError(f"No skill manifests found in: {manifest_dir}")
        return definitions


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Skill manifest must be an object: {path}")
    return payload


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
        local_resources=_string_list(payload.get("local_resources")),
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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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
