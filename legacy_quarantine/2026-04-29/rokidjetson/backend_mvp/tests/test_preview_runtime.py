import queue
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.browser_media_runtime import LatestFrame
from app.preview_runtime import PreviewProcess, PreviewRuntime


class PreviewRuntimeTests(unittest.TestCase):
    def _build_runtime(
        self,
        *,
        ai_requires_frame_bus_provider=None,
        preview_processes: dict[str, PreviewProcess] | None = None,
        latest_frames: dict[str, LatestFrame] | None = None,
        latest_ai_results: dict[str, dict] | None = None,
        latest_codec_config_frames: dict[str, bytes] | None = None,
        latest_preview_session_id: str | None = None,
        events: list[tuple[str, dict]] | None = None,
    ) -> tuple[PreviewRuntime, SimpleNamespace]:
        state = SimpleNamespace(latest_preview_session_id=latest_preview_session_id)
        event_log = events if events is not None else []
        runtime = PreviewRuntime(
            append_session_log=lambda session, event, payload: event_log.append((event, dict(payload))),
            session_lookup=lambda session_id: None,
            session_preview_dir_provider=lambda session: Path("/tmp") / session.session_id,
            preview_processes=preview_processes or {},
            latest_frames=latest_frames or {},
            latest_ai_results=latest_ai_results or {},
            latest_codec_config_frames=latest_codec_config_frames or {},
            latest_preview_session_id_getter=lambda: state.latest_preview_session_id,
            latest_preview_session_id_setter=lambda value: setattr(state, "latest_preview_session_id", value),
            now_ms_provider=lambda: 1234,
            enable_hls_preview=False,
            enable_frame_bus=False,
            ai_requires_frame_bus_provider=ai_requires_frame_bus_provider or (lambda session: False),
            enable_local_preview=False,
            raw_frame_target_fps=10,
            preview_jpeg_quality=82,
            preview_pipe_queue_max=4,
            local_preview_display=":0",
            local_preview_xauthority="/tmp/xauth",
            local_preview_mode="ffplay",
            local_preview_sink="xvimagesink",
            local_preview_port=9080,
        )
        return runtime, state

    def test_needs_preview_restart_when_stream_shape_changes(self) -> None:
        runtime, _ = self._build_runtime()
        preview = PreviewProcess(
            session_id="sess_demo",
            playlist_path=Path("/tmp/index.m3u8"),
            width=720,
            height=960,
            target_fps=10,
            target_bitrate=1_100_000,
            profile_label="MEDIUM",
        )

        self.assertFalse(
            runtime.needs_preview_restart(
                preview,
                width=720,
                height=960,
                target_fps=10,
                target_bitrate=1_100_000,
                profile_label="MEDIUM",
            )
        )
        self.assertTrue(
            runtime.needs_preview_restart(
                preview,
                width=960,
                height=960,
                target_fps=10,
                target_bitrate=1_100_000,
                profile_label="MEDIUM",
            )
        )

    def test_local_preview_command_matches_selected_mode(self) -> None:
        runtime, _ = self._build_runtime()
        ffplay_cmd = runtime.local_preview_command("sess_demo")
        self.assertIn("ffplay", ffplay_cmd[0])
        self.assertIn("pipe:0", ffplay_cmd)

        overlay_runtime, _ = self._build_runtime()
        overlay_runtime._local_preview_mode = "ffplay_overlay"
        overlay_cmd = overlay_runtime.local_preview_command("sess_demo")
        self.assertIn("ffplay", overlay_cmd[0])
        self.assertIn("/preview/sessions/sess_demo/live.mjpg", overlay_cmd[-1])

        gst_runtime, _ = self._build_runtime()
        gst_runtime._local_preview_mode = "gst"
        gst_cmd = gst_runtime.local_preview_command("sess_demo")
        self.assertEqual("gst-launch-1.0", gst_cmd[0])

    def test_stop_preview_process_clears_cached_state(self) -> None:
        events: list[tuple[str, dict]] = []
        preview_processes = {
            "sess_demo": PreviewProcess(
                session_id="sess_demo",
                playlist_path=Path("/tmp/index.m3u8"),
                payload_queue=queue.Queue(),
            )
        }
        latest_frames = {
            "sess_demo": LatestFrame(
                session_id="sess_demo",
                width=720,
                height=960,
                sequence=1,
                timestamp_ms=111,
                bgr_bytes=b"bgr",
                jpeg_bytes=b"jpg",
            )
        }
        latest_ai_results = {"sess_demo": {"headline": "ready"}}
        runtime, state = self._build_runtime(
            preview_processes=preview_processes,
            latest_frames=latest_frames,
            latest_ai_results=latest_ai_results,
            latest_preview_session_id="sess_demo",
            events=events,
        )
        session = SimpleNamespace(session_id="sess_demo", preview_url="http://preview")

        runtime.stop_preview_process(session, reason="test_stop")

        self.assertNotIn("sess_demo", preview_processes)
        self.assertNotIn("sess_demo", latest_frames)
        self.assertNotIn("sess_demo", latest_ai_results)
        self.assertIsNone(state.latest_preview_session_id)
        self.assertEqual(events[-1][0], "preview_stopped")
        self.assertEqual(events[-1][1]["reason"], "test_stop")

    def test_preview_not_required_when_all_sinks_are_off(self) -> None:
        runtime, _ = self._build_runtime()
        session = SimpleNamespace(session_id="sess_demo")

        self.assertFalse(runtime.preview_required_for_session(session))

    def test_preview_required_when_ai_needs_frame_bus_for_session(self) -> None:
        runtime, _ = self._build_runtime(ai_requires_frame_bus_provider=lambda session: session.mode == "scene_monitor")
        session = SimpleNamespace(session_id="sess_demo", mode="scene_monitor")

        self.assertTrue(runtime.preview_required_for_session(session))


if __name__ == "__main__":
    unittest.main()
