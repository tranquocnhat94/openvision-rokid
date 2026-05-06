import sys
import unittest
from pathlib import Path
import asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.preview_store import PreviewStore


class PreviewStoreTest(unittest.TestCase):
    def test_record_frame_exposes_status_without_image_bytes(self):
        store = PreviewStore(events=InMemoryEventStore())

        status = store.record_frame(
            session_id="sess_test",
            source="iphone_webrtc",
            image_bytes=b"jpeg",
            width=640,
            height=480,
            frame_count=11,
            metadata={"orientation": "landscape", "profile": "snapshot"},
        )

        self.assertTrue(status["has_frame"])
        self.assertEqual(status["image_url"], "/api/preview/sess_test/frame.jpg")
        self.assertEqual(status["mjpeg_url"], "/api/preview/sess_test/stream.mjpeg")
        self.assertEqual(status["metadata"]["orientation"], "landscape")
        self.assertEqual(status["metadata"]["profile"], "snapshot")
        self.assertNotIn("image_bytes", status)
        self.assertEqual(store.latest_image("sess_test"), (b"jpeg", "image/jpeg"))

    def test_recent_frames_keeps_bounded_tail(self):
        store = PreviewStore(events=InMemoryEventStore(), recent_frame_limit=3)

        for index in range(5):
            store.record_frame(
                session_id="sess_test",
                source="unit",
                image_bytes=f"jpeg-{index}".encode("utf-8"),
                frame_count=index + 1,
            )

        frames = store.recent_frames("sess_test", limit=10)

        self.assertEqual([frame.frame_count for frame in frames], [3, 4, 5])
        self.assertEqual(frames[-1].image_bytes, b"jpeg-4")


class PreviewStoreStreamTest(unittest.IsolatedAsyncioTestCase):
    async def test_subscriber_receives_latest_frame_and_drops_stale_frames(self):
        store = PreviewStore(events=InMemoryEventStore())
        queue = store.subscribe("sess_test")
        try:
            store.record_frame(
                session_id="sess_test",
                source="unit",
                image_bytes=b"first",
                frame_count=1,
            )
            first = await asyncio.wait_for(queue.get(), timeout=0.1)
            self.assertEqual(first.image_bytes, b"first")

            store.record_frame(
                session_id="sess_test",
                source="unit",
                image_bytes=b"stale",
                frame_count=2,
            )
            store.record_frame(
                session_id="sess_test",
                source="unit",
                image_bytes=b"latest",
                frame_count=3,
            )
            latest = await asyncio.wait_for(queue.get(), timeout=0.1)
            self.assertEqual(latest.image_bytes, b"latest")
        finally:
            store.unsubscribe("sess_test", queue)

    async def test_remove_session_clears_status_and_closes_subscriber(self):
        store = PreviewStore(events=InMemoryEventStore())
        store.record_frame(
            session_id="sess_test",
            source="unit",
            image_bytes=b"jpeg",
            frame_count=1,
        )
        queue = store.subscribe("sess_test")

        self.assertTrue(store.remove_session("sess_test"))
        self.assertIsNone(store.status("sess_test"))
        closed = await asyncio.wait_for(queue.get(), timeout=0.1)
        self.assertIsNone(closed)

    async def test_mark_session_stale_keeps_last_frame_for_inspection(self):
        store = PreviewStore(events=InMemoryEventStore())
        store.record_frame(
            session_id="sess_test",
            source="rv101_live_h264",
            image_bytes=b"jpeg",
            frame_count=7,
        )
        queue = store.subscribe("sess_test")
        try:
            initial = await asyncio.wait_for(queue.get(), timeout=0.1)
            self.assertEqual(initial.frame_count, 7)

            self.assertTrue(store.mark_session_stale("sess_test", reason="live_video_timeout"))
            status = store.status("sess_test")
            stale = await asyncio.wait_for(queue.get(), timeout=0.1)

            self.assertTrue(status["has_frame"])
            self.assertTrue(status["metadata"]["preview_stale"])
            self.assertEqual(status["metadata"]["preview_status"], "stopped")
            self.assertEqual(status["metadata"]["ended_reason"], "live_video_timeout")
            self.assertEqual(stale.image_bytes, b"jpeg")

            self.assertFalse(store.mark_session_stale("sess_test", reason="live_video_timeout"))
            self.assertTrue(queue.empty())
        finally:
            store.unsubscribe("sess_test", queue)

    async def test_mark_session_stale_emits_once_per_reason(self):
        events = InMemoryEventStore()
        store = PreviewStore(events=events)
        store.record_frame(
            session_id="sess_test",
            source="rv101_live_h264",
            image_bytes=b"jpeg",
            frame_count=7,
        )

        self.assertTrue(store.mark_session_stale("sess_test", reason="live_video_timeout"))
        self.assertFalse(store.mark_session_stale("sess_test", reason="live_video_timeout"))

        stale_events = [
            event
            for event in events.list(session_id="sess_test")
            if event["module"] == "preview" and event["event_type"] == "session_marked_stale"
        ]
        self.assertEqual(len(stale_events), 1)


if __name__ == "__main__":
    unittest.main()
