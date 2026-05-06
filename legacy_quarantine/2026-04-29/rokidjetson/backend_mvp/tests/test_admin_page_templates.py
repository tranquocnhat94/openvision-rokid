import unittest

from app.admin_page_templates import (
    build_dashboard_page,
    build_preview_live_page,
    build_simulator_page,
    simulator_page_headers,
)


class AdminPageTemplatesTest(unittest.TestCase):
    def test_preview_page_includes_latest_session_label(self) -> None:
        html = build_preview_live_page("sess_demo")

        self.assertIn("Latest session: sess_demo", html)
        self.assertIn("Jetson Sensor Debug Preview", html)
        self.assertIn("/preview/latest/live.mjpg", html)
        self.assertNotIn("fallback HLS", html)

    def test_dashboard_page_keeps_ops_console_copy(self) -> None:
        html = build_dashboard_page()

        self.assertIn("Rokid Jetson Ops Console", html)
        self.assertIn("Thin-client ops console for RV101 and browser harness", html)
        self.assertIn("Product path: speech -> OpenAI Realtime tool call", html)
        self.assertIn("openai_realtime_skills (primary)", html)
        self.assertIn("Default console surface: health, sessions, skill trace, HUD scene, simulator link, and sensor preview only.", html)
        self.assertIn("Advanced Lab: runtime settings and fallback/offline rails", html)
        self.assertIn("Advanced Lab: manual session controls and raw traces", html)
        self.assertLess(html.index("Product Ops"), html.index("API key"))
        self.assertLess(html.index("Advanced Lab: runtime settings"), html.index("API key"))

    def test_simulator_page_keeps_glasses_hud_mirror_and_no_store(self) -> None:
        html = build_simulator_page()
        headers = simulator_page_headers()

        self.assertIn("Glasses HUD mirror", html)
        self.assertIn("720 x 960 (glasses-like default)", html)
        self.assertIn("15 fps (glasses-like default)", html)
        self.assertIn("Shell debug rail", html)
        self.assertIn("browser-harness15", html)
        self.assertEqual(headers["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(headers["Pragma"], "no-cache")


if __name__ == "__main__":
    unittest.main()
