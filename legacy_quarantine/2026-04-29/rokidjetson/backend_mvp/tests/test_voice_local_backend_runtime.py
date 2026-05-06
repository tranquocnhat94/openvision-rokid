import unittest

from app.voice_local_backend_runtime import (
    LocalBackendSupervisor,
    health_check_cache_hit,
    restart_cooldown_active,
)


class VoiceLocalBackendRuntimeTests(unittest.TestCase):
    def test_health_check_cache_hit_respects_minimum_cache_window(self) -> None:
        self.assertTrue(health_check_cache_hit(last_check_ms=1000, now_ms=1200, cache_ms=50))
        self.assertFalse(health_check_cache_hit(last_check_ms=1000, now_ms=1300, cache_ms=250))

    def test_restart_cooldown_active_uses_default_window(self) -> None:
        self.assertTrue(restart_cooldown_active(last_attempt_ms=1000, now_ms=4500))
        self.assertFalse(restart_cooldown_active(last_attempt_ms=1000, now_ms=5000))

    def test_ensure_running_without_start_command_accepts_direct_local_http_path(self) -> None:
        state_changes: list[str] = []
        errors: list[str] = []
        clears: list[str] = []
        supervisor = LocalBackendSupervisor(
            config_provider=lambda: {
                "localStartCommand": "",
                "localHealthUrl": "",
                "localTranscribeUrl": "http://127.0.0.1:9000/transcribe",
            },
            log_handler=lambda session_id, event, payload: None,
            set_backend_state=state_changes.append,
            set_backend_error=errors.append,
            clear_backend_error=lambda: clears.append("clear"),
            now_ms=lambda: 1000,
        )

        self.assertTrue(supervisor.ensure_running("session-1"))
        self.assertEqual(state_changes, ["warm"])
        self.assertEqual(errors, [])
        self.assertEqual(clears, [])

    def test_running_uses_cached_health_result_before_rechecking(self) -> None:
        supervisor = LocalBackendSupervisor(
            config_provider=lambda: {
                "localHealthUrl": "http://127.0.0.1:9000/health",
                "localHealthCacheMs": 1000,
            },
            log_handler=lambda session_id, event, payload: None,
            set_backend_state=lambda next_state: None,
            set_backend_error=lambda message: None,
            clear_backend_error=lambda: None,
            now_ms=lambda: 1500,
        )
        supervisor.state.last_health_check_ms = 1000
        supervisor.state.last_health_ok = True
        supervisor._ping_health_url = lambda url: False  # type: ignore[method-assign]

        self.assertTrue(supervisor.running())

    def test_stop_clears_pid_and_health_cache(self) -> None:
        state_changes: list[str] = []
        clears: list[str] = []
        supervisor = LocalBackendSupervisor(
            config_provider=lambda: {"localStopCommand": ""},
            log_handler=lambda session_id, event, payload: None,
            set_backend_state=state_changes.append,
            set_backend_error=lambda message: None,
            clear_backend_error=lambda: clears.append("clear"),
            now_ms=lambda: 1000,
        )
        supervisor.state.pid = 77
        supervisor.state.last_health_check_ms = 900
        supervisor.state.last_health_ok = True

        supervisor.stop("reconfigure", keep_sleep_state=True)

        self.assertIsNone(supervisor.state.pid)
        self.assertEqual(supervisor.state.last_health_check_ms, 0)
        self.assertFalse(supervisor.state.last_health_ok)
        self.assertEqual(state_changes, ["sleeping"])
        self.assertEqual(clears, ["clear"])


if __name__ == "__main__":
    unittest.main()
