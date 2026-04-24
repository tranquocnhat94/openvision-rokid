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
        )

        self.assertTrue(status["has_frame"])
        self.assertEqual(status["image_url"], "/api/preview/sess_test/frame.jpg")
        self.assertEqual(status["mjpeg_url"], "/api/preview/sess_test/stream.mjpeg")
        self.assertNotIn("image_bytes", status)
        self.assertEqual(store.latest_image("sess_test"), (b"jpeg", "image/jpeg"))


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


if __name__ == "__main__":
    unittest.main()
