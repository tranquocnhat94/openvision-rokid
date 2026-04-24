"""Typed skill registry skeleton for v2."""

from __future__ import annotations

from typing import Any

from .contracts import SkillCall, SkillDefinition, new_id, to_jsonable, utc_now


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


class SkillRegistry:
    def __init__(self) -> None:
        self._skills = {
            definition.name: definition
            for definition in [
                SkillDefinition(
                    name="count_people",
                    description="Count visible people using Jetson-owned detections/tracks.",
                    input_schema=_object_schema(
                        {
                            "frame_window_ms": {"type": "integer", "minimum": 100, "maximum": 5000},
                            "min_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        }
                    ),
                    result_schema=_object_schema(
                        {
                            "count": {"type": "integer", "minimum": 0},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "evidence": {"type": "array", "items": {"type": "string"}},
                        },
                        ["count", "confidence"],
                    ),
                    local_resources=["perception_graph", "yolo26_rokid_adapter"],
                    cloud_allowed=False,
                    hud_policy="answer_strip",
                    timeout_ms=1500,
                ),
                SkillDefinition(
                    name="query_scene",
                    description="Answer a visual question from current Jetson frame evidence.",
                    input_schema=_object_schema(
                        {
                            "question": {"type": "string", "minLength": 1},
                            "include_crops": {"type": "boolean"},
                        },
                        ["question"],
                    ),
                    result_schema=_object_schema(
                        {
                            "answer": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}},
                        },
                        ["answer"],
                    ),
                    local_resources=["frame_bus", "perception_graph"],
                    cloud_allowed=True,
                    hud_policy="answer_strip",
                    timeout_ms=5000,
                ),
                SkillDefinition(
                    name="search_targets",
                    description=(
                        "Find people/objects and return target candidates. Attribute queries "
                        "such as shirt color, glasses, standing/sitting are unverified until a "
                        "cloud attribute resolver confirms them; do not treat candidates as "
                        "confirmed matches when the tool returns needs_cloud."
                    ),
                    input_schema=_object_schema(
                        {
                            "query": {"type": "string", "minLength": 1},
                            "max_candidates": {"type": "integer", "minimum": 1, "maximum": 8},
                        },
                        ["query"],
                    ),
                    result_schema=_object_schema(
                        {
                            "candidates": {"type": "array", "items": {"type": "object"}},
                            "summary": {"type": "string"},
                        },
                        ["candidates"],
                    ),
                    local_resources=["perception_graph", "crop_store"],
                    cloud_allowed=True,
                    hud_policy="thumbnail_strip",
                    timeout_ms=6500,
                ),
                SkillDefinition(
                    name="select_target",
                    description="Set the active selected target for follow-up visual questions.",
                    input_schema=_object_schema(
                        {
                            "target_id": {"type": "string", "minLength": 1},
                            "reason": {"type": "string"},
                        },
                        ["target_id"],
                    ),
                    result_schema=_object_schema(
                        {
                            "selected_target": {"type": "object"},
                            "hud_hint": {"type": "object"},
                        },
                        ["selected_target"],
                    ),
                    local_resources=["selected_target_state"],
                    cloud_allowed=False,
                    hud_policy="target_hint",
                    timeout_ms=1000,
                ),
                SkillDefinition(
                    name="analyze_selected_target",
                    description="Answer a follow-up question about the currently selected target.",
                    input_schema=_object_schema(
                        {
                            "question": {"type": "string", "minLength": 1},
                            "include_recent_crops": {"type": "boolean"},
                        },
                        ["question"],
                    ),
                    result_schema=_object_schema(
                        {
                            "answer": {"type": "string"},
                            "target_id": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}},
                        },
                        ["answer"],
                    ),
                    local_resources=["selected_target_state", "crop_store"],
                    cloud_allowed=True,
                    hud_policy="answer_strip",
                    timeout_ms=5000,
                ),
                SkillDefinition(
                    name="clear_target",
                    description="Clear selected target state and remove target HUD cues.",
                    input_schema=_object_schema({}),
                    result_schema=_object_schema({"cleared": {"type": "boolean"}}, ["cleared"]),
                    local_resources=["selected_target_state"],
                    cloud_allowed=False,
                    hud_policy="clear_target",
                    timeout_ms=500,
                ),
            ]
        }

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
                "local_resources": definition.local_resources,
                "cloud_allowed": definition.cloud_allowed,
                "hud_policy": definition.hud_policy,
                "note": "Skill schema is registered; executor is pending runtime adapter wiring.",
            }
        return to_jsonable(call)
