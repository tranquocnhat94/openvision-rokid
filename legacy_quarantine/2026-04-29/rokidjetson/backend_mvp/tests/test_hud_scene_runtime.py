import unittest

from app.hud_scene_runtime import (
    build_hud_scene_payload,
    build_target_search_hud_scene_payload,
    scene_component,
    scene_gallery_items,
)


class HudSceneRuntimeTests(unittest.TestCase):
    def test_build_hud_scene_payload_keeps_expected_component_order(self) -> None:
        payload = build_hud_scene_payload(
            session_id="session-1",
            scene_id="scene-1",
            task_chip="Tim nguoi",
            mic_chip="listening",
            answer_text="Da tim thay",
            status_text="Dang cap nhat",
            gallery_items=[{"label": "Nguoi 1"}],
            direction_hint="Ben trai",
            target_marker={"kind": "target_marker", "id": "target", "zone": "center"},
        )

        self.assertEqual(payload["type"], "hud_scene")
        self.assertEqual(payload["sessionId"], "session-1")
        self.assertEqual(payload["sceneId"], "scene-1")
        self.assertEqual(
            [component["kind"] for component in payload["components"]],
            [
                "chip",
                "chip",
                "answer_strip",
                "status_strip",
                "gallery",
                "direction_hint",
                "target_marker",
            ],
        )

    def test_build_target_search_hud_scene_payload_prefers_selected_target_copy(self) -> None:
        payload = build_target_search_hud_scene_payload(
            session_id="session-1",
            scene_id="scene-2",
            query="nguoi ao do",
            selected_target_track_id="track-7",
            selected_target_visible=True,
            selected_target_label="Nguoi ao do",
            gallery_items=[{"label": "Nguoi ao do", "trackId": "track-7", "selected": True}],
            direction_hint="Phia truoc",
            target_marker={"kind": "target_marker", "id": "target", "zone": "center"},
        )

        answer = scene_component(payload, "answer_strip")
        self.assertIsNotNone(answer)
        self.assertEqual(answer["text"], "Nguoi ao do dang duoc theo doi")
        self.assertEqual(scene_gallery_items(payload)[0]["trackId"], "track-7")

    def test_build_target_search_hud_scene_payload_uses_scan_status_without_candidates(self) -> None:
        payload = build_target_search_hud_scene_payload(
            session_id="session-1",
            scene_id="scene-3",
            query="xe buyt",
            selected_target_track_id="",
            selected_target_visible=False,
            selected_target_label="",
            gallery_items=[],
            direction_hint=None,
            target_marker=None,
        )

        self.assertIsNone(scene_component(payload, "answer_strip"))
        status = scene_component(payload, "status_strip")
        direction = scene_component(payload, "direction_hint")
        self.assertIsNotNone(status)
        self.assertEqual(status["text"], "Dang quet xe buyt")
        self.assertIsNotNone(direction)
        self.assertEqual(direction["text"], "Dang quet khung hinh")

    def test_scene_helpers_filter_payload_shapes(self) -> None:
        payload = {
            "components": [
                {"kind": "gallery", "items": [{"label": "A"}, "bad-item"]},
                {"kind": "status_strip", "text": "Dang xu ly"},
                "bad-component",
            ]
        }

        self.assertEqual(scene_gallery_items(payload), [{"label": "A"}])
        self.assertEqual(scene_component(payload, "status_strip"), {"kind": "status_strip", "text": "Dang xu ly"})
        self.assertIsNone(scene_component(payload, "answer_strip"))


if __name__ == "__main__":
    unittest.main()
