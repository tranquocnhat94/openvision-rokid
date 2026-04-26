import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.settings import load_runtime_settings, load_settings


class SettingsTest(unittest.TestCase):
    def test_missing_key_is_redacted(self):
        with patch.dict(os.environ, {}, clear=True):
            snapshot = load_settings()

        self.assertFalse(snapshot["openai_key_present"])
        self.assertEqual(snapshot["openai_key_source"], "missing")
        self.assertFalse(snapshot["debug_stt_enabled"])
        self.assertTrue(snapshot["secrets_redacted"])

    def test_debug_stt_settings_are_explicit_opt_in(self):
        with patch.dict(
            os.environ,
            {
                "OPENVISION_DEBUG_STT_ENABLED": "1",
                "OPENVISION_DEBUG_STT_TRANSCRIBE_URL": "http://mini/inference",
                "OPENVISION_DEBUG_STT_AUTH_TOKEN": "debug-token",
            },
            clear=True,
        ):
            runtime = load_runtime_settings()
            snapshot = load_settings()

        self.assertTrue(runtime.debug_stt_enabled)
        self.assertEqual(runtime.debug_stt_transcribe_url, "http://mini/inference")
        self.assertEqual(runtime.debug_stt_auth_token, "debug-token")
        self.assertEqual(runtime.debug_stt_auth_token_source, "env")
        self.assertEqual(runtime.debug_stt_min_audio_ms, 800)
        self.assertTrue(snapshot["debug_stt_enabled"])
        self.assertEqual(snapshot["debug_stt_min_audio_ms"], 800)
        self.assertNotIn("debug-token", str(snapshot))

    def test_debug_stt_auth_token_can_load_from_file_without_snapshot_leak(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            token_path = Path(temp_dir) / "debug_stt_token"
            token_path.write_text("file-token\n", encoding="utf-8")

            with patch.dict(os.environ, {"OPENVISION_DEBUG_STT_AUTH_TOKEN_FILE": str(token_path)}, clear=True):
                runtime = load_runtime_settings()
                snapshot = load_settings()

        self.assertEqual(runtime.debug_stt_auth_token, "file-token")
        self.assertEqual(runtime.debug_stt_auth_token_source, "file")
        self.assertNotIn("file-token", str(snapshot))

    def test_realtime_max_output_tokens_is_configurable(self):
        with patch.dict(os.environ, {"OPENVISION_REALTIME_MAX_OUTPUT_TOKENS": "64"}, clear=True):
            runtime = load_runtime_settings()
            snapshot = load_settings()

        self.assertEqual(runtime.realtime_max_output_tokens, 64)
        self.assertEqual(snapshot["realtime_max_output_tokens"], 64)

    def test_realtime_voice_output_defaults_off_and_can_opt_in(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(load_settings()["realtime_voice_output_enabled"])

        with patch.dict(os.environ, {"OPENVISION_REALTIME_VOICE_OUTPUT_ENABLED": "1"}, clear=True):
            runtime = load_runtime_settings()
            snapshot = load_settings()

        self.assertTrue(runtime.realtime_voice_output_enabled)
        self.assertTrue(snapshot["realtime_voice_output_enabled"])

    def test_env_key_wins_over_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            key_path = Path(temp_dir) / "openai_api_key"
            key_path.write_text("file-key\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "env-key",
                    "OPENAI_API_KEY_FILE": str(key_path),
                },
                clear=True,
            ):
                runtime = load_runtime_settings()

        self.assertEqual(runtime.openai_api_key, "env-key")
        self.assertEqual(runtime.openai_key_source, "env")

    def test_file_key_is_loaded_without_exposing_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            key_path = Path(temp_dir) / "openai_api_key"
            key_path.write_text("file-key\n", encoding="utf-8")

            with patch.dict(os.environ, {"OPENAI_API_KEY_FILE": str(key_path)}, clear=True):
                runtime = load_runtime_settings()
                snapshot = load_settings()

        self.assertEqual(runtime.openai_api_key, "file-key")
        self.assertEqual(snapshot["openai_key_source"], "file")
        self.assertTrue(snapshot["openai_key_present"])
        self.assertNotIn("file-key", str(snapshot))

    def test_missing_file_reports_redacted_error_code(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY_FILE": "/missing/openai_api_key"}, clear=True):
            snapshot = load_settings()

        self.assertFalse(snapshot["openai_key_present"])
        self.assertEqual(snapshot["openai_key_source"], "file_error")
        self.assertEqual(snapshot["secret_load_error"], "FileNotFoundError")


if __name__ == "__main__":
    unittest.main()
