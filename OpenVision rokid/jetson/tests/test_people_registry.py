import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "perception"))

from openvision_jetson.people_registry import ImmichClient, ImmichClientSettings, PeopleRegistryStore, _immich_ref_url
from openvision_jetson.contact_identity import ContactIdentityStore


class FakeImmichClient:
    def __init__(self, people):
        self.settings = ImmichClientSettings(base_url="http://immich.local:2283", api_key="test_key", api_key_source="test")
        self.people = people
        self.updated_names = []
        self.uploads = []

    def list_people(self):
        return self.people

    def update_person_name(self, immich_person_id, display_name):
        self.updated_names.append((immich_person_id, display_name))
        return {"status": "ok"}

    def upload_asset(self, image_bytes, *, filename, content_type="image/jpeg", taken_at=None, device_id="openvision_rokid"):
        self.uploads.append(
            {
                "image_bytes": image_bytes,
                "filename": filename,
                "content_type": content_type,
                "taken_at": taken_at,
                "device_id": device_id,
            }
        )
        return {
            "status": "created",
            "asset_id": "asset_memory_1",
            "device_asset_id": f"{device_id}:asset_memory_1",
            "filename": filename,
            "checksum_sha1": "abc123",
            "uploaded_at": "2026-04-30T00:00:00.000+00:00",
        }


class PeopleRegistryStoreTest(unittest.TestCase):
    def test_sync_from_immich_creates_registry_profiles_without_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PeopleRegistryStore(runtime_dir=Path(temp_dir), immich_settings=ImmichClientSettings())
            fake = FakeImmichClient(
                [
                    {
                        "immich_person_id": "immich_person_1",
                        "display_name": "Tram",
                        "thumbnail_ref": "http://immich.local:2283/api/people/immich_person_1/thumbnail",
                        "asset_count": 12,
                    }
                ]
            )

            sync = store.sync_from_immich(client=fake)
            people = store.list_people()
            raw = store.db_path.read_text(encoding="utf-8")

        self.assertEqual(sync["status"], "ok")
        self.assertEqual(sync["created"], 1)
        self.assertEqual(people[0]["display_name"], "Tram")
        self.assertEqual(people[0]["immich_asset_count"], 12)
        self.assertIn("thumbnail", people[0]["thumbnail_ref"])
        self.assertNotIn("image_bytes", raw)
        self.assertNotIn("base64", raw)

    def test_update_profile_can_sync_local_name_back_to_immich(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PeopleRegistryStore(runtime_dir=Path(temp_dir), immich_settings=ImmichClientSettings())
            fake = FakeImmichClient([{"immich_person_id": "immich_person_1", "display_name": "Unknown"}])
            store.sync_from_immich(client=fake)
            person_id = store.list_people()[0]["person_id"]

            updated = store.update_person_profile(
                person_id=person_id,
                display_name="Tram",
                aliases=["tram"],
                phone="0900000000",
                address="local address",
                age="32",
                where_lives="Da Nang",
                relationship="friend from cafe",
                first_met="first met at Han river",
                links={"facebook": "https://facebook.example/tram"},
                facts={"favorite": "coffee"},
                sync_name_to_immich=True,
                immich_client=fake,
            )

        self.assertEqual(updated["display_name"], "Tram")
        self.assertEqual(updated["name_source"], "openvision")
        self.assertEqual(updated["aliases"], ["tram"])
        self.assertEqual(updated["age"], "32")
        self.assertEqual(updated["where_lives"], "Da Nang")
        self.assertEqual(updated["relationship"], "friend from cafe")
        self.assertEqual(updated["first_met"], "first met at Han river")
        self.assertEqual(updated["facts"]["favorite"], "coffee")
        self.assertEqual(fake.updated_names, [("immich_person_1", "Tram")])
        self.assertEqual(updated["sync"]["status"], "name_synced_to_immich")

    def test_profile_for_identity_match_returns_local_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PeopleRegistryStore(runtime_dir=Path(temp_dir), immich_settings=ImmichClientSettings())
            fake = FakeImmichClient([{"immich_person_id": "immich_person_1", "display_name": "Unknown"}])
            store.sync_from_immich(client=fake)
            person_id = store.list_people()[0]["person_id"]
            store.update_person_profile(
                person_id=person_id,
                display_name="A Bảo",
                aliases=["Bao"],
                phone="0900000000",
                where_lives="Quận 1",
                relationship="bạn cà phê",
                first_met="Đà Nẵng",
                facts={"work": "camera"},
            )

            profile = store.profile_for_identity_match(
                identity_match={"display_name": "Bao", "alias": "A Bảo"},
                session_id="sess_test",
            )

        self.assertEqual(profile["status"], "found")
        self.assertIn(profile["match_method"], {"exact_name_or_alias", "token_overlap"})
        self.assertEqual(profile["person"]["display_name"], "A Bảo")
        self.assertEqual(profile["person"]["relationship"], "bạn cà phê")
        self.assertEqual(profile["person"]["facts"]["work"], "camera")

    def test_sync_reports_name_conflict_when_immich_changes_after_local_edit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PeopleRegistryStore(runtime_dir=Path(temp_dir), immich_settings=ImmichClientSettings())
            first = FakeImmichClient([{"immich_person_id": "immich_person_1", "display_name": "Unknown"}])
            store.sync_from_immich(client=first)
            person_id = store.list_people()[0]["person_id"]
            store.update_person_profile(person_id=person_id, display_name="Tram")
            second = FakeImmichClient([{"immich_person_id": "immich_person_1", "display_name": "Someone Else"}])

            sync = store.sync_from_immich(client=second)
            person = store.list_people()[0]

        self.assertEqual(sync["conflicts"], 1)
        self.assertEqual(person["display_name"], "Tram")
        self.assertEqual(person["sync"]["status"], "name_conflict")
        self.assertEqual(person["sync"]["conflict"]["immich_name"], "Someone Else")

    def test_unconfigured_immich_sync_is_skipped_without_network(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PeopleRegistryStore(runtime_dir=Path(temp_dir), immich_settings=ImmichClientSettings())

            sync = store.sync_from_immich()
            status = store.status()

        self.assertEqual(sync["status"], "skipped")
        self.assertEqual(sync["reason"], "immich_unconfigured")
        self.assertFalse(status["immich"]["configured"])

    def test_corrupt_people_db_is_quarantined_before_rebuild(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PeopleRegistryStore(runtime_dir=Path(temp_dir), immich_settings=ImmichClientSettings())
            store.db_path.parent.mkdir(parents=True, exist_ok=True)
            store.db_path.write_text("{bad json", encoding="utf-8")

            status = store.status()
            store.sync_from_immich(client=FakeImmichClient([]))
            quarantined = list(store.db_path.parent.glob("people_registry.json.corrupt-*"))
            quarantined_text = quarantined[0].read_text(encoding="utf-8") if quarantined else ""

        self.assertEqual(status["status"], "ready_empty")
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined_text, "{bad json")

    def test_corrupt_contact_identity_db_is_quarantined_before_rebuild(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactIdentityStore(runtime_dir=Path(temp_dir))
            store.db_path.parent.mkdir(parents=True, exist_ok=True)
            store.db_path.write_text("[bad", encoding="utf-8")

            status = store.status()
            store.create_contact(display_name="Tram")
            quarantined = list(store.db_path.parent.glob("contacts.json.corrupt-*"))
            quarantined_text = quarantined[0].read_text(encoding="utf-8") if quarantined else ""

        self.assertEqual(status["status"], "ready_empty")
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined_text, "[bad")

    def test_remember_capture_uploads_to_immich_and_keeps_only_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PeopleRegistryStore(
                runtime_dir=Path(temp_dir),
                immich_settings=ImmichClientSettings(base_url="http://immich.local:2283", api_key="test_key"),
            )
            fake = FakeImmichClient([])

            result = store.remember_capture(
                image_bytes=b"jpeg-bytes",
                content_type="image/jpeg",
                session_id="sess_memory",
                display_name="Tram",
                aliases=["tram"],
                notes="met at cafe",
                client=fake,
            )
            status = store.status()
            raw = store.db_path.read_text(encoding="utf-8")

        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(result["capture"]["immich_asset_id"], "asset_memory_1")
        self.assertEqual(result["capture"]["display_name"], "Tram")
        self.assertEqual(status["remembered_capture_count"], 1)
        self.assertEqual(status["pending_face_sync_count"], 1)
        self.assertEqual(fake.uploads[0]["image_bytes"], b"jpeg-bytes")
        self.assertNotIn("jpeg-bytes", raw)
        self.assertNotIn("image_bytes", raw)

    def test_immich_ref_url_rejects_external_origin(self):
        base = "http://immich.local:2283"

        self.assertEqual(
            _immich_ref_url(base, "http://immich.local:2283/api/people/person_1/thumbnail"),
            "http://immich.local:2283/api/people/person_1/thumbnail",
        )
        with self.assertRaises(RuntimeError):
            _immich_ref_url(base, "http://example.invalid/api/people/person_1/thumbnail")

    def test_immich_client_searches_person_assets_for_multi_vector_enrollment(self):
        class RecordingImmichClient(ImmichClient):
            def __init__(self):
                super().__init__(ImmichClientSettings(base_url="http://immich.local:2283", api_key="test_key"))
                self.calls = []

            def _request_json(self, method, path, *, body=None, query=None):
                self.calls.append({"method": method, "path": path, "body": body, "query": query})
                return {"assets": {"items": [{"id": "asset_1"}, {"id": "asset_2"}]}}

        client = RecordingImmichClient()

        assets = client.search_person_assets("person_1", limit=2)

        self.assertEqual([asset["id"] for asset in assets], ["asset_1", "asset_2"])
        self.assertEqual(client.calls[0]["method"], "POST")
        self.assertEqual(client.calls[0]["path"], "/search/metadata")
        self.assertEqual(client.calls[0]["body"]["personIds"], ["person_1"])
        self.assertEqual(client.calls[0]["body"]["size"], 2)


if __name__ == "__main__":
    unittest.main()
