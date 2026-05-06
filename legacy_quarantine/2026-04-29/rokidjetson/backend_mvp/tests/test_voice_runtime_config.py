import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.voice_runtime_config import (
    active_backend_kind,
    is_any_backend_configured,
    load_voice_runtime_config,
    local_backend_configured,
    merge_voice_runtime_config,
    uses_any_realtime_backend,
    uses_local_backend,
    uses_realtime_backend,
    uses_realtime_skill_backend,
)


class VoiceRuntimeConfigTests(unittest.TestCase):
    def test_load_voice_runtime_config_allows_file_override_over_env_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "voice_settings.json"
            config_path.write_text(
                json.dumps(
                    {
                        "asrBackend": "openai_realtime_skills",
                        "loopIntervalMs": 75,
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {"ROKID_ASR_BACKEND": "local_http", "ROKID_VOICE_LOOP_INTERVAL_MS": "60"},
                clear=False,
            ):
                config = load_voice_runtime_config(config_path)

        self.assertEqual(config["asrBackend"], "openai_realtime_skills")
        self.assertEqual(config["loopIntervalMs"], 75)
        self.assertAlmostEqual(config["browserRealtimeSkillMinNonSilentRatio"], 0.05)
        self.assertEqual(config["browserRealtimeSkillIdleCloseMs"], 15000)
        self.assertTrue(config["browserRealtimeSkillUseTranscriptRoute"])
        self.assertEqual(config["browserRealtimeRouteTurnDetection"], "manual")
        self.assertEqual(config["browserRealtimeRouteCommitMs"], 2200)
        self.assertEqual(config["browserRealtimeRouteMinCommitMs"], 640)
        self.assertEqual(config["browserRealtimeRouteMinVoicedMs"], 320)
        self.assertEqual(config["browserRealtimeRouteSilenceCommitMs"], 420)
        self.assertEqual(config["realtimeSkillResponseDebounceMs"], 700)
        self.assertEqual(config["realtimeSkillPingMs"], 8000)
        self.assertFalse(config["realtimeSkillRespondAfterTool"])

    def test_load_voice_runtime_config_defaults_to_product_primary_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "missing_voice_settings.json"
            with patch.dict("os.environ", {}, clear=True):
                config = load_voice_runtime_config(config_path)

        self.assertEqual(config["asrBackend"], "openai_realtime_skills")
        self.assertFalse(config["allowOpenAITranscriptionFallback"])
        self.assertFalse(config["allowOpenAIRouterFallback"])
        self.assertTrue(config["routeSpeechHudEnabled"])
        self.assertFalse(config["localPartialEnabled"])
        self.assertEqual(config["loopIntervalMs"], 40)
        self.assertEqual(config["browserRealtimeSkillIdleCloseMs"], 15000)
        self.assertTrue(config["browserRealtimeSkillUseTranscriptRoute"])
        self.assertEqual(config["browserRealtimeRouteTurnDetection"], "manual")
        self.assertEqual(config["browserRealtimeRouteCommitMs"], 2200)
        self.assertEqual(config["browserRealtimeRouteMinCommitMs"], 640)
        self.assertEqual(config["browserRealtimeRouteMinVoicedMs"], 320)
        self.assertEqual(config["browserRealtimeRouteSilenceCommitMs"], 420)
        self.assertEqual(config["realtimeSkillResponseDebounceMs"], 700)
        self.assertEqual(config["realtimeSkillPingMs"], 8000)

    def test_merge_voice_runtime_config_normalizes_updates_and_preserves_masked_secrets(self) -> None:
        current = {
            "asrBackend": "openai_realtime_skills",
            "minSegmentMs": 900,
            "enableOpenAI": True,
            "openaiApiKey": "test-openai-key-old",
        }

        merged = merge_voice_runtime_config(
            current,
            {
                "asrBackend": " hybrid_local_openai ",
                "minSegmentMs": "1200",
                "enableOpenAI": 0,
                "localHttpHeaders": {"Authorization": "Bearer token"},
                "openaiApiKey": "****masked****",
            },
        )

        self.assertEqual(merged["asrBackend"], "hybrid_local_openai")
        self.assertEqual(merged["minSegmentMs"], 1200)
        self.assertFalse(merged["enableOpenAI"])
        self.assertEqual(merged["localHttpHeaders"], {"Authorization": "Bearer token"})
        self.assertEqual(merged["openaiApiKey"], "test-openai-key-old")

    def test_backend_policy_helpers_reflect_current_product_direction(self) -> None:
        realtime_skills = {"asrBackend": "openai_realtime_skills"}
        local_hybrid = {"asrBackend": "hybrid_local_openai", "localTranscribeUrl": "http://127.0.0.1:9000"}

        self.assertEqual(active_backend_kind(local_hybrid), "local_first")
        self.assertTrue(uses_realtime_skill_backend(realtime_skills))
        self.assertFalse(uses_realtime_backend(realtime_skills))
        self.assertTrue(uses_any_realtime_backend(realtime_skills))
        self.assertTrue(uses_local_backend(local_hybrid))

    def test_backend_configured_checks_handle_openai_and_local_fallbacks(self) -> None:
        realtime_skills = {"asrBackend": "openai_realtime_skills"}
        local_http = {"asrBackend": "local_http", "localTranscribeUrl": "http://127.0.0.1:9000"}
        hybrid = {"asrBackend": "hybrid_local_openai", "localStartCommand": "python server.py"}

        self.assertTrue(is_any_backend_configured(realtime_skills, has_api_key=True))
        self.assertFalse(is_any_backend_configured(realtime_skills, has_api_key=False))
        self.assertTrue(local_backend_configured(local_http))
        self.assertTrue(is_any_backend_configured(local_http, has_api_key=False))
        self.assertTrue(is_any_backend_configured(hybrid, has_api_key=False))


if __name__ == "__main__":
    unittest.main()
