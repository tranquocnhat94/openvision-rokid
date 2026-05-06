import json
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.cloud_gateway import CloudGateway, OpenAIResponsesVisionProvider, image_bytes_to_data_url
from openvision_jetson.event_store import InMemoryEventStore


class CloudGatewayTest(unittest.TestCase):
    def test_builds_schema_valid_evidence_bundle_and_missing_provider_result(self):
        events = InMemoryEventStore()
        gateway = CloudGateway(events=events)

        bundle = gateway.build_evidence_bundle(
            session_id="sess_test",
            skill_id="search_targets",
            user_query="người áo xanh",
            local_summary={"candidate_count": 1},
            candidates=[{"candidate_id": "obj_1", "class": "person", "confidence": 0.9}],
            contains_face=True,
            allow_cloud=True,
            privacy_level="medium",
        )
        response = gateway.request_verification(bundle)

        self.assertEqual(bundle["schema_version"], "cloud_evidence_bundle.v1")
        self.assertTrue(bundle["bundle_id"].startswith("bundle_"))
        self.assertIn("created_at", bundle)
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["cloud_result"]["error"]["code"], "cloud_provider_missing")
        self.assertEqual(response["validation_errors"], [])
        self.assertEqual(gateway.validate_evidence_bundle(bundle), [])
        self.assertEqual(gateway.validate_gateway_response(response, bundle=bundle), [])
        trace_events = events.list(session_id="sess_test")
        bundle_event = next(event for event in trace_events if event["event_type"] == "bundle_created")
        result_event = next(event for event in trace_events if event["event_type"] == "provider_missing")
        self.assertEqual(bundle_event["payload"]["frame_ref_count"], 0)
        self.assertEqual(bundle_event["payload"]["crop_ref_count"], 0)
        self.assertTrue(bundle_event["payload"]["contains_face"])
        self.assertTrue(bundle_event["payload"]["allow_cloud"])
        self.assertEqual(bundle_event["payload"]["max_answer_chars"], 60)
        self.assertEqual(result_event["payload"]["error_code"], "cloud_provider_missing")
        self.assertEqual(result_event["payload"]["validation_error_count"], 0)
        self.assertEqual(result_event["payload"]["result_status"], "error")
        self.assertEqual(
            gateway.validate_cloud_escalation_result(
                {
                    "cloud_evidence_bundle": bundle,
                    "cloud_gateway": response,
                    "cloud_result": response["cloud_result"],
                }
            ),
            [],
        )

    def test_validate_cloud_escalation_result_rejects_missing_bundle_contract(self):
        gateway = CloudGateway(events=InMemoryEventStore())

        errors = gateway.validate_cloud_escalation_result(
            {
                "summary": "ambiguous visual answer",
                "cloud_evidence_bundle": None,
                "cloud_gateway": None,
                "cloud_result": None,
            }
        )

        self.assertIn("result.cloud_evidence_bundle must be object", errors)
        self.assertIn("result.cloud_gateway must be object", errors)
        self.assertIn("result.cloud_result must be object", errors)

    def test_privacy_gate_blocks_before_provider(self):
        called = False

        def provider(bundle):
            nonlocal called
            called = True
            return {"schema_version": "cloud_result.v1", "status": "ok", "answer_short": "ok", "confidence": 1, "safety_flags": []}

        gateway = CloudGateway(events=InMemoryEventStore(), provider=provider)
        bundle = gateway.build_evidence_bundle(
            session_id="sess_test",
            skill_id="search_targets",
            user_query="người áo xanh",
            local_summary={},
            candidates=[],
            allow_cloud=False,
        )
        response = gateway.request_verification(bundle)

        self.assertFalse(called)
        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["cloud_result"]["error"]["code"], "privacy_blocked")

    def test_request_budget_is_thread_safe_and_strict(self):
        gateway = CloudGateway(events=InMemoryEventStore(), max_requests_per_minute=2)
        bundle = gateway.build_evidence_bundle(
            session_id="sess_test",
            skill_id="search_targets",
            user_query="người áo xanh",
            local_summary={},
            candidates=[],
        )

        with ThreadPoolExecutor(max_workers=8) as executor:
            responses = list(executor.map(lambda _index: gateway.request_verification(bundle), range(8)))

        statuses = [response["cloud_result"]["error"]["code"] for response in responses]
        self.assertEqual(statuses.count("cloud_provider_missing"), 2)
        self.assertEqual(statuses.count("budget_exceeded"), 6)

    def test_invalid_cloud_result_is_rejected(self):
        gateway = CloudGateway(events=InMemoryEventStore(), provider=lambda bundle: {"status": "ok"})
        bundle = gateway.build_evidence_bundle(
            session_id="sess_test",
            skill_id="search_targets",
            user_query="người áo xanh",
            local_summary={},
            candidates=[],
        )
        response = gateway.request_verification(bundle)

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["cloud_result"]["error"]["code"], "invalid_cloud_result")

    def test_openai_responses_provider_builds_structured_vision_request(self):
        captured = {}

        def fake_post(url, headers, body, timeout_s):
            captured["url"] = url
            captured["headers"] = headers
            captured["body"] = body
            captured["timeout_s"] = timeout_s
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "schema_version": "cloud_result.v1",
                                        "status": "ok",
                                        "answer_short": "Một người phía trước",
                                        "answer_long": "Có một người trong ảnh.",
                                        "confidence": 0.82,
                                        "selected_candidate_id": "obj_1",
                                        "hud_scene": None,
                                        "safety_flags": [],
                                        "memory_event": None,
                                        "error": None,
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        ],
                    }
                ]
            }

        provider = OpenAIResponsesVisionProvider(
            api_key="test-key",
            model="gpt-4.1-mini",
            timeout_s=3.0,
            image_detail="low",
            image_ref_resolver=lambda ref, bundle: image_bytes_to_data_url(b"jpeg-bytes", "image/jpeg"),
            http_post_json=fake_post,
        )
        gateway = CloudGateway(events=InMemoryEventStore(), provider=provider)
        bundle = gateway.build_evidence_bundle(
            session_id="sess_test",
            skill_id="query_scene",
            user_query="đang có gì trước mặt",
            local_summary={"evidence": "client_snapshot_preview"},
            frame_refs=["/api/preview/sess_test/frame.jpg"],
            candidates=[],
            max_answer_chars=60,
        )
        response = gateway.request_verification(bundle)

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["cloud_result"]["answer_short"], "Một người phía trước")
        self.assertEqual(captured["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["timeout_s"], 3.0)
        self.assertEqual(captured["body"]["model"], "gpt-4.1-mini")
        self.assertFalse(captured["body"]["store"])
        self.assertEqual(captured["body"]["text"]["format"]["type"], "json_schema")
        image_input = captured["body"]["input"][0]["content"][1]
        self.assertEqual(image_input["type"], "input_image")
        self.assertEqual(image_input["detail"], "low")
        self.assertTrue(image_input["image_url"].startswith("data:image/jpeg;base64,"))

    def test_object_counter_prompt_allows_approximate_visual_counts(self):
        captured = {}

        def fake_post(url, headers, body, timeout_s):
            captured["prompt"] = body["input"][0]["content"][0]["text"]
            return {
                "output_text": json.dumps(
                    {
                        "schema_version": "cloud_result.v1",
                        "status": "uncertain",
                        "answer_short": "Ước khoảng 12 hạt.",
                        "answer_long": None,
                        "confidence": 0.62,
                        "selected_candidate_id": None,
                        "hud_scene": None,
                        "safety_flags": ["approximate_count"],
                        "memory_event": None,
                        "error": None,
                    },
                    ensure_ascii=False,
                )
            }

        provider = OpenAIResponsesVisionProvider(
            api_key="test-key",
            image_ref_resolver=lambda ref, bundle: image_bytes_to_data_url(b"jpeg-bytes", "image/jpeg"),
            http_post_json=fake_post,
        )
        gateway = CloudGateway(events=InMemoryEventStore(), provider=provider)
        bundle = gateway.build_evidence_bundle(
            session_id="sess_test",
            skill_id="object_counter",
            user_query="có bao nhiêu hạt",
            local_summary={"task": "count_visible_objects", "target": "hạt"},
            frame_refs=["/api/preview/sess_test/frame.jpg"],
            candidates=[],
            max_answer_chars=80,
        )

        response = gateway.request_verification(bundle)

        self.assertEqual(response["status"], "uncertain")
        self.assertEqual(response["cloud_result"]["answer_short"], "Ước khoảng 12 hạt.")
        self.assertIn("count the requested visible object type", captured["prompt"])
        self.assertIn("do not refuse only because the count is approximate", captured["prompt"])

    def test_text_reader_prompt_forbids_inventing_missing_words(self):
        captured = {}

        def fake_post(url, headers, body, timeout_s):
            captured["prompt"] = body["input"][0]["content"][0]["text"]
            return {
                "output_text": json.dumps(
                    {
                        "schema_version": "cloud_result.v1",
                        "status": "ok",
                        "answer_short": "Biển ghi: Lối ra.",
                        "answer_long": None,
                        "confidence": 0.86,
                        "selected_candidate_id": None,
                        "hud_scene": None,
                        "safety_flags": [],
                        "memory_event": None,
                        "error": None,
                    },
                    ensure_ascii=False,
                )
            }

        provider = OpenAIResponsesVisionProvider(
            api_key="test-key",
            image_ref_resolver=lambda ref, bundle: image_bytes_to_data_url(b"jpeg-bytes", "image/jpeg"),
            http_post_json=fake_post,
        )
        gateway = CloudGateway(events=InMemoryEventStore(), provider=provider)
        bundle = gateway.build_evidence_bundle(
            session_id="sess_text",
            skill_id="text_reader",
            user_query="biển này ghi gì",
            local_summary={"task": "read_visible_text"},
            frame_refs=["/api/preview/sess_text/frame.jpg"],
            candidates=[],
            max_answer_chars=100,
        )

        response = gateway.request_verification(bundle)

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["cloud_result"]["answer_short"], "Biển ghi: Lối ra.")
        self.assertIn("read only text that is actually visible", captured["prompt"])
        self.assertIn("Do not invent missing words", captured["prompt"])

    def test_openai_responses_provider_returns_uncertain_when_image_ref_cannot_resolve(self):
        called = False

        def fake_post(url, headers, body, timeout_s):
            nonlocal called
            called = True
            return {}

        provider = OpenAIResponsesVisionProvider(
            api_key="test-key",
            image_ref_resolver=lambda ref, bundle: None,
            http_post_json=fake_post,
        )
        bundle = CloudGateway(events=InMemoryEventStore()).build_evidence_bundle(
            session_id="sess_test",
            skill_id="query_scene",
            user_query="đang có gì trước mặt",
            local_summary={"evidence": "client_snapshot_preview"},
            frame_refs=["/api/preview/sess_test/frame.jpg"],
            candidates=[],
        )

        result = provider(bundle)

        self.assertFalse(called)
        self.assertEqual(result["status"], "uncertain")
        self.assertIn("no_image_evidence", result["safety_flags"])


if __name__ == "__main__":
    unittest.main()
