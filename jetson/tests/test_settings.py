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
            },
            clear=True,
        ):
            runtime = load_runtime_settings()
            snapshot = load_settings()

        self.assertTrue(runtime.debug_stt_enabled)
        self.assertEqual(runtime.debug_stt_transcribe_url, "http://mini/inference")
        self.assertTrue(snapshot["debug_stt_enabled"])

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
