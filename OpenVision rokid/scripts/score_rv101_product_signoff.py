#!/usr/bin/env python3
"""Run a bounded RV101 product signoff flow.

The harness is intentionally device-safe: it only uses ADB user-space commands,
starts the OpenVision APK, sends typed Jetson MediaCommand/DisplayCommand
requests, and verifies cleanup. It never roots, deletes system files, changes
firmware, or holds Wi-Fi awake.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "com.openvision.rokid"
ACTIVITY = "com.openvision.rokid/.MainActivity"
DEFAULT_TAILNET_BASE = "http://jay.tail8dd874.ts.net:8765"
DEFAULT_TAILNET_WS = "ws://jay.tail8dd874.ts.net:8765/ws"
DEFAULT_TUNNEL_BASE = "http://127.0.0.1:8765"
DEFAULT_TUNNEL_WS = "ws://127.0.0.1:8765/ws"
DEFAULT_SSH_TARGET = "jay@jay.tail8dd874.ts.net"
TUNNEL_PORTS = (8765, 8770, 8771)
FINAL_MEDIA_STATUSES = {"ok", "timeout", "cancelled", "error"}


@dataclass(slots=True)
class Check:
    name: str
    status: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        payload = {"name": self.name, "status": self.status, "detail": self.detail}
        if self.data:
            payload["data"] = self.data
        return payload


class Signoff:
    def __init__(self) -> None:
        self.checks: list[Check] = []
        self.artifacts: dict[str, Any] = {}

    def add(self, name: str, status: str, detail: str, **data: Any) -> None:
        self.checks.append(Check(name=name, status=status, detail=detail, data={k: v for k, v in data.items() if v is not None}))

    def status(self) -> str:
        statuses = {check.status for check in self.checks}
        if "fail" in statuses:
            return "fail"
        if "blocked" in statuses:
            return "blocked"
        if "warn" in statuses:
            return "warn"
        return "pass"

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status(),
            "checks": [check.to_json() for check in self.checks],
            "artifacts": self.artifacts,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", choices=["auto", "tailnet", "tunnel"], default="auto")
    parser.add_argument("--tailnet-base-url", default=DEFAULT_TAILNET_BASE)
    parser.add_argument("--tailnet-ws-url", default=DEFAULT_TAILNET_WS)
    parser.add_argument("--tunnel-base-url", default=DEFAULT_TUNNEL_BASE)
    parser.add_argument("--tunnel-ws-url", default=DEFAULT_TUNNEL_WS)
    parser.add_argument("--ssh-target", default=DEFAULT_SSH_TARGET, help="SSH target used to create missing local tunnel ports")
    parser.add_argument("--no-ssh-tunnel", action="store_true", help="Do not create missing local SSH tunnels for tunnel route")
    parser.add_argument("--allow-tunnel", action="store_true", help="Allow auto route to fall back to ADB tunnel")
    parser.add_argument("--adb-reverse", action="store_true", help="Set ADB reverse tcp:8765, tcp:8770, and tcp:8771 before tunnel tests")
    parser.add_argument("--install-apk", help="Optional APK path to install with adb install -r before launch")
    parser.add_argument("--no-start-app", action="store_true", help="Do not launch the OpenVision activity")
    parser.add_argument("--force-stop-app", action="store_true", help="Force-stop only com.openvision.rokid before launch for a fresh session")
    parser.add_argument("--no-grant-permissions", action="store_true", help="Do not pm grant CAMERA/RECORD_AUDIO")
    parser.add_argument("--skip-media", action="store_true")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--skip-ptt", action="store_true", help="Deprecated alias: do not exercise the debug PTT fallback")
    parser.add_argument(
        "--exercise-ptt-fallback",
        action="store_true",
        help="Explicitly exercise debug/noisy push-to-talk fallback; product voice signoff uses conversation_realtime/server_vad",
    )
    parser.add_argument("--ptt-seconds", type=float, default=4.0)
    parser.add_argument("--ptt-say", default="", help="Optional macOS say prompt to play while PTT is active")
    parser.add_argument("--session-wait-s", type=float, default=20.0)
    parser.add_argument("--command-wait-s", type=float, default=14.0)
    parser.add_argument("--json-output", help="Optional path for the JSON report")
    args = parser.parse_args()

    signoff = Signoff()
    route = resolve_route(args, signoff)
    if route is None:
        return finish(signoff, args.json_output)

    base_url = route["base_url"]
    ws_url = route["ws_url"]
    signoff.artifacts["route"] = route

    before_health = safe_get_json(base_url, "/api/health")
    if before_health is None:
        signoff.add("jetson_health", "blocked", f"Jetson HTTP is not reachable at {base_url}")
        return finish(signoff, args.json_output)
    signoff.add(
        "jetson_health",
        "pass",
        "Jetson health endpoint reachable",
        runtime_epoch=before_health.get("runtime_epoch"),
        openai_key_present=before_health.get("openai_key_present"),
        active_live_count=before_health.get("active_live_count"),
    )

    before_session_state = rv101_session_state_by_id(base_url)
    before_sessions = set(before_session_state)
    if args.install_apk:
        install_apk(args.install_apk, signoff)
    if not args.no_grant_permissions:
        grant_runtime_permissions(signoff)

    check_device_package(signoff)
    check_no_network_locks(signoff)
    check_camera_cleanup(signoff, "preflight_camera_cleanup")

    session_id: str | None = None
    if args.no_start_app:
        session_id = latest_rv101_session(base_url, before_sessions)
        if session_id:
            signoff.add("session_select", "warn", "Using latest existing RV101 session because app launch was disabled", session_id=session_id)
    else:
        start_app(ws_url, signoff, force_stop=args.force_stop_app)
        session_id = wait_for_new_session(base_url, before_sessions, args.session_wait_s, before_state=before_session_state)
        if session_id:
            reused = session_id in before_sessions
            signoff.add(
                "session_accept",
                "pass",
                "OpenVision app accepted a Jetson RV101 session",
                session_id=session_id,
                reused_session=reused,
            )
        else:
            signoff.add("session_accept", "blocked", "No new or reused connected RV101 session appeared after app launch")

    if not session_id:
        return finish(signoff, args.json_output)
    signoff.artifacts["session_id"] = session_id

    check_rv101_voice_contract(base_url, session_id, signoff)
    check_realtime_ready(base_url, session_id, signoff)
    run_hud_ttl_check(base_url, session_id, signoff)

    if args.skip_media:
        signoff.add("media_checks", "skip", "Media checks skipped by operator")
    else:
        run_snapshot_quality_gate(base_url, session_id, args.command_wait_s, signoff)
        check_camera_cleanup(signoff, "post_snapshot_camera_cleanup")
        if args.skip_live:
            signoff.add("live_video", "skip", "live_video check skipped by operator")
        else:
            run_live_video_check(base_url, session_id, args.command_wait_s, signoff)
            check_camera_cleanup(signoff, "post_live_camera_cleanup")

    if args.skip_ptt:
        signoff.add("ptt_fallback_realtime", "skip", "PTT fallback check skipped by operator")
    elif not args.exercise_ptt_fallback:
        signoff.add(
            "ptt_fallback_realtime",
            "skip",
            "PTT fallback is skipped by default; product voice gate is conversation_realtime with Cloud Realtime server_vad",
        )
    else:
        run_ptt_check(base_url, session_id, args.ptt_seconds, args.ptt_say, signoff)

    after_health = safe_get_json(base_url, "/api/health") or {}
    signoff.artifacts["health_after"] = {
        "runtime_epoch": after_health.get("runtime_epoch"),
        "active_live_count": after_health.get("active_live_count"),
        "rv101_h264_preview": after_health.get("rv101_h264_preview"),
    }
    if before_health.get("runtime_epoch") == after_health.get("runtime_epoch"):
        signoff.add("runtime_epoch", "pass", "Jetson runtime epoch stayed stable", runtime_epoch=after_health.get("runtime_epoch"))
    else:
        signoff.add(
            "runtime_epoch",
            "fail",
            "Jetson runtime epoch changed during signoff",
            before=before_health.get("runtime_epoch"),
            after=after_health.get("runtime_epoch"),
        )
    return finish(signoff, args.json_output)


def resolve_route(args: argparse.Namespace, signoff: Signoff) -> dict[str, str] | None:
    if not shutil.which("adb"):
        signoff.add("adb_available", "blocked", "adb binary was not found in PATH")
        return None
    device = run(["adb", "devices", "-l"], timeout=8)
    if device.returncode != 0 or not re.search(r"^\S+\s+device\b", device.stdout, flags=re.M):
        signoff.add("adb_device", "blocked", "No connected RV101 ADB device is available", output=device.stdout + device.stderr)
        return None
    signoff.add("adb_device", "pass", "ADB device is connected", devices=device.stdout.strip())

    if args.route in {"auto", "tailnet"}:
        tailnet_ok = device_http_health(
            args.tailnet_base_url,
            signoff,
            failure_status="blocked" if args.route == "tailnet" else "warn",
        )
        if tailnet_ok:
            signoff.add("route", "pass", "Using normal RV101 tailnet route")
            return {"name": "tailnet", "base_url": args.tailnet_base_url.rstrip("/"), "ws_url": args.tailnet_ws_url}
        if args.route == "tailnet":
            signoff.add("route", "blocked", "Tailnet route requested but RV101 cannot reach Jetson")
            return None
        signoff.add("route_tailnet", "warn", "RV101 tailnet route is not reachable; checking tunnel fallback")

    if args.route == "auto" and not args.allow_tunnel:
        signoff.add("route", "blocked", "Auto route did not use tunnel because --allow-tunnel was not set")
        return None
    if args.route == "tunnel" or args.allow_tunnel:
        if not args.no_ssh_tunnel:
            ensure_local_ssh_tunnels(args.ssh_target, signoff)
        if args.adb_reverse:
            for port in TUNNEL_PORTS:
                run(["adb", "reverse", f"tcp:{port}", f"tcp:{port}"], timeout=8)
            signoff.add("adb_reverse", "pass", "ADB reverse requested for 8765, 8770, and 8771")
        reverse = run(["adb", "reverse", "--list"], timeout=8)
        missing_reverse = [port for port in TUNNEL_PORTS if f"tcp:{port} tcp:{port}" not in reverse.stdout]
        if missing_reverse:
            signoff.add("adb_reverse", "blocked", "ADB tunnel route needs reverse tcp:8765, tcp:8770, and tcp:8771", reverse=reverse.stdout.strip())
            return None
        missing_local = [port for port in TUNNEL_PORTS if not local_tcp_open("127.0.0.1", port)]
        if missing_local:
            signoff.add("local_tunnel_ports", "blocked", "Local SSH tunnel is missing required forwarded ports", missing_ports=missing_local)
            return None
        if safe_get_json(args.tunnel_base_url, "/api/health") is None:
            signoff.add("route", "blocked", f"Tunnel base URL is not reachable: {args.tunnel_base_url}")
            return None
        signoff.add("route", "warn", "Using USB/ADB tunnel fallback, not product tailnet signoff")
        return {"name": "tunnel", "base_url": args.tunnel_base_url.rstrip("/"), "ws_url": args.tunnel_ws_url}
    return None


def device_http_health(base_url: str, signoff: Signoff, *, failure_status: str) -> bool:
    url = base_url.rstrip("/") + "/api/health"
    ping_host = re.sub(r"^https?://", "", base_url).split(":", 1)[0].split("/", 1)[0]
    ping = adb_shell(f"ping -c 1 -W 4 {shell_quote(ping_host)}", timeout=6)
    curl = adb_shell(f"curl -m 5 -sS {shell_quote(url)}", timeout=7)
    if curl.returncode == 0:
        try:
            payload = json.loads(curl.stdout)
        except json.JSONDecodeError:
            payload = {}
        if payload.get("ok"):
            signoff.add("tailnet_device_health", "pass", "RV101 can reach Jetson health over tailnet", host=ping_host)
            return True
    signoff.add(
        "tailnet_device_health",
        failure_status,
        "RV101 cannot reach Jetson health over tailnet",
        ping=(ping.stdout + ping.stderr).strip(),
        curl=(curl.stdout + curl.stderr).strip(),
    )
    return False


def install_apk(path: str, signoff: Signoff) -> None:
    apk = Path(path)
    if not apk.exists():
        signoff.add("install_apk", "fail", "APK path does not exist", path=str(apk))
        return
    result = run(["adb", "install", "-r", str(apk)], timeout=90)
    status = "pass" if result.returncode == 0 and "Success" in result.stdout else "fail"
    signoff.add("install_apk", status, "adb install -r completed" if status == "pass" else "adb install -r failed", output=(result.stdout + result.stderr).strip())


def grant_runtime_permissions(signoff: Signoff) -> None:
    for permission in ("android.permission.CAMERA", "android.permission.RECORD_AUDIO"):
        result = adb_shell(f"pm grant {PACKAGE} {permission}", timeout=8)
        if result.returncode not in {0, 1}:
            signoff.add("grant_permission", "warn", "pm grant returned an unexpected code", permission=permission, output=result.stderr.strip())
    signoff.add("grant_permissions", "pass", "Runtime camera/audio permissions were granted or already granted")


def check_device_package(signoff: Signoff) -> None:
    package = adb_shell(f"dumpsys package {PACKAGE}", timeout=10)
    if package.returncode != 0 or PACKAGE not in package.stdout:
        signoff.add("package_installed", "blocked", "OpenVision package is not installed", output=package.stderr.strip())
        return
    forbidden = ["android.permission.WAKE_LOCK"]
    present_forbidden = [item for item in forbidden if item in package.stdout]
    granted = {
        permission: f"{permission}: granted=true" in package.stdout
        for permission in ("android.permission.CAMERA", "android.permission.RECORD_AUDIO")
    }
    if present_forbidden:
        signoff.add("package_permissions", "fail", "Package requests forbidden power/network permission", forbidden=present_forbidden)
    elif all(granted.values()):
        signoff.add("package_permissions", "pass", "Package permissions are clean and runtime media permissions are granted", granted=granted)
    else:
        signoff.add("package_permissions", "warn", "Package permissions are clean but a runtime media permission is not granted", granted=granted)


def check_no_network_locks(signoff: Signoff) -> None:
    wifi = adb_shell("dumpsys wifi", timeout=10)
    power = adb_shell("dumpsys power", timeout=10)
    wifi_mentions = package_has_held_wifi_lock(wifi.stdout, PACKAGE)
    power_mentions = package_has_held_wake_lock(power.stdout, PACKAGE)
    if wifi_mentions or power_mentions:
        signoff.add("power_network_locks", "fail", "OpenVision appears in Wi-Fi/power locks", wifi=wifi_mentions, power=power_mentions)
    else:
        signoff.add("power_network_locks", "pass", "No OpenVision WifiLock/WakeLock is held")


def check_camera_cleanup(signoff: Signoff, name: str) -> None:
    camera = adb_shell("dumpsys media.camera", timeout=10)
    active = extract_active_camera_clients(camera.stdout)
    if active == "[]":
        signoff.add(name, "pass", "RV101 camera has no active clients")
    else:
        signoff.add(name, "fail", "RV101 camera has active clients after bounded check", active_camera_clients=active)


def package_has_held_wifi_lock(dumpsys: str, package: str) -> bool:
    section = _section_after_header(
        dumpsys,
        headers=("Locks held:", "Wifi Locks held:", "Wi-Fi Locks held:"),
        stop_prefixes=("Locks acquired", "Locks released", "Multicast Locks", "Latest scan", "mWifiInfo", "mWifiConfigManager"),
    )
    return any(package in line and ("WifiLock" in line or "WiFiLock" in line or "LOCK" in line.upper()) for line in section)


def package_has_held_wake_lock(dumpsys: str, package: str) -> bool:
    section = _section_after_header(
        dumpsys,
        headers=("Wake Locks:", "Wake locks:", "PARTIAL_WAKE_LOCK"),
        stop_prefixes=("Suspend Blockers:", "Display Power:", "Settings and Configuration:", "Looper state:", "Battery Saver"),
    )
    return any(package in line and ("WakeLock" in line or "wake lock" in line.lower() or "PARTIAL_WAKE_LOCK" in line) for line in section)


def _section_after_header(dumpsys: str, *, headers: tuple[str, ...], stop_prefixes: tuple[str, ...]) -> list[str]:
    lines = str(dumpsys or "").splitlines()
    start: int | None = None
    section: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if any(stripped.startswith(header) for header in headers):
            start = index + 1
            inline = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            if inline and inline not in {"[]", "0", "none", "None"}:
                section.append(inline)
            break
    if start is None:
        return []
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            if section:
                break
            continue
        if any(stripped.startswith(prefix) for prefix in stop_prefixes):
            break
        if stripped.startswith(("m", "Wi-Fi", "Wifi", "Network", "Locks ")) and section:
            break
        section.append(stripped)
    return section


def start_app(ws_url: str, signoff: Signoff, *, force_stop: bool) -> None:
    if force_stop:
        stopped = adb_shell(f"am force-stop {PACKAGE}", timeout=8)
        signoff.add(
            "app_force_stop",
            "pass" if stopped.returncode == 0 else "warn",
            "Stopped only the OpenVision app before fresh signoff launch",
            output=(stopped.stdout + stopped.stderr).strip() or None,
        )
        time.sleep(0.5)
    result = run(
        [
            "adb",
            "shell",
            "am",
            "start",
            "-n",
            ACTIVITY,
            "--es",
            "jetson_ws_url",
            ws_url,
        ],
        timeout=12,
    )
    if result.returncode == 0:
        signoff.add("app_launch", "pass", "OpenVision activity start command sent", ws_url=ws_url)
    else:
        signoff.add("app_launch", "fail", "OpenVision activity start failed", output=(result.stdout + result.stderr).strip())


def wait_for_new_session(
    base_url: str,
    before_ids: set[str],
    wait_s: float,
    *,
    before_state: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    deadline = time.monotonic() + wait_s
    latest: str | None = None
    while time.monotonic() < deadline:
        latest = latest_rv101_session(base_url, before_ids)
        if latest:
            return latest
        reused = reused_connected_rv101_session(base_url, before_state or {})
        if reused:
            return reused
        time.sleep(0.5)
    return latest


def latest_rv101_session(base_url: str, before_ids: set[str] | None = None) -> str | None:
    sessions = (safe_get_json(base_url, "/api/sessions") or {}).get("sessions", [])
    candidates = [
        session
        for session in sessions
        if session.get("client_kind") == "rv101_glasses"
        and (not before_ids or session.get("session_id") not in before_ids)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: str(item.get("created_at") or ""))
    return str(candidates[-1].get("session_id"))


def session_ids(base_url: str) -> set[str]:
    sessions = (safe_get_json(base_url, "/api/sessions") or {}).get("sessions", [])
    return {str(session.get("session_id")) for session in sessions if session.get("session_id")}


def rv101_session_state_by_id(base_url: str) -> dict[str, dict[str, Any]]:
    sessions = (safe_get_json(base_url, "/api/sessions") or {}).get("sessions", [])
    output: dict[str, dict[str, Any]] = {}
    for session in sessions:
        if not isinstance(session, dict) or session.get("client_kind") != "rv101_glasses":
            continue
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            continue
        output[session_id] = {
            "status": session.get("status"),
            "created_at": session.get("created_at"),
            "updated_at": session.get("updated_at"),
        }
    return output


def reused_connected_rv101_session(base_url: str, before_state: dict[str, dict[str, Any]]) -> str | None:
    if not before_state:
        return None
    sessions = (safe_get_json(base_url, "/api/sessions") or {}).get("sessions", [])
    candidates: list[dict[str, Any]] = []
    for session in sessions:
        if not isinstance(session, dict) or session.get("client_kind") != "rv101_glasses":
            continue
        session_id = str(session.get("session_id") or "").strip()
        previous = before_state.get(session_id)
        if not session_id or previous is None:
            continue
        if str(session.get("status") or "") != "connected":
            continue
        if session.get("updated_at") == previous.get("updated_at") and previous.get("status") == "connected":
            continue
        candidates.append(session)
    if not candidates:
        return None
    candidates.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))
    return str(candidates[-1].get("session_id"))


def check_realtime_ready(base_url: str, session_id: str, signoff: Signoff) -> None:
    status: dict[str, Any] | None = None
    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        statuses = (safe_get_json(base_url, "/api/realtime") or {}).get("realtime", [])
        status = next((item for item in statuses if item.get("session_id") == session_id), None)
        if status and status.get("status") != "connecting":
            break
        time.sleep(0.5)
    if not status:
        signoff.add("realtime_session", "blocked", "No Realtime status exists for RV101 session", session_id=session_id)
        return
    if status.get("status") == "connected":
        signoff.add("realtime_session", "pass", "Realtime session is connected", session_id=session_id, model=status.get("model"))
    else:
        signoff.add("realtime_session", "blocked", "Realtime session is not connected", session_id=session_id, realtime_status=status)


def check_rv101_voice_contract(base_url: str, session_id: str, signoff: Signoff) -> None:
    events = (safe_get_json(base_url, f"/api/events?session_id={session_id}&limit=1000") or {}).get("events", [])
    accept_payload = None
    for event in events:
        if event.get("module") == "rv101_control" and event.get("event_type") == "session_accept":
            payload = event.get("payload")
            if isinstance(payload, dict):
                accept_payload = payload
    statuses = (safe_get_json(base_url, "/api/realtime") or {}).get("realtime", [])
    realtime_status = next((item for item in statuses if item.get("session_id") == session_id), {}) or {}
    if not isinstance(accept_payload, dict):
        signoff.add("rv101_voice_contract", "fail", "No rv101_control/session_accept event was found for the session")
        return

    voice_output = accept_payload.get("voice_output") or accept_payload.get("voiceOutput") or {}
    if not isinstance(voice_output, dict):
        voice_output = {}
    voice_mode = str(accept_payload.get("voice_mode") or accept_payload.get("voiceMode") or "")
    turn_policy = str(accept_payload.get("turn_policy") or accept_payload.get("turnPolicy") or "")
    realtime_turn_policy = str(realtime_status.get("turn_policy") or "")
    voice_output_path = str(voice_output.get("path") or "")
    requires_bootstrap = voice_output.get("requiresRestBootstrap", voice_output.get("requires_rest_bootstrap"))

    expected_path = f"/ws/realtime/{session_id}/audio"
    ok = (
        voice_mode == "conversation_realtime"
        and turn_policy == "server_vad"
        and (not realtime_turn_policy or realtime_turn_policy == "server_vad")
        and voice_output_path == expected_path
        and requires_bootstrap is False
    )
    if ok:
        signoff.add(
            "rv101_voice_contract",
            "pass",
            "RV101 accepted app-open conversation_realtime with Cloud Realtime server_vad and session_accept voice output",
            voice_mode=voice_mode,
            turn_policy=turn_policy,
            realtime_turn_policy=realtime_turn_policy or None,
            voice_output_enabled=voice_output.get("enabled"),
            output_modalities=voice_output.get("output_modalities"),
        )
    else:
        signoff.add(
            "rv101_voice_contract",
            "fail",
            "RV101 voice contract is not aligned with app-open conversation_realtime/server_vad",
            voice_mode=voice_mode or None,
            turn_policy=turn_policy or None,
            realtime_turn_policy=realtime_turn_policy or None,
            voice_output_path=voice_output_path or None,
            expected_voice_output_path=expected_path,
            requires_rest_bootstrap=requires_bootstrap,
        )


def run_hud_ttl_check(base_url: str, session_id: str, signoff: Signoff) -> None:
    marker = f"SIGNOFF TTL {int(time.time())}"
    payload = {
        "kind": "text_hud",
        "session_id": session_id,
        "skill_id": "rv101_product_signoff",
        "ttl_ms": 3000,
        "payload": {"text": marker, "edge_chips": ["signoff", "ttl"]},
    }
    response = safe_post_json(base_url, "/api/display/commands", payload)
    if response is None:
        signoff.add("hud_ttl", "fail", "DisplayCommand request failed")
        return
    time.sleep(0.8)
    before = dump_ui_texts()
    time.sleep(3.4)
    after = dump_ui_texts()
    if marker in before and marker not in after and "Ready" in after:
        signoff.add("hud_ttl", "pass", "HUD displayed marker and cleared after ttl_ms", marker=marker)
    else:
        signoff.add("hud_ttl", "warn", "HUD TTL could not be fully proven from uiautomator text", marker=marker, before=before, after=after)


def run_snapshot_quality_gate(base_url: str, session_id: str, wait_s: float, signoff: Signoff) -> None:
    response = safe_post_json(
        base_url,
        "/api/media/commands",
        {
            "mode": "snapshot",
            "session_id": session_id,
            "skill_id": "person_info",
            "reason": "RV101 product signoff quality_gate snapshot",
            "timeout_ms": 5000,
            "resolution": {"width": 1280, "height": 720},
            "params": {
                "requested_by": "rv101_product_signoff",
                "quality_gate": {
                    "mode": "best_of_burst",
                    "sample_count": 4,
                    "min_new_frames": 4,
                    "settle_ms": 850,
                    "score": "face_quality_then_sharpness",
                    "server_recent_frame_limit": 6,
                },
            },
        },
    )
    command = (response or {}).get("command") or {}
    command_id = command.get("command_id")
    if not command_id:
        signoff.add("snapshot_quality_gate", "fail", "Failed to create snapshot MediaCommand", response=response)
        return
    final = wait_media_final(base_url, command_id, wait_s)
    event = (final or {}).get("event") or {}
    status = event.get("status")
    event_payload = event.get("payload") or {}
    quality_gate = event_payload.get("quality_gate") or {}
    if (
        status == "ok"
        and event_payload.get("adapter_status") == "rv101_snapshot_quality_gate_ready"
        and int(quality_gate.get("uploaded_frame_count") or 0) >= 4
    ):
        signoff.add(
            "snapshot_quality_gate",
            "pass",
            "quality_gate snapshot completed and uploaded frames",
            command_id=command_id,
            uploaded_frame_count=quality_gate.get("uploaded_frame_count"),
            capture_duration_ms=event_payload.get("capture_duration_ms"),
        )
    else:
        signoff.add("snapshot_quality_gate", "fail", "quality_gate snapshot did not meet product gate", command_id=command_id, final=final)


def run_live_video_check(base_url: str, session_id: str, wait_s: float, signoff: Signoff) -> None:
    before = safe_get_json(base_url, "/api/health") or {}
    response = safe_post_json(
        base_url,
        "/api/media/commands",
        {
            "mode": "live_video",
            "session_id": session_id,
            "skill_id": "target_finder",
            "reason": "RV101 product signoff 1280x720@30fps bounded live_video smoke",
            "timeout_ms": 4500,
            "fps": 30.0,
            "resolution": {"width": 1280, "height": 720},
            "params": {"requested_by": "rv101_product_signoff", "action": "start", "profile": "smoke_1280x720_30fps"},
        },
    )
    command = (response or {}).get("command") or {}
    command_id = command.get("command_id")
    if not command_id:
        signoff.add("live_video_1280x720_30fps", "fail", "Failed to create live_video MediaCommand", response=response)
        return
    final = wait_media_final(base_url, command_id, wait_s)
    media = media_session_status(base_url, session_id) or {}
    after = safe_get_json(base_url, "/api/health") or {}
    event = (final or {}).get("event") or {}
    payload = event.get("payload") or {}
    video = media.get("video") if isinstance(media.get("video"), dict) else {}
    metadata = video.get("metadata") if isinstance(video.get("metadata"), dict) else {}
    stable = before.get("runtime_epoch") == after.get("runtime_epoch")
    ok_status = event.get("status") in {"ok", "timeout"}
    inactive = after.get("active_live_count") == 0 and payload.get("active_live_video") is False
    sent_frames = int(payload.get("sent_frames") or 0)
    app_fps = _to_float(payload.get("sent_fps_estimate"))
    backend_fps = _to_float(video.get("estimated_fps"))
    app_fps_ok = app_fps is not None and app_fps >= 24.0
    backend_fps_ok = backend_fps is not None and backend_fps >= 20.0
    app_size_ok = int(payload.get("width") or 0) == 1280 and int(payload.get("height") or 0) == 720
    backend_size_ok = int(video.get("width") or 0) == 1280 and int(video.get("height") or 0) == 720
    command_fps_ok = abs(float(command.get("fps") or 0.0) - 30.0) < 0.01
    metadata_fps_ok = _to_float(metadata.get("requested_fps")) == 30.0 or _to_float(metadata.get("capture_fps_max")) == 30.0
    no_writer_error = "live_video_write_error" not in str(payload.get("error") or "")
    if (
        stable
        and ok_status
        and inactive
        and sent_frames > 0
        and app_size_ok
        and backend_size_ok
        and command_fps_ok
        and metadata_fps_ok
        and app_fps_ok
        and backend_fps_ok
        and no_writer_error
    ):
        signoff.add(
            "live_video_1280x720_30fps",
            "pass",
            "bounded 1280x720@30fps live_video delivered frames, reported app/backend FPS, and cleaned up",
            command_id=command_id,
            final_status=event.get("status"),
            sent_frames=sent_frames,
            app_sent_fps_estimate=app_fps,
            backend_estimated_fps=backend_fps,
            width=payload.get("width"),
            height=payload.get("height"),
            active_live_count=after.get("active_live_count"),
        )
    else:
        signoff.add(
            "live_video_1280x720_30fps",
            "fail",
            "bounded 1280x720@30fps live_video failed product FPS/cleanup/frame gate",
            command_id=command_id,
            final=final,
            media=media,
            checks={
                "stable_runtime": stable,
                "ok_status": ok_status,
                "inactive": inactive,
                "sent_frames": sent_frames,
                "app_size_ok": app_size_ok,
                "backend_size_ok": backend_size_ok,
                "command_fps_ok": command_fps_ok,
                "metadata_fps_ok": metadata_fps_ok,
                "app_fps_ok": app_fps_ok,
                "backend_fps_ok": backend_fps_ok,
                "no_writer_error": no_writer_error,
            },
            active_live_count=after.get("active_live_count"),
            runtime_epoch_before=before.get("runtime_epoch"),
            runtime_epoch_after=after.get("runtime_epoch"),
        )


def run_ptt_check(base_url: str, session_id: str, seconds: float, say_prompt: str, signoff: Signoff) -> None:
    before_count = len((safe_get_json(base_url, f"/api/events?session_id={session_id}&limit=1000") or {}).get("events", []))
    if not tap_ui_text("Talk"):
        signoff.add("ptt_fallback_realtime", "blocked", "Could not find Talk button in uiautomator dump")
        return
    say_proc: subprocess.Popen[str] | None = None
    if say_prompt.strip() and shutil.which("say"):
        say_proc = subprocess.Popen(["say", say_prompt], text=True)
    time.sleep(max(1.0, seconds))
    if say_proc and say_proc.poll() is None:
        try:
            say_proc.terminate()
        except OSError:
            pass
    stop_tapped = tap_ui_text("Stop")
    ui_after_stop = None
    if not stop_tapped:
        ui_after_stop = dump_ui_texts()
    time.sleep(7.0)
    events = (safe_get_json(base_url, f"/api/events?session_id={session_id}&limit=1000") or {}).get("events", [])
    new_events = events[before_count:] if before_count < len(events) else events
    event_types = [event.get("event_type") for event in new_events]
    realtime_types = [
        (event.get("payload") or {}).get("type")
        for event in new_events
        if event.get("module") == "realtime" and isinstance(event.get("payload"), dict)
    ]
    audio_stats = [
        event
        for event in new_events
        if event.get("module") == "rv101_control" and event.get("event_type") == "audio_stats"
    ]
    latest_audio = (audio_stats[-1].get("payload") if audio_stats else {}) or {}
    has_ptt = "ptt_down" in event_types and "ptt_up" in event_types
    observed_server_vad_ptt = "ptt_down_observed_server_vad" in event_types and "ptt_up_observed_server_vad" in event_types
    has_audio = int(latest_audio.get("sentChunks") or 0) > 0 and int(latest_audio.get("sentBytes") or 0) > 0
    has_commit = "input_audio_buffer.committed" in realtime_types
    has_response = any(str(item or "").startswith("response.") for item in realtime_types)
    if has_ptt and has_audio and has_commit and has_response:
        signoff.add(
            "ptt_fallback_realtime",
            "pass",
            "Debug PTT fallback sent audio, committed after stop, and Realtime responded",
            stop_tapped=stop_tapped,
            sent_chunks=latest_audio.get("sentChunks"),
            sent_bytes=latest_audio.get("sentBytes"),
            realtime_response_types=[item for item in realtime_types if str(item or "").startswith("response.")][:8],
        )
    elif observed_server_vad_ptt:
        signoff.add(
            "ptt_fallback_realtime",
            "warn",
            "Talk/Stop was observed during a server_vad conversation session; Jetson correctly did not force manual commit",
            has_audio=has_audio,
            has_response=has_response,
            stop_tapped=stop_tapped,
            sent_chunks=latest_audio.get("sentChunks"),
            sent_bytes=latest_audio.get("sentBytes"),
            realtime_types=[item for item in realtime_types if item][-12:],
        )
    else:
        signoff.add(
            "ptt_fallback_realtime",
            "warn",
            "Debug PTT fallback control/audio happened but full spoken Realtime answer was not proven",
            has_ptt=has_ptt,
            has_audio=has_audio,
            has_commit=has_commit,
            has_response=has_response,
            stop_tapped=stop_tapped,
            ui_after_stop=ui_after_stop,
            sent_chunks=latest_audio.get("sentChunks"),
            sent_bytes=latest_audio.get("sentBytes"),
            realtime_types=[item for item in realtime_types if item][-12:],
        )


def wait_media_final(base_url: str, command_id: str, wait_s: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + wait_s
    latest: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        statuses = (safe_get_json(base_url, "/api/media/commands") or {}).get("media_commands", {})
        commands = statuses.get("commands", []) if isinstance(statuses, dict) else statuses
        for item in commands:
            if ((item.get("command") or {}).get("command_id")) == command_id:
                latest = item
                event = item.get("event") or {}
                if event.get("status") in FINAL_MEDIA_STATUSES:
                    return item
        time.sleep(0.5)
    return latest


def media_session_status(base_url: str, session_id: str) -> dict[str, Any] | None:
    media = (safe_get_json(base_url, "/api/media") or {}).get("media", [])
    for item in media:
        if isinstance(item, dict) and item.get("session_id") == session_id:
            return item
    return None


def dump_ui_texts() -> list[str]:
    xml = dump_ui_xml()
    if not xml:
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    texts: list[str] = []
    for node in root.iter("node"):
        text = (node.attrib.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts


def ensure_local_ssh_tunnels(ssh_target: str, signoff: Signoff) -> None:
    if not ssh_target.strip():
        signoff.add("ssh_tunnel", "warn", "No SSH target configured for local tunnel creation")
        return
    started: list[int] = []
    failed: list[dict[str, Any]] = []
    for port in TUNNEL_PORTS:
        if local_tcp_open("127.0.0.1", port):
            continue
        result = run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ExitOnForwardFailure=yes",
                "-fN",
                "-L",
                f"127.0.0.1:{port}:127.0.0.1:{port}",
                ssh_target,
            ],
            timeout=10,
        )
        if result.returncode == 0:
            started.append(port)
        else:
            failed.append({"port": port, "output": (result.stdout + result.stderr).strip()})
    missing = [port for port in TUNNEL_PORTS if not local_tcp_open("127.0.0.1", port)]
    if failed or missing:
        signoff.add("ssh_tunnel", "blocked", "Could not create all local SSH tunnel ports", started=started, failed=failed, missing=missing)
    else:
        detail = "Local SSH tunnel ports are already available"
        if started:
            detail = "Created missing local SSH tunnel ports"
        signoff.add("ssh_tunnel", "pass", detail, started_ports=started or None)


def local_tcp_open(host: str, port: int, timeout_s: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def tap_ui_text(text: str) -> bool:
    xml = dump_ui_xml()
    if not xml:
        return False
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return False
    wanted = text.strip().casefold()
    for node in root.iter("node"):
        if (node.attrib.get("text") or "").strip().casefold() == wanted:
            bounds = node.attrib.get("bounds") or ""
            match = re.match(r"\[(\d+),(\d+)]\[(\d+),(\d+)]", bounds)
            if not match:
                return False
            left, top, right, bottom = map(int, match.groups())
            x = (left + right) // 2
            y = (top + bottom) // 2
            return adb_shell(f"input tap {x} {y}", timeout=5).returncode == 0
    return False


def dump_ui_xml() -> str:
    dump = adb_shell("uiautomator dump /sdcard/openvision-window.xml >/dev/null && cat /sdcard/openvision-window.xml", timeout=10)
    return dump.stdout if dump.returncode == 0 else ""


def extract_active_camera_clients(dumpsys: str) -> str:
    match = re.search(r"Active Camera Clients:\s*(.*?)\nAllowed user IDs:", dumpsys, flags=re.S)
    if not match:
        return "unknown"
    return " ".join(match.group(1).split())


def safe_get_json(base_url: str, path: str) -> dict[str, Any] | None:
    try:
        return request_json(Request(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")), method="GET"))
    except RuntimeError:
        return None


def safe_post_json(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        data = json.dumps(payload).encode("utf-8")
        return request_json(
            Request(
                urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
                data=data,
                headers={"content-type": "application/json"},
                method="POST",
            )
        )
    except RuntimeError:
        return None


def request_json(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=8) as response:  # noqa: S310 - local/tailnet operator URL.
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {request.full_url}: {body}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Request failed for {request.full_url}: {exc}") from exc


def adb_shell(command: str, timeout: float) -> subprocess.CompletedProcess[str]:
    return run(["adb", "shell", command], timeout=timeout)


def run(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(command, 124, stdout=exc.stdout or "", stderr=exc.stderr or "timeout")


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def finish(signoff: Signoff, output_path: str | None) -> int:
    report = signoff.to_json()
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if output_path:
        Path(output_path).write_text(text + "\n", encoding="utf-8")
    return {"pass": 0, "warn": 1, "blocked": 2, "fail": 3}.get(report["status"], 3)


if __name__ == "__main__":
    raise SystemExit(main())
