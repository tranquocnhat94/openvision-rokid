import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIMULATOR_JS = ROOT / "jetson" / "web_ui" / "static" / "simulator" / "simulator.js"


class WebUiStaticTest(unittest.TestCase):
    def test_iphone_simulator_requests_media_before_realtime_or_webrtc(self):
        source = SIMULATOR_JS.read_text(encoding="utf-8")
        click_handler = re.search(
            r'ui\.start\.addEventListener\("click", async \(\) => \{(?P<body>.*?)\n\}\);',
            source,
            re.DOTALL,
        )

        self.assertIsNotNone(click_handler)
        body = click_handler.group("body")
        media_index = body.index("const media = await startMedia();")
        session_index = body.index("await createSession();")
        realtime_index = body.index("await startRealtime();")
        webrtc_index = body.index("await connectWebRtc(media);")

        self.assertLess(media_index, session_index)
        self.assertLess(media_index, realtime_index)
        self.assertLess(media_index, webrtc_index)

    def test_iphone_simulator_stops_media_when_startup_fails(self):
        source = SIMULATOR_JS.read_text(encoding="utf-8")

        self.assertIn("function stopMedia()", source)
        self.assertIn("stopMedia();", source)


if __name__ == "__main__":
    unittest.main()
