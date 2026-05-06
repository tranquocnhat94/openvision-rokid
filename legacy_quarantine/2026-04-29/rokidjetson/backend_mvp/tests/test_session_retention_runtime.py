import unittest

from app.session_retention_runtime import (
    SessionRetentionSnapshot,
    session_last_activity_ts,
    session_prune_eligible,
)


class SessionRetentionRuntimeTests(unittest.TestCase):
    def test_session_last_activity_prefers_latest_ping_or_message(self) -> None:
        snapshot = SessionRetentionSnapshot(
            connected_at=100.0,
            last_ping_at=120.0,
            last_message_at=135.0,
            control_connected=False,
            video_connected=False,
            audio_connected=False,
        )

        self.assertEqual(session_last_activity_ts(snapshot), 135.0)

    def test_prune_eligible_after_retention_window_for_inactive_session(self) -> None:
        snapshot = SessionRetentionSnapshot(
            connected_at=100.0,
            last_ping_at=120.0,
            last_message_at=130.0,
            control_connected=False,
            video_connected=False,
            audio_connected=False,
        )

        self.assertTrue(session_prune_eligible(snapshot, now_ts=191.0, retention_sec=60.0))
        self.assertFalse(session_prune_eligible(snapshot, now_ts=189.0, retention_sec=60.0))

    def test_active_session_is_never_pruned(self) -> None:
        snapshot = SessionRetentionSnapshot(
            connected_at=100.0,
            last_ping_at=120.0,
            last_message_at=130.0,
            control_connected=True,
            video_connected=False,
            audio_connected=False,
        )

        self.assertFalse(session_prune_eligible(snapshot, now_ts=999.0, retention_sec=30.0))


if __name__ == "__main__":
    unittest.main()
