import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.rv101_h264_live import Rv101H264LiveStore


class Rv101H264LiveStoreTest(unittest.IsolatedAsyncioTestCase):
    async def test_publish_exposes_h264_status_and_latest_sample_to_subscriber(self):
        store = Rv101H264LiveStore(events=InMemoryEventStore())

        status = store.publish_sample(
            session_id="sess_test",
            header={
                "sequence": 7,
                "isKeyframe": True,
                "width": 1280,
                "height": 720,
                "presentationTimeUs": 123_000,
                "rotation_degrees": 270,
            },
            payload=b"\x00\x00\x00\x01\x67sps",
            media_status={"video": {"metadata": {"profile": "rv101_live_h264_landscape"}}},
        )
        queue = store.subscribe("sess_test")
        try:
            sample = await asyncio.wait_for(queue.get(), timeout=0.1)

            self.assertTrue(status["has_h264_live"])
            self.assertEqual(status["h264_ws_url"], "/ws/preview/sess_test/h264")
            self.assertEqual(status["sample_count"], 1)
            self.assertEqual(status["keyframe_count"], 1)
            self.assertEqual(sample.payload, b"\x00\x00\x00\x01\x67sps")
            self.assertEqual(sample.ws_metadata()["sequence"], 7)
            self.assertEqual(sample.ws_metadata()["metadata"]["rotation_degrees"], 270)
        finally:
            store.unsubscribe("sess_test", queue)

    async def test_queue_is_bounded_and_closes_on_session_close(self):
        store = Rv101H264LiveStore(events=InMemoryEventStore(), queue_size=1)
        queue = store.subscribe("sess_test")
        try:
            store.publish_sample(session_id="sess_test", header={"sequence": 1}, payload=b"first", media_status={})
            store.publish_sample(session_id="sess_test", header={"sequence": 2}, payload=b"latest", media_status={})
            latest = await asyncio.wait_for(queue.get(), timeout=0.1)

            self.assertEqual(latest.payload, b"latest")
            self.assertEqual(store.status("sess_test")["drop_count"], 1)

            store.close_session("sess_test")
            closed = await asyncio.wait_for(queue.get(), timeout=0.1)
            self.assertIsNone(closed)
            self.assertIsNone(store.status("sess_test"))
        finally:
            store.unsubscribe("sess_test", queue)


if __name__ == "__main__":
    unittest.main()
