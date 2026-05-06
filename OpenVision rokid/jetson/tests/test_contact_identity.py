import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.contact_identity import ContactIdentityStore


class ContactIdentityStoreTest(unittest.TestCase):
    def test_enroll_vector_and_match_requested_contact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(runtime_dir=Path(temp_dir), min_confidence=0.8)
            enrolled = store.enroll_sample(
                display_name="Trâm",
                aliases=["tram"],
                vector=[1.0, 0.0, 0.0],
            )

            result = store.match_candidates(
                session_id="sess_test",
                query="tìm Trâm trong đám đông",
                candidates=[
                    {
                        "target_id": "obj_1",
                        "track_id": "p1",
                        "anonymous_id": "P1",
                        "label": "person",
                        "attributes": {"identity_vector": [0.99, 0.02, 0.0]},
                    }
                ],
            )

        self.assertEqual(enrolled["status"], "enrolled")
        self.assertEqual(enrolled["contact"]["sample_count"], 1)
        self.assertNotIn("vector", enrolled["contact"]["samples"][0])
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["matches"][0]["display_name"], "Trâm")
        self.assertEqual(result["matches"][0]["track_id"], "p1")
        self.assertGreater(result["matches"][0]["confidence"], 0.95)

    def test_enroll_sface_vector_and_match_sface_candidate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(runtime_dir=Path(temp_dir), min_confidence=0.8)
            enrolled = store.enroll_sample(
                display_name="Trâm",
                aliases=["tram"],
                vector=[1.0, 0.0, 0.0],
                source_note="opencv_sface:/tmp/tram.jpg",
            )

            result = store.match_candidates(
                session_id="sess_test",
                query="tìm Trâm trong đám đông",
                candidates=[
                    {
                        "target_id": "obj_1",
                        "track_id": "f1",
                        "anonymous_id": "P1",
                        "label": "person",
                        "attributes": {
                            "embedding_model": "sface",
                            "identity_vector": [0.99, 0.02, 0.0],
                        },
                    }
                ],
            )

        self.assertEqual(enrolled["sample"]["provider"], "sface_v1")
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["matches"][0]["display_name"], "Trâm")

    def test_match_requested_contact_by_significant_name_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(runtime_dir=Path(temp_dir), min_confidence=0.8)
            store.enroll_sample(
                display_name="A Bảo",
                vector=[1.0, 0.0, 0.0],
                source_note="opencv_sface:/tmp/abao.jpg",
            )

            result = store.match_candidates(
                session_id="sess_test",
                query="tìm Bảo",
                candidates=[
                    {
                        "target_id": "obj_1",
                        "track_id": "f1",
                        "anonymous_id": "P1",
                        "label": "person",
                        "attributes": {
                            "embedding_model": "sface",
                            "identity_vector": [0.99, 0.02, 0.0],
                        },
                    }
                ],
            )

        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["requested_contact_count"], 1)
        self.assertEqual(result["matches"][0]["display_name"], "A Bảo")

    def test_generic_people_query_matches_against_all_enrolled_contacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(runtime_dir=Path(temp_dir), min_confidence=0.8)
            store.enroll_sample(
                display_name="Trâm",
                aliases=["tram"],
                vector=[1.0, 0.0, 0.0],
                source_note="opencv_sface:/tmp/tram.jpg",
            )
            store.enroll_sample(
                display_name="A Bảo",
                vector=[0.0, 1.0, 0.0],
                source_note="opencv_sface:/tmp/abao.jpg",
            )

            result = store.match_candidates(
                session_id="sess_test",
                query="tìm người trong đám đông",
                candidates=[
                    {
                        "target_id": "obj_1",
                        "track_id": "f1",
                        "anonymous_id": "P1",
                        "label": "person",
                        "attributes": {
                            "embedding_model": "sface",
                            "identity_vector": [0.99, 0.02, 0.0],
                        },
                    }
                ],
            )

        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["requested_contact_count"], 2)
        self.assertEqual(result["matches"][0]["display_name"], "Trâm")

    def test_multiple_samples_per_contact_use_best_vector(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(runtime_dir=Path(temp_dir), min_confidence=0.8)
            store.enroll_sample(
                display_name="A Bảo",
                vector=[1.0, 0.0, 0.0],
                source_note="opencv_sface:immich_person:bao:asset:dark",
            )
            enrolled = store.enroll_sample(
                display_name="A Bảo",
                vector=[0.0, 1.0, 0.0],
                source_note="opencv_sface:immich_person:bao:asset:bright",
            )

            result = store.match_candidates(
                session_id="sess_test",
                query="người này là ai",
                candidates=[
                    {
                        "target_id": "obj_1",
                        "track_id": "f1",
                        "label": "person",
                        "attributes": {
                            "embedding_model": "sface",
                            "identity_vector": [0.02, 0.99, 0.0],
                        },
                    }
                ],
            )

        self.assertEqual(enrolled["contact"]["sample_count"], 2)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["matches"][0]["display_name"], "A Bảo")
        self.assertGreater(result["matches"][0]["confidence"], 0.95)

    def test_enroll_replaces_existing_sample_with_same_source_ref(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(runtime_dir=Path(temp_dir), min_confidence=0.8)
            store.enroll_sample(
                display_name="A Bảo",
                vector=[1.0, 0.0, 0.0],
                source_note="opencv_sface:immich_person:bao:asset:1",
            )
            enrolled = store.enroll_sample(
                display_name="A Bảo",
                vector=[0.0, 1.0, 0.0],
                source_note="opencv_sface:immich_person:bao:asset:1",
            )

        self.assertEqual(enrolled["contact"]["sample_count"], 1)

    def test_no_match_reports_nearest_contact_for_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(runtime_dir=Path(temp_dir), min_confidence=0.95, sface_min_confidence=0.95)
            store.enroll_sample(
                display_name="A Bảo",
                vector=[1.0, 0.0, 0.0],
                source_note="opencv_sface:immich_person:bao:asset:1",
            )

            result = store.match_candidates(
                session_id="sess_test",
                query="người này là ai",
                candidates=[
                    {
                        "target_id": "obj_1",
                        "label": "person",
                        "attributes": {
                            "embedding_model": "sface",
                            "identity_vector": [0.7, 0.714, 0.0],
                        },
                    }
                ],
            )

        self.assertEqual(result["status"], "no_match")
        self.assertEqual(result["best_match"]["display_name"], "A Bảo")
        self.assertGreater(result["best_score"], 0.65)

    def test_known_person_info_query_matches_against_all_enrolled_contacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(runtime_dir=Path(temp_dir), min_confidence=0.8)
            store.enroll_sample(
                display_name="A Bảo",
                vector=[1.0, 0.0, 0.0],
                source_note="opencv_sface:/tmp/abao.jpg",
            )

            result = store.match_candidates(
                session_id="sess_test",
                query="có ai quen không",
                candidates=[
                    {
                        "target_id": "obj_1",
                        "track_id": "f1",
                        "anonymous_id": "P1",
                        "label": "person",
                        "attributes": {
                            "embedding_model": "sface",
                            "identity_vector": [0.99, 0.02, 0.0],
                        },
                    }
                ],
            )

        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["requested_contact_count"], 1)
        self.assertEqual(result["matches"][0]["display_name"], "A Bảo")

    def test_match_accepts_sface_v1_embedding_model_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(runtime_dir=Path(temp_dir), min_confidence=0.8)
            store.enroll_sample(
                display_name="A Bảo",
                vector=[1.0, 0.0, 0.0],
                source_note="opencv_sface:/tmp/abao.jpg",
            )

            result = store.match_candidates(
                session_id="sess_test",
                query="tìm A Bảo",
                candidates=[
                    {
                        "target_id": "obj_1",
                        "label": "person",
                        "attributes": {
                            "embedding_model": "sface_v1",
                            "identity_vector": [1.0, 0.0, 0.0],
                        },
                    }
                ],
            )

        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["matches"][0]["display_name"], "A Bảo")

    def test_sface_match_uses_sface_threshold(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(
                runtime_dir=Path(temp_dir),
                min_confidence=0.86,
                sface_min_confidence=0.45,
            )
            store.enroll_sample(
                display_name="A Bảo",
                vector=[1.0, 0.0, 0.0],
                source_note="opencv_sface:/tmp/abao.jpg",
            )

            result = store.match_candidates(
                session_id="sess_test",
                query="tìm A Bảo",
                candidates=[
                    {
                        "target_id": "obj_1",
                        "label": "person",
                        "attributes": {
                            "embedding_model": "sface",
                            "identity_vector": [0.5, 0.8660254, 0.0],
                            "face_min_side_px": 92,
                        },
                    }
                ],
            )

        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["matches"][0]["display_name"], "A Bảo")
        self.assertAlmostEqual(result["matches"][0]["confidence"], 0.5, places=3)
        self.assertEqual(result["matches"][0]["sample_provider"], "sface_v1")

    def test_low_quality_face_is_not_reported_as_identity_no_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(
                runtime_dir=Path(temp_dir),
                min_confidence=0.8,
                min_identity_face_side_px=56,
            )
            store.enroll_sample(
                display_name="A Bảo",
                vector=[1.0, 0.0, 0.0],
                source_note="opencv_sface:/tmp/abao.jpg",
            )

            result = store.match_candidates(
                session_id="sess_test",
                query="tìm A Bảo",
                candidates=[
                    {
                        "target_id": "obj_1",
                        "label": "person",
                        "attributes": {
                            "embedding_model": "sface",
                            "identity_vector": [1.0, 0.0, 0.0],
                            "face_min_side_px": 31,
                            "identity_quality": "ok",
                        },
                    }
                ],
            )

        self.assertEqual(result["status"], "low_quality_face")
        self.assertEqual(result["candidate_vector_count"], 0)
        self.assertEqual(result["low_quality_candidate_count"], 1)
        self.assertEqual(result["quality_reasons"], {"too_small_for_identity": 1})
        self.assertEqual(result["match_count"], 0)

    def test_low_light_face_reports_quality_reason_instead_of_no_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(
                runtime_dir=Path(temp_dir),
                min_confidence=0.8,
                min_identity_face_side_px=56,
            )
            store.enroll_sample(
                display_name="A Bảo",
                vector=[1.0, 0.0, 0.0],
                source_note="opencv_sface:/tmp/abao.jpg",
            )

            result = store.match_candidates(
                session_id="sess_test",
                query="người này là ai",
                candidates=[
                    {
                        "target_id": "obj_1",
                        "label": "person",
                        "attributes": {
                            "embedding_model": "sface",
                            "identity_vector": [1.0, 0.0, 0.0],
                            "face_min_side_px": 120,
                            "identity_quality": "too_dark_for_identity",
                            "identity_quality_reasons": ["too_dark_for_identity", "low_contrast_for_identity"],
                        },
                    }
                ],
            )

        self.assertEqual(result["status"], "low_quality_face")
        self.assertEqual(result["candidate_vector_count"], 0)
        self.assertEqual(result["low_quality_candidate_count"], 1)
        self.assertEqual(
            result["quality_reasons"],
            {"too_dark_for_identity": 1, "low_contrast_for_identity": 1},
        )
        self.assertIn("too dark", result["message"])

    def test_match_skips_incompatible_vector_dimensions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(runtime_dir=Path(temp_dir), min_confidence=0.8)
            store.enroll_sample(
                display_name="Trâm",
                aliases=["tram"],
                vector=[1.0, 0.0, 0.0],
                source_note="opencv_sface:/tmp/tram.jpg",
            )

            result = store.match_candidates(
                session_id="sess_test",
                query="tìm Trâm trong đám đông",
                candidates=[
                    {
                        "target_id": "obj_1",
                        "label": "person",
                        "attributes": {
                            "embedding_model": "sface",
                            "identity_vector": [1.0, 0.0],
                        },
                    }
                ],
            )

        self.assertEqual(result["status"], "no_match")
        self.assertEqual(result["match_count"], 0)

    def test_match_reports_no_samples_before_enrollment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(runtime_dir=Path(temp_dir))

            result = store.match_candidates(
                query="tìm Trâm",
                candidates=[{"target_id": "obj_1", "label": "person", "attributes": {"identity_vector": [1, 0]}}],
            )

        self.assertEqual(result["status"], "no_samples")
        self.assertEqual(result["match_count"], 0)

    def test_resolve_crop_ref_stays_inside_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir)
            crop_dir = runtime / "crops" / "sess_test"
            crop_dir.mkdir(parents=True)
            (crop_dir / "p1_latest.jpg").write_bytes(b"jpeg")
            store = ContactIdentityStore(runtime_dir=runtime)

            resolved = store.resolve_image_ref("/api/crops/sess_test/p1_latest.jpg")
            blocked = store.resolve_image_ref("/api/crops/../../ring_security/p1_latest.jpg")

        self.assertEqual(resolved, (crop_dir / "p1_latest.jpg").resolve())
        self.assertIsNone(blocked)


if __name__ == "__main__":
    unittest.main()
