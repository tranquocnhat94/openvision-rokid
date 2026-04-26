"""OpenVision Rokid v2 Jetson control plane.

The package is intentionally split across the Jetson module folders
(`media_gateway`, `skills`, `perception`, and so on) while keeping the
stable import namespace `openvision_jetson.*` available for tests, service
startup, and deployment.
"""

from pathlib import Path

_JETSON_ROOT = Path(__file__).resolve().parents[2]
_MODULE_FOLDERS = (
    "audio_turns",
    "cloud_gateway",
    "hud_authority",
    "lab_fallbacks",
    "media_gateway",
    "perception",
    "realtime_agent",
    "simulator_bridge",
    "skills",
)

for _folder in _MODULE_FOLDERS:
    _package_dir = _JETSON_ROOT / _folder / "openvision_jetson"
    if _package_dir.is_dir():
        __path__.append(str(_package_dir))  # type: ignore[name-defined]

from .control_plane import OpenVisionControlPlane

__all__ = ["OpenVisionControlPlane"]
