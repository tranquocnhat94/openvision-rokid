import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.cloud_gateway import CloudGateway
from openvision_jetson.perception_graph import PerceptionGraph
from openvision_jetson.skill_executor import SkillExecutor


class SkillExecutorTest(unittest.TestCase):
    def test_count_people_uses_latest_perception_snapshot(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="unit",
            detections=[
                {"label": "person", "confidence": 0.9, "bbox": [0, 0, 1, 1]},
                {"label": "person", "confidence": 0.8, "bbox": [1, 0, 2, 1]},
                {"label": "bag", "confidence": 0.7},
            ],
        )
        executor = SkillExecutor(perception=perception, events=events)

        result = executor.execute(
            name="count_people",
            args={"min_confidence": 0.25},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["count"], 2)
        self.assertEqual(result["result"]["hud"]["answer_strip"], "2 người")

    def test_skill_execution_event_summary_omits_raw_identity_text(self):
        events = InMemoryEventStore()
        executor = SkillExecutor(
            perception=PerceptionGraph(events=events),
            events=events,
        )

        executor.execute(
            name="select_target",
            args={"target_id": "obj_person_1", "display_name": "Trâm", "reason": "user confirmed"},
            session_id="sess_test",
        )

        executed = [
            event
            for event in events.list(session_id="sess_test")
            if event["module"] == "skills" and event["event_type"] == "executed"
        ][-1]
        payload = executed["payload"]
        self.assertEqual(payload["name"], "select_target")
        self.assertIn("duration_ms", payload)
        self.assertTrue(payload["result_summary"]["hud_answer_present"])
        self.assertNotIn("Trâm", json.dumps(payload, ensure_ascii=False))

    def test_count_people_returns_no_evidence_without_snapshot(self):
        executor = SkillExecutor(
            perception=PerceptionGraph(events=InMemoryEventStore()),
            events=InMemoryEventStore(),
        )

        result = executor.execute(name="count_people", args={}, session_id="sess_missing")

        self.assertEqual(result["status"], "no_evidence")

    def test_count_people_reports_captured_preview_without_detector(self):
        preview = {
            "session_id": "sess_test",
            "source": "iphone_webrtc",
            "width": 508,
            "height": 904,
            "frame_count": 3,
            "image_url": "/api/preview/sess_test/frame.jpg",
        }
        executor = SkillExecutor(
            perception=PerceptionGraph(events=InMemoryEventStore()),
            events=InMemoryEventStore(),
            preview_status_provider=lambda session_id: preview if session_id == "sess_test" else None,
        )

        result = executor.execute(name="count_people", args={}, session_id="sess_test")

        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["result"]["missing_runtime"], "perception_snapshot")
        self.assertEqual(result["result"]["preview"]["image_url"], "/api/preview/sess_test/frame.jpg")
        self.assertEqual(result["result"]["hud"]["answer_strip"], "Đã chụp ảnh; chưa đếm được")

    def test_query_scene_builds_cloud_bundle_from_captured_preview(self):
        preview = {
            "session_id": "sess_test",
            "source": "iphone_webrtc",
            "width": 508,
            "height": 904,
            "frame_count": 3,
            "image_url": "/api/preview/sess_test/frame.jpg",
        }
        executor = SkillExecutor(
            perception=PerceptionGraph(events=InMemoryEventStore()),
            events=InMemoryEventStore(),
            preview_status_provider=lambda session_id: preview if session_id == "sess_test" else None,
        )

        result = executor.execute(
            name="query_scene",
            args={"question": "đang có gì trước mặt"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "needs_cloud")
        self.assertEqual(result["result"]["preview"]["image_url"], "/api/preview/sess_test/frame.jpg")
        self.assertEqual(result["result"]["cloud_evidence_bundle"]["frame_refs"], ["/api/preview/sess_test/frame.jpg"])
        self.assertEqual(result["result"]["cloud_result"]["error"]["code"], "cloud_provider_missing")
        self.assertEqual(result["result"]["hud"]["answer_strip"], "Đã chụp ảnh; visual verifier chưa sẵn sàng.")

    def test_query_scene_uses_cloud_answer_from_captured_preview(self):
        preview = {
            "session_id": "sess_test",
            "source": "iphone_webrtc",
            "width": 508,
            "height": 904,
            "frame_count": 3,
            "image_url": "/api/preview/sess_test/frame.jpg",
        }

        def provider(bundle):
            return {
                "schema_version": "cloud_result.v1",
                "status": "ok",
                "answer_short": "Trước mặt có laptop và một cái cốc.",
                "confidence": 0.82,
                "safety_flags": [],
            }

        events = InMemoryEventStore()
        executor = SkillExecutor(
            perception=PerceptionGraph(events=events),
            events=events,
            cloud_gateway=CloudGateway(events=events, provider=provider),
            preview_status_provider=lambda session_id: preview if session_id == "sess_test" else None,
        )

        result = executor.execute(
            name="query_scene",
            args={"question": "đang có gì trước mặt tôi"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "needs_cloud")
        self.assertEqual(result["result"]["answer"], "Trước mặt có laptop và một cái cốc.")
        self.assertEqual(result["result"]["user_message"], "Trước mặt có laptop và một cái cốc.")
        self.assertEqual(result["result"]["hud"]["answer_strip"], "Trước mặt có laptop và một cái cốc.")

    def test_scene_describe_uses_cloud_gateway_with_scene_skill_id(self):
        preview = {
            "session_id": "sess_test",
            "source": "iphone_webrtc",
            "width": 508,
            "height": 904,
            "frame_count": 3,
            "image_url": "/api/preview/sess_test/frame.jpg",
        }
        seen_bundles = []

        def provider(bundle):
            seen_bundles.append(bundle)
            return {
                "schema_version": "cloud_result.v1",
                "status": "ok",
                "answer_short": "Trước mặt có bàn làm việc và màn hình.",
                "confidence": 0.85,
                "safety_flags": [],
            }

        events = InMemoryEventStore()
        executor = SkillExecutor(
            perception=PerceptionGraph(events=events),
            events=events,
            cloud_gateway=CloudGateway(events=events, provider=provider),
            preview_status_provider=lambda session_id: preview if session_id == "sess_test" else None,
        )

        result = executor.execute(
            name="scene_describe",
            args={"focus": "đang có gì trước mặt tôi"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "needs_cloud")
        self.assertEqual(seen_bundles[0]["skill_id"], "scene_describe")
        self.assertEqual(seen_bundles[0]["user_query"], "đang có gì trước mặt tôi")
        self.assertEqual(result["result"]["answer"], "Trước mặt có bàn làm việc và màn hình.")
        self.assertEqual(result["result"]["hud"]["answer_strip"], "Trước mặt có bàn làm việc và màn hình.")
        self.assertIn("scene_describe", result["result"]["hud"]["edge_chips"])

    def test_text_reader_uses_cloud_gateway_for_ocr_preview(self):
        preview = {
            "session_id": "sess_text",
            "source": "rv101_tcp",
            "width": 1280,
            "height": 720,
            "frame_count": 9,
            "image_url": "/api/preview/sess_text/frame.jpg",
        }
        seen_bundles = []

        def provider(bundle):
            seen_bundles.append(bundle)
            return {
                "schema_version": "cloud_result.v1",
                "status": "ok",
                "answer_short": "Biển ghi: Lối ra.",
                "confidence": 0.88,
                "safety_flags": [],
            }

        events = InMemoryEventStore()
        executor = SkillExecutor(
            perception=PerceptionGraph(events=events),
            events=events,
            cloud_gateway=CloudGateway(events=events, provider=provider),
            preview_status_provider=lambda session_id: preview if session_id == "sess_text" else None,
        )

        result = executor.execute(
            name="text_reader",
            args={"question": "biển này ghi gì", "language_hint": "vi"},
            session_id="sess_text",
        )

        self.assertEqual(result["status"], "needs_cloud")
        self.assertEqual(seen_bundles[0]["skill_id"], "text_reader")
        self.assertEqual(seen_bundles[0]["user_query"], "biển này ghi gì")
        self.assertEqual(seen_bundles[0]["local_summary"]["task"], "read_visible_text")
        self.assertEqual(seen_bundles[0]["frame_refs"], ["/api/preview/sess_text/frame.jpg"])
        self.assertEqual(result["result"]["answer"], "Biển ghi: Lối ra.")
        self.assertEqual(result["result"]["text"], "Biển ghi: Lối ra.")
        self.assertEqual(result["result"]["hud"]["answer_strip"], "Biển ghi: Lối ra.")
        self.assertIn("text_reader", result["result"]["hud"]["edge_chips"])

    def test_object_counter_uses_cloud_gateway_for_preview_counting(self):
        preview = {
            "session_id": "sess_test",
            "source": "iphone_webrtc",
            "width": 508,
            "height": 904,
            "frame_count": 3,
            "image_url": "/api/preview/sess_test/frame.jpg",
        }
        seen_bundles = []

        def provider(bundle):
            seen_bundles.append(bundle)
            return {
                "schema_version": "cloud_result.v1",
                "status": "uncertain",
                "answer_short": "Ước khoảng 12 hạt.",
                "confidence": 0.62,
                "safety_flags": ["approximate_count"],
            }

        events = InMemoryEventStore()
        executor = SkillExecutor(
            perception=PerceptionGraph(events=events),
            events=events,
            cloud_gateway=CloudGateway(events=events, provider=provider),
            preview_status_provider=lambda session_id: preview if session_id == "sess_test" else None,
        )

        result = executor.execute(
            name="object_counter",
            args={"question": "có bao nhiêu hạt trong ảnh", "target": "hạt"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "needs_cloud")
        self.assertEqual(seen_bundles[0]["skill_id"], "object_counter")
        self.assertEqual(seen_bundles[0]["local_summary"]["target"], "hạt")
        self.assertEqual(result["result"]["answer"], "Ước khoảng 12 hạt.")
        self.assertEqual(result["result"]["hud"]["answer_strip"], "Ước khoảng 12 hạt.")
        self.assertIn("object_counter", result["result"]["hud"]["edge_chips"])

    def test_object_counter_can_count_matching_local_detections(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="unit",
            detections=[
                {"label": "cup", "confidence": 0.9},
                {"label": "cup", "confidence": 0.8},
                {"label": "bag", "confidence": 0.7},
            ],
        )
        executor = SkillExecutor(perception=perception, events=events)

        result = executor.execute(
            name="object_counter",
            args={"question": "có mấy cup", "target": "cup"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["count"], 2)
        self.assertEqual(result["result"]["hud"]["answer_strip"], "Có 2 cup.")

    def test_remember_person_uses_snapshot_preview_and_people_provider(self):
        preview = {
            "session_id": "sess_memory",
            "source": "iphone_webrtc",
            "width": 508,
            "height": 904,
            "frame_count": 3,
            "image_url": "/api/preview/sess_memory/frame.jpg",
        }
        seen = []

        def memory_provider(**kwargs):
            seen.append(kwargs)
            return {
                "status": "uploaded",
                "message": "Capture uploaded to Immich.",
                "capture": {"capture_id": "capture_1", "immich_asset_id": "asset_1"},
                "identity_enrollment": {"status": "enrolled"},
            }

        executor = SkillExecutor(
            perception=PerceptionGraph(events=InMemoryEventStore()),
            events=InMemoryEventStore(),
            preview_status_provider=lambda session_id: preview if session_id == "sess_memory" else None,
            person_memory_provider=memory_provider,
        )

        result = executor.execute(
            name="remember_person",
            args={"display_name": "Trâm", "aliases": ["tram"]},
            session_id="sess_memory",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(seen[0]["display_name"], "Trâm")
        self.assertTrue(seen[0]["enroll_identity"])
        self.assertEqual(result["result"]["memory"]["status"], "uploaded")
        self.assertIn("identity", result["result"]["hud"]["edge_chips"])
        self.assertIn("Đã ghi nhớ Trâm", result["result"]["answer"])

    def test_target_finder_returns_anonymous_aim_assist_for_people(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="unit",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [300, 120, 390, 430],
                    "track_id": "p1",
                    "crop_ref": "/api/crops/sess_test/p1.jpg",
                },
                {
                    "label": "person",
                    "confidence": 0.82,
                    "bbox": [20, 110, 120, 420],
                    "track_id": "p2",
                },
                {"label": "bag", "confidence": 0.7, "bbox": [10, 10, 80, 80]},
            ],
        )
        executor = SkillExecutor(perception=perception, events=events)

        result = executor.execute(
            name="target_finder",
            args={"query": "tìm người trong đám đông", "target_type": "person"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["candidate_count"], 2)
        self.assertEqual(result["result"]["identity_policy"]["status"], "identity_scan_unavailable")
        self.assertEqual(result["result"]["detector_status"]["status"], "fallback_perception")
        self.assertFalse(result["result"]["detector_status"]["has_yolo26_stream"])
        self.assertEqual(result["result"]["target_hint"]["status"], "guiding")
        self.assertEqual(result["result"]["target_hint"]["anonymous_id"], "P1")
        self.assertEqual(result["result"]["target_hint"]["crosshair"]["style"], "tiny_center_reticle")
        self.assertIn("target_finder", result["result"]["hud"]["edge_chips"])
        self.assertEqual(len(result["result"]["hud"]["thumbnails"]), 2)

    def test_target_finder_surfaces_yolo26_stream_detector_status(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="yolo26_rokid_stream:openvision_iphone_yolo26",
            width=640,
            height=480,
            frame_id="frame_42",
            detections=[
                {
                    "label": "person",
                    "confidence": 0.94,
                    "bbox": [300, 120, 390, 430],
                    "track_id": "p1",
                },
            ],
        )
        executor = SkillExecutor(
            perception=perception,
            events=events,
            detector_status_provider=lambda: {
                "name": "yolo26_rokid",
                "mode": "external_stream",
                "status": "ready",
                "stream_ingest_enabled": True,
            },
        )

        result = executor.execute(
            name="target_finder",
            args={"query": "tìm người trong đám đông", "target_type": "person"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["detector_status"]["status"], "ready")
        self.assertTrue(result["result"]["detector_status"]["has_yolo26_stream"])
        self.assertTrue(result["result"]["detector_status"]["ready_for_target_finder"])
        self.assertEqual(result["result"]["detector_status"]["frame_id"], "frame_42")
        self.assertIn("yolo26", result["result"]["hud"]["edge_chips"])
        self.assertIn("YOLO26 stream bbox", result["result"]["summary"])

    def test_target_finder_surfaces_face_identity_stream_detector_status(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            frame_id="face_42",
            detections=[
                {
                    "label": "person",
                    "confidence": 0.94,
                    "bbox": [250, 90, 330, 230],
                    "track_id": "f1",
                    "attributes": {"identity_vector": [1.0, 0.0], "face_confidence": 0.94},
                },
            ],
        )
        executor = SkillExecutor(
            perception=perception,
            events=events,
            detector_status_provider=lambda: {
                "name": "yolo26_rokid",
                "mode": "external_stream",
                "status": "ready",
                "stream_ingest_enabled": True,
                "face_identity_status": {
                    "name": "face_identity",
                    "mode": "external_stream",
                    "status": "ready",
                    "stream_ingest_enabled": True,
                },
            },
        )

        result = executor.execute(
            name="target_finder",
            args={"query": "tìm người trong đám đông", "target_type": "person"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["detector_status"]["status"], "ready")
        self.assertTrue(result["result"]["detector_status"]["has_face_identity_stream"])
        self.assertTrue(result["result"]["detector_status"]["ready_for_target_finder"])
        self.assertEqual(result["result"]["detector_status"]["frame_id"], "face_42")
        self.assertIn("face_id", result["result"]["hud"]["edge_chips"])
        self.assertIn("face identity stream", result["result"]["summary"])

    def test_target_finder_named_contact_waits_for_identity_db_when_unwired(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="unit",
            width=640,
            height=480,
            detections=[
                {"label": "person", "confidence": 0.91, "bbox": [280, 100, 400, 450], "track_id": "p1"},
                {"label": "person", "confidence": 0.86, "bbox": [30, 120, 150, 450], "track_id": "p2"},
            ],
        )
        executor = SkillExecutor(perception=perception, events=events)

        result = executor.execute(
            name="target_finder",
            args={"query": "tìm Trâm trong đám đông", "target_type": "person"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["confirmed_match_count"], 0)
        self.assertEqual(result["result"]["identity_policy"]["status"], "identity_lookup_unavailable")
        self.assertEqual(result["result"]["target_hint"]["status"], "manual_selection_required")
        self.assertIsNone(result["result"]["selected_candidate_id"])
        self.assertIn("identity_setup", result["result"]["hud"]["edge_chips"])

    def test_target_finder_uses_local_contact_identity_provider(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="yolo26_rokid_stream:openvision_iphone_yolo26",
            width=640,
            height=480,
            detections=[
                {"label": "person", "confidence": 0.91, "bbox": [280, 100, 400, 450], "track_id": "p1"},
                {"label": "person", "confidence": 0.86, "bbox": [30, 120, 150, 450], "track_id": "p2"},
            ],
        )

        def identity_provider(*, candidates, query, session_id):
            self.assertEqual(query, "tìm Trâm trong đám đông")
            self.assertEqual(session_id, "sess_test")
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "confirmed",
                "provider": "openvision_local_contact_identity",
                "match_count": 1,
                "matches": [
                    {
                        "track_id": "p2",
                        "contact_id": "contact_tram",
                        "display_name": "Trâm",
                        "confidence": 0.94,
                        "identity_match": "contact_db",
                        "match_status": "identity_confirmed",
                    }
                ],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            detector_status_provider=lambda: {
                "name": "yolo26_rokid",
                "mode": "external_stream",
                "status": "ready",
                "stream_ingest_enabled": True,
            },
            identity_match_provider=identity_provider,
        )

        result = executor.execute(
            name="target_finder",
            args={"query": "tìm Trâm trong đám đông", "target_type": "person"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["confirmed_match_count"], 1)
        self.assertEqual(result["result"]["identity_policy"]["status"], "contact_match_confirmed")
        self.assertEqual(result["result"]["identity_provider"]["status"], "confirmed")
        self.assertEqual(result["result"]["target_hint"]["display_name"], "Trâm")
        self.assertEqual(result["result"]["target_hint"]["contact_id"], "contact_tram")
        self.assertEqual(result["result"]["target_hint"]["status"], "guiding")
        self.assertEqual(result["result"]["selected_candidate_id"], result["result"]["candidates"][1]["target_id"])
        self.assertIn("contact_db", result["result"]["hud"]["edge_chips"])

    def test_target_finder_named_query_uses_identity_provider_for_non_hardcoded_name(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [280, 100, 400, 450],
                    "track_id": "f1",
                    "attributes": {"embedding_model": "sface", "identity_vector": [1.0, 0.0]},
                }
            ],
        )
        calls = []

        def identity_provider(*, candidates, query, session_id):
            calls.append({"query": query, "session_id": session_id, "candidate_count": len(candidates)})
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "confirmed",
                "provider": "openvision_local_contact_identity",
                "candidate_count": len(candidates),
                "candidate_vector_count": 1,
                "requested_contact_count": 1,
                "match_count": 1,
                "matches": [
                    {
                        "track_id": "f1",
                        "contact_id": "contact_abao",
                        "display_name": "A Bảo",
                        "confidence": 0.94,
                        "identity_match": "contact_db",
                        "match_status": "identity_confirmed",
                    }
                ],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
        )

        result = executor.execute(
            name="target_finder",
            args={"query": "tìm A Bảo", "target_type": "person"},
            session_id="sess_test",
        )

        self.assertEqual(calls, [{"query": "tìm A Bảo", "session_id": "sess_test", "candidate_count": 1}])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["identity_policy"]["status"], "contact_match_confirmed")
        self.assertEqual(result["result"]["target_hint"]["display_name"], "A Bảo")
        self.assertEqual(result["result"]["hud"]["answer_strip"], "A Bảo · đúng tâm")
        identity_events = [
            event
            for event in events.list(session_id="sess_test")
            if event["module"] == "skills" and event["event_type"] == "target_finder_identity_checked"
        ]
        self.assertEqual(identity_events[-1]["payload"]["provider_status"], "confirmed")
        self.assertEqual(identity_events[-1]["payload"]["match_count"], 1)

    def test_person_info_identifies_known_person_and_enriches_people_profile(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [260, 90, 390, 440],
                    "track_id": "f1",
                    "attributes": {"embedding_model": "sface", "identity_vector": [1.0, 0.0]},
                }
            ],
        )
        identity_queries = []

        def identity_provider(*, candidates, query, session_id):
            identity_queries.append(query)
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "confirmed",
                "provider": "openvision_local_contact_identity",
                "candidate_count": len(candidates),
                "candidate_vector_count": 1,
                "requested_contact_count": 12,
                "match_count": 1,
                "matches": [
                    {
                        "track_id": "f1",
                        "contact_id": "contact_abao",
                        "display_name": "A Bảo",
                        "confidence": 0.94,
                        "identity_match": "contact_db",
                        "match_status": "identity_confirmed",
                    }
                ],
            }

        def profile_provider(**kwargs):
            self.assertEqual(kwargs["display_name"], "A Bảo")
            return {
                "status": "found",
                "match_method": "exact_name_or_alias",
                "person": {
                    "display_name": "A Bảo",
                    "aliases": ["Bao"],
                    "phone": "0900000000",
                    "address": "HCM",
                    "age": "32",
                    "where_lives": "Quận 1",
                    "relationship": "bạn cà phê",
                    "first_met": "gặp lần đầu ở Đà Nẵng",
                    "links": {"facebook": "https://facebook.example/bao"},
                    "facts": {"work": "camera"},
                    "notes": "hay nói chuyện AI",
                },
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
            person_profile_provider=profile_provider,
        )

        result = executor.execute(
            name="person_info",
            args={"query": "cho tôi thông tin về người này", "info_focus": "summary"},
            session_id="sess_test",
        )

        self.assertEqual(identity_queries, ["cho tôi thông tin về người này"])
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["result"]["known_person"])
        self.assertEqual(result["result"]["identity_match"]["display_name"], "A Bảo")
        self.assertIn("A Bảo", result["result"]["answer"])
        self.assertIn("bạn cà phê", result["result"]["answer"])
        self.assertIn("people_registry", result["result"]["hud"]["edge_chips"])
        self.assertEqual(result["result"]["hud"]["target_hint"]["status"], "identified")
        identity_events = [
            event
            for event in events.list(session_id="sess_test")
            if event["module"] == "skills" and event["event_type"] == "person_info_identity_checked"
        ]
        self.assertEqual(identity_events[-1]["payload"]["provider_status"], "confirmed")
        self.assertEqual(identity_events[-1]["payload"]["identity_query"], "cho tôi thông tin về người này")

    def test_person_info_follow_up_uses_last_known_profile_when_face_frame_drops(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [260, 90, 390, 440],
                    "track_id": "f1",
                    "attributes": {"embedding_model": "sface", "identity_vector": [1.0, 0.0]},
                }
            ],
        )

        def identity_provider(*, candidates, query, session_id):
            if not candidates:
                return {
                    "schema_version": "openvision.contact_identity_match.v1",
                    "status": "no_candidate_vectors",
                    "provider": "openvision_local_contact_identity",
                    "match_count": 0,
                    "matches": [],
                }
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "confirmed",
                "provider": "openvision_local_contact_identity",
                "candidate_vector_count": 1,
                "requested_contact_count": 1,
                "match_count": 1,
                "matches": [
                    {
                        "track_id": "f1",
                        "contact_id": "contact_abao",
                        "display_name": "A Bảo",
                        "confidence": 0.94,
                        "identity_match": "contact_db",
                        "match_status": "identity_confirmed",
                    }
                ],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
            person_profile_provider=lambda **_: {
                "status": "found",
                "person": {"display_name": "A Bảo", "phone": "0900000000", "relationship": "bạn cà phê"},
            },
        )
        first = executor.execute(
            name="person_info",
            args={"query": "có ai quen không"},
            session_id="sess_test",
        )
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            detections=[],
        )
        second = executor.execute(
            name="person_info",
            args={"query": "còn thông tin gì không", "info_focus": "full"},
            session_id="sess_test",
        )

        self.assertEqual(first["result"]["answer"], "Có, A Bảo. Bạn cần thêm thông tin gì nữa không?")
        self.assertEqual(second["status"], "ok")
        self.assertIn("số điện thoại", second["result"]["answer"])
        self.assertEqual(second["result"]["held_context"]["status"], "using_last_known_person")
        self.assertIn("held_context", second["result"]["hud"]["edge_chips"])

    def test_person_info_explains_low_light_face_quality(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_snapshot:person_info",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [260, 90, 390, 440],
                    "track_id": "snap_f1",
                    "attributes": {
                        "embedding_model": "sface",
                        "identity_vector": [1.0, 0.0],
                        "identity_quality": "too_dark_for_identity",
                        "identity_quality_reasons": ["too_dark_for_identity", "low_contrast_for_identity"],
                    },
                }
            ],
        )

        def identity_provider(*, candidates, query, session_id):
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "low_quality_face",
                "provider": "openvision_local_contact_identity",
                "candidate_count": len(candidates),
                "candidate_vector_count": 0,
                "low_quality_candidate_count": 1,
                "quality_reasons": {"too_dark_for_identity": 1, "low_contrast_for_identity": 1},
                "requested_contact_count": 12,
                "match_count": 0,
                "matches": [],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
        )

        result = executor.execute(
            name="person_info",
            args={"query": "người này là ai"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["result"]["known_person"])
        self.assertIn("hơi tối", result["result"]["answer"])
        self.assertIn("face_dark", result["result"]["hud"]["edge_chips"])
        identity_events = [
            event
            for event in events.list(session_id="sess_test")
            if event["module"] == "skills" and event["event_type"] == "person_info_identity_checked"
        ]
        self.assertEqual(identity_events[-1]["payload"]["quality_reasons"], {"too_dark_for_identity": 1, "low_contrast_for_identity": 1})

    def test_person_info_name_reminder_holds_same_weak_match_briefly(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [260, 90, 390, 440],
                    "track_id": "f1",
                    "attributes": {"embedding_model": "sface", "identity_vector": [1.0, 0.0]},
                }
            ],
        )
        calls = 0

        def identity_provider(*, candidates, query, session_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {
                    "schema_version": "openvision.contact_identity_match.v1",
                    "status": "confirmed",
                    "provider": "openvision_local_contact_identity",
                    "candidate_count": len(candidates),
                    "candidate_vector_count": 1,
                    "requested_contact_count": 1,
                    "match_count": 1,
                    "matches": [
                        {
                            "track_id": "f1",
                            "contact_id": "contact_miu",
                            "display_name": "Miu Thúi",
                            "confidence": 0.61,
                            "identity_match": "contact_db",
                            "match_status": "identity_confirmed",
                        }
                    ],
                }
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "no_match",
                "provider": "openvision_local_contact_identity",
                "candidate_count": len(candidates),
                "candidate_vector_count": 1,
                "requested_contact_count": 1,
                "match_count": 0,
                "best_score": 0.39,
                "best_match": {
                    "contact_id": "contact_miu",
                    "display_name": "Miu Thúi",
                    "confidence": 0.39,
                },
                "matches": [],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
        )

        first = executor.execute(
            name="person_info",
            args={"query": "bật chế độ nhắc tên", "scan_mode": "name_reminder", "info_focus": "name"},
            session_id="sess_test",
        )
        second = executor.execute(
            name="person_info",
            args={"query": "bật chế độ nhắc tên", "scan_mode": "name_reminder", "info_focus": "name"},
            session_id="sess_test",
        )

        self.assertEqual(first["result"]["answer"], "Miu Thúi")
        self.assertEqual(second["result"]["answer"], "Miu Thúi")
        self.assertEqual(second["result"]["held_context"]["status"], "using_last_known_person")
        self.assertIn("held_context", second["result"]["hud"]["edge_chips"])

    def test_person_info_name_reminder_does_not_switch_to_weak_different_match(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [260, 90, 390, 440],
                    "track_id": "f1",
                    "attributes": {"embedding_model": "sface", "identity_vector": [1.0, 0.0]},
                }
            ],
        )
        calls = 0

        def identity_provider(*, candidates, query, session_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {
                    "schema_version": "openvision.contact_identity_match.v1",
                    "status": "confirmed",
                    "provider": "openvision_local_contact_identity",
                    "candidate_count": len(candidates),
                    "candidate_vector_count": 1,
                    "requested_contact_count": 36,
                    "match_count": 1,
                    "matches": [
                        {
                            "track_id": "f1",
                            "contact_id": "contact_miu",
                            "display_name": "Miu Thúi",
                            "confidence": 0.64,
                            "identity_match": "contact_db",
                            "match_status": "identity_confirmed",
                        }
                    ],
                }
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "confirmed",
                "provider": "openvision_local_contact_identity",
                "candidate_count": len(candidates),
                "candidate_vector_count": 1,
                "requested_contact_count": 36,
                "match_count": 1,
                "best_score": 0.54,
                "best_match": {
                    "contact_id": "contact_phuc",
                    "display_name": "Phúc Nguyên",
                    "confidence": 0.54,
                },
                "matches": [
                    {
                        "track_id": "f1",
                        "contact_id": "contact_phuc",
                        "display_name": "Phúc Nguyên",
                        "confidence": 0.54,
                        "identity_match": "contact_db",
                        "match_status": "identity_confirmed",
                    }
                ],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
        )

        first = executor.execute(
            name="person_info",
            args={"query": "bật chế độ nhắc tên", "scan_mode": "name_reminder", "info_focus": "name"},
            session_id="sess_test",
        )
        second = executor.execute(
            name="person_info",
            args={"query": "bật chế độ nhắc tên", "scan_mode": "name_reminder", "info_focus": "name"},
            session_id="sess_test",
        )

        self.assertEqual(first["result"]["answer"], "Miu Thúi")
        self.assertEqual(second["result"]["answer"], "Miu Thúi")
        self.assertEqual(second["result"]["identity_match"]["contact_id"], "contact_miu")
        self.assertEqual(second["result"]["held_context"]["status"], "using_last_known_person")

    def test_person_info_name_reminder_hides_initial_weak_name(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [260, 90, 390, 440],
                    "track_id": "f1",
                    "attributes": {"embedding_model": "sface", "identity_vector": [1.0, 0.0]},
                }
            ],
        )

        def identity_provider(*, candidates, query, session_id):
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "confirmed",
                "provider": "openvision_local_contact_identity",
                "candidate_count": len(candidates),
                "candidate_vector_count": 1,
                "requested_contact_count": 36,
                "match_count": 1,
                "best_score": 0.52,
                "best_match": {
                    "contact_id": "contact_phuc",
                    "display_name": "Phúc Nguyên",
                    "confidence": 0.52,
                },
                "matches": [
                    {
                        "track_id": "f1",
                        "contact_id": "contact_phuc",
                        "display_name": "Phúc Nguyên",
                        "confidence": 0.52,
                        "identity_match": "contact_db",
                        "match_status": "identity_confirmed",
                    }
                ],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
        )

        result = executor.execute(
            name="person_info",
            args={"query": "bật chế độ nhắc tên", "scan_mode": "name_reminder", "info_focus": "name"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["result"]["known_person"])
        self.assertIn("chưa đủ chắc", result["result"]["answer"])
        self.assertIn("identity_uncertain", result["result"]["hud"]["edge_chips"])

    def test_target_finder_uses_target_name_when_cloud_simplifies_query(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [280, 100, 400, 450],
                    "track_id": "f1",
                    "attributes": {"embedding_model": "sface", "identity_vector": [1.0, 0.0]},
                }
            ],
        )
        calls = []

        def identity_provider(*, candidates, query, session_id):
            calls.append(query)
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "confirmed",
                "provider": "openvision_local_contact_identity",
                "candidate_count": len(candidates),
                "candidate_vector_count": 1,
                "requested_contact_count": 1,
                "match_count": 1,
                "matches": [
                    {
                        "track_id": "f1",
                        "contact_id": "contact_tram",
                        "display_name": "Trâm",
                        "confidence": 0.94,
                        "identity_match": "contact_db",
                        "match_status": "identity_confirmed",
                    }
                ],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
        )

        result = executor.execute(
            name="target_finder",
            args={
                "query": "tìm người",
                "target_type": "person",
                "target_name": "Trâm",
                "identity_query": True,
            },
            session_id="sess_test",
        )

        self.assertEqual(calls, ["tìm người Trâm"])
        self.assertEqual(result["result"]["raw_query"], "tìm người")
        self.assertEqual(result["result"]["query"], "tìm người Trâm")
        self.assertEqual(result["result"]["target_name"], "Trâm")
        self.assertEqual(result["result"]["identity_policy"]["status"], "contact_match_confirmed")
        self.assertEqual(result["result"]["target_hint"]["display_name"], "Trâm")

    def test_target_finder_named_contact_reports_missing_identity_contact(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [280, 100, 400, 450],
                    "track_id": "f1",
                    "attributes": {"embedding_model": "sface", "identity_vector": [1.0, 0.0]},
                }
            ],
        )

        def identity_provider(*, candidates, query, session_id):
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "no_requested_contact",
                "provider": "openvision_local_contact_identity",
                "candidate_count": len(candidates),
                "candidate_vector_count": 0,
                "requested_contact_count": 0,
                "match_count": 0,
                "matches": [],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
        )

        result = executor.execute(
            name="target_finder",
            args={"query": "tìm người", "target_type": "person", "target_name": "Trâm", "identity_query": True},
            session_id="sess_test",
        )

        self.assertEqual(result["result"]["identity_provider"]["status"], "no_requested_contact")
        self.assertEqual(result["result"]["hud"]["answer_strip"], "Chưa có Trâm trong DB; có 1 ID.")

    def test_target_finder_generic_people_query_scans_identity_opportunistically(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [280, 100, 400, 450],
                    "track_id": "f1",
                    "attributes": {"embedding_model": "sface", "identity_vector": [1.0, 0.0]},
                }
            ],
        )

        calls = []

        def identity_provider(*, candidates, query, session_id):
            calls.append({"query": query, "session_id": session_id, "candidate_count": len(candidates)})
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "confirmed",
                "provider": "openvision_local_contact_identity",
                "candidate_count": len(candidates),
                "candidate_vector_count": 1,
                "requested_contact_count": 36,
                "match_count": 1,
                "matches": [
                    {
                        "track_id": "f1",
                        "contact_id": "contact_tram",
                        "display_name": "Trâm",
                        "confidence": 0.94,
                        "identity_match": "contact_db",
                        "match_status": "identity_confirmed",
                    }
                ],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
        )

        result = executor.execute(
            name="target_finder",
            args={"query": "tìm người trong đám đông", "target_type": "person"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(calls, [{"query": "tìm người trong đám đông", "session_id": "sess_test", "candidate_count": 1}])
        self.assertEqual(result["result"]["identity_policy"]["status"], "contact_match_confirmed")
        self.assertEqual(result["result"]["target_hint"]["display_name"], "Trâm")
        identity_events = [
            event
            for event in events.list(session_id="sess_test")
            if event["module"] == "skills" and event["event_type"] == "target_finder_identity_checked"
        ]
        self.assertTrue(identity_events[-1]["payload"]["identity_requested"])
        self.assertTrue(identity_events[-1]["payload"]["identity_optional"])

    def test_target_finder_opportunistic_identity_no_match_still_guides_candidate(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [280, 100, 400, 450],
                    "track_id": "f1",
                    "attributes": {"embedding_model": "sface", "identity_vector": [1.0, 0.0]},
                }
            ],
        )

        def identity_provider(*, candidates, query, session_id):
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "no_match",
                "provider": "openvision_local_contact_identity",
                "candidate_count": len(candidates),
                "candidate_vector_count": 1,
                "requested_contact_count": 36,
                "match_count": 0,
                "matches": [],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
        )

        result = executor.execute(
            name="target_finder",
            args={"query": "tìm người trong đám đông", "target_type": "person"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["identity_policy"]["status"], "identity_scan_no_match")
        self.assertEqual(result["result"]["target_hint"]["status"], "guiding")
        self.assertEqual(result["result"]["confirmed_match_count"], 0)
        self.assertIn("identity_scan", result["result"]["hud"]["edge_chips"])

    def test_target_finder_reports_low_quality_face_before_identity_no_match(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=960,
            height=540,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [450, 210, 482, 248],
                    "track_id": "f1",
                    "attributes": {
                        "embedding_model": "sface",
                        "identity_vector": [1.0, 0.0],
                        "identity_quality": "too_small_for_identity",
                        "face_min_side_px": 32,
                    },
                }
            ],
        )

        def identity_provider(*, candidates, query, session_id):
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "low_quality_face",
                "provider": "openvision_local_contact_identity",
                "candidate_count": len(candidates),
                "candidate_vector_count": 0,
                "low_quality_candidate_count": 1,
                "quality_reasons": {"too_small_for_identity": 1},
                "requested_contact_count": 1,
                "match_count": 0,
                "min_identity_face_side_px": 56,
                "matches": [],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
        )

        result = executor.execute(
            name="target_finder",
            args={"query": "tìm A Bảo", "target_type": "person"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["identity_policy"]["status"], "identity_lookup_low_quality")
        self.assertEqual(result["result"]["confirmed_match_count"], 0)
        self.assertEqual(result["result"]["target_hint"]["status"], "guiding")
        self.assertEqual(result["result"]["hud"]["answer_strip"], "Mặt hơi xa hoặc quá nhỏ; lại gần hơn một chút. · đúng tâm")
        self.assertIn("face_quality", result["result"]["hud"]["edge_chips"])
        self.assertIn("face_small", result["result"]["hud"]["edge_chips"])
        identity_events = [
            event
            for event in events.list(session_id="sess_test")
            if event["module"] == "skills" and event["event_type"] == "target_finder_identity_checked"
        ]
        self.assertEqual(identity_events[-1]["payload"]["provider_status"], "low_quality_face")
        self.assertEqual(identity_events[-1]["payload"]["low_quality_candidate_count"], 1)
        self.assertEqual(identity_events[-1]["payload"]["min_identity_face_side_px"], 56)

    def test_target_finder_holds_last_named_match_during_brief_empty_face_frame(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            frame_id="face_1",
            detections=[
                {
                    "label": "person",
                    "confidence": 0.91,
                    "bbox": [280, 100, 400, 450],
                    "track_id": "f1",
                    "attributes": {"embedding_model": "sface", "identity_vector": [1.0, 0.0]},
                }
            ],
        )

        def identity_provider(*, candidates, query, session_id):
            if not candidates:
                return {
                    "schema_version": "openvision.contact_identity_match.v1",
                    "status": "no_candidate_vectors",
                    "provider": "openvision_local_contact_identity",
                    "candidate_count": 0,
                    "candidate_vector_count": 0,
                    "requested_contact_count": 1,
                    "match_count": 0,
                    "matches": [],
                }
            return {
                "schema_version": "openvision.contact_identity_match.v1",
                "status": "confirmed",
                "provider": "openvision_local_contact_identity",
                "candidate_count": len(candidates),
                "candidate_vector_count": 1,
                "requested_contact_count": 1,
                "match_count": 1,
                "matches": [
                    {
                        "track_id": "f1",
                        "contact_id": "contact_abao",
                        "display_name": "A Bảo",
                        "confidence": 0.94,
                        "identity_match": "contact_db",
                        "match_status": "identity_confirmed",
                    }
                ],
            }

        executor = SkillExecutor(
            perception=perception,
            events=events,
            identity_match_provider=identity_provider,
        )
        first = executor.execute(
            name="target_finder",
            args={"query": "tìm A Bảo", "target_type": "person"},
            session_id="sess_test",
        )
        perception.update_snapshot(
            session_id="sess_test",
            source="face_identity_stream:openvision_iphone_face_identity",
            width=640,
            height=480,
            frame_id="face_empty",
            detections=[],
        )
        second = executor.execute(
            name="target_finder",
            args={"query": "tìm A Bảo", "target_type": "person"},
            session_id="sess_test",
        )

        self.assertEqual(first["result"]["hud"]["answer_strip"], "A Bảo · đúng tâm")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(second["result"]["hud"]["answer_strip"], "A Bảo · đúng tâm")
        self.assertEqual(second["result"]["target_hold"]["status"], "holding_last_good_target")
        self.assertIn("hold", second["result"]["hud"]["edge_chips"])

    def test_target_finder_can_use_user_confirmed_session_label(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="unit",
            width=640,
            height=480,
            detections=[
                {"label": "person", "confidence": 0.91, "bbox": [280, 100, 400, 450], "track_id": "p1"},
                {"label": "person", "confidence": 0.86, "bbox": [30, 120, 150, 450], "track_id": "p2"},
            ],
        )
        executor = SkillExecutor(perception=perception, events=events)
        selected = executor.execute(
            name="select_target",
            args={"target_id": "p1", "display_name": "Trâm", "reason": "user confirmed"},
            session_id="sess_test",
        )

        result = executor.execute(
            name="target_finder",
            args={"query": "tìm Trâm trong đám đông", "target_type": "person"},
            session_id="sess_test",
        )

        self.assertEqual(selected["result"]["hud"]["answer_strip"], "Đã chọn Trâm")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["confirmed_match_count"], 1)
        self.assertEqual(result["result"]["identity_policy"]["status"], "manual_label_confirmed")
        self.assertEqual(result["result"]["target_hint"]["display_name"], "Trâm")
        self.assertEqual(result["result"]["target_hint"]["status"], "guiding")
        self.assertIn("manual_label", result["result"]["hud"]["edge_chips"])

    def test_target_finder_preview_waits_for_detector(self):
        preview = {
            "session_id": "sess_test",
            "source": "iphone_webrtc",
            "width": 508,
            "height": 904,
            "frame_count": 3,
            "image_url": "/api/preview/sess_test/frame.jpg",
        }
        executor = SkillExecutor(
            perception=PerceptionGraph(events=InMemoryEventStore()),
            events=InMemoryEventStore(),
            preview_status_provider=lambda session_id: preview if session_id == "sess_test" else None,
        )

        result = executor.execute(
            name="target_finder",
            args={"query": "tìm người trong đám đông"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["result"]["missing_runtime"], "perception_snapshot")
        self.assertEqual(result["result"]["required_runtime"], "yolo26_rokid_external_stream")
        self.assertIn("detector_status", result["result"])
        self.assertEqual(result["result"]["target_hint"]["mode"], "aim_assist_waiting")
        self.assertEqual(result["result"]["hud"]["target_hint"]["crosshair"]["style"], "tiny_center_reticle")

    def test_search_targets_marks_attribute_queries_as_needing_cloud(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="unit",
            detections=[
                {"label": "person", "confidence": 0.9, "bbox": [0, 0, 1, 1], "track_id": "p1"},
                {"label": "person", "confidence": 0.8, "bbox": [1, 0, 2, 1], "track_id": "p2"},
                {"label": "bag", "confidence": 0.7},
            ],
        )
        executor = SkillExecutor(perception=perception, events=events)

        result = executor.execute(
            name="search_targets",
            args={"query": "người mặc áo màu xanh"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "needs_cloud")
        self.assertEqual(result["result"]["candidate_count"], 2)
        self.assertEqual(result["result"]["confirmed_match_count"], 0)
        self.assertEqual(result["result"]["cloud_attribute_resolution"], "required")
        self.assertEqual(result["result"]["cloud_evidence_bundle"]["schema_version"], "cloud_evidence_bundle.v1")
        self.assertEqual(result["result"]["cloud_gateway"]["status"], "error")
        self.assertEqual(result["result"]["cloud_result"]["error"]["code"], "cloud_provider_missing")
        self.assertIn("chưa xác minh", result["result"]["user_message"])
        self.assertEqual(
            result["result"]["candidates"][0]["match_status"],
            "unverified_attribute_candidate",
        )
        self.assertIn("chưa xác minh", result["result"]["hud"]["answer_strip"])
        self.assertEqual(len(result["result"]["hud"]["thumbnails"]), 2)
        self.assertEqual(result["result"]["hud"]["thumbnails"][0]["target_id"], result["result"]["candidates"][0]["target_id"])
        self.assertEqual(result["result"]["hud"]["thumbnails"][0]["match_status"], "unverified_attribute_candidate")

    def test_search_targets_allows_label_only_candidates(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="unit",
            detections=[
                {"label": "person", "confidence": 0.9, "track_id": "p1"},
                {"label": "bag", "confidence": 0.7, "track_id": "b1"},
            ],
        )
        executor = SkillExecutor(perception=perception, events=events)

        result = executor.execute(
            name="search_targets",
            args={"query": "người"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["candidate_semantics"], "label_matches")
        self.assertEqual(result["result"]["confirmed_match_count"], 1)
        self.assertEqual(len(result["result"]["hud"]["thumbnails"]), 1)

    def test_manifest_input_schema_is_enforced_before_execution(self):
        executor = SkillExecutor(
            perception=PerceptionGraph(events=InMemoryEventStore()),
            events=InMemoryEventStore(),
        )

        bad_confidence = executor.execute(
            name="count_people",
            args={"min_confidence": "abc"},
            session_id="sess_test",
        )
        too_many_candidates = executor.execute(
            name="search_targets",
            args={"query": "người", "max_candidates": 999},
            session_id="sess_test",
        )
        missing_query = executor.execute(
            name="search_targets",
            args={},
            session_id="sess_test",
        )

        self.assertEqual(bad_confidence["status"], "error")
        self.assertEqual(bad_confidence["error"]["code"], "invalid_skill_args")
        self.assertIn("args.min_confidence must be number", bad_confidence["error"]["details"])
        self.assertIn("args.max_candidates must be <= 8", too_many_candidates["error"]["details"])
        self.assertIn("args.query is required", missing_query["error"]["details"])

    def test_select_and_clear_target_emit_hud_contracts(self):
        executor = SkillExecutor(
            perception=PerceptionGraph(events=InMemoryEventStore()),
            events=InMemoryEventStore(),
        )

        selected = executor.execute(
            name="select_target",
            args={"target_id": "obj_person_1", "reason": "user pointed"},
            session_id="sess_test",
        )
        cleared = executor.execute(name="clear_target", args={}, session_id="sess_test")

        self.assertEqual(selected["status"], "ok")
        self.assertEqual(selected["result"]["hud"]["target_hint"]["target_id"], "obj_person_1")
        self.assertEqual(selected["result"]["hud_hint"]["status"], "selected")
        self.assertEqual(cleared["status"], "ok")
        self.assertEqual(cleared["result"]["hud"]["edge_chips"], ["target_clear"])


if __name__ == "__main__":
    unittest.main()
