import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.cloud_gateway import CloudGateway
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


if __name__ == "__main__":
    unittest.main()
