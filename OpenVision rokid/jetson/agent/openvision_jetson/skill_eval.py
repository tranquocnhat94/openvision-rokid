"""Skill-level replay evaluation for product hardening.

The session scorecard checks stream/audio/HUD health. This module checks the
typed skill path itself: Cloud Realtime tool call -> Jetson skill executor ->
media/evidence/cloud/HUD output. It intentionally uses compact event summaries
so replay files remain useful without copying raw profile text into eval logs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .contracts import utc_now
from .hud_authority import validate_hud_scene


CORE_VISUAL_SKILLS = {
    "scene_describe",
    "query_scene",
    "text_reader",
    "object_counter",
    "count_people",
    "person_info",
    "target_finder",
    "search_targets",
    "analyze_selected_target",
}
CLOUD_CAPABLE_SKILLS = {
    "scene_describe",
    "query_scene",
    "text_reader",
    "object_counter",
    "search_targets",
    "analyze_selected_target",
}
IDENTITY_SKILLS = {"person_info", "target_finder"}
SUCCESS_MEDIA_STATUSES = {"ok", "timeout"}
CLOUD_RESULT_EVENT_TYPES = {
    "result",
    "provider_missing",
    "provider_error",
    "privacy_blocked",
    "budget_blocked",
    "bundle_rejected",
    "result_rejected",
    "verification_completed",
    "verification_failed",
    "verification_blocked",
}
CLOUD_BLOCKED_EVENT_TYPES = {"privacy_blocked", "budget_blocked", "verification_blocked"}
CLOUD_INVALID_CONTRACT_EVENT_TYPES = {"bundle_rejected", "result_rejected"}
CLOUD_INVALID_CONTRACT_CODES = {"invalid_evidence_bundle", "invalid_cloud_result"}
CLOUD_SAFE_FALLBACK_CODES = {"cloud_provider_missing", "privacy_blocked", "budget_exceeded"}
CLOUD_SUCCESS_STATUSES = {"ok", "no_match", "uncertain"}


def build_skill_eval(
    replay: dict[str, Any],
    *,
    expected_skills: list[str] | tuple[str, ...] | set[str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build an operator-facing eval for typed visual skill behavior."""

    generated_at = generated_at or utc_now()
    events = _list(replay.get("events"))
    hud_scenes = _list(replay.get("hud_scenes"))
    perception = _list(replay.get("perception"))
    expected = _ordered_unique(str(item).strip() for item in (expected_skills or []) if str(item).strip())

    skill_events = [
        event
        for event in events
        if event.get("module") == "skills" and event.get("event_type") == "executed"
    ]
    realtime_tool_events = [event for event in events if event.get("module") == "realtime_tool"]
    media_events = [event for event in events if event.get("module") == "media_command"]
    cloud_events = [event for event in events if event.get("module") == "cloud_gateway"]
    identity_events = [
        event
        for event in events
        if event.get("module") == "skills"
        and event.get("event_type") in {"person_info_identity_checked", "target_finder_identity_checked"}
    ]
    skill_names = _ordered_unique(
        [
            *(_payload_string(event, "name") for event in skill_events),
            *(_payload_string(event, "tool_name") for event in realtime_tool_events),
        ]
    )
    skill_names = [name for name in skill_names if name]
    visual_skill_names = [name for name in skill_names if name in CORE_VISUAL_SKILLS]
    cloud_skill_names = [name for name in skill_names if name in CLOUD_CAPABLE_SKILLS]
    identity_skill_names = [name for name in skill_names if name in IDENTITY_SKILLS]

    skill_statuses = [_payload_string(event, "status") or "unknown" for event in skill_events]
    skill_error_count = sum(1 for status in skill_statuses if status == "error")
    no_evidence_count = sum(1 for status in skill_statuses if status == "no_evidence")
    needs_cloud_count = sum(1 for status in skill_statuses if status == "needs_cloud")
    tool_errors = _count_tool_errors(realtime_tool_events)
    media_summary = _media_summary(media_events, visual_skill_names=visual_skill_names)
    cloud_summary = _cloud_summary(cloud_events, cloud_skill_names=cloud_skill_names)
    hud_summary = _hud_summary(hud_scenes, skill_names=skill_names, generated_at=generated_at)
    identity_summary = _identity_summary(identity_events)
    max_skill_duration_ms = _max_payload_int(skill_events, "duration_ms")

    gates = {
        "skill_invocation": _skill_invocation_gate(
            skill_names=skill_names,
            expected_skills=expected,
        ),
        "tool_contract": _tool_contract_gate(
            realtime_tool_events=realtime_tool_events,
            tool_errors=tool_errors,
        ),
        "skill_results": _skill_results_gate(
            skill_events=skill_events,
            skill_error_count=skill_error_count,
            no_evidence_count=no_evidence_count,
        ),
        "media_evidence": _media_evidence_gate(
            visual_skill_names=visual_skill_names,
            media_summary=media_summary,
            perception_count=len(perception),
        ),
        "hud_output": _hud_output_gate(
            skill_names=skill_names,
            hud_summary=hud_summary,
        ),
        "cloud_evidence": _cloud_evidence_gate(
            cloud_skill_names=cloud_skill_names,
            needs_cloud_count=needs_cloud_count,
            cloud_summary=cloud_summary,
        ),
        "identity_pipeline": _identity_pipeline_gate(
            identity_skill_names=identity_skill_names,
            identity_summary=identity_summary,
        ),
        "skill_latency": _skill_latency_gate(max_skill_duration_ms=max_skill_duration_ms),
    }
    metrics = {
        "skill_call_count": len(skill_events),
        "skill_names": skill_names,
        "expected_skills": expected,
        "expected_missing_count": len([name for name in expected if name not in skill_names]),
        "visual_skill_call_count": len(visual_skill_names),
        "visual_skill_names": visual_skill_names,
        "cloud_capable_skill_names": cloud_skill_names,
        "identity_skill_names": identity_skill_names,
        "skill_error_count": skill_error_count,
        "skill_no_evidence_count": no_evidence_count,
        "skill_needs_cloud_count": needs_cloud_count,
        "realtime_tool_event_count": len(realtime_tool_events),
        "realtime_tool_error_count": tool_errors,
        "media_command_event_count": len(media_events),
        "media_visual_command_count": media_summary["visual_command_count"],
        "media_visual_success_count": media_summary["visual_success_count"],
        "cloud_gateway_event_count": len(cloud_events),
        "cloud_bundle_count": cloud_summary["bundle_count"],
        "cloud_result_count": cloud_summary["result_count"],
        "cloud_error_count": cloud_summary["error_count"],
        "identity_check_count": identity_summary["check_count"],
        "identity_confirmed_count": identity_summary["confirmed_count"],
        "hud_scene_count": len(hud_scenes),
        "hud_valid_scene_count": hud_summary["valid_scene_count"],
        "hud_skill_chip_match_count": hud_summary["skill_chip_match_count"],
        "max_skill_duration_ms": max_skill_duration_ms,
    }
    return {
        "schema_version": "openvision.skill_eval.v1",
        "generated_at": generated_at,
        "session_id": replay.get("session_id"),
        "status": _overall_status(gates),
        "score": _score_gates(gates),
        "gates": gates,
        "metrics": metrics,
        "skill_runs": _skill_runs(skill_events),
        "top_failures": _top_failures(gates),
    }


def _gate(
    *,
    status: str,
    required: bool,
    message: str,
    observed: dict[str, Any] | None = None,
    threshold: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "required": required,
        "message": message,
        "observed": observed or {},
        "threshold": threshold or {},
    }


def _skill_invocation_gate(*, skill_names: list[str], expected_skills: list[str]) -> dict[str, Any]:
    missing = [name for name in expected_skills if name not in skill_names]
    observed = {"skill_names": skill_names, "expected_skills": expected_skills, "missing": missing}
    if expected_skills and missing:
        return _gate(
            status="fail",
            required=True,
            message=f"missing expected skill calls: {', '.join(missing)}",
            observed=observed,
        )
    if skill_names:
        return _gate(
            status="pass",
            required=bool(expected_skills),
            message=f"{len(skill_names)} typed skill names observed",
            observed=observed,
        )
    return _gate(
        status="warn",
        required=bool(expected_skills),
        message="no typed skill invocation observed",
        observed=observed,
    )


def _tool_contract_gate(*, realtime_tool_events: list[dict[str, Any]], tool_errors: int) -> dict[str, Any]:
    completed = sum(1 for event in realtime_tool_events if event.get("event_type") == "call_completed")
    observed = {"tool_event_count": len(realtime_tool_events), "completed": completed, "error_count": tool_errors}
    if tool_errors:
        return _gate(status="fail", required=False, message=f"{tool_errors} realtime tool errors", observed=observed)
    if completed:
        return _gate(status="pass", required=False, message=f"{completed} typed realtime tool calls completed", observed=observed)
    return _gate(status="warn", required=False, message="no completed realtime tool call recorded", observed=observed)


def _skill_results_gate(
    *,
    skill_events: list[dict[str, Any]],
    skill_error_count: int,
    no_evidence_count: int,
) -> dict[str, Any]:
    statuses = [_payload_string(event, "status") or "unknown" for event in skill_events]
    observed = {"skill_call_count": len(skill_events), "statuses": statuses}
    if skill_error_count:
        return _gate(status="fail", required=False, message=f"{skill_error_count} skill executions returned error", observed=observed)
    if no_evidence_count:
        return _gate(status="warn", required=False, message=f"{no_evidence_count} skill executions lacked evidence", observed=observed)
    if skill_events:
        return _gate(status="pass", required=False, message="skill executions completed without error", observed=observed)
    return _gate(status="warn", required=False, message="no skill result event recorded", observed=observed)


def _media_evidence_gate(
    *,
    visual_skill_names: list[str],
    media_summary: dict[str, Any],
    perception_count: int,
) -> dict[str, Any]:
    observed = {**media_summary, "perception_snapshot_count": perception_count, "visual_skill_names": visual_skill_names}
    if not visual_skill_names:
        return _gate(status="warn", required=False, message="no visual skill was invoked", observed=observed)
    if media_summary["visual_error_count"]:
        return _gate(
            status="fail",
            required=False,
            message=f"{media_summary['visual_error_count']} visual media commands failed",
            observed=observed,
        )
    if media_summary["visual_success_count"] or perception_count:
        return _gate(status="pass", required=False, message="visual skill has media or perception evidence", observed=observed)
    if media_summary["visual_command_count"]:
        return _gate(status="warn", required=False, message="visual media command observed but no final success yet", observed=observed)
    return _gate(status="fail", required=False, message="visual skill ran without media/perception evidence", observed=observed)


def _hud_output_gate(*, skill_names: list[str], hud_summary: dict[str, Any]) -> dict[str, Any]:
    observed = dict(hud_summary)
    if not skill_names:
        return _gate(status="warn", required=False, message="no skill invocation to verify HUD output", observed=observed)
    if hud_summary["invalid_scene_count"]:
        return _gate(status="fail", required=False, message="invalid HUD scene observed", observed=observed)
    if hud_summary["skill_chip_match_count"]:
        return _gate(status="pass", required=False, message="HUD scene carries skill chips", observed=observed)
    if hud_summary["valid_scene_count"]:
        return _gate(status="warn", required=False, message="HUD scene exists but is not linked to skill chips", observed=observed)
    return _gate(status="fail", required=False, message="skill ran without schema-valid HUD output", observed=observed)


def _cloud_evidence_gate(
    *,
    cloud_skill_names: list[str],
    needs_cloud_count: int,
    cloud_summary: dict[str, Any],
) -> dict[str, Any]:
    observed = {**cloud_summary, "cloud_skill_names": cloud_skill_names, "needs_cloud_count": needs_cloud_count}
    if cloud_summary["invalid_contract_count"]:
        return _gate(
            status="fail",
            required=False,
            message=f"{cloud_summary['invalid_contract_count']} invalid cloud evidence/result contracts",
            observed=observed,
        )
    if cloud_summary["error_count"]:
        return _gate(status="warn", required=False, message=f"{cloud_summary['error_count']} cloud gateway fallback/error events", observed=observed)
    if needs_cloud_count and cloud_summary["bundle_count"] and cloud_summary["result_count"]:
        if cloud_summary["blocked_count"] or cloud_summary["fallback_count"] or cloud_summary["provider_error_count"]:
            return _gate(
                status="warn",
                required=False,
                message="needs_cloud skill used a safe cloud fallback/block path",
                observed=observed,
            )
        return _gate(status="pass", required=False, message="needs_cloud skill has evidence bundle and cloud result", observed=observed)
    if needs_cloud_count:
        return _gate(status="fail", required=False, message="needs_cloud skill missing cloud evidence/result events", observed=observed)
    if cloud_summary["bundle_count"] and not cloud_summary["result_count"]:
        return _gate(status="fail", required=False, message="cloud evidence bundle was created without a result event", observed=observed)
    if cloud_skill_names and cloud_summary["bundle_count"]:
        return _gate(status="pass", required=False, message="cloud-capable skill created evidence bundle", observed=observed)
    return _gate(status="pass", required=False, message="no cloud escalation required in this replay", observed=observed)


def _identity_pipeline_gate(
    *,
    identity_skill_names: list[str],
    identity_summary: dict[str, Any],
) -> dict[str, Any]:
    observed = {**identity_summary, "identity_skill_names": identity_skill_names}
    if not identity_skill_names:
        return _gate(status="pass", required=False, message="no identity skill invoked", observed=observed)
    if identity_summary["check_count"] <= 0:
        return _gate(status="warn", required=False, message="identity skill ran without identity check event", observed=observed)
    if identity_summary["error_count"]:
        return _gate(status="fail", required=False, message="identity provider reported errors", observed=observed)
    if identity_summary["confirmed_count"]:
        return _gate(status="pass", required=False, message="identity provider confirmed at least one match", observed=observed)
    return _gate(status="warn", required=False, message="identity check ran but no confirmed match", observed=observed)


def _skill_latency_gate(*, max_skill_duration_ms: int | None) -> dict[str, Any]:
    observed = {"max_skill_duration_ms": max_skill_duration_ms}
    threshold = {"warn_max_ms": 4_000, "fail_max_ms": 12_000}
    if max_skill_duration_ms is None:
        return _gate(status="warn", required=False, message="skill latency was not measured", observed=observed, threshold=threshold)
    if max_skill_duration_ms > threshold["fail_max_ms"]:
        return _gate(status="fail", required=False, message=f"skill latency exceeded {threshold['fail_max_ms']}ms", observed=observed, threshold=threshold)
    if max_skill_duration_ms > threshold["warn_max_ms"]:
        return _gate(status="warn", required=False, message=f"skill latency is high at {max_skill_duration_ms}ms", observed=observed, threshold=threshold)
    return _gate(status="pass", required=False, message="skill latency is within interactive budget", observed=observed, threshold=threshold)


def _media_summary(events: list[dict[str, Any]], *, visual_skill_names: list[str]) -> dict[str, Any]:
    by_skill: dict[str, dict[str, Any]] = {}
    visual_commands = 0
    visual_success = 0
    visual_errors = 0
    for event in events:
        payload = _payload(event)
        skill_id = str(payload.get("skill_id") or "").strip()
        mode = str(payload.get("mode") or "").strip()
        status = str(payload.get("status") or "").strip()
        if skill_id:
            item = by_skill.setdefault(skill_id, {"count": 0, "success_count": 0, "error_count": 0, "modes": [], "statuses": []})
            item["count"] += 1
            if mode and mode not in item["modes"]:
                item["modes"].append(mode)
            if status and status not in item["statuses"]:
                item["statuses"].append(status)
            if status in SUCCESS_MEDIA_STATUSES:
                item["success_count"] += 1
            if status == "error":
                item["error_count"] += 1
        if skill_id in visual_skill_names:
            visual_commands += 1
            if status in SUCCESS_MEDIA_STATUSES:
                visual_success += 1
            if status == "error":
                visual_errors += 1
    return {
        "commands_by_skill": by_skill,
        "visual_command_count": visual_commands,
        "visual_success_count": visual_success,
        "visual_error_count": visual_errors,
    }


def _cloud_summary(events: list[dict[str, Any]], *, cloud_skill_names: list[str]) -> dict[str, Any]:
    bundle_count = 0
    result_count = 0
    error_count = 0
    blocked_count = 0
    fallback_count = 0
    provider_error_count = 0
    missing_provider_count = 0
    invalid_contract_count = 0
    success_count = 0
    validation_error_count = 0
    latencies: list[int] = []
    error_codes: list[str] = []
    statuses: list[str] = []
    by_skill: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = _payload(event)
        skill_id = str(payload.get("skill_id") or "").strip()
        if skill_id:
            item = by_skill.setdefault(
                skill_id,
                {
                    "bundle_count": 0,
                    "result_count": 0,
                    "success_count": 0,
                    "blocked_count": 0,
                    "fallback_count": 0,
                    "provider_error_count": 0,
                    "missing_provider_count": 0,
                    "invalid_contract_count": 0,
                    "error_count": 0,
                    "statuses": [],
                    "error_codes": [],
                    "max_latency_ms": None,
                },
            )
        else:
            item = None
        event_type = str(event.get("event_type") or "")
        severity = str(event.get("severity") or "")
        status = str(payload.get("status") or "").strip()
        error_code = str(payload.get("error_code") or "").strip()
        if event_type == "bundle_created":
            bundle_count += 1
            if item is not None:
                item["bundle_count"] += 1
        is_result_event = event_type in CLOUD_RESULT_EVENT_TYPES or (
            event_type != "bundle_created" and bool(status)
        )
        if is_result_event:
            result_count += 1
            if item is not None:
                item["result_count"] += 1
        if status in CLOUD_SUCCESS_STATUSES:
            success_count += 1
            if item is not None:
                item["success_count"] += 1
        if status == "blocked" or event_type in CLOUD_BLOCKED_EVENT_TYPES or error_code in {"privacy_blocked", "budget_exceeded"}:
            blocked_count += 1
            if item is not None:
                item["blocked_count"] += 1
        if event_type == "provider_missing" or error_code == "cloud_provider_missing":
            missing_provider_count += 1
            fallback_count += 1
            if item is not None:
                item["missing_provider_count"] += 1
                item["fallback_count"] += 1
        elif event_type == "provider_error":
            provider_error_count += 1
            fallback_count += 1
            if item is not None:
                item["provider_error_count"] += 1
                item["fallback_count"] += 1
        elif status == "error" and error_code not in CLOUD_INVALID_CONTRACT_CODES:
            fallback_count += 1
            if item is not None:
                item["fallback_count"] += 1
        payload_validation_errors = _validation_error_count(payload)
        if (
            event_type in CLOUD_INVALID_CONTRACT_EVENT_TYPES
            or error_code in CLOUD_INVALID_CONTRACT_CODES
            or payload_validation_errors > 0
        ):
            invalid_contract_count += 1
            if item is not None:
                item["invalid_contract_count"] += 1
        validation_error_count += payload_validation_errors
        if severity == "error" or status == "error":
            error_count += 1
            if item is not None:
                item["error_count"] += 1
        if item is not None and status and status not in item["statuses"]:
            item["statuses"].append(status)
        if error_code:
            if error_code not in error_codes:
                error_codes.append(error_code)
            if item is not None and error_code not in item["error_codes"]:
                item["error_codes"].append(error_code)
        latency_ms = _to_int_or_none(payload.get("latency_ms"))
        if latency_ms is not None:
            latencies.append(latency_ms)
            if item is not None:
                current = item.get("max_latency_ms")
                item["max_latency_ms"] = latency_ms if current is None else max(int(current), latency_ms)
        if status and status not in statuses:
            statuses.append(status)
    return {
        "bundle_count": bundle_count,
        "result_count": result_count,
        "success_count": success_count,
        "blocked_count": blocked_count,
        "fallback_count": fallback_count,
        "provider_error_count": provider_error_count,
        "missing_provider_count": missing_provider_count,
        "invalid_contract_count": invalid_contract_count,
        "validation_error_count": validation_error_count,
        "error_count": error_count,
        "statuses": statuses,
        "error_codes": error_codes,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "max_latency_ms": max(latencies) if latencies else None,
        "by_skill": {name: by_skill[name] for name in sorted(by_skill) if not cloud_skill_names or name in cloud_skill_names},
    }


def _hud_summary(hud_scenes: list[dict[str, Any]], *, skill_names: list[str], generated_at: str) -> dict[str, Any]:
    valid = []
    invalid = 0
    skill_chip_matches = 0
    latest_age_ms = None
    for scene in hud_scenes:
        if not isinstance(scene, dict) or validate_hud_scene(scene):
            invalid += 1
            continue
        valid.append(scene)
        chips = scene.get("edge_chips") if isinstance(scene.get("edge_chips"), list) else []
        if any(name in chips for name in skill_names):
            skill_chip_matches += 1
    latest = _latest_scene(valid)
    if latest:
        latest_age_ms = _age_ms(latest.get("created_at"), generated_at)
    return {
        "valid_scene_count": len(valid),
        "invalid_scene_count": invalid,
        "skill_chip_match_count": skill_chip_matches,
        "latest_scene_age_ms": latest_age_ms,
    }


def _identity_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    confirmed = 0
    low_quality = 0
    error_count = 0
    provider_statuses: list[str] = []
    for event in events:
        payload = _payload(event)
        status = str(payload.get("provider_status") or "").strip()
        if status and status not in provider_statuses:
            provider_statuses.append(status)
        if status == "confirmed" or _to_int(payload.get("match_count")) > 0:
            confirmed += 1
        if status == "low_quality_face" or _to_int(payload.get("low_quality_candidate_count")) > 0:
            low_quality += 1
        if status in {"error", "provider_error"} or event.get("severity") == "error":
            error_count += 1
    return {
        "check_count": len(events),
        "confirmed_count": confirmed,
        "low_quality_count": low_quality,
        "error_count": error_count,
        "provider_statuses": provider_statuses,
    }


def _skill_runs(skill_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for event in skill_events[-24:]:
        payload = _payload(event)
        summary = payload.get("result_summary") if isinstance(payload.get("result_summary"), dict) else {}
        runs.append(
            {
                "event_id": event.get("event_id"),
                "name": payload.get("name"),
                "status": payload.get("status"),
                "duration_ms": payload.get("duration_ms"),
                "args_summary": payload.get("args_summary") if isinstance(payload.get("args_summary"), dict) else {},
                "result_summary": summary,
                "error": payload.get("error") if isinstance(payload.get("error"), dict) else None,
            }
        )
    return runs


def _top_failures(gates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for name, gate in gates.items():
        if gate["status"] == "fail" or (gate["required"] and gate["status"] == "warn"):
            failures.append(
                {
                    "source": "skill_eval_gate",
                    "gate": name,
                    "status": gate["status"],
                    "message": gate["message"],
                    "observed": gate["observed"],
                }
            )
    return failures[:8]


def _overall_status(gates: dict[str, dict[str, Any]]) -> str:
    if any(gate["required"] and gate["status"] == "fail" for gate in gates.values()):
        return "fail"
    if any(gate["status"] == "fail" for gate in gates.values()):
        return "warn"
    if any(gate["status"] == "warn" for gate in gates.values()):
        return "warn"
    return "pass"


def _score_gates(gates: dict[str, dict[str, Any]]) -> float:
    values = {"pass": 1.0, "warn": 0.5, "fail": 0.0}
    return round(sum(values.get(gate["status"], 0.0) for gate in gates.values()) / len(gates), 4) if gates else 0.0


def _count_tool_errors(events: list[dict[str, Any]]) -> int:
    count = 0
    for event in events:
        payload = _payload(event)
        event_type = str(event.get("event_type") or "")
        status = str(payload.get("status") or "")
        if event_type in {"call_failed", "tool_error"} or status == "error" or event.get("severity") == "error":
            count += 1
    return count


def _max_payload_int(events: list[dict[str, Any]], key: str) -> int | None:
    values = []
    for event in events:
        try:
            values.append(int(_payload(event).get(key)))
        except (TypeError, ValueError):
            continue
    return max(values) if values else None


def _to_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _to_int_or_none(value: Any) -> int | None:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _validation_error_count(payload: dict[str, Any]) -> int:
    value = payload.get("validation_error_count")
    count = _to_int_or_none(value)
    if count is not None:
        return count
    errors = payload.get("validation_errors")
    return len(errors) if isinstance(errors, list) else 0


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return payload


def _payload_string(event: dict[str, Any], key: str) -> str:
    return str(_payload(event).get(key) or "").strip()


def _list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _ordered_unique(values: Any) -> list[str]:
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in output:
            output.append(text)
    return output


def _latest_scene(scenes: list[dict[str, Any]]) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    latest_timestamp: datetime | None = None
    for scene in scenes:
        created_at = _parse_timestamp(scene.get("created_at"))
        if created_at and (latest_timestamp is None or created_at >= latest_timestamp):
            latest = scene
            latest_timestamp = created_at
    return latest or (scenes[-1] if scenes else None)


def _age_ms(start: Any, end: Any) -> int | None:
    start_time = _parse_timestamp(start)
    end_time = _parse_timestamp(end)
    if not start_time or not end_time:
        return None
    return max(0, int((end_time - start_time).total_seconds() * 1000))


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
