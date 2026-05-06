import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.cloud_gateway import CloudGateway
from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.jetson_tool_server import JetsonToolServer, ToolServerPolicy
from openvision_jetson.skill_registry import SkillRegistry


class JetsonToolServerTest(unittest.TestCase):
    def test_builds_typed_realtime_tool_call(self):
        server = JetsonToolServer(events=InMemoryEventStore(), skills=SkillRegistry())

        tool_call = server.build_tool_call(
            {
                "call_id": "call_1",
                "name": "count_people",
                "arguments": {"min_confidence": 0.5},
            },
            session_id="sess_test",
        )

        self.assertEqual(tool_call.schema_version, "openvision.realtime_tool_call.v1")
        self.assertEqual(tool_call.call_id, "call_1")
        self.assertEqual(tool_call.name, "count_people")
        self.assertEqual(tool_call.arguments["min_confidence"], 0.5)
        self.assertEqual(tool_call.session_id, "sess_test")

    def test_validates_unknown_tool_before_execution(self):
        events = InMemoryEventStore()
        server = JetsonToolServer(events=events, skills=SkillRegistry())
        tool_call = server.build_tool_call(
            {"call_id": "call_1", "name": "missing_tool", "arguments": {}},
            session_id="sess_test",
        )

        result = server.execute(tool_call)

        self.assertEqual(result["schema_version"], "openvision.tool_error.v1")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "unknown_tool")
        self.assertEqual(events.list()[-1]["module"], "realtime_tool")
        self.assertEqual(events.list()[-1]["event_type"], "call_failed")

    def test_validates_manifest_args_before_handler(self):
        calls = []
        server = JetsonToolServer(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            skill_handler=lambda name, args, session_id: calls.append((name, args, session_id)) or {"status": "ok"},
        )
        tool_call = server.build_tool_call(
            {"call_id": "call_1", "name": "count_people", "arguments": {"min_confidence": "bad"}},
            session_id="sess_test",
        )

        result = server.execute(tool_call)

        self.assertEqual(result["schema_version"], "openvision.tool_error.v1")
        self.assertEqual(result["error"]["code"], "invalid_tool_args")
        self.assertEqual(calls, [])

    def test_executes_valid_skill_handler_as_tool_result(self):
        events = InMemoryEventStore()
        server = JetsonToolServer(
            events=events,
            skills=SkillRegistry(),
            skill_handler=lambda name, args, session_id: {
                "skill_call_id": "skill_1",
                "name": name,
                "args": args,
                "session_id": session_id,
                "status": "ok",
                "result": {"count": 2},
            },
        )
        tool_call = server.build_tool_call(
            {"call_id": "call_1", "name": "count_people", "arguments": {"min_confidence": 0.4}},
            session_id="sess_test",
        )

        result = server.execute(tool_call)

        self.assertEqual(result["schema_version"], "openvision.tool_result.v1")
        self.assertEqual(result["tool_call_id"], "call_1")
        self.assertEqual(result["tool_name"], "count_people")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["skill_call_id"], "skill_1")
        self.assertEqual(events.list()[-1]["event_type"], "call_completed")

    def test_call_received_logs_safe_argument_summary(self):
        events = InMemoryEventStore()
        server = JetsonToolServer(
            events=events,
            skills=SkillRegistry(),
            skill_handler=lambda name, args, session_id: {
                "skill_call_id": "skill_1",
                "name": name,
                "args": args,
                "session_id": session_id,
                "status": "ok",
                "result": {"summary": "queued"},
            },
        )
        tool_call = server.build_tool_call(
            {
                "call_id": "call_1",
                "name": "target_finder",
                "arguments": {
                    "query": "tìm người",
                    "target_type": "person",
                    "target_name": "Trâm",
                    "identity_query": True,
                },
            },
            session_id="sess_test",
        )

        server.execute(tool_call)

        received = next(event for event in events.list(session_id="sess_test") if event["event_type"] == "call_received")
        self.assertEqual(received["payload"]["arguments"]["query"], "tìm người")
        self.assertEqual(received["payload"]["arguments"]["target_name"], "Trâm")
        self.assertTrue(received["payload"]["arguments"]["identity_query"])

    def test_rejects_needs_cloud_payload_without_evidence_bundle(self):
        calls = []

        def handler(name, args, session_id):
            calls.append((name, args, session_id))
            return {
                "skill_call_id": "skill_1",
                "name": name,
                "args": args,
                "session_id": session_id,
                "status": "needs_cloud",
                "result": {"summary": "ambiguous visual attributes"},
            }

        server = JetsonToolServer(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            skill_handler=handler,
        )
        tool_call = server.build_tool_call(
            {"call_id": "call_1", "name": "search_targets", "arguments": {"query": "người áo xanh"}},
            session_id="sess_test",
        )

        result = server.execute(tool_call)

        self.assertEqual(result["schema_version"], "openvision.tool_error.v1")
        self.assertEqual(result["error"]["code"], "invalid_cloud_escalation")
        self.assertIn("skill_payload.result.cloud_evidence_bundle must be object", result["error"]["details"])
        self.assertEqual(calls[0][0], "search_targets")

    def test_accepts_needs_cloud_payload_with_valid_gateway_contract(self):
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
        gateway_response = gateway.request_verification(bundle)

        server = JetsonToolServer(
            events=events,
            skills=SkillRegistry(),
            cloud_gateway=gateway,
            skill_handler=lambda name, args, session_id: {
                "skill_call_id": "skill_1",
                "name": name,
                "args": args,
                "session_id": session_id,
                "status": "needs_cloud",
                "result": {
                    "summary": "attribute resolution requires cloud gateway",
                    "cloud_evidence_bundle": bundle,
                    "cloud_gateway": gateway_response,
                    "cloud_result": gateway_response["cloud_result"],
                },
            },
        )
        tool_call = server.build_tool_call(
            {"call_id": "call_1", "name": "search_targets", "arguments": {"query": "người áo xanh"}},
            session_id="sess_test",
        )

        result = server.execute(tool_call)

        self.assertEqual(result["schema_version"], "openvision.tool_result.v1")
        self.assertEqual(result["status"], "needs_cloud")
        self.assertEqual(
            result["result"]["result"]["cloud_result"]["error"]["code"],
            "cloud_provider_missing",
        )
        self.assertEqual(events.list()[-1]["event_type"], "call_completed")

    def test_rejects_tool_call_without_session(self):
        calls = []
        server = JetsonToolServer(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            skill_handler=lambda name, args, session_id: calls.append((name, args, session_id)) or {"status": "ok"},
        )
        tool_call = server.build_tool_call(
            {"call_id": "call_1", "name": "count_people", "arguments": {}},
            session_id=None,
        )

        result = server.execute(tool_call)

        self.assertEqual(result["schema_version"], "openvision.tool_error.v1")
        self.assertEqual(result["error"]["code"], "missing_session")
        self.assertEqual(calls, [])

    def test_rejects_unknown_session_when_validator_is_configured(self):
        server = JetsonToolServer(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            skill_handler=lambda name, args, session_id: {"status": "ok"},
            session_validator=lambda session_id: session_id == "sess_known",
        )
        tool_call = server.build_tool_call(
            {"call_id": "call_1", "name": "count_people", "arguments": {}},
            session_id="sess_missing",
        )

        result = server.execute(tool_call)

        self.assertEqual(result["schema_version"], "openvision.tool_error.v1")
        self.assertEqual(result["error"]["code"], "unknown_session")

    def test_rejects_cloud_tool_when_policy_disables_cloud_tools(self):
        server = JetsonToolServer(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            skill_handler=lambda name, args, session_id: {"status": "ok"},
            policy=ToolServerPolicy(allow_cloud_tools=False),
        )
        tool_call = server.build_tool_call(
            {"call_id": "call_1", "name": "search_targets", "arguments": {"query": "person"}},
            session_id="sess_test",
        )

        result = server.execute(tool_call)

        self.assertEqual(result["schema_version"], "openvision.tool_error.v1")
        self.assertEqual(result["error"]["code"], "cloud_tool_blocked")

    def test_rejects_tool_above_privacy_policy(self):
        server = JetsonToolServer(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            skill_handler=lambda name, args, session_id: {"status": "ok"},
            policy=ToolServerPolicy(max_privacy_level="low"),
        )
        tool_call = server.build_tool_call(
            {"call_id": "call_1", "name": "select_target", "arguments": {"target_id": "target_1"}},
            session_id="sess_test",
        )

        result = server.execute(tool_call)

        self.assertEqual(result["schema_version"], "openvision.tool_error.v1")
        self.assertEqual(result["error"]["code"], "privacy_level_blocked")

    def test_rejects_tool_calls_after_session_budget_is_exhausted(self):
        server = JetsonToolServer(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            skill_handler=lambda name, args, session_id: {"status": "ok"},
            policy=ToolServerPolicy(max_tool_calls_per_session=1),
        )
        first = server.build_tool_call(
            {"call_id": "call_1", "name": "count_people", "arguments": {}},
            session_id="sess_test",
        )
        second = server.build_tool_call(
            {"call_id": "call_2", "name": "count_people", "arguments": {}},
            session_id="sess_test",
        )

        self.assertEqual(server.execute(first)["schema_version"], "openvision.tool_result.v1")
        result = server.execute(second)

        self.assertEqual(result["schema_version"], "openvision.tool_error.v1")
        self.assertEqual(result["error"]["code"], "tool_budget_exceeded")

    def test_rejects_cloud_tool_after_cloud_budget_is_exhausted(self):
        server = JetsonToolServer(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            skill_handler=lambda name, args, session_id: {"status": "ok"},
            policy=ToolServerPolicy(max_cloud_calls_per_session=1),
        )
        first = server.build_tool_call(
            {"call_id": "call_1", "name": "search_targets", "arguments": {"query": "person"}},
            session_id="sess_test",
        )
        second = server.build_tool_call(
            {"call_id": "call_2", "name": "search_targets", "arguments": {"query": "person"}},
            session_id="sess_test",
        )

        self.assertEqual(server.execute(first)["schema_version"], "openvision.tool_result.v1")
        result = server.execute(second)

        self.assertEqual(result["schema_version"], "openvision.tool_error.v1")
        self.assertEqual(result["error"]["code"], "cloud_budget_exceeded")

    def test_times_out_slow_tool_handler(self):
        def slow_handler(name, args, session_id):
            time.sleep(0.05)
            return {"status": "ok"}

        server = JetsonToolServer(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            skill_handler=slow_handler,
            policy=ToolServerPolicy(max_timeout_ms=1),
        )
        tool_call = server.build_tool_call(
            {"call_id": "call_1", "name": "count_people", "arguments": {}},
            session_id="sess_test",
        )

        result = server.execute(tool_call)

        self.assertEqual(result["schema_version"], "openvision.tool_error.v1")
        self.assertEqual(result["error"]["code"], "tool_timeout")
        self.assertEqual(result["error"]["details"]["timeout_ms"], 1)

    def test_timed_out_tool_keeps_worker_slot_until_handler_returns(self):
        release = threading.Event()

        def blocking_handler(name, args, session_id):
            release.wait(timeout=1.0)
            return {"status": "ok"}

        server = JetsonToolServer(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            skill_handler=blocking_handler,
            policy=ToolServerPolicy(max_timeout_ms=1, max_concurrent_tool_workers=1),
        )
        first = server.build_tool_call(
            {"call_id": "call_1", "name": "count_people", "arguments": {}},
            session_id="sess_test",
        )
        second = server.build_tool_call(
            {"call_id": "call_2", "name": "count_people", "arguments": {}},
            session_id="sess_test",
        )

        try:
            timed_out = server.execute(first)
            busy = server.execute(second)
        finally:
            release.set()
            server.close()

        self.assertEqual(timed_out["error"]["code"], "tool_timeout")
        self.assertEqual(busy["error"]["code"], "tool_server_busy")


if __name__ == "__main__":
    unittest.main()
