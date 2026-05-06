"""Concrete v2 skill executor backed by the perception graph."""

from __future__ import annotations

from collections.abc import Callable
import copy
import time
from typing import Any
import unicodedata

from .cloud_gateway import CloudGateway
from .contracts import new_id, utc_now
from .event_store import InMemoryEventStore
from .perception_graph import PerceptionGraph
from .skill_registry import SkillRegistry


PreviewStatusProvider = Callable[[str], dict[str, Any] | None]
DetectorStatusProvider = Callable[[], dict[str, Any]]
IdentityMatchProvider = Callable[..., dict[str, Any]]
PersonMemoryProvider = Callable[..., dict[str, Any]]
PersonProfileProvider = Callable[..., dict[str, Any]]


NAME_REMINDER_HOLD_MAX_AGE_S = 4.0
NAME_REMINDER_SWITCH_MIN_CONFIDENCE = 0.58
NAME_REMINDER_SWITCH_CONFIDENCE_MARGIN = 0.08


class SkillExecutor:
    def __init__(
        self,
        *,
        perception: PerceptionGraph,
        events: InMemoryEventStore,
        registry: SkillRegistry | None = None,
        cloud_gateway: CloudGateway | None = None,
        preview_status_provider: PreviewStatusProvider | None = None,
        detector_status_provider: DetectorStatusProvider | None = None,
        identity_match_provider: IdentityMatchProvider | None = None,
        person_memory_provider: PersonMemoryProvider | None = None,
        person_profile_provider: PersonProfileProvider | None = None,
    ) -> None:
        self._perception = perception
        self._events = events
        self._registry = registry or SkillRegistry()
        self._cloud_gateway = cloud_gateway or CloudGateway(events=events)
        self._preview_status_provider = preview_status_provider
        self._detector_status_provider = detector_status_provider
        self._identity_match_provider = identity_match_provider
        self._person_memory_provider = person_memory_provider
        self._person_profile_provider = person_profile_provider
        self._selected_targets: dict[str, dict[str, Any]] = {}
        self._target_labels: dict[str, dict[str, dict[str, Any]]] = {}
        self._target_finder_last_good: dict[str, dict[str, Any]] = {}
        self._person_info_last_match: dict[str, dict[str, Any]] = {}

    def execute(self, *, name: str, args: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
        started_at = utc_now()
        started_s = time.perf_counter()
        definition = self._registry.get(name)
        if definition is None:
            result = {
                "status": "error",
                "error": {"code": "unknown_skill", "message": f"Unknown skill: {name}"},
            }
        else:
            validation_errors = self._registry.validate_args(name, args)
            if validation_errors:
                result = _invalid_args(validation_errors)
            elif name == "count_people":
                result = self._count_people(args=args, session_id=session_id)
            elif name == "object_counter":
                result = self._object_counter(args=args, session_id=session_id)
            elif name == "target_finder":
                result = self._target_finder(args=args, session_id=session_id)
            elif name == "remember_person":
                result = self._remember_person(args=args, session_id=session_id)
            elif name == "person_info":
                result = self._person_info(args=args, session_id=session_id)
            elif name == "search_targets":
                result = self._search_targets(args=args, session_id=session_id)
            elif name == "select_target":
                result = self._select_target(args=args, session_id=session_id)
            elif name == "clear_target":
                result = self._clear_target(session_id=session_id)
            elif name == "scene_describe":
                result = self._scene_describe(args=args, session_id=session_id)
            elif name == "query_scene":
                result = self._query_scene(args=args, session_id=session_id)
            elif name == "text_reader":
                result = self._text_reader(args=args, session_id=session_id)
            elif name == "analyze_selected_target":
                result = self._analyze_selected_target(args=args, session_id=session_id)
            else:
                result = {
                    "status": "error",
                    "error": {
                        "code": "skill_not_implemented",
                        "message": f"Skill manifest exists but no executor is wired: {name}",
                    },
                }
        payload = {
            "skill_call_id": new_id("skill"),
            "name": name,
            "args": args,
            "session_id": session_id,
            "status": result.get("status", "ok"),
            "result": result.get("result"),
            "error": result.get("error"),
            "created_at": started_at,
            "updated_at": utc_now(),
        }
        cloud_errors = self._cloud_gateway.validate_needs_cloud_payload(payload)
        if cloud_errors:
            payload["status"] = "error"
            payload["result"] = None
            payload["error"] = {
                "code": "invalid_cloud_escalation",
                "message": "Skill returned needs_cloud without a valid cloud evidence/result contract.",
                "details": cloud_errors,
            }
            payload["updated_at"] = utc_now()
        duration_ms = max(0, int((time.perf_counter() - started_s) * 1000))
        self._events.add(
            "skills",
            "executed",
            {
                "name": name,
                "status": payload["status"],
                "duration_ms": duration_ms,
                "args_summary": _skill_args_summary(args),
                "result_summary": _skill_result_summary(payload.get("result")),
                "error": _skill_error_summary(payload.get("error")),
            },
            session_id=session_id,
            severity="error" if payload["status"] == "error" else "info",
        )
        return payload

    def _count_people(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        snapshot = self._require_snapshot(session_id)
        if not snapshot:
            preview = self._require_preview(session_id)
            if preview:
                return _preview_without_local_detector(
                    message="Snapshot preview is available, but no local detector has published a perception snapshot.",
                    user_message="Đã chụp ảnh; chưa có detector để đếm người.",
                    answer_strip="Đã chụp ảnh; chưa đếm được",
                    preview=preview,
                    edge_chips=["camera", "detector_offline", "count_people"],
                )
            return _no_evidence("No perception snapshot is available for this session.")
        min_confidence = float(args.get("min_confidence", 0.25))
        people = [
            item
            for item in snapshot["objects"]
            if item["label"] in {"person", "people"} and float(item["confidence"]) >= min_confidence
        ]
        return {
            "status": "ok",
            "result": {
                "count": len(people),
                "confidence": _mean_confidence(people),
                "evidence": [item["object_id"] for item in people],
                "snapshot_id": snapshot["snapshot_id"],
                "hud": {"answer_strip": f"{len(people)} người"},
            },
        }

    def _remember_person(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        display_name = str(args.get("display_name") or "").strip()
        aliases = [str(item).strip() for item in args.get("aliases") or [] if str(item).strip()]
        notes = str(args.get("notes") or "").strip()
        enroll_identity = bool(args.get("enroll_identity", bool(display_name)))
        if not session_id:
            return {
                "status": "error",
                "error": {"code": "missing_session", "message": "remember_person requires an active session."},
            }
        preview = self._require_preview(session_id)
        if not preview:
            return _no_evidence("No snapshot preview is available for person memory.")
        if not self._person_memory_provider:
            return {
                "status": "error",
                "error": {
                    "code": "person_memory_provider_unavailable",
                    "message": "People Registry / Immich memory provider is not wired.",
                },
            }
        try:
            memory = dict(
                self._person_memory_provider(
                    session_id=session_id,
                    display_name=display_name or None,
                    aliases=aliases,
                    notes=notes or None,
                    enroll_identity=enroll_identity,
                )
            )
        except Exception as exc:
            memory = {
                "status": "memory_failed",
                "message": f"Person memory provider failed: {exc.__class__.__name__}",
            }
        status = str(memory.get("status") or "")
        identity = memory.get("identity_enrollment") if isinstance(memory.get("identity_enrollment"), dict) else {}
        identity_status = str(identity.get("status") or "")
        if status == "uploaded":
            if display_name and identity_status == "enrolled":
                answer = f"Đã ghi nhớ {display_name} vào Immich và mẫu local."
                chips = ["remember_person", "immich", "identity"]
            elif display_name:
                answer = f"Đã lưu ảnh {display_name} vào Immich."
                chips = ["remember_person", "immich", "face_sync_pending"]
            else:
                answer = "Đã lưu ảnh người này vào Immich."
                chips = ["remember_person", "immich", "face_sync_pending"]
        elif status == "immich_unconfigured":
            answer = "Immich chưa cấu hình; chưa lưu ảnh."
            chips = ["remember_person", "immich_unconfigured"]
        elif status == "upload_failed":
            answer = "Upload Immich lỗi; chưa ghi nhớ được."
            chips = ["remember_person", "immich_error"]
        else:
            answer = "Chưa ghi nhớ được người này."
            chips = ["remember_person", "memory_error"]
        return {
            "status": "ok",
            "result": {
                "summary": str(memory.get("message") or answer),
                "answer": answer,
                "user_message": answer,
                "memory": memory,
                "preview": preview,
                "hud": {
                    "answer_strip": answer,
                    "edge_chips": chips,
                    "ttl_ms": 5000,
                },
            },
        }

    def _person_info(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        query = str(args.get("question") or args.get("query") or "người này tôi đã gặp chưa").strip()
        info_focus = _person_info_focus(query=query, explicit=args.get("info_focus"))
        identity_query = _person_info_identity_query(query)
        scan_mode = str(args.get("scan_mode") or "snapshot").strip().lower() or "snapshot"
        name_reminder = scan_mode in {"name_reminder", "realtime_names"}
        max_candidates = max(1, min(int(args.get("max_candidates") or 4), 8))
        snapshot = self._require_snapshot(session_id)
        if not snapshot:
            preview = self._require_preview(session_id)
            if preview:
                return _person_info_waiting_for_face(
                    query=query,
                    preview=preview,
                    detector_status=self._detector_status(),
                )
            cached = self._held_person_info_match(session_id=session_id, query=query, info_focus=info_focus)
            if cached:
                return cached
            return _no_evidence("No perception snapshot or live preview is available for known-person lookup.")

        objects = [item for item in snapshot.get("objects") or [] if isinstance(item, dict)]
        people = [item for item in objects if str(item.get("label") or "") in {"person", "people"}]
        candidates = [
            _target_finder_candidate(
                item,
                index=index,
                snapshot=snapshot,
                query=query,
                zoom_if_far=False,
            )
            for index, item in enumerate(people[:max_candidates], start=1)
        ]
        identity_provider = self._match_contact_identity(
            candidates=candidates,
            query=identity_query,
            session_id=session_id,
            enabled=True,
        )
        _apply_identity_provider_matches(candidates=candidates, identity_provider=identity_provider)
        identity_policy = _identity_policy_for_query(
            query,
            target_type="person",
            identity_provider=identity_provider,
            requested=True,
            optional=False,
        )
        self._events.add(
            "skills",
            "person_info_identity_checked",
            {
                "query": query,
                "identity_query": identity_query,
                "info_focus": info_focus,
                "scan_mode": scan_mode,
                "provider_status": identity_provider.get("status"),
                "provider": identity_provider.get("provider"),
                "candidate_count": len(candidates),
                "candidate_vector_count": identity_provider.get("candidate_vector_count"),
                "low_quality_candidate_count": identity_provider.get("low_quality_candidate_count"),
                "quality_reasons": identity_provider.get("quality_reasons"),
                "best_score": identity_provider.get("best_score"),
                "best_match": identity_provider.get("best_match"),
                "requested_contact_count": identity_provider.get("requested_contact_count"),
                "match_count": identity_provider.get("match_count"),
                "identity_policy_status": identity_policy.get("status"),
            },
            session_id=session_id,
            severity="info",
        )

        matches = identity_provider.get("matches") if isinstance(identity_provider.get("matches"), list) else []
        selected_match = _person_info_best_match(matches)
        selected = _person_info_candidate_for_match(candidates, selected_match) or (
            _select_guidance_candidate(candidates, identity_policy=identity_policy) if candidates else None
        )
        thumbnails = [_candidate_thumbnail(candidate, index=index) for index, candidate in enumerate(candidates, start=1)]
        detector_status = _target_finder_detector_status(snapshot=snapshot, adapter_status=self._detector_status())
        known_people = self._person_info_known_people(
            matches=matches,
            candidates=candidates,
            session_id=session_id,
        )

        if name_reminder and selected_match:
            cached = self._held_person_info_match(
                session_id=session_id,
                query=query,
                info_focus=info_focus,
                name_reminder=True,
                max_age_s=NAME_REMINDER_HOLD_MAX_AGE_S,
            )
            if cached and _name_reminder_should_hold_cached_match(
                selected_match=selected_match,
                cached_response=cached,
            ):
                return cached
            if not _name_reminder_match_is_displayable(
                selected_match=selected_match,
                cached_response=cached,
            ):
                if cached:
                    return cached
                return _person_info_name_reminder_uncertain(
                    query=query,
                    identity_query=identity_query,
                    info_focus=info_focus,
                    scan_mode=scan_mode,
                    identity_policy=identity_policy,
                    identity_provider=identity_provider,
                    candidates=candidates,
                    thumbnails=thumbnails,
                    detector_status=detector_status,
                    snapshot_id=snapshot.get("snapshot_id"),
                    selected=selected,
                )

        if len(candidates) > 1 and not name_reminder:
            if known_people:
                names = [str(item.get("display_name") or "").strip() for item in known_people if item.get("display_name")]
                shown_names = ", ".join(names[:3])
                answer = f"Thấy {len(candidates)} người; nhận ra {shown_names}. Bạn muốn hỏi ai?"
                chips = ["person_info", "snapshot", "multi_face", "known_person", "choose_person"]
            else:
                answer = f"Thấy {len(candidates)} người, nhưng chưa nhận ra ai trong DB."
                chips = ["person_info", "snapshot", "multi_face", "unknown_person"]
            result = {
                "status": "ok",
                "result": {
                    "answer": answer,
                    "user_message": answer,
                    "query": query,
                    "identity_query": identity_query,
                    "info_focus": info_focus,
                    "scan_mode": scan_mode,
                    "known_person": bool(known_people),
                    "known_people": known_people,
                    "identity_policy": identity_policy,
                    "identity_provider": identity_provider,
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                    "detector_status": detector_status,
                    "snapshot_id": snapshot.get("snapshot_id"),
                    "hud": {
                        "answer_strip": _short_text(answer, max_chars=96),
                        "edge_chips": chips,
                        "thumbnails": thumbnails,
                        "target_hint": _person_info_selection_hint(candidates=candidates, known_people=known_people),
                        "ttl_ms": 9000,
                    },
                },
            }
            return result

        if selected_match and selected:
            profile = self._lookup_person_profile(match=selected_match, candidate=selected, session_id=session_id)
            answer = _person_info_answer(
                display_name=str(selected_match.get("display_name") or selected.get("display_name") or "người này"),
                identity_confidence=selected_match.get("confidence"),
                profile=profile,
                info_focus=info_focus,
                name_reminder=name_reminder,
                prompt_followup=not name_reminder and scan_mode == "snapshot" and info_focus == "name",
            )
            result = {
                "status": "ok",
                "result": {
                    "answer": answer,
                    "user_message": answer,
                    "query": query,
                    "identity_query": identity_query,
                    "info_focus": info_focus,
                    "scan_mode": scan_mode,
                    "known_person": True,
                    "known_people": known_people,
                    "identity_policy": identity_policy,
                    "identity_provider": identity_provider,
                    "identity_match": selected_match,
                    "profile": profile,
                    "candidate_count": len(candidates),
                    "selected_candidate_id": selected.get("target_id"),
                    "candidates": candidates,
                    "detector_status": detector_status,
                    "snapshot_id": snapshot.get("snapshot_id"),
                    "hud": {
                        "answer_strip": answer,
                        "edge_chips": [
                            "person_info",
                            "name_reminder" if name_reminder else "snapshot",
                            "known_person",
                            "contact_db",
                            *_person_info_profile_chips(profile),
                        ],
                        "thumbnails": thumbnails,
                        "target_hint": _person_info_target_hint(selected, selected_match),
                        "ttl_ms": 6500,
                    },
                },
            }
            self._remember_person_info_match(session_id=session_id, query=query, response=result)
            return result

        provider_status = str(identity_provider.get("status") or "")
        if name_reminder and provider_status in {"no_match", "no_candidate_vectors", ""}:
            cached = self._held_person_info_match(
                session_id=session_id,
                query=query,
                info_focus=info_focus,
                name_reminder=True,
                max_age_s=NAME_REMINDER_HOLD_MAX_AGE_S,
            )
            if cached and (
                provider_status in {"no_candidate_vectors", ""}
                or _identity_provider_best_match_matches_cached(identity_provider, cached)
            ):
                return cached
        if provider_status == "low_quality_face":
            answer = _identity_quality_user_hint(
                identity_provider,
                default="Có thấy mặt, nhưng chưa đủ rõ; lại gần hoặc đổi góc một chút.",
            )
            chips = ["person_info", "face_quality", *_identity_quality_chips(identity_provider)]
        elif provider_status == "no_samples":
            answer = "DB khuôn mặt chưa có mẫu đã enroll, nên chưa biết người này."
            chips = ["person_info", "identity_empty"]
        elif provider_status in {"no_candidate_vectors", ""} and candidates:
            answer = "Đang thấy người, nhưng chưa có vector mặt đủ để so DB."
            chips = ["person_info", "face_wait"]
        elif candidates:
            answer = "Mình chưa nhận ra người này trong DB quen biết."
            chips = ["person_info", "unknown_person"]
        else:
            cached = self._held_person_info_match(session_id=session_id, query=query, info_focus=info_focus)
            if cached:
                return cached
            answer = "Chưa thấy khuôn mặt nào đủ rõ để kiểm tra."
            chips = ["person_info", "no_face"]
        return {
            "status": "ok",
            "result": {
                "answer": answer,
                "user_message": answer,
                "query": query,
                "identity_query": identity_query,
                "info_focus": info_focus,
                "scan_mode": scan_mode,
                "known_person": False,
                "known_people": [],
                "identity_policy": identity_policy,
                "identity_provider": identity_provider,
                "candidate_count": len(candidates),
                "candidates": candidates,
                "detector_status": detector_status,
                "snapshot_id": snapshot.get("snapshot_id"),
                "hud": {
                    "answer_strip": answer,
                    "edge_chips": chips,
                    "thumbnails": thumbnails,
                    "target_hint": _person_info_target_hint(selected, None) if selected else None,
                    "ttl_ms": 5000,
                },
            },
        }

    def _lookup_person_profile(
        self,
        *,
        match: dict[str, Any],
        candidate: dict[str, Any],
        session_id: str | None,
    ) -> dict[str, Any]:
        if not self._person_profile_provider:
            return {
                "status": "unavailable",
                "message": "People Registry profile provider is not wired.",
            }
        try:
            return dict(
                self._person_profile_provider(
                    identity_match=match,
                    display_name=match.get("display_name") or candidate.get("display_name"),
                    aliases=[str(match.get("alias"))] if match.get("alias") else [],
                    session_id=session_id,
                )
            )
        except Exception as exc:
            return {
                "status": "error",
                "message": f"People Registry profile lookup failed: {exc.__class__.__name__}",
            }

    def _person_info_known_people(
        self,
        *,
        matches: list[Any],
        candidates: list[dict[str, Any]],
        session_id: str | None,
    ) -> list[dict[str, Any]]:
        people: list[dict[str, Any]] = []
        for match in [item for item in matches if isinstance(item, dict)]:
            candidate = _person_info_candidate_for_match(candidates, match)
            if not candidate:
                continue
            profile = self._lookup_person_profile(match=match, candidate=candidate, session_id=session_id)
            people.append(
                {
                    "display_name": match.get("display_name") or candidate.get("display_name"),
                    "contact_id": match.get("contact_id") or candidate.get("contact_id"),
                    "confidence": match.get("confidence") or candidate.get("identity_confidence"),
                    "candidate_id": candidate.get("target_id"),
                    "track_id": candidate.get("track_id"),
                    "anonymous_id": candidate.get("anonymous_id"),
                    "thumbnail_id": candidate.get("target_id"),
                    "crop_ref": candidate.get("crop_ref"),
                    "profile": profile,
                }
            )
        return people

    def _remember_person_info_match(
        self,
        *,
        session_id: str | None,
        query: str,
        response: dict[str, Any],
    ) -> None:
        if not session_id:
            return
        self._person_info_last_match[session_id] = {
            "stored_s": time.monotonic(),
            "query": _normalize_identity_text(query),
            "response": copy.deepcopy(response),
        }

    def _held_person_info_match(
        self,
        *,
        session_id: str | None,
        query: str,
        info_focus: str,
        name_reminder: bool = False,
        max_age_s: float = 20.0,
    ) -> dict[str, Any] | None:
        if not session_id:
            return None
        cached = self._person_info_last_match.get(session_id)
        if not cached:
            return None
        age_s = time.monotonic() - float(cached.get("stored_s") or 0.0)
        if age_s > max_age_s:
            return None
        held = copy.deepcopy(cached.get("response") or {})
        result = held.get("result") if isinstance(held.get("result"), dict) else {}
        match = result.get("identity_match") if isinstance(result.get("identity_match"), dict) else {}
        profile = result.get("profile") if isinstance(result.get("profile"), dict) else {}
        if match:
            answer = _person_info_answer(
                display_name=str(match.get("display_name") or "người này"),
                identity_confidence=match.get("confidence"),
                profile=profile,
                info_focus=info_focus,
                name_reminder=name_reminder,
            )
            result["answer"] = answer
            result["user_message"] = answer
            result["info_focus"] = info_focus
            result["held_context"] = {"status": "using_last_known_person", "age_ms": int(age_s * 1000), "query": query}
            hud = result.get("hud") if isinstance(result.get("hud"), dict) else {}
            if hud:
                hud["answer_strip"] = answer
                chips = [str(chip) for chip in hud.get("edge_chips") or []]
                if "held_context" not in chips:
                    chips.append("held_context")
                hud["edge_chips"] = chips
                hud["ttl_ms"] = max(int(hud.get("ttl_ms") or 0), 5000)
            return held
        return None

    def _object_counter(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        question = str(args.get("question") or "đếm đồ vật trong ảnh").strip()
        target = str(args.get("target") or "").strip() or _count_target_from_question(question)
        snapshot = self._require_snapshot(session_id)
        if snapshot and snapshot.get("objects"):
            return self._object_counter_from_snapshot(snapshot=snapshot, question=question, target=target)
        preview = self._require_preview(session_id)
        if preview:
            return self._object_counter_from_preview(
                args=args,
                session_id=session_id,
                preview=preview,
                question=question,
                target=target,
            )
        return _no_evidence("No perception snapshot or preview frame is available for object counting.")

    def _object_counter_from_snapshot(
        self,
        *,
        snapshot: dict[str, Any],
        question: str,
        target: str | None,
    ) -> dict[str, Any]:
        objects = [item for item in snapshot.get("objects") or [] if isinstance(item, dict)]
        matched = _matching_objects(objects, target)
        count = len(matched)
        label = target or "đối tượng"
        answer = f"Có {count} {label}." if target else f"Có {count} đối tượng đã phát hiện."
        return {
            "status": "ok",
            "result": {
                "answer": answer,
                "user_message": answer,
                "count": count,
                "target": target,
                "question": question,
                "confidence": _mean_confidence(matched),
                "evidence": [str(item.get("object_id")) for item in matched if item.get("object_id")],
                "snapshot_id": snapshot.get("snapshot_id"),
                "hud": {
                    "answer_strip": answer,
                    "edge_chips": ["object_counter", "local_count"],
                    "ttl_ms": 5000,
                },
            },
        }

    def _object_counter_from_preview(
        self,
        *,
        args: dict[str, Any],
        session_id: str | None,
        preview: dict[str, Any],
        question: str,
        target: str | None,
    ) -> dict[str, Any]:
        frame_ref = preview.get("image_url") if isinstance(preview.get("image_url"), str) else None
        frame_refs = [frame_ref] if frame_ref else []
        cloud_evidence_bundle = self._cloud_gateway.build_evidence_bundle(
            session_id=session_id or "",
            skill_id="object_counter",
            user_query=question,
            local_summary={
                "task": "count_visible_objects",
                "target": target,
                "approximate_ok": bool(args.get("approximate_ok", True)),
                "evidence": "client_snapshot_preview",
                "preview_source": preview.get("source"),
                "width": preview.get("width"),
                "height": preview.get("height"),
                "frame_count": preview.get("frame_count"),
                "uncertainty": "arbitrary object counting requires cloud visual verification when detector is missing",
            },
            frame_refs=frame_refs,
            candidates=[],
            contains_face=False,
            allow_cloud=True,
            store_result=False,
            privacy_level="medium",
            max_answer_chars=80,
        )
        cloud_gateway = self._cloud_gateway.request_verification(cloud_evidence_bundle)
        cloud_result = cloud_gateway["cloud_result"]
        user_message = _scene_cloud_user_message(cloud_result)
        return {
            "status": "needs_cloud",
            "result": {
                "answer": user_message,
                "user_message": user_message,
                "count": None,
                "target": target,
                "question": question,
                "summary": "Snapshot preview captured; arbitrary object counting uses the cloud gateway until a local detector is available.",
                "evidence": frame_refs,
                "preview": preview,
                "cloud_evidence_bundle": cloud_evidence_bundle,
                "cloud_gateway": cloud_gateway,
                "cloud_result": cloud_result,
                "hud": {
                    "answer_strip": user_message,
                    "edge_chips": ["object_counter", "snapshot", *_cloud_edge_chips(cloud_result)],
                    "ttl_ms": 5000,
                },
            },
        }

    def _target_finder(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        raw_query = str(args.get("query") or "tìm mục tiêu").strip()
        target_name = str(args.get("target_name") or "").strip()
        query = _target_finder_effective_query(raw_query, target_name=target_name)
        target_type = str(args.get("target_type") or "person").strip().lower()
        max_candidates = max(1, min(int(args.get("max_candidates") or 6), 8))
        snapshot = self._require_snapshot(session_id)
        explicit_identity_requested = bool(args.get("identity_query")) or bool(target_name) or _identity_requested(
            query,
            target_type=target_type,
        )
        opportunistic_identity = _opportunistic_identity_scan(query, target_type=target_type)
        identity_requested = explicit_identity_requested or opportunistic_identity
        identity_optional = identity_requested and not explicit_identity_requested
        identity_policy = _identity_policy_for_query(
            query,
            target_type=target_type,
            requested=identity_requested,
            optional=identity_optional,
        )
        adapter_status = self._detector_status()
        if not snapshot:
            preview = self._require_preview(session_id)
            if preview:
                return _target_finder_waiting_for_detector(
                    query=query,
                    preview=preview,
                    identity_policy=identity_policy,
                    detector_status=adapter_status,
                )
            return _no_evidence("No perception snapshot or live preview is available for target finding.")
        detector_status = _target_finder_detector_status(
            snapshot=snapshot,
            adapter_status=adapter_status,
        )
        objects = [item for item in snapshot.get("objects") or [] if isinstance(item, dict)]
        objects = _target_finder_filter_objects(objects, query=query, target_type=target_type)
        candidates = [
            _target_finder_candidate(
                item,
                index=index,
                snapshot=snapshot,
                query=query,
                zoom_if_far=bool(args.get("zoom_if_far", True)),
            )
            for index, item in enumerate(objects[:max_candidates], start=1)
        ]
        self._apply_session_target_labels(candidates=candidates, session_id=session_id)
        identity_provider = self._match_contact_identity(
            candidates=candidates,
            query=query,
            session_id=session_id,
            enabled=identity_requested,
        )
        _apply_identity_provider_matches(candidates=candidates, identity_provider=identity_provider)
        identity_policy = _identity_policy_for_query(
            query,
            target_type=target_type,
            identity_provider=identity_provider,
            requested=identity_requested,
            optional=identity_optional,
        )
        self._events.add(
            "skills",
            "target_finder_identity_checked",
            {
                "query": query,
                "target_type": target_type,
                "identity_requested": identity_requested,
                "identity_optional": identity_optional,
                "provider_status": identity_provider.get("status"),
                "provider": identity_provider.get("provider"),
                "candidate_count": len(candidates),
                "candidate_vector_count": identity_provider.get("candidate_vector_count"),
                "low_quality_candidate_count": identity_provider.get("low_quality_candidate_count"),
                "quality_reasons": identity_provider.get("quality_reasons"),
                "best_score": identity_provider.get("best_score"),
                "best_match": identity_provider.get("best_match"),
                "min_identity_face_side_px": identity_provider.get("min_identity_face_side_px"),
                "requested_contact_count": identity_provider.get("requested_contact_count"),
                "match_count": identity_provider.get("match_count"),
                "identity_policy_status": identity_policy.get("status"),
            },
            session_id=session_id,
            severity="info",
        )
        manual_match = _manual_contact_match(candidates, query=query)
        if manual_match and identity_policy.get("status") != "contact_match_confirmed":
            identity_policy = {
                **identity_policy,
                "status": "manual_label_confirmed",
                "message": "Target name comes from a user-confirmed session label.",
                "contact_reminder_source": "session_manual_label",
            }
        if not candidates:
            held = self._held_target_finder_result(
                session_id=session_id,
                query=query,
                detector_status=detector_status,
                identity_policy=identity_policy,
                identity_provider=identity_provider,
            )
            if held:
                return held
        selected = _select_guidance_candidate(candidates, identity_policy=identity_policy) or manual_match
        target_hint = _target_finder_hud_hint(
            selected=selected,
            candidates=candidates,
            identity_policy=identity_policy,
            query=query,
        )
        thumbnails = [_candidate_thumbnail(candidate, index=index) for index, candidate in enumerate(candidates, start=1)]
        if not candidates:
            answer = "Chưa thấy ứng viên mục tiêu."
            chips = ["target_finder", "live", "no_candidate"]
        elif identity_policy["status"] == "contact_match_confirmed" and selected:
            name = str(selected.get("display_name") or selected.get("anonymous_id") or "mục tiêu")
            direction = _aim_user_text(selected.get("aim") if selected else None)
            answer = name if not direction else f"{name} · {direction}"
            chips = ["target_finder", "live", "contact_db", "aim_assist"]
        elif identity_policy["status"] in {"identity_lookup_low_quality", "identity_scan_low_quality"}:
            direction = _aim_user_text(selected.get("aim") if selected else None)
            answer = _identity_quality_user_hint(identity_provider, default="Mặt chưa đủ rõ; lại gần hoặc đổi góc.")
            if direction:
                answer = f"{answer} · {direction}"
            chips = ["target_finder", "live", "face_quality", *_identity_quality_chips(identity_provider), "aim_assist"]
        elif identity_policy["status"] in {"identity_lookup_no_match", "identity_lookup_unavailable"}:
            if identity_provider.get("status") == "no_requested_contact" and target_name:
                answer = f"Chưa có {target_name} trong DB; có {len(candidates)} ID."
            else:
                answer = f"Chưa khớp tên; có {len(candidates)} ID."
            chips = ["target_finder", "live", "anonymous_ids", "identity_setup"]
        elif identity_policy["status"] == "manual_confirmation_required":
            answer = f"{len(candidates)} người được đánh ID; cần bạn chọn ID."
            chips = ["target_finder", "live", "anonymous_ids", "manual_confirm"]
        elif identity_policy["status"] == "manual_label_confirmed" and selected:
            name = str(selected.get("display_name") or selected.get("anonymous_id") or "mục tiêu")
            direction = _aim_user_text(selected.get("aim") if selected else None)
            answer = f"{name}"
            if direction:
                answer = f"{answer} · {direction}"
            chips = ["target_finder", "live", "manual_label", "aim_assist"]
        elif str(identity_policy.get("status") or "").startswith("identity_scan_"):
            direction = _aim_user_text(selected.get("aim") if selected else None)
            answer = f"{len(candidates)} ứng viên"
            if direction:
                answer = f"{answer} · {direction}"
            chips = ["target_finder", "live", "identity_scan", "aim_assist"]
        else:
            direction = _aim_user_text(selected.get("aim") if selected else None)
            answer = f"{len(candidates)} ứng viên"
            if direction:
                answer = f"{answer} · {direction}"
            chips = ["target_finder", "live", "aim_assist"]
        if detector_status.get("has_yolo26_stream"):
            chips = [*chips, "yolo26"]
        if detector_status.get("has_face_identity_stream"):
            chips = [*chips, "face_id"]
        summary = _target_finder_summary(detector_status=detector_status)
        response = {
            "status": "ok",
            "result": {
                "summary": summary,
                "answer": answer,
                "user_message": answer,
                "query": query,
                "raw_query": raw_query,
                "target_name": target_name or None,
                "candidate_count": len(candidates),
                "confirmed_match_count": _target_finder_confirmed_count(
                    candidates,
                    identity_policy=identity_policy,
                ),
                "candidate_semantics": (
                    "contact_identity_candidates"
                    if identity_policy.get("status") == "contact_match_confirmed"
                    else "anonymous_candidates"
                ),
                "detector_status": detector_status,
                "selected_candidate_id": selected.get("target_id") if selected else None,
                "identity_policy": identity_policy,
                "identity_provider": identity_provider,
                "candidates": candidates,
                "target_hint": target_hint,
                "snapshot_id": snapshot.get("snapshot_id"),
                "hud": {
                    "answer_strip": answer,
                    "edge_chips": chips,
                    "thumbnails": thumbnails,
                    "target_hint": target_hint,
                    "priority": "high" if candidates else "normal",
                    "ttl_ms": 3000,
                },
            },
        }
        if candidates:
            self._remember_target_finder_result(session_id=session_id, query=query, response=response)
        return response

    def _remember_target_finder_result(
        self,
        *,
        session_id: str | None,
        query: str,
        response: dict[str, Any],
    ) -> None:
        if not session_id:
            return
        self._target_finder_last_good[session_id] = {
            "stored_s": time.monotonic(),
            "query": _normalize_identity_text(query),
            "response": copy.deepcopy(response),
        }

    def _held_target_finder_result(
        self,
        *,
        session_id: str | None,
        query: str,
        detector_status: dict[str, Any],
        identity_policy: dict[str, Any],
        identity_provider: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not session_id:
            return None
        cached = self._target_finder_last_good.get(session_id)
        if not cached:
            return None
        if _normalize_identity_text(query) != cached.get("query"):
            return None
        age_s = time.monotonic() - float(cached.get("stored_s") or 0.0)
        if age_s > 1.8:
            return None
        held = copy.deepcopy(cached.get("response") or {})
        result = held.get("result") if isinstance(held.get("result"), dict) else {}
        hud = result.get("hud") if isinstance(result.get("hud"), dict) else {}
        result["detector_status"] = detector_status
        result["identity_policy"] = identity_policy
        result["identity_provider"] = identity_provider
        result["target_hold"] = {
            "status": "holding_last_good_target",
            "age_ms": int(age_s * 1000),
            "reason": "Current face/perception frame had no candidates.",
        }
        if hud:
            chips = [str(chip) for chip in hud.get("edge_chips") or []]
            if "hold" not in chips:
                chips.append("hold")
            hud["edge_chips"] = chips
            hud["ttl_ms"] = max(int(hud.get("ttl_ms") or 0), 1200)
        return held

    def _detector_status(self) -> dict[str, Any]:
        if not self._detector_status_provider:
            return {
                "name": "yolo26_rokid",
                "status": "unknown",
                "mode": "unknown",
                "stream_ingest_enabled": False,
                "message": "Detector adapter status provider is not wired.",
            }
        try:
            return dict(self._detector_status_provider())
        except Exception as exc:
            return {
                "name": "yolo26_rokid",
                "status": "error",
                "mode": "unknown",
                "stream_ingest_enabled": False,
                "message": f"Detector adapter status unavailable: {exc.__class__.__name__}",
            }

    def _match_contact_identity(
        self,
        *,
        candidates: list[dict[str, Any]],
        query: str,
        session_id: str | None,
        enabled: bool,
    ) -> dict[str, Any]:
        if not enabled:
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "not_requested",
                "provider": "none",
                "match_count": 0,
                "matches": [],
            }
        if not self._identity_match_provider:
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "unavailable",
                "provider": "none",
                "match_count": 0,
                "matches": [],
                "message": "Local contact identity provider is not wired.",
            }
        try:
            return dict(
                self._identity_match_provider(
                    candidates=candidates,
                    query=query,
                    session_id=session_id,
                )
            )
        except Exception as exc:
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "error",
                "provider": "openvision_local_contact_identity",
                "match_count": 0,
                "matches": [],
                "message": f"Local contact identity provider failed: {exc.__class__.__name__}",
            }

    def _search_targets(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        snapshot = self._require_snapshot(session_id)
        if not snapshot:
            return _no_evidence("No perception snapshot is available for target search.")
        query = str(args.get("query") or "").lower()
        max_candidates = int(args.get("max_candidates") or 6)
        person_query = any(token in query for token in ("người", "person", "áo", "mặc", "đứng", "ngồi"))
        requires_cloud = _requires_cloud_attribute_resolution(query)
        objects = snapshot["objects"]
        if person_query:
            objects = [item for item in objects if item["label"] in {"person", "people"}]
        candidates = [
            {
                "target_id": item["object_id"],
                "label": item["label"],
                "confidence": item["confidence"],
                "bbox": item.get("bbox"),
                "track_id": item.get("track_id"),
                "zone": item.get("zone"),
                "attributes": item.get("attributes") if isinstance(item.get("attributes"), dict) else {},
                "crop_ref": item.get("crop_ref"),
                "match_status": "unverified_attribute_candidate" if requires_cloud else "label_match",
                "cloud_attribute_resolution": "required" if requires_cloud else "not_requested",
            }
            for item in objects[:max_candidates]
        ]
        cloud_gateway: dict[str, Any] | None = None
        cloud_result: dict[str, Any] | None = None
        cloud_evidence_bundle: dict[str, Any] | None = None
        thumbnails = [_candidate_thumbnail(candidate, index=index) for index, candidate in enumerate(candidates, start=1)]
        if requires_cloud:
            user_message = f"{len(candidates)} ứng viên người; chưa xác minh thuộc tính cần tìm."
            summary = (
                f"{len(candidates)} unverified candidates; cloud attribute resolution is required "
                "before confirming the requested visual attributes."
            )
            cloud_evidence_bundle = self._cloud_gateway.build_evidence_bundle(
                session_id=session_id or "",
                skill_id="search_targets",
                user_query=str(args.get("query") or ""),
                local_summary={
                    "candidate_count": len(candidates),
                    "uncertainty": "visual attributes require cloud verification",
                    "snapshot_id": snapshot["snapshot_id"],
                },
                candidates=[_cloud_candidate(candidate) for candidate in candidates],
                crop_refs=[str(candidate["crop_ref"]) for candidate in candidates if candidate.get("crop_ref")],
                contains_face=any(candidate.get("label") in {"person", "people"} for candidate in candidates),
                allow_cloud=True,
                store_result=False,
                privacy_level="medium",
            )
            cloud_gateway = self._cloud_gateway.request_verification(cloud_evidence_bundle)
            cloud_result = cloud_gateway["cloud_result"]
            hud = {
                "answer_strip": user_message,
                "edge_chips": _cloud_edge_chips(cloud_result),
                "thumbnail_count": len(candidates),
                "thumbnails": thumbnails,
            }
        else:
            user_message = f"{len(candidates)} ứng viên"
            summary = f"{len(candidates)} label candidates"
            hud = {"thumbnail_count": len(candidates), "thumbnails": thumbnails}
        return {
            "status": "needs_cloud" if requires_cloud else "ok",
            "result": {
                "user_message": user_message,
                "summary": summary,
                "candidates": candidates,
                "candidate_count": len(candidates),
                "confirmed_match_count": 0 if requires_cloud else len(candidates),
                "candidate_semantics": "unverified_attribute_candidates" if requires_cloud else "label_matches",
                "cloud_attribute_resolution": "required" if requires_cloud else "not_requested",
                "cloud_evidence_bundle": cloud_evidence_bundle,
                "cloud_gateway": cloud_gateway,
                "cloud_result": cloud_result,
                "snapshot_id": snapshot["snapshot_id"],
                "hud": hud,
            },
        }

    def _select_target(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        target_id = str(args.get("target_id") or "").strip()
        if not target_id:
            return {"status": "error", "error": {"code": "missing_target_id", "message": "target_id is required"}}
        reason = str(args.get("reason") or "")
        display_name = str(args.get("display_name") or "").strip()
        contact_note = str(args.get("contact_note") or "").strip()
        selected = {
            "target_id": target_id,
            "reason": reason,
            "selected_at": utc_now(),
        }
        if display_name:
            selected["display_name"] = display_name
        if contact_note:
            selected["contact_note"] = contact_note
        if session_id:
            self._selected_targets[session_id] = selected
            if display_name:
                self._target_labels.setdefault(session_id, {})[target_id] = {
                    "display_name": display_name,
                    "contact_note": contact_note,
                    "source": "user_confirmed_session_label",
                    "created_at": selected["selected_at"],
                }
        hud_hint = {
            "target_id": target_id,
            "status": "selected",
            "reason": reason,
        }
        if display_name:
            hud_hint["display_name"] = display_name
        return {
            "status": "ok",
            "result": {
                "selected_target": selected,
                "hud_hint": hud_hint,
                "hud": {
                    "answer_strip": f"Đã chọn {display_name}" if display_name else "Đã chọn mục tiêu",
                    "edge_chips": ["target", "manual_label"] if display_name else ["target"],
                    "target_hint": hud_hint,
                    "ttl_ms": 5000,
                },
            },
        }

    def _clear_target(self, *, session_id: str | None) -> dict[str, Any]:
        if session_id:
            self._selected_targets.pop(session_id, None)
        return {
            "status": "ok",
            "result": {
                "cleared": True,
                "hud": {
                    "answer_strip": "Đã bỏ chọn mục tiêu",
                    "edge_chips": ["target_clear"],
                    "ttl_ms": 1500,
                },
            },
        }

    def _scene_describe(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        focus = str(args.get("focus") or "mô tả cảnh trước mặt").strip()
        return self._query_scene(
            args={"question": focus},
            session_id=session_id,
            skill_id="scene_describe",
        )

    def _query_scene(
        self,
        *,
        args: dict[str, Any],
        session_id: str | None,
        skill_id: str = "query_scene",
    ) -> dict[str, Any]:
        snapshot = self._require_snapshot(session_id)
        if not snapshot:
            preview = self._require_preview(session_id)
            if preview:
                return self._query_scene_from_preview(
                    args=args,
                    session_id=session_id,
                    preview=preview,
                    skill_id=skill_id,
                )
            return _no_evidence("No perception snapshot is available for scene query.")
        counts: dict[str, int] = {}
        for item in snapshot["objects"]:
            counts[item["label"]] = counts.get(item["label"], 0) + 1
        answer = ", ".join(f"{count} {label}" for label, count in sorted(counts.items())) or "No objects"
        return {
            "status": "ok",
            "result": {
                "answer": answer,
                "counts": counts,
                "snapshot_id": snapshot["snapshot_id"],
                "hud": {"answer_strip": answer},
            },
        }

    def _text_reader(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        question = str(args.get("question") or "đọc chữ trong ảnh").strip()
        snapshot = self._require_snapshot(session_id)
        preview = self._require_preview(session_id)
        if preview:
            return self._text_reader_from_preview(
                args=args,
                session_id=session_id,
                preview=preview,
                question=question,
                snapshot_id=str(snapshot.get("snapshot_id") or "") if snapshot else None,
            )
        return _no_evidence("No preview frame is available for OCR/text reading.")

    def _text_reader_from_preview(
        self,
        *,
        args: dict[str, Any],
        session_id: str | None,
        preview: dict[str, Any],
        question: str,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        frame_ref = preview.get("image_url") if isinstance(preview.get("image_url"), str) else None
        frame_refs = [frame_ref] if frame_ref else []
        cloud_evidence_bundle = self._cloud_gateway.build_evidence_bundle(
            session_id=session_id or "",
            skill_id="text_reader",
            user_query=question,
            local_summary={
                "task": "read_visible_text",
                "target_region": str(args.get("target_region") or "").strip() or None,
                "language_hint": str(args.get("language_hint") or "").strip() or "vi,en",
                "exact_text_required": bool(args.get("exact_text_required", True)),
                "evidence": "client_snapshot_preview",
                "preview_source": preview.get("source"),
                "width": preview.get("width"),
                "height": preview.get("height"),
                "frame_count": preview.get("frame_count"),
                "snapshot_id": snapshot_id,
                "uncertainty": "local OCR is not available, so text reading uses the cloud visual verifier",
            },
            frame_refs=frame_refs,
            candidates=[],
            contains_face=False,
            allow_cloud=True,
            store_result=False,
            privacy_level="medium",
            max_answer_chars=100,
        )
        cloud_gateway = self._cloud_gateway.request_verification(cloud_evidence_bundle)
        cloud_result = cloud_gateway["cloud_result"]
        user_message = _scene_cloud_user_message(cloud_result)
        return {
            "status": "needs_cloud",
            "result": {
                "answer": user_message,
                "user_message": user_message,
                "text": user_message if cloud_result.get("status") in {"ok", "uncertain"} else None,
                "lines": [],
                "question": question,
                "summary": "Snapshot preview captured; OCR uses the cloud gateway until a local text detector is available.",
                "evidence": frame_refs,
                "preview": preview,
                "cloud_evidence_bundle": cloud_evidence_bundle,
                "cloud_gateway": cloud_gateway,
                "cloud_result": cloud_result,
                "hud": {
                    "answer_strip": user_message,
                    "edge_chips": ["text_reader", "snapshot", *_cloud_edge_chips(cloud_result)],
                    "ttl_ms": 5000,
                },
            },
        }

    def _analyze_selected_target(self, *, args: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        selected = self._selected_targets.get(session_id or "")
        if not selected:
            return _no_evidence("No selected target is active.")
        snapshot = self._require_snapshot(session_id)
        target = _find_snapshot_target(snapshot, selected["target_id"]) if snapshot else None
        candidates = [_cloud_candidate_from_object(target)] if target else [{"candidate_id": selected["target_id"]}]
        cloud_evidence_bundle = self._cloud_gateway.build_evidence_bundle(
            session_id=session_id or "",
            skill_id="analyze_selected_target",
            user_query=str(args.get("question") or ""),
            local_summary={
                "selected_target_id": selected["target_id"],
                "selected_reason": selected.get("reason"),
                "snapshot_id": snapshot.get("snapshot_id") if snapshot else None,
                "uncertainty": "selected target needs cloud visual analysis",
            },
            candidates=candidates,
            crop_refs=[str(target["crop_ref"])] if target and target.get("crop_ref") else [],
            contains_face=bool(target and target.get("label") in {"person", "people"}),
            allow_cloud=True,
            store_result=False,
            privacy_level="medium",
        )
        cloud_gateway = self._cloud_gateway.request_verification(cloud_evidence_bundle)
        return {
            "status": "needs_cloud",
            "result": {
                "target_id": selected["target_id"],
                "question": str(args.get("question") or ""),
                "cloud_attribute_resolution": "required",
                "cloud_evidence_bundle": cloud_evidence_bundle,
                "cloud_gateway": cloud_gateway,
                "cloud_result": cloud_gateway["cloud_result"],
                "hud": {
                    "answer_strip": "Cần cloud để xem kỹ mục tiêu",
                    "edge_chips": _cloud_edge_chips(cloud_gateway["cloud_result"]),
                    "target_hint": {
                        "target_id": selected["target_id"],
                        "status": "selected",
                        "reason": selected.get("reason", ""),
                    },
                    "ttl_ms": 5000,
                },
            },
        }

    def _require_snapshot(self, session_id: str | None) -> dict[str, Any] | None:
        return self._perception.latest(session_id) if session_id else None

    def _require_preview(self, session_id: str | None) -> dict[str, Any] | None:
        if not session_id or not self._preview_status_provider:
            return None
        return self._preview_status_provider(session_id)

    def _apply_session_target_labels(self, *, candidates: list[dict[str, Any]], session_id: str | None) -> None:
        labels = self._target_labels.get(session_id or "")
        if not labels:
            return
        for candidate in candidates:
            keys = [candidate.get("target_id"), candidate.get("track_id"), candidate.get("anonymous_id")]
            label = next((labels[str(key)] for key in keys if key is not None and str(key) in labels), None)
            if not label:
                continue
            candidate["display_name"] = label.get("display_name")
            candidate["contact_note"] = label.get("contact_note")
            candidate["contact_label_source"] = label.get("source")
            candidate["identity_match"] = "manual_session_label"
            candidate["match_status"] = "manual_label"

    def _query_scene_from_preview(
        self,
        *,
        args: dict[str, Any],
        session_id: str | None,
        preview: dict[str, Any],
        skill_id: str = "query_scene",
    ) -> dict[str, Any]:
        question = str(args.get("question") or "mô tả cảnh").strip()
        frame_ref = preview.get("image_url") if isinstance(preview.get("image_url"), str) else None
        frame_refs = [frame_ref] if frame_ref else []
        cloud_evidence_bundle = self._cloud_gateway.build_evidence_bundle(
            session_id=session_id or "",
            skill_id=skill_id,
            user_query=question,
            local_summary={
                "evidence": "client_snapshot_preview",
                "preview_source": preview.get("source"),
                "width": preview.get("width"),
                "height": preview.get("height"),
                "frame_count": preview.get("frame_count"),
                "uncertainty": "scene description requires visual verifier or local perception",
            },
            frame_refs=frame_refs,
            candidates=[],
            contains_face=False,
            allow_cloud=True,
            store_result=False,
            privacy_level="medium",
        )
        cloud_gateway = self._cloud_gateway.request_verification(cloud_evidence_bundle)
        cloud_result = cloud_gateway["cloud_result"]
        user_message = _scene_cloud_user_message(cloud_result)
        return {
            "status": "needs_cloud",
            "result": {
                "answer": user_message,
                "user_message": user_message,
                "summary": "Snapshot preview captured; local perception is missing, so visual reasoning must use the cloud gateway.",
                "evidence": frame_refs,
                "preview": preview,
                "cloud_evidence_bundle": cloud_evidence_bundle,
                "cloud_gateway": cloud_gateway,
                "cloud_result": cloud_result,
                "hud": {
                    "answer_strip": user_message,
                    "edge_chips": [skill_id, "snapshot", *_cloud_edge_chips(cloud_result)],
                    "ttl_ms": 5000,
                },
            },
        }


def _mean_confidence(items: list[dict[str, Any]]) -> float:
    if not items:
        return 0.0
    return round(sum(float(item["confidence"]) for item in items) / len(items), 4)


def _no_evidence(message: str) -> dict[str, Any]:
    return {
        "status": "no_evidence",
        "result": {
            "message": message,
            "hud": {"answer_strip": "Chưa có dữ liệu hình ảnh"},
        },
    }


def _preview_without_local_detector(
    *,
    message: str,
    user_message: str,
    answer_strip: str,
    preview: dict[str, Any],
    edge_chips: list[str],
) -> dict[str, Any]:
    return {
        "status": "no_evidence",
        "result": {
            "message": message,
            "user_message": user_message,
            "preview": preview,
            "missing_runtime": "perception_snapshot",
            "hud": {
                "answer_strip": answer_strip,
                "edge_chips": edge_chips,
                "ttl_ms": 5000,
            },
        },
    }


def _target_finder_waiting_for_detector(
    *,
    query: str,
    preview: dict[str, Any],
    identity_policy: dict[str, Any],
    detector_status: dict[str, Any],
) -> dict[str, Any]:
    yolo_stream_ready = bool(detector_status.get("stream_ingest_enabled"))
    face_status = detector_status.get("face_identity_status") if isinstance(detector_status.get("face_identity_status"), dict) else {}
    face_stream_ready = bool(face_status.get("stream_ingest_enabled"))
    identity_active = bool(identity_policy.get("identity_matching_allowed"))
    identity_required = identity_active and not bool(identity_policy.get("identity_matching_optional"))
    if identity_required and face_stream_ready:
        user_message = "Live camera đã bật; đang chờ Face ID local."
        answer_strip = "Đang tìm · chờ Face ID"
        required_runtime = "face_identity_external_stream"
        chips = ["target_finder", "live", "face_wait"]
    elif yolo_stream_ready:
        user_message = "Live camera đã bật; đang chờ YOLO26 bbox."
        answer_strip = "Đang tìm · chờ YOLO26"
        required_runtime = "yolo26_rokid_external_stream"
        chips = ["target_finder", "live", "yolo26_wait"]
    elif face_stream_ready:
        user_message = "Live camera đã bật; đang chờ detector bbox."
        answer_strip = "Đang tìm · chờ detector"
        required_runtime = "face_identity_or_detector_stream"
        chips = ["target_finder", "live", "detector_wait"]
    elif identity_required:
        user_message = "Live camera đã bật; Face ID worker chưa sẵn sàng."
        answer_strip = "Đang tìm · chờ Face ID"
        required_runtime = "face_identity_external_stream"
        chips = ["target_finder", "live", "face_wait"]
    else:
        user_message = "Live camera đã bật; YOLO26 stream bridge chưa sẵn sàng."
        answer_strip = "Đang tìm · chờ YOLO26"
        required_runtime = "yolo26_rokid_external_stream"
        chips = ["target_finder", "live", "detector_wait"]
    target_hint = {
        "mode": "aim_assist_waiting",
        "query": query,
        "crosshair": {"style": "tiny_center_reticle", "center_norm": [0.5, 0.5]},
        "identity_policy": identity_policy,
        "detector_status": detector_status,
        "zoom": {"enabled": False},
    }
    return {
        "status": "no_evidence",
        "result": {
            "message": "Live preview is available, but no detector stream has published bbox perception yet.",
            "user_message": user_message,
            "query": query,
            "preview": preview,
            "missing_runtime": "perception_snapshot",
            "required_runtime": required_runtime,
            "detector_status": detector_status,
            "identity_policy": identity_policy,
            "target_hint": target_hint,
            "hud": {
                "answer_strip": answer_strip,
                "edge_chips": chips,
                "target_hint": target_hint,
                "ttl_ms": 3000,
            },
        },
    }


def _person_info_waiting_for_face(
    *,
    query: str,
    preview: dict[str, Any],
    detector_status: dict[str, Any],
) -> dict[str, Any]:
    face_status = detector_status.get("face_identity_status") if isinstance(detector_status.get("face_identity_status"), dict) else {}
    face_stream_ready = bool(face_status.get("stream_ingest_enabled"))
    if face_stream_ready:
        user_message = "Live camera đã bật; đang chờ Face ID local quét mặt."
        answer_strip = "Đang quét người quen"
        required_runtime = "face_identity_external_stream"
        chips = ["person_info", "live", "face_wait"]
    else:
        user_message = "Live camera đã bật; Face ID worker chưa sẵn sàng để nhận diện."
        answer_strip = "Chờ Face ID"
        required_runtime = "face_identity_worker"
        chips = ["person_info", "live", "face_id_offline"]
    target_hint = {
        "mode": "person_info_waiting",
        "query": query,
        "crosshair": {"style": "tiny_center_reticle", "center_norm": [0.5, 0.5]},
        "detector_status": detector_status,
        "zoom": {"enabled": False},
    }
    return {
        "status": "no_evidence",
        "result": {
            "message": "Live preview is available, but no face identity stream has published a usable face yet.",
            "user_message": user_message,
            "query": query,
            "preview": preview,
            "missing_runtime": "perception_snapshot",
            "required_runtime": required_runtime,
            "detector_status": detector_status,
            "target_hint": target_hint,
            "hud": {
                "answer_strip": answer_strip,
                "edge_chips": chips,
                "target_hint": target_hint,
                "ttl_ms": 3000,
            },
        },
    }


def _person_info_name_reminder_uncertain(
    *,
    query: str,
    identity_query: str,
    info_focus: str,
    scan_mode: str,
    identity_policy: dict[str, Any],
    identity_provider: dict[str, Any],
    candidates: list[dict[str, Any]],
    thumbnails: list[dict[str, Any]],
    detector_status: dict[str, Any],
    snapshot_id: str | None,
    selected: dict[str, Any] | None,
) -> dict[str, Any]:
    best = identity_provider.get("best_match") if isinstance(identity_provider.get("best_match"), dict) else {}
    answer = "Đang thấy mặt, nhưng chưa đủ chắc để nhắc tên."
    return {
        "status": "ok",
        "result": {
            "answer": answer,
            "user_message": answer,
            "query": query,
            "identity_query": identity_query,
            "info_focus": info_focus,
            "scan_mode": scan_mode,
            "known_person": False,
            "known_people": [],
            "identity_policy": identity_policy,
            "identity_provider": identity_provider,
            "identity_uncertain": {
                "status": "below_name_reminder_display_threshold",
                "min_confidence": NAME_REMINDER_SWITCH_MIN_CONFIDENCE,
                "best_match": best,
            },
            "candidate_count": len(candidates),
            "candidates": candidates,
            "detector_status": detector_status,
            "snapshot_id": snapshot_id,
            "hud": {
                "answer_strip": answer,
                "edge_chips": ["person_info", "name_reminder", "identity_uncertain"],
                "thumbnails": thumbnails,
                "target_hint": _person_info_target_hint(selected, None) if selected else None,
                "ttl_ms": 3500,
            },
        },
    }


def _scene_cloud_user_message(cloud_result: dict[str, Any]) -> str:
    status = str(cloud_result.get("status") or "").strip()
    answer = str(cloud_result.get("answer_short") or "").strip()
    if status in {"ok", "no_match", "uncertain"} and answer:
        return answer
    if status == "blocked" and answer:
        return answer
    if status in {"blocked", "error"}:
        return "Đã chụp ảnh; visual verifier chưa sẵn sàng."
    return answer or "Đã chụp ảnh; cần visual verifier để mô tả."


def _invalid_args(errors: list[str]) -> dict[str, Any]:
    return {
        "status": "error",
        "error": {
            "code": "invalid_skill_args",
            "message": "Skill arguments do not match the manifest input schema.",
            "details": errors,
        },
    }


def _requires_cloud_attribute_resolution(query: str) -> bool:
    if not query:
        return False
    attribute_tokens = {
        "áo",
        "ao",
        "mặc",
        "mac",
        "màu",
        "mau",
        "xanh",
        "đỏ",
        "do",
        "đen",
        "den",
        "trắng",
        "trang",
        "vàng",
        "vang",
        "kính",
        "kinh",
        "đứng",
        "dung",
        "ngồi",
        "ngoi",
        "đội",
        "doi",
        "cầm",
        "cam",
        "wearing",
        "shirt",
        "color",
        "glasses",
        "standing",
        "sitting",
    }
    return any(token in query for token in attribute_tokens)


def _identity_requested(query: str, *, target_type: str = "person") -> bool:
    normalized = _normalize_identity_text(query)
    identity_phrases = {
        "tram",
        "immich",
        "khuon mat",
        "face",
        "face id",
        "nhan dien",
        "doi chieu",
        "co so du lieu",
        "database",
        "data mat",
        "id nao la",
        "nguoi ten",
        "ten tram",
        "nguoi quen",
        "la ai",
        "ten gi",
    }
    if any(phrase in normalized for phrase in identity_phrases):
        return True
    return target_type == "person" and _looks_like_named_person_find_query(normalized)


def _opportunistic_identity_scan(query: str, *, target_type: str = "person") -> bool:
    if target_type != "person":
        return False
    normalized = _normalize_identity_text(query)
    if not normalized:
        return True
    generic_person_scan_phrases = {
        "tim nguoi",
        "tim mot nguoi",
        "nguoi trong dam dong",
        "nguoi phia truoc",
        "quet mat",
        "scan mat",
        "scan face",
        "face scan",
        "nhin mat",
        "xem mat",
    }
    return any(phrase in normalized for phrase in generic_person_scan_phrases)


def _target_finder_effective_query(query: str, *, target_name: str | None = None) -> str:
    cleaned_query = str(query or "").strip() or "tìm mục tiêu"
    cleaned_name = str(target_name or "").strip()
    if not cleaned_name:
        return cleaned_query
    normalized_query = _normalize_identity_text(cleaned_query)
    normalized_name = _normalize_identity_text(cleaned_name)
    if normalized_name and normalized_name not in normalized_query:
        return f"{cleaned_query} {cleaned_name}".strip()
    return cleaned_query


def _looks_like_named_person_find_query(normalized_query: str) -> bool:
    tokens = normalized_query.split()
    if "tim" not in tokens:
        return False
    tail = tokens[tokens.index("tim") + 1 :]
    if not tail:
        return False
    if any(
        token in tail
        for token in (
            "ao",
            "mac",
            "mau",
            "xanh",
            "do",
            "den",
            "trang",
            "vang",
            "kinh",
            "toc",
        )
    ):
        return False
    generic_tokens = {
        "nguoi",
        "muc",
        "tieu",
        "trong",
        "dam",
        "dong",
        "quen",
        "phia",
        "truoc",
        "ben",
        "trai",
        "phai",
        "gan",
        "xa",
        "nay",
        "kia",
        "do",
        "vat",
        "cai",
        "chiec",
        "con",
        "balo",
        "tui",
        "xe",
        "dien",
        "thoai",
        "ly",
        "coc",
        "hat",
    }
    specific_tokens = [token for token in tail if token not in generic_tokens]
    return bool(specific_tokens)


def _normalize_identity_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", str(value or "").lower())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("đ", "d")
    return " ".join("".join(char if char.isalnum() else " " for char in normalized).split())


def _identity_quality_reason_counts(identity_provider: dict[str, Any]) -> dict[str, int]:
    raw = identity_provider.get("quality_reasons") if isinstance(identity_provider, dict) else None
    counts: dict[str, int] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            reason = str(key or "").strip()
            if not reason:
                continue
            try:
                count = int(value)
            except (TypeError, ValueError):
                count = 1
            counts[reason] = max(1, count)
    elif isinstance(raw, list):
        for item in raw:
            reason = str(item or "").strip()
            if reason:
                counts[reason] = counts.get(reason, 0) + 1
    return counts


def _identity_quality_chips(identity_provider: dict[str, Any]) -> list[str]:
    reasons = _identity_quality_reason_counts(identity_provider)
    chips: list[str] = []
    if reasons.get("too_small_for_identity"):
        chips.append("face_small")
    if reasons.get("too_dark_for_identity") or reasons.get("low_light_for_identity"):
        chips.append("face_dark")
    if reasons.get("low_contrast_for_identity"):
        chips.append("face_low_contrast")
    if reasons.get("too_soft_for_identity") or reasons.get("too_blurry_for_identity"):
        chips.append("face_blur")
    return chips


def _identity_quality_user_hint(identity_provider: dict[str, Any], *, default: str) -> str:
    reasons = _identity_quality_reason_counts(identity_provider)
    if reasons.get("too_small_for_identity"):
        return "Mặt hơi xa hoặc quá nhỏ; lại gần hơn một chút."
    if reasons.get("too_dark_for_identity") or reasons.get("low_light_for_identity"):
        return "Ảnh mặt hơi tối; đưa mặt ra sáng hơn hoặc đổi góc camera."
    if reasons.get("low_contrast_for_identity"):
        return "Ảnh mặt ít tương phản; đổi góc sáng hoặc giữ mặt rõ hơn."
    if reasons.get("too_soft_for_identity") or reasons.get("too_blurry_for_identity"):
        return "Ảnh mặt hơi mờ; giữ yên camera một chút rồi thử lại."
    return default


def _identity_provider_best_match_matches_cached(
    identity_provider: dict[str, Any],
    cached_response: dict[str, Any],
) -> bool:
    provider_best = identity_provider.get("best_match") if isinstance(identity_provider.get("best_match"), dict) else {}
    return _identity_match_matches_cached(provider_best, cached_response)


def _name_reminder_match_is_displayable(
    *,
    selected_match: dict[str, Any],
    cached_response: dict[str, Any] | None,
) -> bool:
    if cached_response and _identity_match_matches_cached(selected_match, cached_response):
        return True
    return _identity_match_confidence(selected_match) >= NAME_REMINDER_SWITCH_MIN_CONFIDENCE


def _name_reminder_should_hold_cached_match(
    *,
    selected_match: dict[str, Any],
    cached_response: dict[str, Any],
) -> bool:
    cached_match = _cached_identity_match(cached_response)
    if not cached_match:
        return False
    if _identity_match_matches_cached(selected_match, cached_response):
        return False
    selected_confidence = _identity_match_confidence(selected_match)
    cached_confidence = _identity_match_confidence(cached_match)
    return (
        selected_confidence < NAME_REMINDER_SWITCH_MIN_CONFIDENCE
        or selected_confidence <= cached_confidence + NAME_REMINDER_SWITCH_CONFIDENCE_MARGIN
    )


def _identity_match_matches_cached(
    match: dict[str, Any],
    cached_response: dict[str, Any],
) -> bool:
    cached_match = _cached_identity_match(cached_response)
    if not match or not cached_match:
        return False
    provider_contact = str(match.get("contact_id") or "").strip()
    cached_contact = str(cached_match.get("contact_id") or "").strip()
    if provider_contact and cached_contact and provider_contact == cached_contact:
        return True
    provider_name = _normalize_identity_text(str(match.get("display_name") or ""))
    cached_name = _normalize_identity_text(str(cached_match.get("display_name") or ""))
    return bool(provider_name and cached_name and provider_name == cached_name)


def _cached_identity_match(cached_response: dict[str, Any]) -> dict[str, Any]:
    cached_result = cached_response.get("result") if isinstance(cached_response.get("result"), dict) else {}
    return cached_result.get("identity_match") if isinstance(cached_result.get("identity_match"), dict) else {}


def _identity_match_confidence(match: dict[str, Any]) -> float:
    try:
        return float(match.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _identity_policy_for_query(
    query: str,
    target_type: str = "person",
    identity_provider: dict[str, Any] | None = None,
    requested: bool | None = None,
    optional: bool = False,
) -> dict[str, Any]:
    requested = _identity_requested(query, target_type=target_type) if requested is None else bool(requested)
    if not requested:
        return {
            "status": "not_requested",
            "identity_matching_allowed": False,
            "message": "No face identity lookup requested.",
        }
    provider_status = str((identity_provider or {}).get("status") or "")
    provider_name = str((identity_provider or {}).get("provider") or "none")
    match_count = int((identity_provider or {}).get("match_count") or 0)
    if provider_status == "confirmed" and match_count > 0:
        return {
            "status": "contact_match_confirmed",
            "identity_matching_allowed": True,
            "provider": provider_name,
            "confirmed_match_count": match_count,
            "message": "Matched the requested contact from the local OpenVision contact DB.",
            "contact_reminder_source": "local_contact_identity_db",
        }
    if provider_status in {"no_match", "no_candidate_vectors", "no_requested_contact", "no_samples"}:
        if optional:
            vector_count = int((identity_provider or {}).get("candidate_vector_count") or 0)
            return {
                "status": "identity_scan_no_match" if vector_count else "identity_scan_waiting_for_face",
                "identity_matching_allowed": True,
                "identity_matching_optional": True,
                "provider": provider_name,
                "confirmed_match_count": 0,
                "message": "Local contact DB was checked opportunistically; no confident contact match is ready for this frame.",
                "contact_reminder_source": "local_contact_identity_db",
            }
        return {
            "status": "identity_lookup_no_match",
            "identity_matching_allowed": True,
            "provider": provider_name,
            "confirmed_match_count": 0,
            "message": "Local contact DB checked; no contact match is ready for this frame.",
            "contact_reminder_source": "local_contact_identity_db",
        }
    if provider_status == "low_quality_face":
        low_quality_count = int((identity_provider or {}).get("low_quality_candidate_count") or 0)
        quality_reasons = _identity_quality_reason_counts(identity_provider or {})
        base = {
            "identity_matching_allowed": True,
            "provider": provider_name,
            "confirmed_match_count": 0,
            "low_quality_candidate_count": low_quality_count,
            "quality_reasons": quality_reasons,
            "quality_hint": _identity_quality_user_hint(
                identity_provider or {},
                default="Mặt chưa đủ rõ; lại gần hoặc đổi góc.",
            ),
            "best_score": (identity_provider or {}).get("best_score"),
            "min_identity_face_side_px": (identity_provider or {}).get("min_identity_face_side_px"),
            "message": "Face is visible but not clear enough for reliable identity matching; adjust distance, light, or angle.",
            "contact_reminder_source": "local_contact_identity_db",
        }
        if optional:
            return {
                **base,
                "status": "identity_scan_low_quality",
                "identity_matching_optional": True,
            }
        return {
            **base,
            "status": "identity_lookup_low_quality",
        }
    if provider_status in {"unavailable", "error", ""}:
        if optional:
            return {
                "status": "identity_scan_unavailable",
                "identity_matching_allowed": True,
                "identity_matching_optional": True,
                "provider": provider_name,
                "confirmed_match_count": 0,
                "message": "Local contact DB is not ready; continuing anonymous target guidance.",
                "contact_reminder_source": "local_contact_identity_db",
            }
        return {
            "status": "identity_lookup_unavailable",
            "identity_matching_allowed": True,
            "provider": provider_name,
            "confirmed_match_count": 0,
            "message": "Local contact DB is not ready yet; showing anonymous IDs for selection/enrollment.",
            "contact_reminder_source": "local_contact_identity_db",
        }
    return {
        "status": "manual_confirmation_required",
        "identity_matching_allowed": True,
        "provider": provider_name,
        "message": "Showing anonymous IDs until the requested contact is confirmed.",
        "contact_reminder_source": "anonymous_person_ids_manual_selection",
    }


def _target_finder_detector_status(
    *,
    snapshot: dict[str, Any],
    adapter_status: dict[str, Any],
) -> dict[str, Any]:
    source = str(snapshot.get("source") or "")
    objects = [item for item in snapshot.get("objects") or [] if isinstance(item, dict)]
    person_count = len([item for item in objects if str(item.get("label") or "") in {"person", "people"}])
    has_yolo26_stream = source.startswith("yolo26_rokid_stream:")
    has_face_identity_stream = source.startswith("face_identity_stream:")
    has_face_identity_snapshot = source.startswith("face_identity_snapshot:")
    status = "ready" if has_yolo26_stream or has_face_identity_stream or has_face_identity_snapshot else "fallback_perception"
    face_status = adapter_status.get("face_identity_status") if isinstance(adapter_status.get("face_identity_status"), dict) else {}
    return {
        "name": "openvision_perception",
        "status": status,
        "adapter_status": adapter_status.get("status"),
        "adapter_mode": adapter_status.get("mode"),
        "stream_ingest_enabled": bool(adapter_status.get("stream_ingest_enabled")),
        "face_identity_adapter_status": face_status.get("status"),
        "face_identity_stream_ingest_enabled": bool(face_status.get("stream_ingest_enabled")),
        "has_yolo26_stream": has_yolo26_stream,
        "has_face_identity_stream": has_face_identity_stream,
        "has_face_identity_snapshot": has_face_identity_snapshot,
        "perception_source": source,
        "snapshot_id": snapshot.get("snapshot_id"),
        "frame_id": snapshot.get("frame_id"),
        "frame_width": snapshot.get("width"),
        "frame_height": snapshot.get("height"),
        "object_count": len(objects),
        "person_count": person_count,
        "ready_for_target_finder": bool((has_yolo26_stream or has_face_identity_stream) and person_count > 0),
        "ready_for_person_info": bool((has_face_identity_stream or has_face_identity_snapshot) and person_count > 0),
        "message": (
            "YOLO26 stream bbox is feeding target_finder."
            if has_yolo26_stream
            else "Face identity stream is feeding target_finder."
            if has_face_identity_stream
            else "Face identity snapshot is feeding person_info."
            if has_face_identity_snapshot
            else "Target_finder is using a non-dedicated perception snapshot."
        ),
    }


def _target_finder_summary(*, detector_status: dict[str, Any]) -> str:
    if detector_status.get("has_face_identity_stream"):
        return (
            "Live target finder is using local face identity stream tracks from the perception graph. "
            "Named-contact reminders use the local OpenVision contact DB when enrolled samples are available."
        )
    if detector_status.get("has_yolo26_stream"):
        return (
            "Live target finder is using YOLO26 stream bbox tracks from the perception graph. "
            "Named-contact reminders can use the local OpenVision contact DB when enrolled samples are available."
        )
    return (
        "Live target finder uses anonymous tracks from the perception graph. "
        "YOLO26 stream bbox has not been observed for this snapshot."
    )


def _target_finder_filter_objects(
    objects: list[dict[str, Any]],
    *,
    query: str,
    target_type: str,
) -> list[dict[str, Any]]:
    normalized_query = _normalize_count_text(query)
    person_query = target_type == "person" or any(
        token in normalized_query
        for token in (
            "nguoi",
            "person",
            "crowd",
            "dam dong",
            "tram",
            "ao",
            "mac",
            "dung",
            "ngoi",
        )
    )
    if person_query:
        return [item for item in objects if str(item.get("label") or "") in {"person", "people"}]
    target = _count_target_from_question(query) or query
    return _matching_objects(objects, target)


def _target_finder_candidate(
    item: dict[str, Any],
    *,
    index: int,
    snapshot: dict[str, Any],
    query: str,
    zoom_if_far: bool,
) -> dict[str, Any]:
    target_id = str(item.get("object_id") or item.get("track_id") or f"candidate_{index}")
    bbox = item.get("bbox") if isinstance(item.get("bbox"), list) else None
    frame_width = _coerce_positive_int(item.get("frame_width") or snapshot.get("width"))
    frame_height = _coerce_positive_int(item.get("frame_height") or snapshot.get("height"))
    bbox_norm = _normalized_bbox(bbox, frame_width=frame_width, frame_height=frame_height)
    aim = _aim_from_bbox_norm(bbox_norm)
    zone = str(item.get("zone") or "unknown")
    zoom = _zoom_hint(
        item=item,
        bbox_norm=bbox_norm,
        zone=zone,
        enabled=zoom_if_far,
    )
    label = str(item.get("label") or "target")
    match_status = "anonymous_person_candidate" if label in {"person", "people"} else "local_candidate"
    candidate = {
        "target_id": target_id,
        "anonymous_id": f"P{index}" if label in {"person", "people"} else f"T{index}",
        "label": label,
        "confidence": item.get("confidence"),
        "bbox": bbox,
        "bbox_norm": bbox_norm,
        "track_id": item.get("track_id"),
        "zone": zone,
        "attributes": item.get("attributes") if isinstance(item.get("attributes"), dict) else {},
        "crop_ref": item.get("crop_ref"),
        "match_status": match_status,
        "identity_match": "not_performed",
        "query": query,
        "aim": aim,
        "zoom": zoom,
    }
    return {key: value for key, value in candidate.items() if value is not None}


def _select_guidance_candidate(
    candidates: list[dict[str, Any]],
    *,
    identity_policy: dict[str, Any],
) -> dict[str, Any] | None:
    if not candidates:
        return None
    if identity_policy.get("status") == "contact_match_confirmed":
        confirmed = [
            candidate
            for candidate in candidates
            if candidate.get("identity_match") == "contact_db"
            or candidate.get("match_status") == "identity_confirmed"
        ]
        return sorted(confirmed, key=_candidate_guidance_score)[0] if confirmed else None
    if identity_policy.get("status") in {
        "manual_confirmation_required",
        "identity_lookup_no_match",
        "identity_lookup_unavailable",
    }:
        return None
    return sorted(candidates, key=_candidate_guidance_score)[0]


def _apply_identity_provider_matches(
    *,
    candidates: list[dict[str, Any]],
    identity_provider: dict[str, Any],
) -> None:
    matches = identity_provider.get("matches") if isinstance(identity_provider.get("matches"), list) else []
    for candidate in candidates:
        keys = {str(candidate.get("target_id") or ""), str(candidate.get("track_id") or ""), str(candidate.get("anonymous_id") or "")}
        match = next(
            (
                item
                for item in matches
                if isinstance(item, dict)
                and (
                    str(item.get("target_id") or "") in keys
                    or str(item.get("track_id") or "") in keys
                    or str(item.get("anonymous_id") or "") in keys
                )
            ),
            None,
        )
        if not match:
            continue
        candidate["display_name"] = match.get("display_name")
        candidate["contact_id"] = match.get("contact_id")
        candidate["identity_confidence"] = match.get("confidence")
        candidate["identity_sample_id"] = match.get("sample_id")
        candidate["identity_match"] = match.get("identity_match") or "contact_db"
        candidate["match_status"] = match.get("match_status") or "identity_confirmed"


def _manual_contact_match(candidates: list[dict[str, Any]], *, query: str) -> dict[str, Any] | None:
    query_text = _normalize_count_text(query)
    if not query_text:
        return None
    for candidate in candidates:
        name = str(candidate.get("display_name") or "").strip()
        if name and _normalize_count_text(name) in query_text:
            return candidate
    return None


def _target_finder_confirmed_count(
    candidates: list[dict[str, Any]],
    *,
    identity_policy: dict[str, Any],
) -> int:
    if identity_policy.get("status") == "contact_match_confirmed":
        return len(
            [
                candidate
                for candidate in candidates
                if candidate.get("identity_match") == "contact_db"
                or candidate.get("match_status") == "identity_confirmed"
            ]
        )
    if identity_policy.get("status") in {
        "manual_confirmation_required",
        "identity_lookup_no_match",
        "identity_lookup_unavailable",
        "identity_scan_no_match",
        "identity_scan_waiting_for_face",
        "identity_scan_unavailable",
        "identity_scan_low_quality",
        "identity_lookup_low_quality",
    }:
        return 0
    if identity_policy.get("status") == "manual_label_confirmed":
        return 1
    return len(candidates)


def _candidate_guidance_score(candidate: dict[str, Any]) -> float:
    aim = candidate.get("aim") if isinstance(candidate.get("aim"), dict) else {}
    distance = aim.get("distance_norm")
    try:
        return float(distance)
    except (TypeError, ValueError):
        return 999.0


def _target_finder_hud_hint(
    *,
    selected: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    identity_policy: dict[str, Any],
    query: str,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "mode": "aim_assist",
        "query": query,
        "crosshair": {"style": "tiny_center_reticle", "center_norm": [0.5, 0.5]},
        "identity_policy": identity_policy,
        "candidate_count": len(candidates),
    }
    if identity_policy.get("status") in {
        "manual_confirmation_required",
        "identity_lookup_no_match",
        "identity_lookup_unavailable",
    }:
        base.update(
            {
                "status": "manual_selection_required",
                "message": identity_policy.get("message") or "Use anonymous IDs until the contact is confirmed.",
                "candidates": [_hud_candidate_summary(candidate) for candidate in candidates],
                "zoom": {"enabled": False},
            }
        )
        return base
    if not selected:
        base.update({"status": "no_candidate", "zoom": {"enabled": False}})
        return base
    base.update(
        {
            "status": "guiding",
            "target_id": selected.get("target_id"),
            "anonymous_id": selected.get("anonymous_id"),
            "display_name": selected.get("display_name"),
            "contact_id": selected.get("contact_id"),
            "identity_confidence": selected.get("identity_confidence"),
            "match_status": selected.get("match_status"),
            "label": selected.get("label"),
            "bbox": selected.get("bbox"),
            "bbox_norm": selected.get("bbox_norm"),
            "zone": selected.get("zone"),
            "confidence": selected.get("confidence"),
            "aim": selected.get("aim"),
            "zoom": selected.get("zoom") if isinstance(selected.get("zoom"), dict) else {"enabled": False},
            "candidates": [_hud_candidate_summary(candidate) for candidate in candidates],
        }
    )
    return base


def _hud_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "target_id": candidate.get("target_id"),
            "anonymous_id": candidate.get("anonymous_id"),
            "display_name": candidate.get("display_name"),
            "contact_id": candidate.get("contact_id"),
            "identity_confidence": candidate.get("identity_confidence"),
            "match_status": candidate.get("match_status"),
            "label": candidate.get("label"),
            "zone": candidate.get("zone"),
            "bbox_norm": candidate.get("bbox_norm"),
            "aim": candidate.get("aim"),
            "zoom": candidate.get("zoom"),
        }.items()
        if value is not None
    }


def _aim_from_bbox_norm(bbox_norm: list[float] | None) -> dict[str, Any]:
    if not bbox_norm:
        return {
            "status": "unknown",
            "arrow": "unknown",
            "text": "chưa có vị trí",
        }
    center_x = (bbox_norm[0] + bbox_norm[2]) / 2
    center_y = (bbox_norm[1] + bbox_norm[3]) / 2
    dx = round(center_x - 0.5, 4)
    dy = round(center_y - 0.5, 4)
    distance = round((dx * dx + dy * dy) ** 0.5, 4)
    horizontal = "center"
    vertical = "center"
    if dx < -0.08:
        horizontal = "left"
    elif dx > 0.08:
        horizontal = "right"
    if dy < -0.10:
        vertical = "up"
    elif dy > 0.10:
        vertical = "down"
    if horizontal == "center" and vertical == "center":
        arrow = "center"
    elif horizontal == "center":
        arrow = vertical
    elif vertical == "center":
        arrow = horizontal
    else:
        arrow = f"{vertical}_{horizontal}"
    return {
        "status": "ok",
        "center_norm": [round(center_x, 4), round(center_y, 4)],
        "dx_norm": dx,
        "dy_norm": dy,
        "distance_norm": distance,
        "arrow": arrow,
        "text": _aim_user_text({"arrow": arrow}),
        "within_crosshair": arrow == "center",
    }


def _aim_user_text(aim: dict[str, Any] | None) -> str:
    if not isinstance(aim, dict):
        return ""
    arrow = str(aim.get("arrow") or "")
    labels = {
        "center": "đúng tâm",
        "left": "sang trái",
        "right": "sang phải",
        "up": "lên trên",
        "down": "xuống dưới",
        "up_left": "lên trái",
        "up_right": "lên phải",
        "down_left": "xuống trái",
        "down_right": "xuống phải",
    }
    return labels.get(arrow, "")


def _zoom_hint(
    *,
    item: dict[str, Any],
    bbox_norm: list[float] | None,
    zone: str,
    enabled: bool,
) -> dict[str, Any]:
    if not enabled or not bbox_norm:
        return {"enabled": False}
    width = max(0.0, bbox_norm[2] - bbox_norm[0])
    height = max(0.0, bbox_norm[3] - bbox_norm[1])
    area = width * height
    should_zoom = zone == "far" or height < 0.24 or area < 0.06
    if not should_zoom:
        return {"enabled": False}
    crop_ref = item.get("crop_ref")
    zoom: dict[str, Any] = {
        "enabled": True,
        "tile": "top_left",
        "reason": "target_small_or_far",
        "bbox_norm": bbox_norm,
        "label": "zoom",
    }
    if isinstance(crop_ref, str) and crop_ref:
        zoom["crop_ref"] = crop_ref
        if crop_ref.startswith(("/", "http://", "https://")):
            zoom["image_url"] = crop_ref
    return zoom


def _normalized_bbox(
    bbox: list[float] | None,
    *,
    frame_width: int | None,
    frame_height: int | None,
) -> list[float] | None:
    if not bbox or len(bbox) < 4:
        return None
    values = [float(item) for item in bbox[:4]]
    if all(0.0 <= value <= 1.5 for value in values):
        return [_clamp(value, minimum=0.0, maximum=1.0) for value in values]
    if not frame_width or not frame_height:
        return None
    return [
        round(_clamp(values[0] / frame_width, minimum=0.0, maximum=1.0), 4),
        round(_clamp(values[1] / frame_height, minimum=0.0, maximum=1.0), 4),
        round(_clamp(values[2] / frame_width, minimum=0.0, maximum=1.0), 4),
        round(_clamp(values[3] / frame_height, minimum=0.0, maximum=1.0), 4),
    ]


def _coerce_positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clamp(value: float, *, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _count_target_from_question(question: str) -> str | None:
    normalized = question.strip().lower()
    if not normalized:
        return None
    markers = (
        "bao nhiêu",
        "bao nhieu",
        "có mấy",
        "co may",
        "có bao nhiêu",
        "co bao nhieu",
        "đếm",
        "dem",
        "how many",
        "count",
    )
    for marker in markers:
        if marker in normalized:
            tail = normalized.split(marker, 1)[1].strip(" ?.!,:;")
            return _clean_count_target(tail)
    return None


def _clean_count_target(value: str) -> str | None:
    cleaned = value.strip().lower()
    stop_words = {
        "cái",
        "cay",
        "con",
        "chiếc",
        "chiec",
        "thứ",
        "thu",
        "vật",
        "vat",
        "trong",
        "ảnh",
        "anh",
        "hình",
        "hinh",
        "phía",
        "phia",
        "trước",
        "truoc",
        "tôi",
        "toi",
        "there",
        "are",
        "visible",
        "in",
        "the",
        "image",
    }
    words = [word for word in cleaned.replace("/", " ").split() if word and word not in stop_words]
    return " ".join(words[:4]) or None


def _matching_objects(objects: list[dict[str, Any]], target: str | None) -> list[dict[str, Any]]:
    if not target:
        return objects
    target_tokens = set(_normalize_count_text(target).split())
    if not target_tokens:
        return objects
    matched: list[dict[str, Any]] = []
    for item in objects:
        haystack = _normalize_count_text(
            " ".join(
                str(part)
                for part in (
                    item.get("label"),
                    item.get("class"),
                    item.get("name"),
                )
                if part
            )
        )
        if target_tokens & set(haystack.split()):
            matched.append(item)
    return matched


def _normalize_count_text(value: str) -> str:
    normalized = value.lower()
    replacements = {
        "đ": "d",
        "á": "a",
        "à": "a",
        "ả": "a",
        "ã": "a",
        "ạ": "a",
        "ă": "a",
        "â": "a",
        "é": "e",
        "è": "e",
        "ẻ": "e",
        "ẽ": "e",
        "ẹ": "e",
        "ê": "e",
        "í": "i",
        "ì": "i",
        "ỉ": "i",
        "ĩ": "i",
        "ị": "i",
        "ó": "o",
        "ò": "o",
        "ỏ": "o",
        "õ": "o",
        "ọ": "o",
        "ô": "o",
        "ơ": "o",
        "ú": "u",
        "ù": "u",
        "ủ": "u",
        "ũ": "u",
        "ụ": "u",
        "ư": "u",
        "ý": "y",
        "ỳ": "y",
        "ỷ": "y",
        "ỹ": "y",
        "ỵ": "y",
    }
    for source, replacement in replacements.items():
        normalized = normalized.replace(source, replacement)
    return "".join(char if char.isalnum() else " " for char in normalized)


def _candidate_thumbnail(candidate: dict[str, Any], *, index: int) -> dict[str, Any]:
    caption_parts = [str(candidate.get("display_name") or candidate.get("label") or "target")]
    if candidate.get("track_id"):
        caption_parts.append(str(candidate["track_id"]))
    thumbnail: dict[str, Any] = {
        "thumbnail_id": candidate["target_id"],
        "target_id": candidate["target_id"],
        "caption": f"{index}. {' '.join(caption_parts)}",
        "label": candidate.get("label"),
        "confidence": candidate.get("confidence"),
        "display_name": candidate.get("display_name"),
        "contact_id": candidate.get("contact_id"),
        "identity_confidence": candidate.get("identity_confidence"),
        "bbox": candidate.get("bbox"),
        "crop_ref": candidate.get("crop_ref"),
        "match_status": candidate.get("match_status"),
    }
    crop_ref = candidate.get("crop_ref")
    if isinstance(crop_ref, str) and crop_ref.startswith(("/", "http://", "https://")):
        thumbnail["image_url"] = crop_ref
    return thumbnail


def _person_info_identity_query(query: str) -> str:
    normalized = _normalize_identity_text(query)
    if not normalized:
        return "người này là ai"
    if any(
        phrase in normalized
        for phrase in (
            "co ai quen",
            "ai quen",
            "nguoi quen",
            "da gap",
            "gap chua",
            "nguoi nay",
            "nguoi do",
            "nguoi kia",
            "la ai",
            "ten gi",
            "thong tin",
            "co biet nguoi",
            "toi co biet",
            "quet mat",
            "scan mat",
        )
    ):
        return query
    return f"người này là ai {query}".strip()


def _person_info_focus(*, query: str, explicit: Any) -> str:
    allowed = {"auto", "name", "summary", "contact", "relationship", "full"}
    requested = str(explicit or "").strip().lower()
    if requested in allowed and requested != "auto":
        return requested
    normalized = _normalize_identity_text(query)
    if any(phrase in normalized for phrase in ("day du", "tat ca", "full", "het thong tin", "con thong tin")):
        return "full"
    if any(
        phrase in normalized
        for phrase in (
            "so dien thoai",
            "sdt",
            "phone",
            "dia chi",
            "address",
            "facebook",
            "link",
            "lien lac",
            "mxh",
        )
    ):
        return "contact"
    if any(
        phrase in normalized
        for phrase in (
            "vi sao quen",
            "tai sao quen",
            "quen the nao",
            "gap lan dau",
            "lan dau gap",
            "relationship",
            "quan he",
        )
    ):
        return "relationship"
    if any(
        phrase in normalized
        for phrase in (
            "co ai quen",
            "da gap chua",
            "gap chua",
            "la ai",
            "ten gi",
            "co biet nguoi nay",
        )
    ):
        return "name"
    return "summary"


def _person_info_best_match(matches: list[Any]) -> dict[str, Any] | None:
    candidates = [item for item in matches if isinstance(item, dict)]
    if not candidates:
        return None

    def score(item: dict[str, Any]) -> float:
        try:
            return float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    return sorted(candidates, key=score, reverse=True)[0]


def _person_info_candidate_for_match(
    candidates: list[dict[str, Any]],
    match: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not match:
        return None
    keys = {
        str(match.get("target_id") or ""),
        str(match.get("track_id") or ""),
        str(match.get("anonymous_id") or ""),
    }
    return next(
        (
            candidate
            for candidate in candidates
            if str(candidate.get("target_id") or "") in keys
            or str(candidate.get("track_id") or "") in keys
            or str(candidate.get("anonymous_id") or "") in keys
        ),
        None,
    )


def _person_info_answer(
    *,
    display_name: str,
    identity_confidence: Any,
    profile: dict[str, Any],
    info_focus: str,
    name_reminder: bool = False,
    prompt_followup: bool = False,
) -> str:
    name = str(display_name or "").strip() or "người này"
    if name_reminder:
        return name
    person = _person_info_profile_person(profile)
    if info_focus == "name":
        if prompt_followup:
            return f"Có, {name}. Bạn cần thêm thông tin gì nữa không?"
        return f"Có, mình nhận ra {name}."
    details = _person_info_detail_parts(person, info_focus=info_focus)
    if details:
        return _short_text(f"Đây là {name}. " + "; ".join(details), max_chars=260)
    profile_status = str(profile.get("status") or "")
    if profile_status == "found":
        return f"Mình nhận ra {name}, nhưng Face UI chưa có thêm ghi chú cho người này."
    if profile_status == "not_found":
        return f"Mình nhận ra {name}; chưa liên kết được hồ sơ Face UI."
    confidence = _safe_confidence_percent(identity_confidence)
    suffix = f" độ tin cậy khoảng {confidence}%." if confidence is not None and info_focus in {"full", "summary"} else "."
    return f"Mình nhận ra {name}{suffix}"


def _person_info_detail_parts(person: dict[str, Any] | None, *, info_focus: str) -> list[str]:
    if not person:
        return []
    fields_by_focus = {
        "summary": ("relationship", "first_met", "where_lives", "age", "notes"),
        "contact": ("phone", "address", "where_lives"),
        "relationship": ("relationship", "first_met", "notes"),
        "full": ("age", "where_lives", "relationship", "first_met", "phone", "address", "notes"),
    }
    labels = {
        "phone": "số điện thoại",
        "address": "địa chỉ",
        "age": "tuổi/ngày sinh",
        "where_lives": "nơi ở",
        "relationship": "vì sao quen",
        "first_met": "lần đầu gặp",
        "notes": "ghi chú",
    }
    parts: list[str] = []
    for key in fields_by_focus.get(info_focus, fields_by_focus["summary"]):
        value = str(person.get(key) or "").strip()
        if value:
            parts.append(f"{labels[key]}: {value}")
        if info_focus == "summary" and len(parts) >= 3:
            return parts
    facts = person.get("facts") if isinstance(person.get("facts"), dict) else {}
    if info_focus in {"relationship", "full", "summary"}:
        for key, value in facts.items():
            clean_key = str(key or "").strip().replace("_", " ")
            clean_value = str(value or "").strip()
            if clean_key and clean_value:
                parts.append(f"{clean_key}: {clean_value}")
            if len(parts) >= (5 if info_focus == "full" else 3):
                break
    links = person.get("links") if isinstance(person.get("links"), dict) else {}
    if info_focus in {"contact", "full"}:
        for key, value in links.items():
            clean_key = str(key or "").strip()
            clean_value = str(value or "").strip()
            if clean_key and clean_value:
                parts.append(f"{clean_key}: {clean_value}")
            if len(parts) >= (6 if info_focus == "full" else 4):
                break
    return parts


def _person_info_profile_person(profile: dict[str, Any]) -> dict[str, Any] | None:
    person = profile.get("person") if isinstance(profile.get("person"), dict) else None
    return person


def _person_info_profile_chips(profile: dict[str, Any]) -> list[str]:
    status = str(profile.get("status") or "")
    if status == "found":
        person = _person_info_profile_person(profile) or {}
        has_details = any(
            person.get(key)
            for key in ("phone", "address", "age", "where_lives", "relationship", "first_met", "notes")
        ) or bool(person.get("facts")) or bool(person.get("links"))
        return ["people_registry", "profile_details"] if has_details else ["people_registry"]
    if status in {"unavailable", "error"}:
        return ["people_registry_unavailable"]
    return ["profile_missing"]


def _person_info_target_hint(
    selected: dict[str, Any] | None,
    match: dict[str, Any] | None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "mode": "person_info",
        "crosshair": {"style": "tiny_center_reticle", "center_norm": [0.5, 0.5]},
    }
    if not selected:
        return {**base, "status": "no_face", "zoom": {"enabled": False}}
    base.update(
        {
            "status": "identified" if match else "candidate",
            "target_id": selected.get("target_id"),
            "anonymous_id": selected.get("anonymous_id"),
            "display_name": selected.get("display_name") or (match or {}).get("display_name"),
            "contact_id": selected.get("contact_id") or (match or {}).get("contact_id"),
            "identity_confidence": selected.get("identity_confidence") or (match or {}).get("confidence"),
            "bbox": selected.get("bbox"),
            "bbox_norm": selected.get("bbox_norm"),
            "zone": selected.get("zone"),
            "aim": selected.get("aim"),
            "zoom": selected.get("zoom") if isinstance(selected.get("zoom"), dict) else {"enabled": False},
        }
    )
    return {key: value for key, value in base.items() if value is not None}


def _person_info_selection_hint(
    *,
    candidates: list[dict[str, Any]],
    known_people: list[dict[str, Any]],
) -> dict[str, Any]:
    known_by_candidate = {
        str(item.get("candidate_id") or ""): item
        for item in known_people
        if str(item.get("candidate_id") or "").strip()
    }
    return {
        "mode": "person_info",
        "status": "selection_required",
        "message": "Multiple visible people; ask by displayed name or anonymous ID.",
        "crosshair": {"style": "tiny_center_reticle", "center_norm": [0.5, 0.5]},
        "candidate_count": len(candidates),
        "known_count": len(known_people),
        "candidates": [
            {
                **_hud_candidate_summary(candidate),
                "display_name": (
                    known_by_candidate.get(str(candidate.get("target_id") or ""), {}).get("display_name")
                    or candidate.get("display_name")
                ),
                "profile_status": (
                    (
                        known_by_candidate.get(str(candidate.get("target_id") or ""), {}).get("profile")
                        if isinstance(known_by_candidate.get(str(candidate.get("target_id") or ""), {}).get("profile"), dict)
                        else {}
                    ).get("status")
                ),
            }
            for candidate in candidates
        ],
        "zoom": {"enabled": False},
    }


def _safe_confidence_percent(value: Any) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return int(round(_clamp(number, minimum=0.0, maximum=1.0) * 100))


def _short_text(value: str, *, max_chars: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(0, max_chars - 3)].rstrip(" ;,.") + "..."


def _skill_args_summary(args: dict[str, Any]) -> dict[str, Any]:
    """Keep replay useful without copying raw user names/profile text."""

    summary: dict[str, Any] = {
        "has_query": bool(str(args.get("query") or args.get("question") or args.get("focus") or "").strip()),
        "target_name_present": bool(str(args.get("target_name") or "").strip()),
    }
    for key in (
        "target_type",
        "identity_query",
        "info_focus",
        "scan_mode",
        "media_mode",
        "max_candidates",
        "snapshot_sample_count",
        "snapshot_min_new_frames",
        "timeout_ms",
        "fps",
    ):
        if key in args:
            summary[key] = args.get(key)
    return {key: value for key, value in summary.items() if value is not None}


def _skill_result_summary(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"present": False}
    hud = result.get("hud") if isinstance(result.get("hud"), dict) else {}
    cloud_result = result.get("cloud_result") if isinstance(result.get("cloud_result"), dict) else {}
    cloud_gateway = result.get("cloud_gateway") if isinstance(result.get("cloud_gateway"), dict) else {}
    identity_provider = result.get("identity_provider") if isinstance(result.get("identity_provider"), dict) else {}
    identity_match = result.get("identity_match") if isinstance(result.get("identity_match"), dict) else {}
    detector_status = result.get("detector_status") if isinstance(result.get("detector_status"), dict) else {}
    profile = result.get("profile") if isinstance(result.get("profile"), dict) else {}
    memory = result.get("memory") if isinstance(result.get("memory"), dict) else {}
    summary: dict[str, Any] = {
        "present": True,
        "answer_present": bool(str(result.get("answer") or result.get("user_message") or result.get("summary") or "").strip()),
        "hud_present": bool(hud),
        "hud_answer_present": bool(str(hud.get("answer_strip") or "").strip()),
        "hud_chip_count": len(hud.get("edge_chips") or []) if isinstance(hud.get("edge_chips"), list) else 0,
        "hud_thumbnail_count": len(hud.get("thumbnails") or []) if isinstance(hud.get("thumbnails"), list) else 0,
        "target_hint_present": isinstance(hud.get("target_hint") or result.get("target_hint"), dict),
        "preview_present": isinstance(result.get("preview"), dict),
        "snapshot_id_present": bool(result.get("snapshot_id")),
        "candidate_count": _safe_len(result.get("candidates")),
        "known_people_count": _safe_len(result.get("known_people")),
        "known_person": result.get("known_person") if isinstance(result.get("known_person"), bool) else None,
        "count_present": isinstance(result.get("count"), int),
        "cloud_gateway_status": cloud_gateway.get("status"),
        "cloud_result_status": cloud_result.get("status"),
        "cloud_result_confidence": _round_float(cloud_result.get("confidence")),
        "identity_provider_status": identity_provider.get("status"),
        "identity_provider_match_count": _to_nonnegative_int(identity_provider.get("match_count")),
        "identity_provider_candidate_vector_count": _to_nonnegative_int(identity_provider.get("candidate_vector_count")),
        "identity_provider_low_quality_count": _to_nonnegative_int(identity_provider.get("low_quality_candidate_count")),
        "identity_match_present": bool(identity_match),
        "identity_match_confidence": _round_float(identity_match.get("confidence")),
        "profile_status": profile.get("status"),
        "memory_status": memory.get("status"),
        "detector_status": detector_status.get("status"),
        "detector_ready_for_target_finder": detector_status.get("ready_for_target_finder"),
        "detector_ready_for_person_info": detector_status.get("ready_for_person_info"),
        "confirmed_match_count": _to_nonnegative_int(result.get("confirmed_match_count")),
        "missing_runtime": result.get("missing_runtime"),
        "required_runtime": result.get("required_runtime"),
    }
    return {key: value for key, value in summary.items() if value is not None}


def _skill_error_summary(error: Any) -> dict[str, Any] | None:
    if not isinstance(error, dict):
        return None
    summary = {
        "code": error.get("code"),
        "has_message": bool(str(error.get("message") or "").strip()),
        "detail_count": _safe_len(error.get("details")),
    }
    return {key: value for key, value in summary.items() if value is not None}


def _safe_len(value: Any) -> int:
    return len(value) if isinstance(value, (list, tuple, dict)) else 0


def _round_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return round(parsed, 4)


def _to_nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _cloud_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "candidate_id": candidate.get("target_id"),
        "class": candidate.get("label"),
        "zone": candidate.get("zone"),
        "confidence": candidate.get("confidence"),
        "crop_ref": candidate.get("crop_ref"),
        "attributes": candidate.get("attributes") if isinstance(candidate.get("attributes"), dict) else {},
        "match_status": candidate.get("match_status"),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _cloud_candidate_from_object(item: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "candidate_id": item.get("object_id"),
        "class": item.get("label"),
        "zone": item.get("zone"),
        "confidence": item.get("confidence"),
        "crop_ref": item.get("crop_ref"),
        "attributes": item.get("attributes") if isinstance(item.get("attributes"), dict) else {},
        "track_id": item.get("track_id"),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _find_snapshot_target(snapshot: dict[str, Any] | None, target_id: str) -> dict[str, Any] | None:
    if not snapshot:
        return None
    for item in snapshot.get("objects") or []:
        if not isinstance(item, dict):
            continue
        if item.get("object_id") == target_id or item.get("track_id") == target_id:
            return item
    return None


def _cloud_edge_chips(cloud_result: dict[str, Any] | None) -> list[str]:
    if not cloud_result:
        return ["needs_cloud"]
    status = cloud_result.get("status")
    if status in {"blocked", "error"}:
        return ["needs_cloud", "cloud_unavailable"]
    return ["needs_cloud", "cloud_result"]
