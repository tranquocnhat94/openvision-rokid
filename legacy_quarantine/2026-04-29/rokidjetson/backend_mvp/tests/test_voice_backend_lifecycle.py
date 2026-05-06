import unittest

from app.voice_backend_lifecycle import BackendLifecycleSnapshot, evaluate_backend_lifecycle


class VoiceBackendLifecycleTests(unittest.TestCase):
    def test_realtime_backend_goes_active_with_session_and_api_key(self) -> None:
        decision = evaluate_backend_lifecycle(
            BackendLifecycleSnapshot(
                uses_any_realtime_backend=True,
                uses_local_backend=False,
                has_active_sessions=True,
                has_api_key=True,
                backend_state="sleeping",
                auto_wake_on_session=False,
                last_activity_ms=0,
                now_ms=1000,
                idle_unload_ms=60000,
                local_backend_running=False,
                local_process_alive=False,
            )
        )

        self.assertEqual(decision.next_state, "active")
        self.assertTrue(decision.touch_activity)
        self.assertFalse(decision.warm_local_backend)

    def test_realtime_backend_sleeps_when_not_usable(self) -> None:
        decision = evaluate_backend_lifecycle(
            BackendLifecycleSnapshot(
                uses_any_realtime_backend=True,
                uses_local_backend=False,
                has_active_sessions=True,
                has_api_key=False,
                backend_state="active",
                auto_wake_on_session=False,
                last_activity_ms=900,
                now_ms=1000,
                idle_unload_ms=60000,
                local_backend_running=False,
                local_process_alive=False,
            )
        )

        self.assertEqual(decision.next_state, "sleeping")
        self.assertFalse(decision.touch_activity)

    def test_local_backend_warms_on_active_session_when_auto_wake_enabled(self) -> None:
        decision = evaluate_backend_lifecycle(
            BackendLifecycleSnapshot(
                uses_any_realtime_backend=False,
                uses_local_backend=True,
                has_active_sessions=True,
                has_api_key=False,
                backend_state="sleeping",
                auto_wake_on_session=True,
                last_activity_ms=0,
                now_ms=1000,
                idle_unload_ms=60000,
                local_backend_running=False,
                local_process_alive=False,
            )
        )

        self.assertEqual(decision.next_state, "warm")
        self.assertTrue(decision.touch_activity)
        self.assertTrue(decision.warm_local_backend)

    def test_local_backend_can_idle_unload_even_with_active_session(self) -> None:
        decision = evaluate_backend_lifecycle(
            BackendLifecycleSnapshot(
                uses_any_realtime_backend=False,
                uses_local_backend=True,
                has_active_sessions=True,
                has_api_key=False,
                backend_state="active",
                auto_wake_on_session=True,
                last_activity_ms=1000,
                now_ms=62050,
                idle_unload_ms=60000,
                local_backend_running=True,
                local_process_alive=True,
            )
        )

        self.assertTrue(decision.touch_activity)
        self.assertTrue(decision.stop_local_backend)
        self.assertEqual(decision.stop_reason, "idle_unload")

    def test_local_backend_sleeps_when_no_session_and_no_running_process(self) -> None:
        decision = evaluate_backend_lifecycle(
            BackendLifecycleSnapshot(
                uses_any_realtime_backend=False,
                uses_local_backend=True,
                has_active_sessions=False,
                has_api_key=False,
                backend_state="warm",
                auto_wake_on_session=True,
                last_activity_ms=1000,
                now_ms=2000,
                idle_unload_ms=60000,
                local_backend_running=False,
                local_process_alive=False,
            )
        )

        self.assertEqual(decision.next_state, "sleeping")
        self.assertFalse(decision.stop_local_backend)


if __name__ == "__main__":
    unittest.main()
