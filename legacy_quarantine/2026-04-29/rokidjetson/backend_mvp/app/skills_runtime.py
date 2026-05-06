from __future__ import annotations

import json
import re
import time
import unicodedata
from typing import Any, Callable

from .vision_skill_runtime import OpenAIVisionSkillRuntime


def _now_ms() -> int:
    return int(time.time() * 1000)


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _norm_text(value: str) -> str:
    lowered = _strip_accents(value).lower().replace("đ", "d")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def _clean_query(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip(" .,!?:;-_")
    return cleaned


def _shorten(text: str, limit: int = 72) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: max(0, limit - 1)].rstrip()}…"


def _target_query_is_specific(value: str) -> bool:
    tokens = [token for token in _norm_text(value).split(" ") if token]
    if len(tokens) < 2:
        return False
    generic_tokens = {"tim", "kiem", "nguoi", "vat", "do", "nay", "kia", "o", "ben", "phia"}
    informative = [token for token in tokens if token not in generic_tokens]
    return len(informative) >= 1 and not (len(tokens) == 2 and tokens[-1] in {"nguoi", "vat", "do"})


class JetsonSkillRegistry:
    def __init__(
        self,
        *,
        config_provider: Callable[[], dict[str, Any]],
        scene_context_provider: Callable[[str], dict[str, Any]],
        vision_context_provider: Callable[[str, str | None, str | None], dict[str, Any]],
        command_handler: Callable[[dict[str, Any]], None],
        log_handler: Callable[[str, str, dict[str, Any]], None],
    ) -> None:
        self._config_provider = config_provider
        self._scene_context_provider = scene_context_provider
        self._vision_context_provider = vision_context_provider
        self._command_handler = command_handler
        self._log_handler = log_handler
        self._vision_runtime = OpenAIVisionSkillRuntime(
            config_provider=self._config_provider,
            log_handler=self._log_handler,
        )

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "set_jetson_mode",
                "description": (
                    "Switch Jetson into one of the built-in glasses capabilities. "
                    "Use this only for explicit mode-switch commands like traffic counting, scene monitor, radar, "
                    "focus, or a clearly requested return to standby. Never use standby as a fallback for unclear audio."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": [
                                "scene_monitor",
                                "visual_assistant",
                                "focus_bubble",
                                "ar_radar",
                                "alert_burst",
                                "traffic_count",
                                "standby",
                            ],
                            "description": "Capability mode to activate on Jetson.",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Short Vietnamese reason or status line for the HUD.",
                        },
                    },
                    "required": ["mode"],
                },
            },
            {
                "type": "function",
                "name": "query_scene",
                "description": (
                    "Ask Jetson to describe or inspect the current scene. "
                    "Use for commands like 'nhin phia truoc co gi', 'co gi dang xay ra', or 'mo ta canh hien tai'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "focus": {
                            "type": "string",
                            "description": "Optional focus for what the user cares about in the current scene.",
                        }
                    },
                },
            },
            {
                "type": "function",
                "name": "search_target",
                "description": (
                    "Start or update target search on Jetson using a concrete natural-language description "
                    "such as a person, object, clothing, or combination of attributes. "
                    "This tool can use local tracked candidates first, then cloud visual reasoning only if Jetson "
                    "still needs help choosing the right track."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_query": {
                            "type": "string",
                            "description": (
                                "Vietnamese description of the target to find, such as "
                                "'nguoi ao vang deo kinh' or 'tui den o ben trai'."
                            ),
                        }
                    },
                    "required": ["target_query"],
                },
            },
            {
                "type": "function",
                "name": "analyze_selected_target",
                "description": (
                    "Answer a visual follow-up question about the currently selected target, such as "
                    "whether this person appears to wear glasses, what they carry, visible clothing, "
                    "or likely male/female presentation. Use only when the user refers to the already selected target."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Vietnamese follow-up question about the selected visible target.",
                        }
                    },
                    "required": ["question"],
                },
            },
            {
                "type": "function",
                "name": "clear_target_search",
                "description": "Stop the current target search and clear any active search target on Jetson.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Optional short status line for the HUD.",
                        }
                    },
                },
            },
        ]

    def execute(
        self,
        *,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any] | str | None,
        source: str,
    ) -> dict[str, Any]:
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments) if arguments.strip() else {}
            except Exception:
                parsed = {}
        elif isinstance(arguments, dict):
            parsed = dict(arguments)
        else:
            parsed = {}

        normalized_name = str(tool_name or "").strip()
        self._log_handler(
            session_id,
            "voice_skill_requested",
            {
                "tool": normalized_name,
                "arguments": parsed,
                "source": source,
            },
        )

        if normalized_name == "set_jetson_mode":
            return self._set_mode(session_id=session_id, source=source, arguments=parsed)
        if normalized_name == "query_scene":
            return self._query_scene(session_id=session_id, source=source, arguments=parsed)
        if normalized_name == "search_target":
            return self._search_target(session_id=session_id, source=source, arguments=parsed)
        if normalized_name == "analyze_selected_target":
            return self._analyze_selected_target(session_id=session_id, source=source, arguments=parsed)
        if normalized_name == "clear_target_search":
            return self._clear_target_search(session_id=session_id, source=source, arguments=parsed)

        return {
            "ok": False,
            "error": f"Unknown tool: {normalized_name}",
        }

    def _dispatch_action(
        self,
        *,
        session_id: str,
        source: str,
        transcript: str,
        intent: str,
        mode: str | None,
        target_query: str | None,
        status_text: str,
        confidence: float = 1.0,
        answer: str = "",
        selected_track_id: str | None = None,
        selected_target_label: str | None = None,
        selected_target_summary: str | None = None,
    ) -> dict[str, Any]:
        scene = self._scene_context_provider(session_id)
        payload = {
            "timestampMs": _now_ms(),
            "sessionId": session_id,
            "transcript": transcript,
            "source": source,
            "intent": intent,
            "mode": mode,
            "targetQuery": target_query,
            "answer": answer,
            "statusText": status_text,
            "confidence": confidence,
            "sceneSummary": str(scene.get("summary") or "Scene live"),
            "selectedTrackId": selected_track_id,
            "selectedTargetLabel": selected_target_label,
            "selectedTargetSummary": selected_target_summary,
        }
        self._command_handler(payload)
        self._log_handler(
            session_id,
            "voice_skill_dispatched",
            {
                "toolSource": source,
                "intent": intent,
                "mode": mode,
                "targetQuery": target_query,
                "statusText": status_text,
                "selectedTrackId": selected_track_id,
                "selectedTargetLabel": selected_target_label,
            },
        )
        return payload

    def _set_mode(
        self,
        *,
        session_id: str,
        source: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        mode = str(arguments.get("mode") or "").strip()
        if not mode:
            return {"ok": False, "error": "Missing mode"}
        if mode == "standby" and source == "openai_realtime_skills":
            scene = self._scene_context_provider(session_id)
            current_mode = str(scene.get("mode") or "").strip()
            if current_mode == "standby":
                self._log_handler(
                    session_id,
                    "voice_skill_rejected",
                    {
                        "tool": "set_jetson_mode",
                        "mode": mode,
                        "reason": "ambiguous_standby_while_already_standby",
                        "source": source,
                    },
                )
                return {
                    "ok": False,
                    "error": "ambiguous_standby_while_already_standby",
                    "statusText": "Chua nghe ro lenh. Hay noi ngan hon.",
                }
        reason = _shorten(str(arguments.get("reason") or "").strip(), limit=72)
        status_text = reason or {
            "standby": "Da ve che do cho.",
            "scene_monitor": "Da bat scene monitor.",
            "visual_assistant": "Da bat ho tro hinh anh.",
            "focus_bubble": "Da bat Focus Bubble.",
            "ar_radar": "Da bat AR radar.",
            "alert_burst": "Da bat Silent Alert Burst.",
            "traffic_count": "Da bat dem phuong tien.",
        }.get(mode, f"Da chuyen sang {mode}.")
        self._dispatch_action(
            session_id=session_id,
            source=source,
            transcript=reason or mode,
            intent="mode_change",
            mode=mode,
            target_query=None,
            status_text=status_text,
        )
        return {
            "ok": True,
            "mode": mode,
            "statusText": status_text,
        }

    def _query_scene(
        self,
        *,
        session_id: str,
        source: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        scene = self._scene_context_provider(session_id)
        focus = _clean_query(str(arguments.get("focus") or ""))
        summary = _shorten(str(scene.get("summary") or scene.get("headline") or "Scene live"), limit=84)
        status_text = summary if not focus else _shorten(f"{focus}: {summary}", limit=84)
        self._dispatch_action(
            session_id=session_id,
            source=source,
            transcript=focus or "scene query",
            intent="scene_query",
            mode="visual_assistant",
            target_query=None,
            status_text=status_text,
            confidence=0.98,
        )
        return {
            "ok": True,
            "focus": focus or None,
            "summary": str(scene.get("summary") or ""),
            "headline": str(scene.get("headline") or ""),
            "counts": scene.get("counts") or {},
            "topLabels": scene.get("topLabels") or [],
        }

    def _search_target(
        self,
        *,
        session_id: str,
        source: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        target_query = _clean_query(str(arguments.get("target_query") or arguments.get("query") or ""))
        if not _target_query_is_specific(target_query):
            return {
                "ok": False,
                "error": "Target query is too vague",
                "targetQuery": target_query,
                "statusText": "Mo ta muc tieu cu the hon de Jetson khoa dung doi tuong.",
            }
        vision_context = self._vision_context_provider(session_id, target_query, None)
        resolved = self._vision_runtime.resolve_target(
            session_id=session_id,
            target_query=target_query,
            context=vision_context,
        )
        status_text = _shorten(str(resolved.get("statusText") or f"Dang tim {target_query}."), limit=72)
        self._dispatch_action(
            session_id=session_id,
            source=source,
            transcript=target_query,
            intent="target_search",
            mode="visual_assistant",
            target_query=target_query,
            status_text=status_text,
            confidence=float(resolved.get("confidence") or 0.99),
            selected_track_id=str(resolved.get("selectedTrackId") or "").strip() or None,
            selected_target_label=str(resolved.get("selectedTargetLabel") or "").strip() or None,
            selected_target_summary=str(resolved.get("selectedTargetSummary") or "").strip() or None,
        )
        return {
            "ok": True,
            "targetQuery": target_query,
            "statusText": status_text,
            "candidateCount": int(resolved.get("candidateCount") or 0),
            "selectedTrackId": str(resolved.get("selectedTrackId") or ""),
            "selectedTargetLabel": str(resolved.get("selectedTargetLabel") or ""),
            "selectedTargetSummary": str(resolved.get("selectedTargetSummary") or ""),
            "resolutionSource": str(resolved.get("resolutionSource") or "generic"),
        }

    def _analyze_selected_target(
        self,
        *,
        session_id: str,
        source: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        question = _clean_query(str(arguments.get("question") or arguments.get("query") or ""))
        if not question:
            return {"ok": False, "error": "Missing question"}
        context = self._vision_context_provider(session_id, None, None)
        result = self._vision_runtime.analyze_selected_target(
            session_id=session_id,
            question=question,
            context=context,
        )
        if result.get("ok"):
            selected_track_id = str(result.get("selectedTrackId") or "").strip() or None
            selected_target = context.get("selectedTarget") if isinstance(context, dict) else {}
            self._dispatch_action(
                session_id=session_id,
                source=source,
                transcript=question,
                intent="assistant_query",
                mode="visual_assistant",
                target_query=str(context.get("targetQuery") or "").strip() or None,
                answer=_shorten(str(result.get("answer") or "").strip(), limit=96),
                status_text="Da phan tich doi tuong dang chon.",
                confidence=float(result.get("confidence") or 0.85),
                selected_track_id=selected_track_id,
                selected_target_label=str(selected_target.get("label") or "").strip() or None,
                selected_target_summary=str(selected_target.get("summary") or "").strip() or None,
            )
        return result

    def _clear_target_search(
        self,
        *,
        session_id: str,
        source: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        reason = _shorten(str(arguments.get("reason") or "Da dung tim muc tieu.").strip(), limit=72)
        self._dispatch_action(
            session_id=session_id,
            source=source,
            transcript=reason,
            intent="transcript_only",
            mode=None,
            target_query=None,
            status_text=reason,
            confidence=0.98,
            selected_track_id=None,
            selected_target_label=None,
            selected_target_summary=None,
        )
        return {
            "ok": True,
            "statusText": reason,
        }
