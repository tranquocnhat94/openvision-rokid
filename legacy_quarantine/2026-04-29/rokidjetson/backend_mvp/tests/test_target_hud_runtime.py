import unittest

from app.hud_scene_runtime import build_hud_scene_payload, scene_component, scene_gallery_items
from app.target_hud_runtime import (
    TargetHudState,
    evaluate_target_hud_scene,
    reset_target_hud_positive_state,
)


class TargetHudRuntimeTests(unittest.TestCase):
    def test_evaluate_target_hud_scene_holds_last_positive_scene_within_grace_window(self) -> None:
        previous_positive = build_hud_scene_payload(
            session_id="session-1",
            scene_id="scene-positive",
            task_chip="Tim: nguoi ao do",
            mic_chip="target search",
            gallery_items=[{"label": "Nguoi ao do", "trackId": "track-7", "selected": True}],
            direction_hint="Ben trai",
            target_marker={"kind": "target_marker", "id": "target", "zone": "center"},
        )
        scanning_payload = build_hud_scene_payload(
            session_id="session-1",
            scene_id="scene-scan",
            task_chip="Tim: nguoi ao do",
            mic_chip="target search",
            status_text="Dang quet nguoi ao do",
            direction_hint="Dang quet khung hinh",
        )

        evaluation = evaluate_target_hud_scene(
            state=TargetHudState(
                last_positive_scene=previous_positive,
                last_positive_ms=900,
                last_positive_query="nguoi ao do",
            ),
            query="nguoi ao do",
            payload=scanning_payload,
            session_id="session-1",
            hold_scene_id="scene-held",
            now_ms=1000,
            candidate_grace_ms=250,
            scene_interval_ms=850,
        )

        self.assertIsNotNone(evaluation.emit_payload)
        self.assertEqual(evaluation.emit_payload["sceneId"], "scene-held")
        self.assertEqual(
            scene_gallery_items(evaluation.emit_payload),
            [{"label": "Nguoi ao do", "trackId": "track-7", "selected": True}],
        )
        direction = scene_component(evaluation.emit_payload, "direction_hint")
        self.assertIsNotNone(direction)
        self.assertEqual(direction["text"], "Ben trai")

    def test_evaluate_target_hud_scene_updates_positive_memory_even_when_emit_is_throttled(self) -> None:
        payload = build_hud_scene_payload(
            session_id="session-1",
            scene_id="scene-positive",
            task_chip="Tim: xe buyt",
            mic_chip="target search",
            gallery_items=[{"label": "Xe buyt", "trackId": "track-3", "selected": True}],
            direction_hint="Phia truoc",
        )
        baseline = evaluate_target_hud_scene(
            state=TargetHudState(),
            query="xe buyt",
            payload=payload,
            session_id="session-1",
            hold_scene_id="scene-held",
            now_ms=1000,
            candidate_grace_ms=250,
            scene_interval_ms=850,
        )

        throttled = evaluate_target_hud_scene(
            state=TargetHudState(
                last_signature=baseline.next_state.last_signature,
                last_sent_ms=1000,
            ),
            query="xe buyt",
            payload=payload,
            session_id="session-1",
            hold_scene_id="scene-held-2",
            now_ms=1050,
            candidate_grace_ms=250,
            scene_interval_ms=850,
        )

        self.assertIsNone(throttled.emit_payload)
        self.assertEqual(throttled.next_state.last_positive_scene, payload)
        self.assertEqual(throttled.next_state.last_positive_ms, 1050)
        self.assertEqual(throttled.next_state.last_positive_query, "xe buyt")

    def test_reset_target_hud_positive_state_preserves_throttle_fields(self) -> None:
        state = TargetHudState(
            last_signature="sig-1",
            last_sent_ms=1200,
            last_positive_scene={"sceneId": "scene-positive"},
            last_positive_ms=1100,
            last_positive_query="nguoi ao do",
        )

        reset_state = reset_target_hud_positive_state(state)

        self.assertEqual(reset_state.last_signature, "sig-1")
        self.assertEqual(reset_state.last_sent_ms, 1200)
        self.assertEqual(reset_state.last_positive_scene, {})
        self.assertEqual(reset_state.last_positive_ms, 0)
        self.assertEqual(reset_state.last_positive_query, "")

    def test_evaluate_target_hud_scene_returns_no_emit_when_payload_missing(self) -> None:
        state = TargetHudState(
            last_signature="sig-1",
            last_sent_ms=1200,
            last_positive_scene={"sceneId": "scene-positive"},
            last_positive_ms=1100,
            last_positive_query="nguoi ao do",
        )

        evaluation = evaluate_target_hud_scene(
            state=state,
            query="nguoi ao do",
            payload=None,
            session_id="session-1",
            hold_scene_id="scene-held",
            now_ms=1300,
            candidate_grace_ms=250,
            scene_interval_ms=850,
        )

        self.assertIsNone(evaluation.emit_payload)
        self.assertIsNone(evaluation.emit_log_payload)
        self.assertEqual(evaluation.next_state, state)


if __name__ == "__main__":
    unittest.main()
