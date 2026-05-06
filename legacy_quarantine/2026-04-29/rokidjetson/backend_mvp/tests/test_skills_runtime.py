import unittest

from app.skills_runtime import JetsonSkillRegistry


class SkillsRuntimeTests(unittest.TestCase):
    def _build_registry(
        self,
        *,
        scene_context=None,
        command_payloads=None,
        log_records=None,
    ) -> JetsonSkillRegistry:
        scene_context = {} if scene_context is None else scene_context
        command_payloads = [] if command_payloads is None else command_payloads
        log_records = [] if log_records is None else log_records
        return JetsonSkillRegistry(
            config_provider=lambda: {},
            scene_context_provider=lambda session_id: scene_context,
            vision_context_provider=lambda session_id, target_query, track_id: {},
            command_handler=lambda payload: command_payloads.append(payload),
            log_handler=lambda session_id, event, payload: log_records.append((event, payload)),
        )

    def test_memory_lookup_tool_has_no_active_schema_surface(self) -> None:
        registry = self._build_registry()

        names = {schema["name"] for schema in registry.tool_schemas()}

        self.assertIn("search_target", names)
        self.assertIn("analyze_selected_target", names)
        self.assertNotIn("lookup_selected_target_memory", names)

    def test_memory_lookup_tool_has_no_runtime_surface(self) -> None:
        registry = self._build_registry()

        result = registry.execute(
            session_id="sess_demo",
            tool_name="lookup_selected_target_memory",
            arguments={"question": "toi da gap nguoi nay chua"},
            source="unit-test",
        )

        self.assertEqual(result["ok"], False)
        self.assertIn("Unknown tool", result["error"])

    def test_realtime_standby_noop_is_rejected_when_already_standby(self) -> None:
        command_payloads = []
        log_records = []
        registry = self._build_registry(
            scene_context={"mode": "standby"},
            command_payloads=command_payloads,
            log_records=log_records,
        )

        result = registry.execute(
            session_id="sess_demo",
            tool_name="set_jetson_mode",
            arguments={"mode": "standby", "reason": "Chuyển sang chế độ chờ"},
            source="openai_realtime_skills",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(command_payloads, [])
        self.assertIn("voice_skill_rejected", [event for event, _ in log_records])

    def test_manual_standby_still_dispatches(self) -> None:
        command_payloads = []
        registry = self._build_registry(
            scene_context={"mode": "standby"},
            command_payloads=command_payloads,
        )

        result = registry.execute(
            session_id="sess_demo",
            tool_name="set_jetson_mode",
            arguments={"mode": "standby", "reason": "Về chế độ chờ"},
            source="manual",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(command_payloads[0]["mode"], "standby")


if __name__ == "__main__":
    unittest.main()
