"""Normalize RV101 H.264 transport metadata for Jetson media/runtime users."""

from __future__ import annotations

from typing import Any


_ALIASES = {
    "sensorOrientationDegrees": "sensor_orientation_degrees",
    "sensor_orientation_degrees": "sensor_orientation_degrees",
    "sensorOrientation": "orientation",
    "sensor_orientation": "orientation",
    "orientation": "orientation",
    "requestedWidth": "requested_width",
    "requested_width": "requested_width",
    "requestedHeight": "requested_height",
    "requested_height": "requested_height",
    "captureFpsMin": "capture_fps_min",
    "capture_fps_min": "capture_fps_min",
    "captureFpsMax": "capture_fps_max",
    "capture_fps_max": "capture_fps_max",
    "sentFpsEstimate": "sent_fps_estimate",
    "sent_fps_estimate": "sent_fps_estimate",
    "droppedFrames": "dropped_frames",
    "dropped_frames": "dropped_frames",
    "cameraId": "camera_id",
    "camera_id": "camera_id",
    "cameraPreference": "camera_preference",
    "camera_preference": "camera_preference",
    "fovMode": "fov_mode",
    "fov_mode": "fov_mode",
    "cropPolicy": "crop_policy",
    "crop_policy": "crop_policy",
    "fullFov": "full_fov",
    "full_fov": "full_fov",
    "videoStabilization": "video_stabilization",
    "video_stabilization": "video_stabilization",
    "digitalZoom": "digital_zoom",
    "digital_zoom": "digital_zoom",
    "zoomRatio": "zoom_ratio",
    "zoom_ratio": "zoom_ratio",
    "targetFps": "requested_fps",
    "target_fps": "requested_fps",
    "requestedFps": "requested_fps",
    "requested_fps": "requested_fps",
    "profile": "profile",
    "cameraProfile": "profile",
    "camera_profile": "profile",
    "videoProfile": "profile",
    "video_profile": "profile",
    "rotationDegrees": "rotation_degrees",
    "rotation_degrees": "rotation_degrees",
    "displayRotation": "rotation_degrees",
    "display_rotation": "rotation_degrees",
    "mirrored": "mirrored",
    "isMirrored": "mirrored",
    "is_mirrored": "mirrored",
    "sequence": "sequence",
    "frameIndex": "sequence",
    "frame_index": "sequence",
    "isKeyframe": "is_keyframe",
    "is_keyframe": "is_keyframe",
    "isCodecConfig": "is_codec_config",
    "is_codec_config": "is_codec_config",
    "codecConfigPrepended": "codec_config_prepended",
    "codec_config_prepended": "codec_config_prepended",
}

_INT_KEYS = {
    "sensor_orientation_degrees",
    "requested_width",
    "requested_height",
    "dropped_frames",
    "sequence",
}
_FLOAT_KEYS = {"capture_fps_min", "capture_fps_max", "sent_fps_estimate", "requested_fps", "digital_zoom", "zoom_ratio"}


def video_metadata_from_header(header: dict[str, Any] | None) -> dict[str, Any]:
    """Return a bounded, canonical metadata dict from an RV101 RVS1 header."""

    if not isinstance(header, dict):
        return {}
    output: dict[str, Any] = {}
    nested = header.get("metadata")
    if isinstance(nested, dict):
        for key, value in list(nested.items())[:64]:
            _put_metadata(output, key, value)
    for key, value in list(header.items())[:96]:
        if key == "metadata":
            continue
        _put_metadata(output, key, value)
    if output:
        output.setdefault("transport_profile", "rv101_tcp_h264")
    return output


def merge_video_metadata(*items: dict[str, Any] | None) -> dict[str, Any]:
    """Merge metadata dictionaries while dropping empty values."""

    output: dict[str, Any] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for key, value in list(item.items())[:96]:
            clean_key = _clean_key(key)
            clean_value = _clean_value(clean_key, value)
            if clean_key and clean_value is not None:
                output[clean_key] = clean_value
    return output


def _put_metadata(output: dict[str, Any], key: Any, value: Any) -> None:
    clean_key = _canonical_key(key)
    clean_value = _clean_value(clean_key, value)
    if clean_key and clean_value is not None:
        output[clean_key] = clean_value


def _canonical_key(key: Any) -> str | None:
    clean_key = _clean_key(key)
    if not clean_key:
        return None
    return _ALIASES.get(clean_key, clean_key)


def _clean_key(key: Any) -> str | None:
    clean_key = str(key or "").strip()
    if not clean_key or len(clean_key) > 64:
        return None
    return clean_key


def _clean_value(key: str | None, value: Any) -> Any:
    if key is None or value is None:
        return None
    if key in _INT_KEYS:
        return _to_int(value)
    if key in _FLOAT_KEYS:
        return _to_float(value)
    if key in {"is_keyframe", "is_codec_config", "codec_config_prepended", "full_fov", "video_stabilization"}:
        return _to_bool(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned[:240] if cleaned else None
    return None


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None
