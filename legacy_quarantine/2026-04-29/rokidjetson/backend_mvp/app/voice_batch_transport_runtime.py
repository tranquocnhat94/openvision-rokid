from __future__ import annotations

import base64
import io
import json
import subprocess
import urllib.error
import urllib.request
import wave
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def deep_get_path(value: Any, path: str) -> Any:
    current = value
    for chunk in [part for part in str(path).split(".") if part]:
        if isinstance(current, dict):
            current = current.get(chunk)
        else:
            return None
    return current


def build_multipart_field(boundary: str, name: str, value: str) -> bytes:
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        f"{value}\r\n"
    ).encode("utf-8")


def build_multipart_file(
    boundary: str,
    name: str,
    filename: str,
    content_type: str,
    payload: bytes,
) -> bytes:
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    return head + payload + b"\r\n"


def pcm_to_wav_bytes(payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sink:
        sink.setnchannels(1)
        sink.setsampwidth(2)
        sink.setframerate(16_000)
        sink.writeframes(payload)
    return buffer.getvalue()


def parse_json_object_fragment(raw: str) -> dict[str, Any]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("JSON object not found")
    return json.loads(raw[start : end + 1])


def extract_local_response_text(raw: bytes, content_type: str, response_text_path: str) -> str:
    if "application/json" in content_type:
        payload = json.loads(raw.decode("utf-8"))
        return str(deep_get_path(payload, response_text_path) or "").strip()
    return raw.decode("utf-8", errors="ignore").strip()


def request_local_http_transcription(
    *,
    config: dict[str, Any],
    session_id: str,
    wav_bytes: bytes,
    partial_mode: bool,
    now_ms: Callable[[], int] = _now_ms,
) -> str:
    url = str(config.get("localTranscribeUrl") or "").strip()
    if not url:
        return ""

    request_format = str(config.get("localRequestFormat") or "binary_wav").strip()
    headers = dict(config.get("localHttpHeaders") or {})
    language = str(config.get("languageHint") or "vi").strip() or "vi"
    hotwords = str(config.get("localHotwords") or "").strip()
    partial_beam_size = max(1, int(config.get("localPartialBeamSize") or 1))
    partial_vad_filter = bool(config.get("localPartialVadFilter", False))
    profile = str(config.get("localBackendProfile") or "")

    if request_format == "binary_wav":
        request_headers = {
            "Content-Type": "audio/wav",
            "X-Rokid-Session-Id": session_id,
            "X-Rokid-Language": language,
            "X-Rokid-Profile": profile,
            **headers,
        }
        if hotwords:
            request_headers["X-Rokid-Hotwords-Base64"] = base64.b64encode(hotwords.encode("utf-8")).decode("ascii")
        if partial_mode:
            request_headers["X-Rokid-Beam-Size"] = str(partial_beam_size)
            request_headers["X-Rokid-Vad-Filter"] = "true" if partial_vad_filter else "false"
        request = urllib.request.Request(url=url, data=wav_bytes, method="POST", headers=request_headers)
    elif request_format == "json_base64":
        payload = {
            "sessionId": session_id,
            "language": language,
            "profile": profile,
            "audioBase64": base64.b64encode(wav_bytes).decode("ascii"),
        }
        if hotwords:
            payload["hotwords"] = hotwords
        if partial_mode:
            payload["beamSize"] = partial_beam_size
            payload["vadFilter"] = partial_vad_filter
        body = json.dumps(payload).encode("utf-8")
        request_headers = {"Content-Type": "application/json", **headers}
        request = urllib.request.Request(url=url, data=body, method="POST", headers=request_headers)
    else:
        boundary = f"rokid-local-{now_ms()}"
        parts = [
            build_multipart_field(boundary, "language", language),
            build_multipart_field(boundary, "session_id", session_id),
            build_multipart_field(boundary, "profile", profile),
            build_multipart_field(boundary, "beam_size", str(partial_beam_size)) if partial_mode else b"",
            build_multipart_field(boundary, "vad_filter", "true" if partial_vad_filter else "false")
            if partial_mode
            else b"",
            build_multipart_file(boundary, "file", "voice.wav", "audio/wav", wav_bytes),
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
        body = b"".join(parts)
        request_headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            **headers,
        }
        request = urllib.request.Request(url=url, data=body, method="POST", headers=request_headers)

    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read()
        content_type = str(response.headers.get("Content-Type") or "")
    return extract_local_response_text(
        raw,
        content_type,
        str(config.get("localResponseTextPath") or "text"),
    )


def request_openai_audio_transcription(
    *,
    config: dict[str, Any],
    api_key: str,
    wav_bytes: bytes,
    now_ms: Callable[[], int] = _now_ms,
) -> dict[str, Any]:
    boundary = f"rokid-{now_ms()}"
    prompt = str(config.get("openaiTranscriptionPrompt") or "").strip()
    parts = [
        build_multipart_field(boundary, "model", str(config["transcriptionModel"])),
        build_multipart_field(boundary, "language", str(config.get("languageHint") or "vi")),
    ]
    if prompt:
        parts.append(build_multipart_field(boundary, "prompt", prompt))
    parts.extend(
        [
            build_multipart_file(boundary, "file", "voice.wav", "audio/wav", wav_bytes),
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    body = b"".join(parts)
    request = urllib.request.Request(
        url=f"{str(config['openaiBaseUrl']).rstrip('/')}/audio/transcriptions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_openai_route_choice(payload: dict[str, Any]) -> dict[str, Any] | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    content = choices[0].get("message", {}).get("content")
    if not isinstance(content, str):
        return None
    try:
        return parse_json_object_fragment(content)
    except Exception:
        return None


def request_openai_route(
    *,
    config: dict[str, Any],
    api_key: str,
    transcript: str,
    scene_summary: str,
) -> dict[str, Any] | None:
    prompt = (
        "Transcript:\n"
        f"{transcript}\n\n"
        "Current scene summary:\n"
        f"{scene_summary}\n\n"
        "Return JSON only."
    )
    body = json.dumps(
        {
            "model": str(config["chatModel"]),
            "messages": [
                {"role": "system", "content": str(config["routerSystemPrompt"])},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url=f"{str(config['openaiBaseUrl']).rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None
    return extract_openai_route_choice(payload)


def run_local_command_transcription(
    *,
    config: dict[str, Any],
    session_id: str,
    wav_bytes: bytes,
    segment_dir: Path,
    now_ms: Callable[[], int] = _now_ms,
) -> str:
    template = str(config.get("localCommandTemplate") or "").strip()
    if not template:
        return ""

    segment_dir.mkdir(parents=True, exist_ok=True)
    wav_path = segment_dir / f"{session_id}_{now_ms()}.wav"
    wav_path.write_bytes(wav_bytes)
    command = template.replace("{wav_path}", str(wav_path))
    try:
        result = subprocess.run(
            ["bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    finally:
        with suppress(Exception):
            wav_path.unlink()

    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "").strip()[:400]
        raise RuntimeError(f"local_command returncode={result.returncode}: {error_text}")

    raw = (result.stdout or "").strip()
    if raw.startswith("{") and raw.endswith("}"):
        try:
            payload = json.loads(raw)
            return str(deep_get_path(payload, str(config.get("localResponseTextPath") or "text")) or "").strip()
        except Exception:
            return raw
    return raw
