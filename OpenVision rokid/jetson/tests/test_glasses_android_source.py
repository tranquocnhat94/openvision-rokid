import unittest
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANDROID_APP_REPO = Path(
    os.environ.get(
        "OPENVISION_GLASS_APP_REPO",
        str(ROOT.parents[1] / "openvision-rokid-glasses-app"),
    )
)


def _h264_streamer_path() -> Path:
    relative_path = Path("app/src/main/java/com/openvision/rokid/media/H264LiveStreamer.kt")
    candidates = [
        ROOT / "glasses" / "android_client" / relative_path,
        ANDROID_APP_REPO / relative_path,
    ]
    for path in candidates:
        if path.exists():
            return path
    raise unittest.SkipTest("RV101 Android app source is in the standalone app repo and is not available here.")


class GlassesAndroidSourceTest(unittest.TestCase):
    def test_h264_streamer_preserves_codec_config_for_backend_preview_decoder(self):
        source = _h264_streamer_path().read_text(encoding="utf-8")

        self.assertIn("MediaCodec.INFO_OUTPUT_FORMAT_CHANGED", source)
        self.assertIn("codec.outputFormat.codecConfigAnnexB()", source)
        self.assertIn("payloadWithCodecConfig(payload, isKeyframe, isConfig)", source)
        self.assertIn('"isCodecConfig"', source)
        self.assertIn('"codecConfigPrepended"', source)
        self.assertIn("containsH264ParameterSet", source)
        self.assertIn("waitingForSyncFrameAfterDrop", source)
        self.assertIn("requestSyncFrameSoon", source)
        self.assertIn("MAX_PENDING_VIDEO_SAMPLES = 8", source)


if __name__ == "__main__":
    unittest.main()
