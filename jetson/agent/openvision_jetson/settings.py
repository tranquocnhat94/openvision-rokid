"""Environment-backed settings with secret redaction."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .contracts import SettingsSnapshot, to_jsonable


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    environment: str
    openai_api_key: str | None
    realtime_model: str
    realtime_voice: str
    realtime_url: str
    realtime_max_output_tokens: int = 96
    realtime_voice_output_enabled: bool = False
    debug_stt_enabled: bool = False
    debug_stt_transcribe_url: str = ""
    debug_stt_health_url: str = ""
    debug_stt_warm_url: str = ""
    debug_stt_language: str = "vi"
    debug_stt_profile: str = "v2_debug_sentence"
    debug_stt_beam_size: int = 5
    debug_stt_vad_filter: bool = True
    debug_stt_hotwords: str = ""
    debug_stt_timeout_s: float = 20.0
    debug_stt_min_audio_ms: int = 800
    debug_stt_max_audio_ms: int = 12_000
    debug_stt_auth_token: str | None = None
    debug_stt_auth_token_source: str = "missing"
    openai_key_source: str = "missing"
    openai_key_file: str | None = None
    secret_load_error: str | None = None


def load_runtime_settings() -> RuntimeSettings:
    direct_key = _clean_secret(os.getenv("OPENAI_API_KEY"))
    key_file = _clean_path(os.getenv("OPENAI_API_KEY_FILE"))
    key_source = "missing"
    key_error: str | None = None
    key = direct_key

    if direct_key:
        key_source = "env"
    elif key_file:
        key, key_error = _read_secret_file(key_file)
        key_source = "file" if key else "file_error" if key_error else "missing"

    debug_stt_auth_token, debug_stt_auth_token_source = _load_optional_secret(
        env_name="OPENVISION_DEBUG_STT_AUTH_TOKEN",
        file_env_name="OPENVISION_DEBUG_STT_AUTH_TOKEN_FILE",
    )

    return RuntimeSettings(
        environment=os.getenv("OPENVISION_ENV", "dev"),
        openai_api_key=key,
        realtime_model=os.getenv("OPENVISION_REALTIME_MODEL", "gpt-realtime-1.5"),
        realtime_voice=os.getenv("OPENVISION_REALTIME_VOICE", "marin"),
        realtime_url=os.getenv("OPENVISION_REALTIME_URL", "wss://api.openai.com/v1/realtime"),
        realtime_max_output_tokens=_env_int("OPENVISION_REALTIME_MAX_OUTPUT_TOKENS", 96),
        realtime_voice_output_enabled=_env_bool("OPENVISION_REALTIME_VOICE_OUTPUT_ENABLED", False),
        debug_stt_enabled=_env_bool("OPENVISION_DEBUG_STT_ENABLED", False),
        debug_stt_transcribe_url=os.getenv("OPENVISION_DEBUG_STT_TRANSCRIBE_URL", ""),
        debug_stt_health_url=os.getenv("OPENVISION_DEBUG_STT_HEALTH_URL", ""),
        debug_stt_warm_url=os.getenv("OPENVISION_DEBUG_STT_WARM_URL", ""),
        debug_stt_language=os.getenv("OPENVISION_DEBUG_STT_LANGUAGE", "vi"),
        debug_stt_profile=os.getenv("OPENVISION_DEBUG_STT_PROFILE", "v2_debug_sentence"),
        debug_stt_beam_size=_env_int("OPENVISION_DEBUG_STT_BEAM_SIZE", 5),
        debug_stt_vad_filter=_env_bool("OPENVISION_DEBUG_STT_VAD_FILTER", True),
        debug_stt_hotwords=os.getenv("OPENVISION_DEBUG_STT_HOTWORDS", ""),
        debug_stt_timeout_s=_env_float("OPENVISION_DEBUG_STT_TIMEOUT_S", 20.0),
        debug_stt_min_audio_ms=_env_int("OPENVISION_DEBUG_STT_MIN_AUDIO_MS", 800),
        debug_stt_max_audio_ms=_env_int("OPENVISION_DEBUG_STT_MAX_AUDIO_MS", 12_000),
        debug_stt_auth_token=debug_stt_auth_token,
        debug_stt_auth_token_source=debug_stt_auth_token_source,
        openai_key_source=key_source,
        openai_key_file=key_file,
        secret_load_error=key_error,
    )


def load_settings() -> dict[str, object]:
    runtime = load_runtime_settings()
    snapshot = SettingsSnapshot(
        environment=runtime.environment,
        openai_key_present=bool(runtime.openai_api_key),
        realtime_model=runtime.realtime_model,
        realtime_voice=runtime.realtime_voice,
        realtime_url=runtime.realtime_url,
        realtime_max_output_tokens=runtime.realtime_max_output_tokens,
        realtime_voice_output_enabled=runtime.realtime_voice_output_enabled,
        debug_stt_enabled=runtime.debug_stt_enabled,
        debug_stt_transcribe_url=runtime.debug_stt_transcribe_url,
        debug_stt_health_url=runtime.debug_stt_health_url,
        debug_stt_min_audio_ms=runtime.debug_stt_min_audio_ms,
        debug_stt_max_audio_ms=runtime.debug_stt_max_audio_ms,
        openai_key_source=runtime.openai_key_source,
        secret_load_error=runtime.secret_load_error,
    )
    return to_jsonable(snapshot)


def _clean_secret(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_path(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    return cleaned or None


def _load_optional_secret(*, env_name: str, file_env_name: str) -> tuple[str | None, str]:
    direct_secret = _clean_secret(os.getenv(env_name))
    secret_file = _clean_path(os.getenv(file_env_name))
    if direct_secret:
        return direct_secret, "env"
    if not secret_file:
        return None, "missing"
    secret, error = _read_secret_file(secret_file)
    if secret:
        return secret, "file"
    return None, "file_error" if error else "missing"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _read_secret_file(path: str) -> tuple[str | None, str | None]:
    try:
        secret = Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        return None, exc.__class__.__name__
    return _clean_secret(secret), None
