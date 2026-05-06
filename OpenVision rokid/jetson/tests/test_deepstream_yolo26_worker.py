import json
import tempfile
import unittest
from urllib.error import HTTPError
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "perception"))

from openvision_jetson.deepstream_yolo26_worker import (
    DeepStreamYolo26Worker,
    DeepStreamYolo26WorkerSettings,
    Rv101RtspRelay,
    _SessionRuntime,
    _MqttPayloadAssembler,
    _annexb_nal_types,
    _inactive_live_conflict_error,
    parse_deepstream_payload,
    probe_deepstream_runtime,
    render_deepstream_configs,
)


class CapturingStatusWriter:
    def __init__(self):
        self.payloads = []

    def write(self, payload):
        self.payloads.append(payload)


class FakeApi:
    def list_active_live(self):
        return []


class CapturingApi(FakeApi):
    def __init__(self):
        self.posts = []

    def post_stream_detections(self, *, session_id, payload):
        self.posts.append({"session_id": session_id, "payload": payload})
        return {"status": "accepted"}


class FakeProcess:
    def __init__(self, lines):
        self.stdout = lines


class FakeApiWithLive:
    def __init__(self, active):
        self._active = active

    def list_active_live(self):
        return self._active


class FakeRtspRelay:
    def __init__(self, status):
        self._status = status

    def status(self):
        return self._status


class DeepStreamYolo26WorkerTest(unittest.TestCase):
    def test_disabled_worker_writes_compatible_status(self):
        writer = CapturingStatusWriter()
        worker = DeepStreamYolo26Worker(
            settings=DeepStreamYolo26WorkerSettings(enabled=False),
            api=FakeApi(),
            status_writer=writer,
        )

        status = worker.run_once()

        self.assertEqual(status["status"], "disabled")
        self.assertEqual(status["backend"], "deepstream")
        self.assertEqual(status["schema_version"], "openvision.deepstream_yolo26_worker_status.v1")
        self.assertEqual(writer.payloads[-1]["status"], "disabled")

    def test_rtsp_relay_status_reports_server_readiness(self):
        relay = Rv101RtspRelay(session_id="sess_test", port=8785, fps=15.0)

        status = relay.status()

        self.assertFalse(status["server_ready"])
        self.assertIsNone(status["server_attach_id"])
        self.assertIsNone(status["server_ready_at"])

    def test_runtime_restarts_when_deepstream_never_attaches_after_h264_preroll(self):
        worker = DeepStreamYolo26Worker(
            settings=DeepStreamYolo26WorkerSettings(enabled=True),
            api=FakeApi(),
            status_writer=CapturingStatusWriter(),
            clock=lambda: 10.0,
        )
        runtime = _SessionRuntime(
            session_id="sess_test",
            command_id="media_cmd_test",
            skill_id="target_finder",
            topic="openvision/rv101/yolo26/sess_test/detections",
            rtsp_uri="rtsp://127.0.0.1:8785/sess_test",
            config_dir=Path("/tmp/openvision-test"),
            stream_width=800,
            stream_height=600,
            rtsp_relay=FakeRtspRelay(
                {
                    "input_sample_count": 60,
                    "media_configure_count": 0,
                    "pushed_sample_count": 0,
                }
            ),
            started_monotonic_s=0.0,
        )

        self.assertTrue(worker._runtime_needs_restart(runtime))
        self.assertEqual(runtime.last_error, "rtsp_source_not_attached_after_h264_preroll")

    def test_port_allocator_skips_ports_used_by_remaining_sessions(self):
        worker = DeepStreamYolo26Worker(
            settings=DeepStreamYolo26WorkerSettings(
                enabled=True,
                max_sessions=3,
                rtsp_port=8785,
                annotated_rtsp_port=8795,
                annotated_udp_port=5600,
            ),
            api=FakeApi(),
            status_writer=CapturingStatusWriter(),
        )
        worker._sessions["sess_b"] = _SessionRuntime(
            session_id="sess_b",
            command_id="media_cmd_b",
            skill_id="target_finder",
            topic="openvision/rv101/yolo26/sess_b/detections",
            rtsp_uri="rtsp://127.0.0.1:8786/sess_b",
            config_dir=Path("/tmp/openvision-test"),
            stream_width=800,
            stream_height=600,
            rtsp_port=8786,
        )

        ports = worker._allocate_session_ports()

        self.assertEqual(ports, (8785, 8795, 5600))

    def test_empty_deepstream_frame_posts_empty_snapshot_to_clear_stale_boxes(self):
        api = CapturingApi()
        worker = DeepStreamYolo26Worker(
            settings=DeepStreamYolo26WorkerSettings(enabled=True, source="openvision_rv101_yolo26_deepstream"),
            api=api,
            status_writer=CapturingStatusWriter(),
            clock=lambda: 20.0,
        )
        runtime = _SessionRuntime(
            session_id="sess_test",
            command_id="media_cmd_test",
            skill_id="target_finder",
            topic="openvision/rv101/yolo26/sess_test/detections",
            rtsp_uri="rtsp://127.0.0.1:8785/sess_test",
            config_dir=Path("/tmp/openvision-test"),
            stream_width=800,
            stream_height=600,
            mqtt_process=FakeProcess([json.dumps({"frameWidth": 800, "frameHeight": 600, "objects": []})]),
        )
        worker._sessions[runtime.session_id] = runtime

        worker._mqtt_loop(runtime)

        self.assertEqual(runtime.posted_frame_count, 1)
        self.assertEqual(runtime.ignored_message_count, 0)
        self.assertEqual(runtime.last_payload_status, "posted_empty_frame")
        self.assertEqual(api.posts[0]["session_id"], "sess_test")
        self.assertEqual(api.posts[0]["payload"]["detections"], [])
        self.assertEqual(api.posts[0]["payload"]["width"], 800)
        self.assertEqual(api.posts[0]["payload"]["metadata"]["perception_branch"], "yolo26_objects")

    def test_parse_deepstream_payload_supports_frame_object_lists(self):
        payload = json.dumps(
            {
                "frames": [
                    {
                        "frameWidth": 800,
                        "frameHeight": 600,
                        "objects": [
                            {
                                "classId": 0,
                                "confidence": 0.91,
                                "rect_params": {"left": 10, "top": 20, "width": 100, "height": 140},
                                "trackingId": 42,
                            }
                        ],
                    }
                ]
            }
        )

        detections, metadata = parse_deepstream_payload(payload, labels=["person"])

        self.assertEqual(metadata["width"], 800)
        self.assertEqual(metadata["height"], 600)
        self.assertEqual(detections[0]["label"], "person")
        self.assertEqual(detections[0]["confidence"], 0.91)
        self.assertEqual(detections[0]["bbox"], [10.0, 20.0, 110.0, 160.0])
        self.assertEqual(detections[0]["track_id"], "42")
        self.assertEqual(detections[0]["attributes"]["accelerator"], "deepstream")

    def test_parse_deepstream_payload_supports_nvmsgconv_object_schema_without_confidence(self):
        payload = json.dumps(
            {
                "@timestamp": "2026-05-02T00:00:00Z",
                "frameWidth": 1280,
                "frameHeight": 720,
                "object": {
                    "objType": "Person",
                    "id": "person-7",
                    "bbox": {
                        "topleftx": 101,
                        "toplefty": 55,
                        "bottomrightx": 220,
                        "bottomrighty": 300,
                    },
                },
            }
        )

        detections, metadata = parse_deepstream_payload(payload, labels=[])

        self.assertEqual(metadata["deepstream_timestamp"], "2026-05-02T00:00:00Z")
        self.assertEqual(detections[0]["label"], "person")
        self.assertEqual(detections[0]["confidence"], 0.25)
        self.assertEqual(detections[0]["bbox"], [101.0, 55.0, 220.0, 300.0])
        self.assertEqual(detections[0]["track_id"], "person-7")
        self.assertEqual(detections[0]["attributes"]["confidence_source"], "missing")

    def test_parse_deepstream_payload_marks_generic_object_schema_as_unclassified(self):
        payload = json.dumps(
            {
                "frameWidth": 800,
                "frameHeight": 600,
                "object": {
                    "objType": "object",
                    "id": "8",
                    "bbox": {
                        "topleftx": 391,
                        "toplefty": 560,
                        "bottomrightx": 536,
                        "bottomrighty": 600,
                    },
                },
            }
        )

        detections, metadata = parse_deepstream_payload(payload, labels=["person"])

        self.assertEqual(detections[0]["label"], "object")
        self.assertEqual(detections[0]["confidence"], 0.25)
        self.assertEqual(detections[0]["attributes"]["classification_status"], "unclassified")
        self.assertEqual(detections[0]["attributes"]["display_name"], "YOLO track 8")
        self.assertEqual(metadata["classification_status"], "unclassified")
        self.assertEqual(metadata["missing_confidence_count"], 1)

    def test_parse_deepstream_payload_uses_nested_msgconv_class_confidence(self):
        payload = json.dumps(
            {
                "frameWidth": 800,
                "frameHeight": 600,
                "object": {
                    "id": "4",
                    "mouse": {"confidence": 0.25390625},
                    "bbox": {
                        "topleftx": 332,
                        "toplefty": 571,
                        "bottomrightx": 480,
                        "bottomrighty": 600,
                    },
                },
            }
        )

        detections, metadata = parse_deepstream_payload(payload, labels=["person", "mouse", "laptop"])

        self.assertNotIn("classification_status", metadata)
        self.assertNotIn("missing_confidence_count", metadata)
        self.assertEqual(detections[0]["label"], "mouse")
        self.assertEqual(detections[0]["confidence"], 0.25390625)
        self.assertEqual(detections[0]["attributes"]["label_source"], "nested_msgconv_class")
        self.assertEqual(detections[0]["attributes"]["confidence_source"], "nested_msgconv_class")

    def test_parse_deepstream_payload_supports_compact_object_strings(self):
        detections, _metadata = parse_deepstream_payload(
            json.dumps({"object": "car|track9|1|2|30|40|0.77"}),
            labels=[],
        )

        self.assertEqual(detections[0]["label"], "car")
        self.assertEqual(detections[0]["bbox"], [1.0, 2.0, 31.0, 42.0])
        self.assertEqual(detections[0]["confidence"], 0.77)
        self.assertEqual(detections[0]["track_id"], "track9")

    def test_mqtt_payload_assembler_reconstructs_deepstream_multiline_json(self):
        topic = "openvision/rv101/yolo26/sess_test/detections"
        assembler = _MqttPayloadAssembler(topic)
        lines = [
            f"{topic} {{",
            '  "@timestamp": "2026-05-02T00:00:00Z",',
            '  "frameWidth": 800,',
            '  "frameHeight": 600,',
            '  "object": {',
            '    "objType": "Person",',
            '    "id": "person-42",',
            '    "bbox": {',
            '      "topleftx": 10,',
            '      "toplefty": 20,',
            '      "bottomrightx": 110,',
            '      "bottomrighty": 160',
            "    }",
            "  }",
            "}",
        ]
        payloads = []
        for line in lines:
            payloads.extend(assembler.feed(line))

        self.assertEqual(len(payloads), 1)
        detections, metadata = parse_deepstream_payload(payloads[0], labels=[])
        self.assertEqual(metadata["width"], 800)
        self.assertEqual(metadata["height"], 600)
        self.assertEqual(detections[0]["label"], "person")
        self.assertEqual(detections[0]["track_id"], "person-42")
        self.assertEqual(detections[0]["bbox"], [10.0, 20.0, 110.0, 160.0])

    def test_mqtt_payload_assembler_ignores_stray_non_json_lines(self):
        topic = "openvision/rv101/yolo26/sess_test/detections"
        assembler = _MqttPayloadAssembler(topic)

        self.assertEqual(assembler.feed("}"), [])
        self.assertEqual(assembler.feed("deepstream warning text"), [])
        self.assertEqual(assembler.feed(f'{topic} {{"object":"person|7|1|2|3|4|0.9"}}'), ['{"object":"person|7|1|2|3|4|0.9"}'])

    def test_rtsp_relay_caches_h264_preroll_until_deepstream_attaches(self):
        relay = Rv101RtspRelay(session_id="sess_test", port=8785, fps=15)

        relay.push_h264(
            b"\x00\x00\x00\x01\x67sps\x00\x00\x00\x01\x68pps",
            metadata={"type": "sample", "sequence": 1, "is_keyframe": True, "is_codec_config": True},
        )
        relay.push_h264(
            b"\x00\x00\x00\x01\x65idr",
            metadata={"type": "sample", "sequence": 2, "is_keyframe": True},
        )

        status = relay.status()
        self.assertEqual(status["input_sample_count"], 2)
        self.assertEqual(status["pushed_sample_count"], 0)
        self.assertEqual(status["queued_before_appsrc_count"], 2)
        self.assertEqual(status["pending_sample_count"], 2)
        self.assertTrue(status["has_cached_codec_config"])
        self.assertTrue(status["has_cached_keyframe"])
        self.assertEqual(_annexb_nal_types(b"\x00\x00\x00\x01\x67sps\x00\x00\x01\x65idr"), [7, 5])

    def test_render_deepstream_configs_uses_openvision_topic_and_rejects_protected_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            labels = root / "labels.txt"
            onnx = root / "yolo26.onnx"
            custom = root / "libcustom.so"
            for path in (labels, onnx, custom):
                path.write_text("x", encoding="utf-8")
            settings = DeepStreamYolo26WorkerSettings(
                enabled=True,
                runtime_dir=root,
                labels_path=str(labels),
                onnx_path=str(onnx),
                engine_path=str(root / "openvision.engine"),
                custom_lib_path=str(custom),
                mqtt_host="127.0.0.1",
                mqtt_port=1884,
                streammux_width=800,
                streammux_height=600,
            )

            paths = render_deepstream_configs(
                settings=settings,
                session_id="sess_test",
                rtsp_uri="rtsp://127.0.0.1:8785/sess_test",
                mqtt_topic="openvision/rv101/yolo26/sess_test/detections",
                output_dir=root / "session",
            )
            app_config = Path(paths["app_config"]).read_text(encoding="utf-8")
            infer_config = Path(paths["infer_config"]).read_text(encoding="utf-8")
            msgconv_config = Path(paths["app_config"]).with_name("msgconv_openvision.txt").read_text(encoding="utf-8")

            self.assertIn("uri=rtsp://127.0.0.1:8785/sess_test", app_config)
            self.assertIn("topic=openvision/rv101/yolo26/sess_test/detections", app_config)
            self.assertIn("type=6", app_config)
            self.assertIn("[sink0]\nenable=0\ntype=1", app_config)
            self.assertIn("[sink2]\nenable=1\ntype=4", app_config)
            self.assertIn("codec=1", app_config)
            self.assertIn("rtsp-port=8795", app_config)
            self.assertIn("udp-port=5600", app_config)
            self.assertEqual(paths["annotated_rtsp_uri"], "rtsp://127.0.0.1:8795/ds-test")
            self.assertIn("[osd]\nenable=1", app_config)
            self.assertIn("display-bbox=1", app_config)
            self.assertIn("border-width=2", app_config)
            self.assertIn("font=Sans", app_config)
            self.assertIn(str(custom), infer_config)
            self.assertIn("pre-cluster-threshold=0.350", infer_config)
            self.assertIn("location=0;0;0", msgconv_config)
            self.assertNotIn("ring", app_config.lower() + infer_config.lower())
            self.assertNotIn("security", app_config.lower() + infer_config.lower())

            blocked = DeepStreamYolo26WorkerSettings(
                enabled=True,
                custom_lib_path="/mnt/ssd/ai-security-ds/libcustom.so",
            )
            with self.assertRaises(ValueError):
                render_deepstream_configs(
                    settings=blocked,
                    session_id="sess_test",
                    rtsp_uri="rtsp://127.0.0.1:8785/sess_test",
                    mqtt_topic="openvision/rv101/yolo26/sess_test/detections",
                    output_dir=root / "blocked",
                )

    def test_deepstream_worker_filters_to_declared_yolo26_preview_branch(self):
        worker = DeepStreamYolo26Worker(
            settings=DeepStreamYolo26WorkerSettings(enabled=False, max_sessions=4),
            api=FakeApiWithLive(
                [
                    {
                        "session_id": "sess_face",
                        "skill_id": "person_info",
                        "params": {
                            "preview_route": {"route_kind": "raw_h264", "primary_branch": "face_identity"},
                            "perception_branches": ["face_identity"],
                        },
                    },
                    {
                        "session_id": "sess_yolo",
                        "skill_id": "target_finder",
                        "params": {
                            "preview_route": {"route_kind": "stable_overlay_h264", "primary_branch": "yolo26_objects"},
                            "perception_branches": ["yolo26_objects", "face_identity"],
                        },
                    },
                ]
            ),
        )

        selected = worker._target_live_sessions(worker._api.list_active_live())

        self.assertEqual([item["session_id"] for item in selected], ["sess_yolo"])

    def test_worker_treats_409_post_as_inactive_live_cleanup_race(self):
        self.assertTrue(_inactive_live_conflict_error(HTTPError("http://jetson", 409, "Conflict", None, None)))
        self.assertFalse(_inactive_live_conflict_error(HTTPError("http://jetson", 500, "Server Error", None, None)))
        self.assertFalse(_inactive_live_conflict_error(RuntimeError("boom")))

    def test_parse_deepstream_payload_prefers_nested_msgconv_class_over_conflicting_class_id(self):
        payload = json.dumps(
            {
                "frameWidth": 800,
                "frameHeight": 600,
                "object": {
                    "classId": 2,
                    "id": "8",
                    "person": {"confidence": 0.8125},
                    "bbox": {
                        "topleftx": 0,
                        "toplefty": 408,
                        "bottomrightx": 173,
                        "bottomrighty": 555,
                    },
                },
            }
        )

        detections, _metadata = parse_deepstream_payload(payload, labels=["person", "mouse", "laptop"])

        self.assertEqual(detections[0]["label"], "person")
        self.assertEqual(detections[0]["attributes"]["class_id"], 2)
        self.assertEqual(detections[0]["attributes"]["class_id_label"], "laptop")
        self.assertEqual(detections[0]["attributes"]["label_conflict"], "nested_msgconv_class_overrode_class_id")

    def test_probe_deepstream_runtime_blocks_missing_and_protected_runtime(self):
        settings = DeepStreamYolo26WorkerSettings(
            enabled=True,
            deepstream_app_bin="missing-deepstream-app",
            mosquitto_sub_bin="missing-mosquitto-sub",
        )

        status = probe_deepstream_runtime(settings)

        self.assertEqual(status["status"], "blocked")
        self.assertEqual(status["reason"], "missing_dependency")
        self.assertIn("deepstream_app", status["missing"])

        protected = probe_deepstream_runtime(
            DeepStreamYolo26WorkerSettings(enabled=True, custom_lib_path="/opt/ring/security/lib.so")
        )
        self.assertEqual(protected["status"], "blocked")
        self.assertEqual(protected["reason"], "protected_runtime_path")

    def test_probe_deepstream_runtime_reports_ready_when_dependencies_and_mqtt_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            labels = root / "labels.txt"
            onnx = root / "yolo26.onnx"
            custom = root / "libcustom.so"
            tracker = root / "tracker.yml"
            for path in (labels, onnx, custom, tracker):
                path.write_text("x", encoding="utf-8")
            settings = DeepStreamYolo26WorkerSettings(
                enabled=True,
                deepstream_app_bin="deepstream-app",
                mosquitto_sub_bin="mosquitto_sub",
                labels_path=str(labels),
                onnx_path=str(onnx),
                custom_lib_path=str(custom),
                tracker_config_path=str(tracker),
            )

            with patch("shutil.which", side_effect=lambda binary: f"/usr/bin/{binary}"), patch(
                "openvision_jetson.deepstream_yolo26_worker._tcp_connects", return_value=True
            ):
                status = probe_deepstream_runtime(settings)

            self.assertEqual(status["status"], "ready")
            self.assertTrue(status["mqtt"]["broker_reachable"])
            self.assertTrue(status["annotated_h264"]["enabled"])
            self.assertEqual(status["annotated_h264"]["rtsp_port"], 8795)


if __name__ == "__main__":
    unittest.main()
