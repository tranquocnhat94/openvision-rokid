import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from app.admin_session_runtime import (
    latest_session_id,
    serialize_live_voice_session,
    serialize_session,
    sort_sessions_by_connected_at,
    tail_session_log_lines,
)


@dataclass
class _DummySession:
    session_id: str
    connected_at: float
    active: bool = True
    control_connected: bool = True
    audio_connected: bool = True
    video_connected: bool = True
    mode: str = "standby"
    latest_speech_state: dict | None = None
    latest_hud_scene: dict | None = None
    latest_voice_command: str | None = None
    latest_skill_trace: list[dict] = field(default_factory=list)
    selected_target_track_id: int | None = None
    selected_target_label: str | None = None
    selected_target_summary: str | None = None
    selected_target_query: str | None = None
    selected_target_visible: bool = False
    selected_target_updated_ms: int = 0

    def summary(self) -> dict:
        return {"sessionId": self.session_id, "mode": self.mode}


class AdminSessionRuntimeTest(unittest.TestCase):
    def test_tail_session_log_lines_parses_json_and_raw_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session.log"
            path.write_text('{"type":"hello"}\nraw line\n', encoding="utf-8")

            items = tail_session_log_lines(path, limit=10)

        self.assertEqual(items[0]["type"], "hello")
        self.assertEqual(items[1]["raw"], "raw line")

    def test_serialize_session_includes_ai_and_voice_context(self) -> None:
        session = _DummySession(
            session_id="sess_a",
            connected_at=10.0,
            latest_skill_trace=[{"tool": "search_target"}],
        )

        payload = serialize_session(
            session,
            latest_ai_result={"headline": "ready"},
            voice_context={"route": "search_target"},
        )

        self.assertEqual(payload["sessionId"], "sess_a")
        self.assertEqual(payload["latestAiResult"], {"headline": "ready"})
        self.assertEqual(payload["voiceContext"], {"route": "search_target"})
        self.assertEqual(payload["latestSkillTrace"], [{"tool": "search_target"}])

    def test_serialize_live_voice_session_omits_empty_selected_target(self) -> None:
        session = _DummySession(session_id="sess_a", connected_at=10.0)

        payload = serialize_live_voice_session(session)

        self.assertIsNone(payload["selectedTarget"])

    def test_sort_sessions_and_latest_id_follow_connected_at_descending(self) -> None:
        sessions = [
            _DummySession(session_id="sess_old", connected_at=5.0),
            _DummySession(session_id="sess_new", connected_at=10.0),
        ]

        sorted_sessions = sort_sessions_by_connected_at(sessions)

        self.assertEqual([item.session_id for item in sorted_sessions], ["sess_new", "sess_old"])
        self.assertEqual(latest_session_id(sorted_sessions), "sess_new")


if __name__ == "__main__":
    unittest.main()
