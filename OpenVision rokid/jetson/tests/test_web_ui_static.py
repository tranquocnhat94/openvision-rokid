import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS_APP_JS = ROOT / "jetson" / "web_ui" / "static" / "app.js"
OPS_INDEX_HTML = ROOT / "jetson" / "web_ui" / "static" / "index.html"
PEOPLE_JS = ROOT / "jetson" / "web_ui" / "static" / "people.js"
PEOPLE_HTML = ROOT / "jetson" / "web_ui" / "static" / "people.html"
RECORDINGS_JS = ROOT / "jetson" / "web_ui" / "static" / "recordings.js"
RECORDINGS_HTML = ROOT / "jetson" / "web_ui" / "static" / "recordings.html"
SIMULATOR_JS = ROOT / "jetson" / "web_ui" / "static" / "simulator" / "simulator.js"
SIMULATOR_HTML = ROOT / "jetson" / "web_ui" / "static" / "simulator" / "index.html"


class WebUiStaticTest(unittest.TestCase):
    def test_iphone_simulator_requests_microphone_before_realtime_or_webrtc(self):
        source = SIMULATOR_JS.read_text(encoding="utf-8")
        click_handler = re.search(
            r'ui\.start\.addEventListener\("click", async \(\) => \{(?P<body>.*?)\n\}\);',
            source,
            re.DOTALL,
        )

        self.assertIsNotNone(click_handler)
        body = click_handler.group("body")
        media_index = body.index("const audioMedia = await startAudio();")
        session_index = body.index("await createSession();")
        realtime_index = body.index("await startRealtime();")
        webrtc_index = body.index("await connectWebRtc(audioMedia);")

        self.assertLess(media_index, session_index)
        self.assertLess(media_index, realtime_index)
        self.assertLess(media_index, webrtc_index)
        self.assertIn("Requesting microphone", body)
        self.assertNotIn("Requesting camera", body)

    def test_iphone_simulator_stops_media_when_startup_fails(self):
        source = SIMULATOR_JS.read_text(encoding="utf-8")

        self.assertIn("function stopMedia()", source)
        self.assertIn("stopMedia();", source)

    def test_iphone_simulator_keeps_camera_off_until_media_command(self):
        source = SIMULATOR_JS.read_text(encoding="utf-8")

        self.assertIn("async function startAudio()", source)
        self.assertIn("video: false", source)
        self.assertIn('peer.addTransceiver("video", { direction: "sendonly" }).sender', source)
        self.assertIn("async function ensureCameraActive(command)", source)
        self.assertIn("await videoSender.replaceTrack(track);", source)
        self.assertIn("async function stopCamera()", source)

    def test_iphone_simulator_reports_media_command_events(self):
        source = SIMULATOR_JS.read_text(encoding="utf-8")

        self.assertIn("function startMediaCommandPolling()", source)
        self.assertIn("const MEDIA_COMMAND_POLL_MS = 250;", source)
        self.assertIn("const HUD_POLL_MS = 250;", source)
        self.assertIn('api("/api/media/commands")', source)
        self.assertIn('/api/media/commands/${encodeURIComponent(command.command_id)}/events', source)
        self.assertIn("simulator_snapshot_ready", source)
        self.assertIn("client_timing_ms", source)
        self.assertIn("server_command_age_ms", source)
        self.assertIn("simulator_live_video_running", source)
        self.assertIn("simulator_camera_off", source)

    def test_iphone_simulator_reports_and_preserves_video_budget(self):
        source = SIMULATOR_JS.read_text(encoding="utf-8")

        self.assertIn("function requestedVideoBudget(command)", source)
        self.assertIn("function safeTrackSettings(track)", source)
        self.assertIn("function safeTrackConstraints(track)", source)
        self.assertIn("function clientVideoPayload(command = null)", source)
        self.assertIn("requested: command ? requestedVideoBudget(command) : null", source)
        self.assertIn("settings: safeTrackSettings(track)", source)
        self.assertIn("constraints: safeTrackConstraints(track)", source)
        self.assertIn('{ exact: "environment" }', source)
        self.assertIn("function openEnvironmentCamera(command)", source)
        self.assertIn("function trackIsUserFacing(track)", source)
        self.assertIn("const PERSON_INFO_SNAPSHOT_SAMPLE_COUNT = 4;", source)
        self.assertIn("const PERSON_INFO_SNAPSHOT_MIN_NEW_FRAMES = 4;", source)
        self.assertIn("const PERSON_INFO_SNAPSHOT_MIN_SETTLE_MS = 850;", source)
        self.assertIn("requireSettle: true", source)
        self.assertIn("function snapshotPreviewWaitOptions(command)", source)
        self.assertIn("snapshot_wait_policy", source)
        self.assertIn('params.degradationPreference = "maintain-resolution"', source)
        self.assertIn("scaleResolutionDownBy: 1", source)
        self.assertIn("await applyVideoSenderBudget(command, track);", source)
        self.assertIn("await applyVideoSenderBudget(command, existingTrack);", source)

    def test_iphone_simulator_starts_with_voice_output_enabled(self):
        source = SIMULATOR_HTML.read_text(encoding="utf-8")
        js_source = SIMULATOR_JS.read_text(encoding="utf-8")

        self.assertIn('id="voiceToggle"', source)
        self.assertIn('id="voiceStatus"', source)
        self.assertIn("checked", source)
        self.assertIn("function updateVoiceStatus(label)", js_source)
        self.assertIn("async function primeVoiceAudio()", js_source)
        self.assertIn("Voice audio chunk", js_source)
        self.assertIn("audio_done", js_source)

    def test_iphone_simulator_renders_target_finder_aim_overlay(self):
        html = SIMULATOR_HTML.read_text(encoding="utf-8")
        source = SIMULATOR_JS.read_text(encoding="utf-8")

        self.assertIn('id="hudAim"', html)
        self.assertIn('id="hudAimArrow"', html)
        self.assertIn('id="hudZoom"', html)
        self.assertIn("function renderAim(targetHint)", source)
        self.assertIn('targetHint.mode !== "aim_assist"', source)
        self.assertIn("tiny_center_reticle", source)
        self.assertIn("PICK ID", source)
        self.assertIn("function renderZoom(zoom)", source)
        self.assertIn('markMediaCommandHandled(command, "live_starting")', source)

    def test_ops_console_surfaces_yolo26_stream_bbox_details(self):
        source = OPS_APP_JS.read_text(encoding="utf-8")

        self.assertIn("YOLO26 or Face ID stream bbox output will appear here", source)
        self.assertIn("function bboxText(bbox)", source)
        self.assertIn("object.bbox", source)
        self.assertIn("adapter.stream_ingest_enabled", source)
        self.assertIn('api("/api/adapters/yolo26/worker")', source)
        self.assertIn("worker backend", source)
        self.assertIn('api("/api/adapters/face-identity")', source)
        self.assertIn('api("/api/adapters/face-identity/worker")', source)
        self.assertIn("Face Identity Local", source)
        self.assertIn('api("/api/identity/status")', source)
        self.assertIn('api("/api/identity/contacts")', source)

    def test_ops_console_realtime_start_uses_server_vad_by_default(self):
        source = OPS_APP_JS.read_text(encoding="utf-8")

        self.assertIn('turn_policy: "server_vad"', source)
        self.assertNotIn('turn_policy: "manual"', source)

    def test_ops_console_labels_preview_resolution_and_sensor_metadata(self):
        source = OPS_APP_JS.read_text(encoding="utf-8")

        self.assertIn("function previewResolutionLabel", source)
        self.assertIn("preview downscaled 640x360", source)
        self.assertIn("function previewFrameUrl", source)
        self.assertIn("function objectDisplayLabel", source)
        self.assertNotIn("function bboxForPreview", source)
        self.assertNotIn("function bboxRotationForPreview", source)
        self.assertNotIn("function rotateBbox", source)
        self.assertNotIn("bboxStyleForPreview", source)
        self.assertNotIn("bbox-layer", source)
        self.assertNotIn("renderPreviewOverlay", source)
        self.assertIn("processed recording available", source)
        self.assertIn("function previewDeepStreamH264WsUrl", source)
        self.assertIn("function previewUsesDeepStreamH264", source)
        self.assertIn("function previewUsesStableOverlay", source)
        self.assertIn("function renderPreviewStableOverlay", source)
        self.assertIn("Stable YOLO26 overlay H.264", source)
        self.assertIn("preview-bbox", source)
        self.assertIn("DeepStream OSD H.264", source)
        self.assertIn("/deepstream-h264", source)
        self.assertIn("preview-stage-deepstream", source)
        self.assertIn("processed recording available for review; live Sensor Preview stays on routed H.264", source)
        self.assertIn("preview.review_preview?.available", source)
        self.assertIn("const sensorPreviewDisplayState = new Map();", source)
        self.assertIn("isStaleDecodedLiveFrame", source)
        self.assertIn("requestAnimationFrame(() => this.drawPendingFrame());", source)
        self.assertIn("active_live_route_does_not_require_jpeg_preview", (ROOT / "jetson" / "agent" / "openvision_jetson" / "control_plane.py").read_text(encoding="utf-8"))
        self.assertNotIn("function previewProcessedStreamUrl", source)
        self.assertNotIn("preview-stage-processed", source)
        update_preview_stage = re.search(r"function updatePreviewStage\(card, preview\) \{(?P<body>.*?)\n\}", source, re.DOTALL)
        self.assertIsNotNone(update_preview_stage)
        body = update_preview_stage.group("body")
        self.assertLess(source.index("const deepstream = previewDeepStreamH264WsUrl(preview);"), source.index("const direct = preview.h264_ws_url"))
        self.assertNotIn("processedUrl", body)
        self.assertIn("preview.image_url", source)
        self.assertNotIn("PERCEPTION_OVERLAY_REFRESH_MS", source)
        self.assertIn("function connectPerceptionStream", source)
        self.assertIn("/ws/perception", source)
        self.assertIn("Promise.all", source)
        self.assertIn("function sensorMetadataLabel", source)
        self.assertIn("fov ${metadata.fov_mode}", source)
        self.assertIn("crop ${metadata.crop_policy}", source)
        self.assertIn("stabilization ${metadata.video_stabilization}", source)
        self.assertIn("orientation/profile metadata not reported", source)
        self.assertIn("preview-inspect", source)
        self.assertIn("function renderIdentity()", source)
        preview_metadata = re.search(r"function previewMetadata\(preview\) \{(?P<body>.*?)\n\}", source, re.DOTALL)
        self.assertIsNotNone(preview_metadata)
        body = preview_metadata.group("body")
        self.assertIn("preview.metadata", body)
        self.assertNotIn("perception && perception.metadata", body)
        self.assertIn("Contact Identity DB", source)
        self.assertIn('api("/api/people/status")', source)
        self.assertIn("function renderPeopleRegistry()", source)
        self.assertIn("People Registry", source)

    def test_people_registry_is_managed_on_dedicated_page(self):
        index = OPS_INDEX_HTML.read_text(encoding="utf-8")
        app_source = OPS_APP_JS.read_text(encoding="utf-8")
        html = PEOPLE_HTML.read_text(encoding="utf-8")
        source = PEOPLE_JS.read_text(encoding="utf-8")

        self.assertIn('href="/people.html"', index)
        self.assertIn('href="/people.html"', app_source)
        self.assertIn('api("/api/people/status")', app_source)
        self.assertNotIn('api("/api/people")', app_source)
        self.assertIn("People Registry Status", app_source)
        self.assertIn("pending face sync", app_source)

        self.assertIn("Face / People Registry", html)
        self.assertIn('id="peopleRegistry"', html)
        self.assertIn("/people.js", html)
        self.assertIn('api("/api/people/status")', source)
        self.assertIn('api("/api/people")', source)
        self.assertIn("function renderPeopleRegistry()", source)
        self.assertIn("remembered captures", source)
        self.assertIn('id="peopleSearch"', source)
        self.assertIn('id="peopleFilter"', source)
        self.assertIn("function saveSelectedPerson", source)
        self.assertIn("function enrollSelectedPersonIdentity", source)
        self.assertIn('id="peopleAge"', source)
        self.assertIn('id="peopleWhereLives"', source)
        self.assertIn('id="peopleRelationship"', source)
        self.assertIn('id="peopleFirstMet"', source)
        self.assertIn('id="peopleFacts"', source)
        self.assertIn("function parsePeopleFacts", source)
        self.assertIn("person.facts", source)
        self.assertIn("/enroll-identity", source)
        self.assertIn("/thumbnail", source)

    def test_recordings_are_managed_on_dedicated_page(self):
        index = OPS_INDEX_HTML.read_text(encoding="utf-8")
        html = RECORDINGS_HTML.read_text(encoding="utf-8")
        source = RECORDINGS_JS.read_text(encoding="utf-8")

        self.assertIn('href="/recordings.html"', index)
        self.assertNotIn('id="recordingsList"', index)
        self.assertIn("Recording Review", html)
        self.assertIn('id="recordingsList"', html)
        self.assertIn("/recordings.js", html)
        self.assertIn('api("/api/recordings?limit=100")', source)
        self.assertNotIn("/processed/stream.mjpeg", source)
        self.assertIn("<video", source)
        self.assertIn("processed-preview-mp4", source)
        self.assertIn("raw-video-mp4", source)
        self.assertIn("Create MP4", source)
        self.assertIn("Processed overlay MP4", source)
        self.assertIn("processed_fps_estimate", source)
        self.assertIn("raw-audio", source)
        self.assertIn("raw-video", source)
        self.assertNotIn("loopPlaybackToggle", html)


if __name__ == "__main__":
    unittest.main()
