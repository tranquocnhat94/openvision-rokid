from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .openai_realtime_skills import DEFAULT_REALTIME_SKILL_INSTRUCTIONS

DEFAULT_ROUTE_TRANSCRIPTION_PROMPT = (
    "Transcribe spoken Vietnamese for smart glasses. Prefer natural Vietnamese with proper "
    "diacritics. Ignore brief English filler or unrelated foreign words. If the speech is "
    "unclear, fragmented, or not Vietnamese, return an empty string."
)

DEFAULT_LIVE_CAPTION_PROMPT = (
    "Transcribe ongoing spoken Vietnamese only. Return only the spoken Vietnamese transcript "
    "with proper diacritics. Do not repeat instructions, English prompt text, or system text. "
    "If the speech is unclear, fragmented, or not Vietnamese, return an empty string."
)

DEFAULT_REALTIME_SKILL_MODEL = "gpt-realtime-1.5"

VOICE_CONFIG_STRING_KEYS = (
    "asrBackend",
    "openaiBaseUrl",
    "openaiRealtimeWsUrl",
    "transcriptionModel",
    "openaiTranscriptionPrompt",
    "chatModel",
    "languageHint",
    "routerSystemPrompt",
    "openaiRealtimeVoiceModel",
    "openaiRealtimeSkillInstructions",
    "openaiVisionModel",
    "realtimeSkillTurnDetection",
    "realtimeSkillSemanticEagerness",
    "browserRealtimeRouteTurnDetection",
    "localBackendProfile",
    "localHotwords",
    "localRequestFormat",
    "localTranscribeUrl",
    "localHealthUrl",
    "localWarmUrl",
    "localStartCommand",
    "localStopCommand",
    "localCommandTemplate",
    "localResponseTextPath",
    "realtimeNoiseReduction",
    "liveCaptionModel",
    "openaiLiveCaptionPrompt",
)

VOICE_CONFIG_BOOL_KEYS = (
    "enableOpenAI",
    "allowOpenAITranscriptionFallback",
    "allowOpenAIRouterFallback",
    "autoWakeOnSession",
    "realtimeIncludeLogprobs",
    "realtimeSkillCompleteToolTurn",
    "realtimeSkillRespondAfterTool",
    "liveCaptionsEnabled",
    "routeSpeechHudEnabled",
    "localPartialEnabled",
    "browserRealtimeSkillUseTranscriptRoute",
    "localPartialVadFilter",
    "openaiVisionReasoningEnabled",
)

VOICE_CONFIG_INT_KEYS = (
    "minSegmentMs",
    "maxSegmentMs",
    "idleFlushMs",
    "fastMinSegmentMs",
    "rollingFlushMs",
    "segmentOverlapMs",
    "maxBufferedMs",
    "loopIntervalMs",
    "silenceFloor",
    "backendIdleUnloadMs",
    "backendStartupTimeoutMs",
    "localHealthCacheMs",
    "realtimeChunkMs",
    "realtimeVadPrefixPaddingMs",
    "realtimeVadSilenceDurationMs",
    "realtimePartialDebounceMs",
    "realtimeReplayMs",
    "browserRealtimeSkillReplayMs",
    "browserRealtimeRouteCommitMs",
    "browserRealtimeRouteMinCommitMs",
    "browserRealtimeRouteMinVoicedMs",
    "browserRealtimeRouteSilenceCommitMs",
    "realtimeSpeechIdleCloseMs",
    "browserRealtimeSkillIdleCloseMs",
    "realtimeSkillResponseDebounceMs",
    "realtimeSkillPingMs",
    "liveCaptionCommitMs",
    "liveCaptionMinCommitMs",
    "liveCaptionSilenceCommitMs",
    "liveCaptionReplayMs",
    "localPartialProbeMs",
    "localPartialMinMs",
    "localPartialWindowMs",
    "localPartialIdleClearMs",
    "localPartialBeamSize",
    "minVoicedSegmentMs",
    "minVoicedHoldIdleMs",
    "openaiVisionMaxCandidates",
    "openaiVisionMaxImages",
    "openaiVisionCropMaxSidePx",
)

VOICE_CONFIG_FLOAT_KEYS = (
    "realtimeVadThreshold",
    "browserRealtimeSkillMinNonSilentRatio",
)


def _bool_env(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw not in ("0", "false", "no", "off", "")


def _json_env(name: str, default: dict[str, str]) -> dict[str, str]:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return dict(default)
    try:
        payload = json.loads(raw)
    except Exception:
        return dict(default)
    if not isinstance(payload, dict):
        return dict(default)
    return {str(key): str(value) for key, value in payload.items()}


def load_voice_runtime_config(config_path: Path) -> dict[str, Any]:
    defaults = {
        "asrBackend": os.getenv("ROKID_ASR_BACKEND", "openai_realtime_skills").strip(),
        "enableOpenAI": _bool_env("ROKID_ENABLE_OPENAI", True),
        "allowOpenAITranscriptionFallback": _bool_env("ROKID_ALLOW_OPENAI_STT_FALLBACK", False),
        "allowOpenAIRouterFallback": _bool_env("ROKID_ALLOW_OPENAI_ROUTER_FALLBACK", False),
        "openaiApiKey": os.getenv("OPENAI_API_KEY", "").strip(),
        "openaiBaseUrl": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
        "openaiRealtimeWsUrl": os.getenv("ROKID_OPENAI_REALTIME_WS_URL", "").strip(),
        "transcriptionModel": os.getenv("ROKID_OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe").strip(),
        "openaiTranscriptionPrompt": os.getenv(
            "ROKID_OPENAI_TRANSCRIPTION_PROMPT",
            DEFAULT_ROUTE_TRANSCRIPTION_PROMPT,
        ).strip(),
        "liveCaptionsEnabled": _bool_env("ROKID_LIVE_CAPTIONS_ENABLED", False),
        "routeSpeechHudEnabled": _bool_env("ROKID_ROUTE_SPEECH_HUD_ENABLED", True),
        "localPartialEnabled": _bool_env("ROKID_LOCAL_PARTIAL_ENABLED", False),
        "browserRealtimeSkillUseTranscriptRoute": _bool_env(
            "ROKID_BROWSER_REALTIME_SKILL_USE_TRANSCRIPT_ROUTE",
            True,
        ),
        "browserRealtimeRouteTurnDetection": os.getenv(
            "ROKID_BROWSER_REALTIME_ROUTE_TURN_DETECTION",
            "manual",
        ).strip(),
        "liveCaptionModel": os.getenv("ROKID_OPENAI_LIVE_CAPTION_MODEL", "gpt-4o-transcribe").strip(),
        "openaiLiveCaptionPrompt": os.getenv(
            "ROKID_OPENAI_LIVE_CAPTION_PROMPT",
            DEFAULT_LIVE_CAPTION_PROMPT,
        ).strip(),
        "chatModel": os.getenv("ROKID_OPENAI_CHAT_MODEL", "gpt-4.1-mini").strip(),
        "languageHint": os.getenv("ROKID_VOICE_LANGUAGE_HINT", "vi").strip(),
        "minSegmentMs": int(os.getenv("ROKID_VOICE_MIN_SEGMENT_MS", "900")),
        "maxSegmentMs": int(os.getenv("ROKID_VOICE_MAX_SEGMENT_MS", "1800")),
        "idleFlushMs": int(os.getenv("ROKID_VOICE_IDLE_FLUSH_MS", "220")),
        "fastMinSegmentMs": int(os.getenv("ROKID_VOICE_FAST_MIN_SEGMENT_MS", "320")),
        "rollingFlushMs": int(os.getenv("ROKID_VOICE_ROLLING_FLUSH_MS", "520")),
        "segmentOverlapMs": int(os.getenv("ROKID_VOICE_SEGMENT_OVERLAP_MS", "200")),
        "minVoicedSegmentMs": int(os.getenv("ROKID_VOICE_MIN_VOICED_SEGMENT_MS", "640")),
        "minVoicedHoldIdleMs": int(os.getenv("ROKID_VOICE_MIN_VOICED_HOLD_IDLE_MS", "260")),
        "maxBufferedMs": int(os.getenv("ROKID_VOICE_MAX_BUFFERED_MS", "8000")),
        "loopIntervalMs": int(os.getenv("ROKID_VOICE_LOOP_INTERVAL_MS", "40")),
        "silenceFloor": int(os.getenv("ROKID_VOICE_SILENCE_FLOOR", "72")),
        "backendIdleUnloadMs": int(os.getenv("ROKID_VOICE_BACKEND_IDLE_UNLOAD_MS", "60000")),
        "backendStartupTimeoutMs": int(os.getenv("ROKID_VOICE_BACKEND_STARTUP_TIMEOUT_MS", "15000")),
        "localHealthCacheMs": int(os.getenv("ROKID_LOCAL_ASR_HEALTH_CACHE_MS", "1000")),
        "autoWakeOnSession": _bool_env("ROKID_VOICE_AUTO_WAKE_ON_SESSION", True),
        "realtimeChunkMs": int(os.getenv("ROKID_REALTIME_CHUNK_MS", "80")),
        "realtimeVadThreshold": float(os.getenv("ROKID_REALTIME_VAD_THRESHOLD", "0.45")),
        "realtimeVadPrefixPaddingMs": int(os.getenv("ROKID_REALTIME_VAD_PREFIX_PADDING_MS", "320")),
        "realtimeVadSilenceDurationMs": int(os.getenv("ROKID_REALTIME_VAD_SILENCE_MS", "420")),
        "realtimePartialDebounceMs": int(os.getenv("ROKID_REALTIME_PARTIAL_DEBOUNCE_MS", "100")),
        "realtimeReplayMs": int(os.getenv("ROKID_REALTIME_REPLAY_MS", "1200")),
        "browserRealtimeSkillReplayMs": int(
            os.getenv("ROKID_BROWSER_REALTIME_SKILL_REPLAY_MS", "4000")
        ),
        "browserRealtimeRouteCommitMs": int(
            os.getenv("ROKID_BROWSER_REALTIME_ROUTE_COMMIT_MS", "2200")
        ),
        "browserRealtimeRouteMinCommitMs": int(
            os.getenv("ROKID_BROWSER_REALTIME_ROUTE_MIN_COMMIT_MS", "640")
        ),
        "browserRealtimeRouteMinVoicedMs": int(
            os.getenv("ROKID_BROWSER_REALTIME_ROUTE_MIN_VOICED_MS", "320")
        ),
        "browserRealtimeRouteSilenceCommitMs": int(
            os.getenv("ROKID_BROWSER_REALTIME_ROUTE_SILENCE_COMMIT_MS", "420")
        ),
        "realtimeSpeechIdleCloseMs": int(os.getenv("ROKID_REALTIME_SPEECH_IDLE_CLOSE_MS", "6000")),
        "browserRealtimeSkillIdleCloseMs": int(
            os.getenv("ROKID_BROWSER_REALTIME_SKILL_IDLE_CLOSE_MS", "15000")
        ),
        "realtimeSkillResponseDebounceMs": int(
            os.getenv("ROKID_REALTIME_SKILL_RESPONSE_DEBOUNCE_MS", "700")
        ),
        "realtimeSkillPingMs": int(os.getenv("ROKID_REALTIME_SKILL_PING_MS", "8000")),
        "browserRealtimeSkillMinNonSilentRatio": float(
            os.getenv("ROKID_BROWSER_REALTIME_SKILL_MIN_NON_SILENT_RATIO", "0.05")
        ),
        "liveCaptionCommitMs": int(os.getenv("ROKID_LIVE_CAPTION_COMMIT_MS", "560")),
        "liveCaptionMinCommitMs": int(os.getenv("ROKID_LIVE_CAPTION_MIN_COMMIT_MS", "240")),
        "liveCaptionSilenceCommitMs": int(os.getenv("ROKID_LIVE_CAPTION_SILENCE_COMMIT_MS", "220")),
        "liveCaptionReplayMs": int(os.getenv("ROKID_LIVE_CAPTION_REPLAY_MS", "1200")),
        "localPartialProbeMs": int(os.getenv("ROKID_LOCAL_PARTIAL_PROBE_MS", "280")),
        "localPartialMinMs": int(os.getenv("ROKID_LOCAL_PARTIAL_MIN_MS", "320")),
        "localPartialWindowMs": int(os.getenv("ROKID_LOCAL_PARTIAL_WINDOW_MS", "1200")),
        "localPartialIdleClearMs": int(os.getenv("ROKID_LOCAL_PARTIAL_IDLE_CLEAR_MS", "1400")),
        "localPartialBeamSize": int(os.getenv("ROKID_LOCAL_PARTIAL_BEAM_SIZE", "5")),
        "localPartialVadFilter": _bool_env("ROKID_LOCAL_PARTIAL_VAD_FILTER", True),
        "realtimeNoiseReduction": os.getenv("ROKID_REALTIME_NOISE_REDUCTION", "near_field").strip(),
        "realtimeIncludeLogprobs": _bool_env("ROKID_REALTIME_INCLUDE_LOGPROBS", False),
        "realtimeSkillCompleteToolTurn": _bool_env("ROKID_REALTIME_SKILL_COMPLETE_TOOL_TURN", True),
        "realtimeSkillRespondAfterTool": _bool_env("ROKID_REALTIME_SKILL_RESPOND_AFTER_TOOL", False),
        "localBackendProfile": os.getenv("ROKID_LOCAL_ASR_PROFILE", "vi_small_low_power").strip(),
        "localHotwords": os.getenv("ROKID_LOCAL_ASR_HOTWORDS", "").strip(),
        "localRequestFormat": os.getenv("ROKID_LOCAL_ASR_REQUEST_FORMAT", "binary_wav").strip(),
        "localTranscribeUrl": os.getenv("ROKID_LOCAL_ASR_TRANSCRIBE_URL", "").strip(),
        "localHealthUrl": os.getenv("ROKID_LOCAL_ASR_HEALTH_URL", "").strip(),
        "localWarmUrl": os.getenv("ROKID_LOCAL_ASR_WARM_URL", "").strip(),
        "localStartCommand": os.getenv("ROKID_LOCAL_ASR_START_CMD", "").strip(),
        "localStopCommand": os.getenv("ROKID_LOCAL_ASR_STOP_CMD", "").strip(),
        "localCommandTemplate": os.getenv("ROKID_LOCAL_ASR_COMMAND_TEMPLATE", "").strip(),
        "localResponseTextPath": os.getenv("ROKID_LOCAL_ASR_RESPONSE_TEXT_PATH", "text").strip(),
        "localHttpHeaders": _json_env("ROKID_LOCAL_ASR_HTTP_HEADERS", {}),
        "routerSystemPrompt": os.getenv(
            "ROKID_OPENAI_ROUTER_PROMPT",
            (
                "You are the Jetson voice router for Rokid smart glasses. "
                "Return compact JSON only with keys: intent, mode, target_query, answer, confidence. "
                "Prefer one of these modes when relevant: standby, scene_monitor, visual_assistant, "
                "focus_bubble, ar_radar, alert_burst, traffic_count. "
                "Keep answer under 20 words."
            ),
        ).strip(),
        "openaiRealtimeVoiceModel": os.getenv(
            "ROKID_OPENAI_REALTIME_VOICE_MODEL",
            DEFAULT_REALTIME_SKILL_MODEL,
        ).strip(),
        "openaiRealtimeSkillInstructions": os.getenv(
            "ROKID_OPENAI_REALTIME_SKILL_INSTRUCTIONS",
            DEFAULT_REALTIME_SKILL_INSTRUCTIONS,
        ).strip(),
        "openaiVisionModel": os.getenv("ROKID_OPENAI_VISION_MODEL", "gpt-5.4").strip(),
        "openaiVisionReasoningEnabled": _bool_env("ROKID_OPENAI_VISION_REASONING_ENABLED", True),
        "openaiVisionMaxCandidates": int(os.getenv("ROKID_OPENAI_VISION_MAX_CANDIDATES", "3")),
        "openaiVisionMaxImages": int(os.getenv("ROKID_OPENAI_VISION_MAX_IMAGES", "3")),
        "openaiVisionCropMaxSidePx": int(os.getenv("ROKID_OPENAI_VISION_CROP_MAX_SIDE", "512")),
        "realtimeSkillTurnDetection": os.getenv(
            "ROKID_OPENAI_REALTIME_SKILL_TURN_DETECTION",
            "semantic_vad",
        ).strip(),
        "realtimeSkillSemanticEagerness": os.getenv(
            "ROKID_OPENAI_REALTIME_SKILL_EAGERNESS",
            "medium",
        ).strip(),
    }
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            data = None
        if isinstance(data, dict):
            deprecated_keys = {"immichBaseUrl", "immichApiKey", "enableSelectedTargetMemoryLookup"}
            defaults.update({key: value for key, value in data.items() if key not in deprecated_keys})
    return defaults


def merge_voice_runtime_config(current_config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    next_config = dict(current_config)
    for key in VOICE_CONFIG_STRING_KEYS:
        if key in payload and isinstance(payload[key], str):
            next_config[key] = payload[key].strip()
    for key in VOICE_CONFIG_BOOL_KEYS:
        if key in payload:
            next_config[key] = bool(payload[key])
    for key in VOICE_CONFIG_INT_KEYS:
        if key in payload:
            try:
                next_config[key] = int(payload[key])
            except Exception:
                continue
    for key in VOICE_CONFIG_FLOAT_KEYS:
        if key in payload:
            try:
                next_config[key] = float(payload[key])
            except Exception:
                continue
    if "localHttpHeaders" in payload and isinstance(payload["localHttpHeaders"], dict):
        next_config["localHttpHeaders"] = {
            str(key): str(value) for key, value in payload["localHttpHeaders"].items()
        }
    if "openaiApiKey" in payload:
        provided = str(payload["openaiApiKey"] or "").strip()
        if provided and "*" not in provided:
            next_config["openaiApiKey"] = provided
    return next_config


def active_backend_kind(config: dict[str, Any]) -> str:
    backend = str(config.get("asrBackend") or "openai_realtime_skills").strip()
    if backend == "hybrid_local_openai":
        return "local_first"
    return backend


def uses_realtime_backend(config: dict[str, Any]) -> bool:
    return str(config.get("asrBackend") or "").strip() == "openai_realtime"


def uses_realtime_skill_backend(config: dict[str, Any]) -> bool:
    return str(config.get("asrBackend") or "").strip() == "openai_realtime_skills"


def uses_any_realtime_backend(config: dict[str, Any]) -> bool:
    return uses_realtime_backend(config) or uses_realtime_skill_backend(config)


def uses_local_backend(config: dict[str, Any]) -> bool:
    return str(config.get("asrBackend") or "").strip() in {"local_http", "local_command", "hybrid_local_openai"}


def local_backend_configured(config: dict[str, Any]) -> bool:
    return bool(
        str(config.get("localTranscribeUrl") or "").strip()
        or str(config.get("localCommandTemplate") or "").strip()
        or str(config.get("localStartCommand") or "").strip()
    )


def is_any_backend_configured(config: dict[str, Any], *, has_api_key: bool) -> bool:
    backend = str(config.get("asrBackend") or "").strip()
    if backend == "disabled":
        return False
    if backend in {"openai_realtime", "openai_realtime_skills", "openai"}:
        return has_api_key
    if backend == "local_http":
        return local_backend_configured(config)
    if backend == "local_command":
        return bool(str(config.get("localCommandTemplate") or "").strip())
    if backend == "hybrid_local_openai":
        return local_backend_configured(config) or has_api_key
    return False
