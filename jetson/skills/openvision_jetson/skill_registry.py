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
