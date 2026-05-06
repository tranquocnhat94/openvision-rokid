import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.contracts import utc_now
from openvision_jetson.skill_eval import build_skill_eval


def hud_scene(session_id: str, *, chips: list[str]) -> dict:
    return {
        "scene_id": f"hud_{session_id}",
        "session_id": session_id,
        "answer_strip": "ready",
        "edge_chips": chips,
        "thumbnails": [],
        "target_hint": None,
        "priority": "normal",
        "ttl_ms": 2500,
        "created_at": utc_now(),
    }


class SkillEvalTest(unittest.TestCase):
    def test_skill_eval_passes_visual_cloud_path_with_media_and_hud(self):
        replay = {
            "session_id": "sess_scene",
            "events": [
                {
                    "session_id": "sess_scene",
                    "module": "skills",
                    "event_type": "executed",
                    "severity": "info",
                    "payload": {
                        "name": "scene_describe",
                        "status": "needs_cloud",
                        "duration_ms": 320,
                        "args_summary": {"has_query": True},
                        "result_summary": {
                            "answer_present": True,
                            "hud_present": True,
                            "hud_answer_present": True,
                            "preview_present": True,
                            "cloud_result_status": "ok",
                        },
                    },
                },
                {
                    "session_id": "sess_scene",
                    "module": "realtime_tool",
                    "event_type": "call_completed",
                    "severity": "info",
                    "payload": {"tool_name": "scene_describe", "status": "needs_cloud", "duration_ms": 300},
                },
                {
                    "session_id": "sess_scene",
                    "module": "media_command",
                    "event_type": "command_completed",
                    "severity": "info",
                    "payload": {"skill_id": "scene_describe", "mode": "snapshot", "status": "ok", "duration_ms": 30},
                },
                {
                    "session_id": "sess_scene",
                    "module": "cloud_gateway",
                    "event_type": "bundle_created",
                    "severity": "info",
                    "payload": {"skill_id": "scene_describe", "bundle_id": "bundle_1"},
                },
                {
                    "session_id": "sess_scene",
                    "module": "cloud_gateway",
                    "event_type": "verification_completed",
                    "severity": "info",
                    "payload": {"skill_id": "scene_describe", "bundle_id": "bundle_1", "status": "ok"},
                },
            ],
            "hud_scenes": [hud_scene("sess_scene", chips=["scene_describe", "needs_cloud"])],
            "perception": [],
        }

        eval_result = build_skill_eval(replay)

        self.assertEqual(eval_result["status"], "pass")
        self.assertEqual(eval_result["gates"]["media_evidence"]["status"], "pass")
        self.assertEqual(eval_result["gates"]["cloud_evidence"]["status"], "pass")
        self.assertEqual(eval_result["gates"]["hud_output"]["status"], "pass")
        self.assertEqual(eval_result["metrics"]["skill_names"], ["scene_describe"])

    def test_skill_eval_warns_for_safe_cloud_provider_missing_fallback(self):
        replay = {
            "session_id": "sess_scene",
            "events": [
                {
                    "session_id": "sess_scene",
                    "module": "skills",
                    "event_type": "executed",
                    "severity": "info",
                    "payload": {"name": "scene_describe", "status": "needs_cloud", "duration_ms": 120},
                },
                {
                    "session_id": "sess_scene",
                    "module": "media_command",
                    "event_type": "command_completed",
                    "severity": "info",
                    "payload": {"skill_id": "scene_describe", "mode": "snapshot", "status": "ok", "duration_ms": 30},
                },
                {
                    "session_id": "sess_scene",
                    "module": "cloud_gateway",
                    "event_type": "bundle_created",
                    "severity": "info",
                    "payload": {"skill_id": "scene_describe", "bundle_id": "bundle_1"},
                },
                {
                    "session_id": "sess_scene",
                    "module": "cloud_gateway",
                    "event_type": "provider_missing",
                    "severity": "warning",
                    "payload": {
                        "skill_id": "scene_describe",
                        "bundle_id": "bundle_1",
                        "status": "error",
                        "error_code": "cloud_provider_missing",
                        "latency_ms": 2,
                        "validation_error_count": 0,
                    },
                },
            ],
            "hud_scenes": [hud_scene("sess_scene", chips=["scene_describe", "needs_cloud"])],
            "perception": [],
        }

        eval_result = build_skill_eval(replay)

        self.assertEqual(eval_result["status"], "warn")
        self.assertEqual(eval_result["gates"]["cloud_evidence"]["status"], "warn")
        observed = eval_result["gates"]["cloud_evidence"]["observed"]
        self.assertEqual(observed["missing_provider_count"], 1)
        self.assertEqual(observed["fallback_count"], 1)
        self.assertEqual(observed["invalid_contract_count"], 0)

    def test_skill_eval_fails_invalid_cloud_contract(self):
        replay = {
            "session_id": "sess_scene",
            "events": [
                {
                    "session_id": "sess_scene",
                    "module": "skills",
                    "event_type": "executed",
                    "severity": "info",
                    "payload": {"name": "scene_describe", "status": "needs_cloud", "duration_ms": 120},
                },
                {
                    "session_id": "sess_scene",
                    "module": "cloud_gateway",
                    "event_type": "bundle_created",
                    "severity": "info",
                    "payload": {"skill_id": "scene_describe", "bundle_id": "bundle_1"},
                },
                {
                    "session_id": "sess_scene",
                    "module": "cloud_gateway",
                    "event_type": "result_rejected",
                    "severity": "error",
                    "payload": {
                        "skill_id": "scene_describe",
                        "bundle_id": "bundle_1",
                        "status": "error",
                        "error_code": "invalid_cloud_result",
                        "validation_error_count": 2,
                    },
                },
            ],
            "hud_scenes": [hud_scene("sess_scene", chips=["scene_describe", "needs_cloud"])],
            "perception": [{"session_id": "sess_scene", "objects": [{"label": "person"}]}],
        }

        eval_result = build_skill_eval(replay)

        self.assertEqual(eval_result["gates"]["cloud_evidence"]["status"], "fail")
        self.assertEqual(eval_result["gates"]["cloud_evidence"]["observed"]["invalid_contract_count"], 1)

    def test_skill_eval_fails_missing_expected_skill(self):
        replay = {"session_id": "sess_missing", "events": [], "hud_scenes": [], "perception": []}

        eval_result = build_skill_eval(replay, expected_skills=["person_info"])

        self.assertEqual(eval_result["status"], "fail")
        self.assertEqual(eval_result["gates"]["skill_invocation"]["status"], "fail")
        self.assertEqual(eval_result["metrics"]["expected_missing_count"], 1)
        self.assertEqual(eval_result["top_failures"][0]["gate"], "skill_invocation")

    def test_skill_eval_surfaces_identity_pipeline_status(self):
        replay = {
            "session_id": "sess_identity",
            "events": [
                {
                    "session_id": "sess_identity",
                    "module": "skills",
                    "event_type": "executed",
                    "severity": "info",
                    "payload": {
                        "name": "person_info",
                        "status": "ok",
                        "duration_ms": 80,
                        "args_summary": {"has_query": True, "info_focus": "name"},
                        "result_summary": {
                            "known_person": True,
                            "known_people_count": 1,
                            "identity_provider_status": "confirmed",
                            "identity_provider_match_count": 1,
                            "hud_present": True,
                            "hud_answer_present": True,
                        },
                    },
                },
                {
                    "session_id": "sess_identity",
                    "module": "skills",
                    "event_type": "person_info_identity_checked",
                    "severity": "info",
                    "payload": {"provider_status": "confirmed", "match_count": 1},
                },
            ],
            "hud_scenes": [hud_scene("sess_identity", chips=["person_info", "known_person"])],
            "perception": [{"session_id": "sess_identity", "objects": [{"label": "person"}]}],
        }

        eval_result = build_skill_eval(replay)

        self.assertEqual(eval_result["gates"]["identity_pipeline"]["status"], "pass")
        self.assertEqual(eval_result["metrics"]["identity_check_count"], 1)
        self.assertEqual(eval_result["metrics"]["identity_confirmed_count"], 1)


if __name__ == "__main__":
    unittest.main()
