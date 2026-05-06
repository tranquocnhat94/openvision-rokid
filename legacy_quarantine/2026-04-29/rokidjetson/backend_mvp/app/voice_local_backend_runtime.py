from __future__ import annotations

import subprocess
import time
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable


def health_check_cache_hit(*, last_check_ms: int, now_ms: int, cache_ms: int) -> bool:
    return bool(last_check_ms and now_ms - last_check_ms < max(250, cache_ms))


def restart_cooldown_active(*, last_attempt_ms: int, now_ms: int, cooldown_ms: int = 4000) -> bool:
    return bool(last_attempt_ms and now_ms - last_attempt_ms < cooldown_ms)


@dataclass(slots=True)
class LocalBackendProcessState:
    last_start_attempt_ms: int = 0
    last_warm_attempt_ms: int = 0
    last_health_check_ms: int = 0
    last_health_ok: bool = False
    pid: int | None = None
    process: subprocess.Popen[bytes] | None = None


class LocalBackendSupervisor:
    def __init__(
        self,
        *,
        config_provider: Callable[[], dict[str, Any]],
        log_handler: Callable[[str, str, dict[str, Any]], None],
        set_backend_state: Callable[[str], None],
        set_backend_error: Callable[[str], None],
        clear_backend_error: Callable[[], None],
        now_ms: Callable[[], int],
    ) -> None:
        self._config_provider = config_provider
        self._log_handler = log_handler
        self._set_backend_state = set_backend_state
        self._set_backend_error = set_backend_error
        self._clear_backend_error = clear_backend_error
        self._now_ms = now_ms
        self.state = LocalBackendProcessState()

    @property
    def pid(self) -> int | None:
        return self.state.pid

    def process_alive(self) -> bool:
        process = self.state.process
        return process is not None and process.poll() is None

    def running(self) -> bool:
        if self.process_alive():
            return True
        config = self._config_provider()
        health_url = str(config.get("localHealthUrl") or "").strip()
        if health_url:
            now_ms = self._now_ms()
            cache_ms = int(config.get("localHealthCacheMs") or 1000)
            if health_check_cache_hit(
                last_check_ms=self.state.last_health_check_ms,
                now_ms=now_ms,
                cache_ms=cache_ms,
            ):
                return self.state.last_health_ok
            ok = self._ping_health_url(health_url)
            self.state.last_health_check_ms = now_ms
            self.state.last_health_ok = ok
            return ok
        return False

    def warm(self) -> bool:
        config = self._config_provider()
        warm_url = str(config.get("localWarmUrl") or "").strip()
        if not warm_url:
            return self.running()
        now_ms = self._now_ms()
        if restart_cooldown_active(
            last_attempt_ms=self.state.last_warm_attempt_ms,
            now_ms=now_ms,
        ):
            return self.state.last_health_ok
        self.state.last_warm_attempt_ms = now_ms
        try:
            request = urllib.request.Request(url=warm_url, method="GET")
            with urllib.request.urlopen(request, timeout=8) as response:
                ok = 200 <= int(getattr(response, "status", 200) or 200) < 300
        except Exception as error:
            self._set_backend_error(str(error))
            self.state.last_health_check_ms = now_ms
            self.state.last_health_ok = False
            return False
        self.state.last_health_check_ms = now_ms
        self.state.last_health_ok = ok
        if ok:
            self._set_backend_state("active")
            self._clear_backend_error()
        return ok

    def ensure_running(self, session_id: str) -> bool:
        config = self._config_provider()
        self._set_backend_state("warm")

        start_command = str(config.get("localStartCommand") or "").strip()
        health_url = str(config.get("localHealthUrl") or "").strip()
        if not start_command:
            if self.running():
                return True
            return bool(str(config.get("localTranscribeUrl") or "").strip()) and not health_url
        if self.running():
            if self.process_alive() and self.state.process is not None:
                self.state.pid = self.state.process.pid
            self._set_backend_state("active")
            return True

        now_ms = self._now_ms()
        if restart_cooldown_active(
            last_attempt_ms=self.state.last_start_attempt_ms,
            now_ms=now_ms,
        ):
            return False
        self.state.last_start_attempt_ms = now_ms

        try:
            process = subprocess.Popen(
                ["bash", "-lc", start_command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as error:
            self._set_backend_error(str(error))
            self._log_handler(session_id, "voice_backend_start_error", {"error": str(error)})
            return False

        self.state.process = process
        self.state.pid = process.pid

        timeout_ms = int(config.get("backendStartupTimeoutMs") or 15000)
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            if process.poll() is not None and process.returncode not in (0, None):
                error_text = f"local backend exited with code {process.returncode}"
                self._set_backend_error(error_text)
                self._log_handler(
                    session_id,
                    "voice_backend_start_error",
                    {"error": error_text},
                )
                self.state.process = None
                self.state.pid = None
                return False
            if not health_url:
                if process.poll() is None or process.returncode == 0:
                    self._set_backend_state("active")
                    return True
            if self._ping_health_url(health_url):
                if process.poll() is not None:
                    self.state.process = None
                    self.state.pid = None
                self._set_backend_state("active")
                return True
            time.sleep(0.35)

        if health_url and self._ping_health_url(health_url):
            self._set_backend_state("active")
            return True

        error_text = "local backend startup timeout"
        self._set_backend_error(error_text)
        self._log_handler(session_id, "voice_backend_start_error", {"error": error_text})
        return False

    def stop(self, reason: str, *, keep_sleep_state: bool) -> None:
        config = self._config_provider()
        stop_command = str(config.get("localStopCommand") or "").strip()
        if stop_command:
            with suppress(Exception):
                subprocess.run(
                    ["bash", "-lc", stop_command],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )

        process = self.state.process
        if process is not None and process.poll() is None:
            with suppress(Exception):
                process.terminate()
            with suppress(Exception):
                process.wait(timeout=2.0)
        self.state.process = None
        self.state.pid = None
        self.state.last_health_check_ms = 0
        self.state.last_health_ok = False
        if keep_sleep_state:
            self._set_backend_state("sleeping")
        if reason in {"idle_unload", "shutdown", "reconfigure"}:
            self._clear_backend_error()

    def _ping_health_url(self, url: str) -> bool:
        try:
            request = urllib.request.Request(url=url, method="GET")
            with urllib.request.urlopen(request, timeout=4) as response:
                return 200 <= int(getattr(response, "status", 200) or 200) < 300
        except Exception:
            return False
