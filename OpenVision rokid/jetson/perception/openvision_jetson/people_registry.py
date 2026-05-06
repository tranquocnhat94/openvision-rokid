"""People registry and Immich sync support for OpenVision skills.

The registry stores user-managed metadata about known people while keeping
photos and thumbnails owned by Immich. It is intentionally dependency-free so
Jetson can expose sync/status endpoints without adding another service.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from .contracts import new_id, utc_now
from .event_store import InMemoryEventStore


SCHEMA_VERSION = "openvision.people_registry.v1"
STATUS_SCHEMA_VERSION = "openvision.people_registry_status.v1"
IMMICH_PROVIDER = "immich"
DEFAULT_SYNC_TIMEOUT_S = 8.0


@dataclass(frozen=True, slots=True)
class ImmichClientSettings:
    base_url: str = ""
    api_key: str = ""
    api_key_source: str = "missing"
    timeout_s: float = DEFAULT_SYNC_TIMEOUT_S

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def public_status(self) -> dict[str, Any]:
        return {
            "provider": IMMICH_PROVIDER,
            "configured": self.configured,
            "base_url": self.base_url or None,
            "api_key_present": bool(self.api_key),
            "api_key_source": self.api_key_source,
            "timeout_s": self.timeout_s,
        }


class ImmichClient:
    def __init__(self, settings: ImmichClientSettings | None = None) -> None:
        self.settings = settings or load_immich_client_settings()

    def list_people(self) -> list[dict[str, Any]]:
        self._require_configured()
        payload = self._request_json("GET", "/people", query={"withHidden": "true", "size": "1000"})
        people = _extract_people_payload(payload)
        return [_normalize_immich_person(person, self.settings.base_url) for person in people]

    def update_person_name(self, immich_person_id: str, display_name: str) -> dict[str, Any]:
        self._require_configured()
        person_id = _clean_text(immich_person_id)
        name = _clean_text(display_name)
        if not person_id:
            raise ValueError("immich_person_id is required")
        if not name:
            raise ValueError("display_name is required")
        body = {"people": [{"id": person_id, "name": name}]}
        try:
            return _ensure_dict(self._request_json("PUT", "/people", body=body))
        except RuntimeError as first_exc:
            single_body = {"name": name}
            try:
                return _ensure_dict(self._request_json("PUT", f"/people/{parse.quote(person_id)}", body=single_body))
            except RuntimeError as second_exc:
                raise RuntimeError(f"Immich name sync failed: {second_exc}") from first_exc

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        self._require_configured()
        clean_id = _clean_text(asset_id)
        if not clean_id:
            raise ValueError("asset_id is required")
        return _ensure_dict(self._request_json("GET", f"/assets/{parse.quote(clean_id)}"))

    def search_person_assets(self, immich_person_id: str, *, limit: int = 12) -> list[dict[str, Any]]:
        self._require_configured()
        person_id = _clean_text(immich_person_id)
        if not person_id:
            raise ValueError("immich_person_id is required")
        size = max(1, min(int(limit or 1), 100))
        payload = self._request_json(
            "POST",
            "/search/metadata",
            body={
                "personIds": [person_id],
                "size": size,
                "withArchived": False,
            },
        )
        return _extract_asset_items_payload(payload)[:size]

    def fetch_asset_thumbnail(self, asset_id: str, *, size: str = "preview") -> tuple[bytes, str]:
        self._require_configured()
        clean_id = _clean_text(asset_id)
        if not clean_id:
            raise ValueError("asset_id is required")
        clean_size = _clean_text(size).lower() or "preview"
        if clean_size not in {"preview", "thumbnail"}:
            clean_size = "preview"
        ref = _immich_api_url(
            self.settings.base_url,
            f"/assets/{parse.quote(clean_id)}/thumbnail",
            query={"size": clean_size},
        )
        return self.fetch_bytes(ref)

    def fetch_bytes(self, ref: str) -> tuple[bytes, str]:
        self._require_configured()
        url = _immich_ref_url(self.settings.base_url, ref)
        req = request.Request(url=url, method="GET", headers=self._headers(False))
        try:
            with request.urlopen(req, timeout=max(0.5, self.settings.timeout_s)) as response:  # noqa: S310 - user-configured LAN endpoint.
                content_type = response.headers.get("content-type") or "application/octet-stream"
                return response.read(), content_type
        except error.HTTPError as exc:
            message = _read_http_error_message(exc)
            raise RuntimeError(f"Immich HTTP {exc.code}: {message}") from exc
        except error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"Immich unreachable: {reason}") from exc

    def upload_asset(
        self,
        image_bytes: bytes,
        *,
        filename: str,
        content_type: str = "image/jpeg",
        taken_at: str | None = None,
        device_id: str = "openvision_rokid",
    ) -> dict[str, Any]:
        self._require_configured()
        if not image_bytes:
            raise ValueError("image_bytes is required")
        clean_filename = _safe_filename(filename) or "openvision_memory.jpg"
        checksum = hashlib.sha1(image_bytes).hexdigest()
        timestamp = _clean_text(taken_at) or utc_now()
        device_asset_id = f"{device_id}:{checksum}:{clean_filename}"
        fields = {
            "deviceAssetId": device_asset_id,
            "deviceId": device_id,
            "fileCreatedAt": timestamp,
            "fileModifiedAt": timestamp,
            "isFavorite": "false",
        }
        body, boundary = _multipart_form_data(
            fields=fields,
            file_field="assetData",
            filename=clean_filename,
            content_type=content_type or "application/octet-stream",
            file_bytes=image_bytes,
        )
        headers = self._headers(False)
        headers["content-type"] = f"multipart/form-data; boundary={boundary}"
        req = request.Request(
            url=_immich_api_url(self.settings.base_url, "/assets"),
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with request.urlopen(req, timeout=max(0.5, self.settings.timeout_s)) as response:  # noqa: S310 - user-configured LAN endpoint.
                raw = response.read()
        except error.HTTPError as exc:
            message = _read_http_error_message(exc)
            raise RuntimeError(f"Immich HTTP {exc.code}: {message}") from exc
        except error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"Immich unreachable: {reason}") from exc
        payload: dict[str, Any] = {}
        if raw:
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError("Immich returned non-JSON upload response") from exc
            payload = _ensure_dict(decoded)
        return {
            "status": _clean_text(payload.get("status")) or "ok",
            "asset_id": payload.get("id") or payload.get("assetId"),
            "device_asset_id": device_asset_id,
            "filename": clean_filename,
            "checksum_sha1": checksum,
            "uploaded_at": utc_now(),
            "raw": payload,
        }

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        url = _immich_api_url(self.settings.base_url, path, query=query)
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = request.Request(url=url, data=data, method=method.upper(), headers=self._headers(body is not None))
        try:
            with request.urlopen(req, timeout=max(0.5, self.settings.timeout_s)) as response:  # noqa: S310 - user-configured LAN endpoint.
                raw = response.read()
        except error.HTTPError as exc:
            message = _read_http_error_message(exc)
            raise RuntimeError(f"Immich HTTP {exc.code}: {message}") from exc
        except error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"Immich unreachable: {reason}") from exc
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Immich returned non-JSON response") from exc

    def _headers(self, has_body: bool) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "x-api-key": self.settings.api_key,
        }
        if has_body:
            headers["content-type"] = "application/json"
        return headers

    def _require_configured(self) -> None:
        if not self.settings.configured:
            raise RuntimeError("Immich connector is not configured; set OPENVISION_IMMICH_BASE_URL and API key env/file.")


class PeopleRegistryStore:
    def __init__(
        self,
        *,
        runtime_dir: Path | None = None,
        db_path: Path | None = None,
        events: InMemoryEventStore | None = None,
        immich_settings: ImmichClientSettings | None = None,
    ) -> None:
        self.runtime_dir = (runtime_dir or _default_runtime_dir()).expanduser()
        self.db_path = (db_path or _configured_people_db_path(self.runtime_dir)).expanduser()
        self.events = events
        self.immich_settings = immich_settings or load_immich_client_settings()

    def status(self) -> dict[str, Any]:
        data = self._read()
        people = _people(data)
        captures = _remembered_captures(data)
        linked_count = sum(1 for person in people if person.get("immich_person_id"))
        named_count = sum(1 for person in people if _clean_text(person.get("display_name")))
        pending_face_sync_count = sum(1 for item in captures if item.get("status") == "uploaded" and item.get("pending_people_sync"))
        return {
            "schema_version": STATUS_SCHEMA_VERSION,
            "status": "ready" if people else "ready_empty",
            "db_exists": self.db_path.is_file(),
            "people_count": len(people),
            "linked_immich_count": linked_count,
            "named_count": named_count,
            "remembered_capture_count": len(captures),
            "pending_face_sync_count": pending_face_sync_count,
            "last_remembered_capture": _public_remembered_capture(captures[-1]) if captures else None,
            "provider": "openvision_people_registry",
            "image_storage": "immich_refs_only",
            "immich": self.immich_settings.public_status(),
            "last_sync": data.get("last_sync") if isinstance(data.get("last_sync"), dict) else None,
            "message": "People registry is ready." if people else "People registry is ready but has no synced people yet.",
        }

    def list_people(self) -> list[dict[str, Any]]:
        people = [_public_person(person) for person in _people(self._read())]
        return sorted(people, key=lambda item: (_clean_text(item.get("display_name")).lower(), str(item.get("person_id") or "")))

    def get_person(self, person_id: str) -> dict[str, Any] | None:
        clean_id = _clean_text(person_id)
        person = _find_person(self._read(), clean_id)
        return _public_person(person) if person is not None else None

    def update_person_profile(
        self,
        *,
        person_id: str,
        display_name: str | None = None,
        aliases: list[str] | None = None,
        phone: str | None = None,
        address: str | None = None,
        age: str | None = None,
        where_lives: str | None = None,
        relationship: str | None = None,
        first_met: str | None = None,
        links: dict[str, Any] | None = None,
        facts: dict[str, Any] | None = None,
        notes: str | None = None,
        sync_name_to_immich: bool = False,
        immich_client: ImmichClient | None = None,
    ) -> dict[str, Any]:
        clean_id = _clean_text(person_id)
        if not clean_id:
            raise ValueError("person_id is required")
        data = self._read()
        person = _find_person(data, clean_id)
        if person is None:
            raise ValueError("person_id was not found")
        before_name = _clean_text(person.get("display_name"))
        if display_name is not None:
            clean_name = _clean_text(display_name)
            person["display_name"] = clean_name
            if clean_name and clean_name != before_name:
                person["name_source"] = "openvision"
        if aliases is not None:
            person["aliases"] = _merge_aliases([], aliases)
        if phone is not None:
            person["phone"] = _clean_text(phone)
        if address is not None:
            person["address"] = _clean_text(address)
        if age is not None:
            person["age"] = _clean_text(age)
        if where_lives is not None:
            person["where_lives"] = _clean_text(where_lives)
        if relationship is not None:
            person["relationship"] = _clean_text(relationship)
        if first_met is not None:
            person["first_met"] = _clean_text(first_met)
        if links is not None:
            person["links"] = _clean_links(links)
        if facts is not None:
            person["facts"] = _clean_facts(facts)
        if notes is not None:
            person["notes"] = _clean_text(notes)
        person["updated_at"] = utc_now()
        self._write(data)
        self._event("profile_updated", {"person_id": clean_id, "immich_person_id": person.get("immich_person_id")})
        if sync_name_to_immich:
            self.sync_person_name_to_immich(clean_id, client=immich_client)
            person = _find_person(self._read(), clean_id) or person
        return _public_person(person)

    def profile_for_identity_match(
        self,
        *,
        identity_match: dict[str, Any] | None = None,
        display_name: str | None = None,
        aliases: list[str] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        match = identity_match if isinstance(identity_match, dict) else {}
        names = [
            display_name,
            match.get("display_name"),
            match.get("alias"),
            *(aliases or []),
        ]
        clean_names = [_clean_text(str(name)) for name in names if _clean_text(str(name))]
        data = self._read()
        person, method = _find_person_by_names(data, clean_names)
        if person is None:
            return {
                "status": "not_found",
                "query_names": clean_names,
                "message": "No People Registry profile matched the identity contact name or alias.",
            }
        return {
            "status": "found",
            "match_method": method,
            "query_names": clean_names,
            "person": _public_person(person),
        }

    def sync_from_immich(self, *, client: ImmichClient | None = None, push_names: bool = False) -> dict[str, Any]:
        client = client or ImmichClient(self.immich_settings)
        data = self._read()
        if not client.settings.configured:
            result = {
                "status": "skipped",
                "reason": "immich_unconfigured",
                "message": "Immich connector is not configured.",
                "synced_at": utc_now(),
                "remote_count": 0,
                "created": 0,
                "updated": 0,
                "conflicts": 0,
                "pushed_names": 0,
            }
            data["last_sync"] = result
            self._write(data)
            self._event("immich_sync_skipped", result)
            return result

        try:
            remote_people = client.list_people()
        except RuntimeError as exc:
            result = {
                "status": "error",
                "reason": "immich_unreachable",
                "message": str(exc),
                "synced_at": utc_now(),
                "remote_count": 0,
                "created": 0,
                "updated": 0,
                "conflicts": 0,
                "pushed_names": 0,
            }
            data["last_sync"] = result
            self._write(data)
            self._event("immich_sync_error", result)
            return result

        people = _people(data)
        created = 0
        updated = 0
        conflicts = 0
        pushed_names = 0
        now = utc_now()
        for remote in remote_people:
            immich_id = _clean_text(remote.get("immich_person_id"))
            if not immich_id:
                continue
            person = _find_person_by_immich_id(data, immich_id)
            if person is None:
                person = _new_person_for_immich(remote, now)
                people.append(person)
                created += 1
            else:
                updated += 1
            conflict = _apply_immich_person(person, remote, now)
            if conflict:
                conflicts += 1
            if push_names and _should_push_name(person):
                client.update_person_name(immich_id, str(person.get("display_name") or ""))
                person["last_immich_name"] = person.get("display_name")
                person["sync"] = {"status": "name_synced_to_immich", "last_sync_at": utc_now()}
                pushed_names += 1
        data["people"] = people
        result = {
            "status": "ok",
            "synced_at": utc_now(),
            "remote_count": len(remote_people),
            "created": created,
            "updated": updated,
            "conflicts": conflicts,
            "pushed_names": pushed_names,
        }
        data["last_sync"] = result
        self._write(data)
        self._event("immich_sync_completed", result)
        return result

    def sync_person_name_to_immich(self, person_id: str, *, client: ImmichClient | None = None) -> dict[str, Any]:
        clean_id = _clean_text(person_id)
        data = self._read()
        person = _find_person(data, clean_id)
        if person is None:
            raise ValueError("person_id was not found")
        immich_id = _clean_text(person.get("immich_person_id"))
        name = _clean_text(person.get("display_name"))
        if not immich_id:
            raise ValueError("person is not linked to an Immich person")
        if not name:
            raise ValueError("display_name is required before syncing to Immich")
        client = client or ImmichClient(self.immich_settings)
        client.update_person_name(immich_id, name)
        person["last_immich_name"] = name
        person["name_source"] = "openvision"
        person["sync"] = {"status": "name_synced_to_immich", "last_sync_at": utc_now()}
        person["updated_at"] = utc_now()
        self._write(data)
        result = {"status": "ok", "person_id": clean_id, "immich_person_id": immich_id, "display_name": name}
        self._event("immich_name_synced", result)
        return result

    def remember_capture(
        self,
        *,
        image_bytes: bytes,
        content_type: str = "image/jpeg",
        session_id: str | None = None,
        display_name: str | None = None,
        aliases: list[str] | None = None,
        notes: str | None = None,
        source: str | None = None,
        client: ImmichClient | None = None,
    ) -> dict[str, Any]:
        if not image_bytes:
            raise ValueError("image_bytes is required")
        capture_id = new_id("capture")
        created_at = utc_now()
        filename = f"{capture_id}.{_image_extension(content_type)}"
        record: dict[str, Any] = {
            "capture_id": capture_id,
            "session_id": _clean_text(session_id),
            "display_name": _clean_text(display_name),
            "aliases": _merge_aliases([], aliases),
            "notes": _clean_text(notes),
            "source": _clean_text(source) or "openvision_snapshot",
            "content_type": content_type or "image/jpeg",
            "image_storage": "immich_only",
            "created_at": created_at,
            "updated_at": created_at,
            "pending_people_sync": True,
        }
        upload: dict[str, Any] | None = None
        if not (client or ImmichClient(self.immich_settings)).settings.configured:
            record.update(
                {
                    "status": "immich_unconfigured",
                    "message": "Immich connector is not configured; capture image was not retained locally.",
                }
            )
        else:
            client = client or ImmichClient(self.immich_settings)
            try:
                upload = client.upload_asset(
                    image_bytes,
                    filename=filename,
                    content_type=content_type,
                    taken_at=created_at,
                    device_id="openvision_rokid",
                )
                record.update(
                    {
                        "status": "uploaded",
                        "immich_asset_id": upload.get("asset_id"),
                        "device_asset_id": upload.get("device_asset_id"),
                        "filename": upload.get("filename"),
                        "checksum_sha1": upload.get("checksum_sha1"),
                        "uploaded_at": upload.get("uploaded_at"),
                        "message": "Capture uploaded to Immich; waiting for Immich face detection and next people sync.",
                    }
                )
            except RuntimeError as exc:
                record.update(
                    {
                        "status": "upload_failed",
                        "message": str(exc),
                    }
                )
        data = self._read()
        captures = _remembered_captures(data)
        captures.append(record)
        del captures[:-200]
        data["remembered_captures"] = captures
        self._write(data)
        self._event(
            "remembered_capture_recorded",
            {
                "capture_id": capture_id,
                "status": record.get("status"),
                "immich_asset_id": record.get("immich_asset_id"),
                "display_name": record.get("display_name"),
                "image_storage": record.get("image_storage"),
            },
        )
        return {
            "status": record.get("status"),
            "capture": _public_remembered_capture(record),
            "upload": upload,
        }

    def _read(self) -> dict[str, Any]:
        if not self.db_path.is_file():
            return {"schema_version": SCHEMA_VERSION, "people": [], "created_at": utc_now(), "updated_at": utc_now()}
        try:
            payload = json.loads(self.db_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            quarantine_path = self._quarantine_corrupt_db(reason=exc.__class__.__name__)
            return {
                "schema_version": SCHEMA_VERSION,
                "people": [],
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "read_error": True,
                "quarantined_path": str(quarantine_path) if quarantine_path else None,
            }
        if not isinstance(payload, dict):
            quarantine_path = self._quarantine_corrupt_db(reason="invalid_root")
            return {
                "schema_version": SCHEMA_VERSION,
                "people": [],
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "read_error": True,
                "quarantined_path": str(quarantine_path) if quarantine_path else None,
            }
        payload.setdefault("schema_version", SCHEMA_VERSION)
        payload.setdefault("people", [])
        return payload

    def _quarantine_corrupt_db(self, *, reason: str) -> Path | None:
        if not self.db_path.exists():
            return None
        stamp = utc_now().replace(":", "").replace("+", "Z")
        quarantine_path = self.db_path.with_name(f"{self.db_path.name}.corrupt-{stamp}")
        try:
            self.db_path.replace(quarantine_path)
        except OSError:
            return None
        self._event(
            "db_quarantined",
            {
                "reason": reason,
                "path": str(self.db_path),
                "quarantine_path": str(quarantine_path),
            },
        )
        return quarantine_path

    def _write(self, data: dict[str, Any]) -> None:
        data["schema_version"] = SCHEMA_VERSION
        data["updated_at"] = utc_now()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.db_path.with_suffix(self.db_path.suffix + ".tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self.db_path)

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.events:
            self.events.add("people_registry", event_type, payload)


def load_immich_client_settings() -> ImmichClientSettings:
    base_url = _clean_url(os.getenv("OPENVISION_IMMICH_BASE_URL") or "")
    timeout_s = _env_float("OPENVISION_IMMICH_SYNC_TIMEOUT_S", DEFAULT_SYNC_TIMEOUT_S)
    api_key_file = _clean_text(os.getenv("OPENVISION_IMMICH_API_KEY_FILE"))
    api_key = ""
    api_key_source = "missing"
    if api_key_file:
        try:
            api_key = Path(api_key_file).expanduser().read_text(encoding="utf-8").strip()
            api_key_source = "file" if api_key else "missing"
        except OSError:
            api_key = ""
            api_key_source = "file_missing"
    if not api_key:
        api_key = _clean_text(os.getenv("OPENVISION_IMMICH_API_KEY"))
        if api_key:
            api_key_source = "env"
    return ImmichClientSettings(base_url=base_url, api_key=api_key, api_key_source=api_key_source, timeout_s=timeout_s)


def _default_runtime_dir() -> Path:
    return Path(os.getenv("OPENVISION_RUNTIME_DIR") or Path(__file__).resolve().parents[3] / "runtime")


def _configured_people_db_path(runtime_dir: Path) -> Path:
    value = _clean_text(os.getenv("OPENVISION_PEOPLE_REGISTRY_DB_PATH"))
    if value:
        return Path(value)
    return runtime_dir / "people" / "people_registry.json"


def _people(data: dict[str, Any]) -> list[dict[str, Any]]:
    people = data.get("people")
    if not isinstance(people, list):
        return []
    return [person for person in people if isinstance(person, dict)]


def _remembered_captures(data: dict[str, Any]) -> list[dict[str, Any]]:
    captures = data.get("remembered_captures")
    if not isinstance(captures, list):
        return []
    return [item for item in captures if isinstance(item, dict)]


def _find_person(data: dict[str, Any], person_id: str) -> dict[str, Any] | None:
    for person in _people(data):
        if str(person.get("person_id") or "") == person_id:
            return person
    return None


def _find_person_by_immich_id(data: dict[str, Any], immich_person_id: str) -> dict[str, Any] | None:
    for person in _people(data):
        if str(person.get("immich_person_id") or "") == immich_person_id:
            return person
    return None


def _new_person_for_immich(remote: dict[str, Any], now: str) -> dict[str, Any]:
    person_id = _person_id_for_immich(str(remote.get("immich_person_id") or ""))
    return {
        "person_id": person_id,
        "immich_person_id": remote.get("immich_person_id"),
        "display_name": "",
        "aliases": [],
        "phone": "",
        "address": "",
        "age": "",
        "where_lives": "",
        "relationship": "",
        "first_met": "",
        "links": {},
        "facts": {},
        "notes": "",
        "thumbnail_ref": remote.get("thumbnail_ref"),
        "immich_thumbnail_ref": remote.get("thumbnail_ref"),
        "immich_asset_count": remote.get("asset_count") or 0,
        "name_source": "none",
        "last_immich_name": "",
        "sync": {"status": "linked", "last_sync_at": now},
        "created_at": now,
        "updated_at": now,
    }


def _apply_immich_person(person: dict[str, Any], remote: dict[str, Any], now: str) -> bool:
    remote_name = _clean_text(remote.get("display_name"))
    local_name = _clean_text(person.get("display_name"))
    name_source = _clean_text(person.get("name_source")) or "none"
    previous_remote_name = _clean_text(person.get("last_immich_name"))
    conflict = False
    if remote_name:
        if not local_name or name_source in {"none", "immich"}:
            person["display_name"] = remote_name
            person["name_source"] = "immich"
        elif name_source == "openvision" and remote_name != local_name and remote_name != previous_remote_name:
            person["sync"] = {
                "status": "name_conflict",
                "last_sync_at": now,
                "conflict": {"local_name": local_name, "immich_name": remote_name},
            }
            conflict = True
    person["last_immich_name"] = remote_name
    person["thumbnail_ref"] = remote.get("thumbnail_ref") or person.get("thumbnail_ref")
    person["immich_thumbnail_ref"] = remote.get("thumbnail_ref") or person.get("immich_thumbnail_ref")
    person["immich_asset_count"] = int(remote.get("asset_count") or 0)
    person["immich_visibility"] = {
        "hidden": bool(remote.get("is_hidden")),
        "favorite": bool(remote.get("is_favorite")),
    }
    if not conflict:
        person["sync"] = {"status": "synced", "last_sync_at": now}
    person["updated_at"] = now
    return conflict


def _should_push_name(person: dict[str, Any]) -> bool:
    name = _clean_text(person.get("display_name"))
    if not name or not person.get("immich_person_id"):
        return False
    return _clean_text(person.get("name_source")) == "openvision" and name != _clean_text(person.get("last_immich_name"))


def _public_person(person: dict[str, Any]) -> dict[str, Any]:
    return {
        "person_id": person.get("person_id"),
        "immich_person_id": person.get("immich_person_id"),
        "display_name": person.get("display_name") or "",
        "aliases": person.get("aliases") if isinstance(person.get("aliases"), list) else [],
        "phone": person.get("phone") or "",
        "address": person.get("address") or "",
        "age": person.get("age") or "",
        "where_lives": person.get("where_lives") or "",
        "relationship": person.get("relationship") or "",
        "first_met": person.get("first_met") or "",
        "links": person.get("links") if isinstance(person.get("links"), dict) else {},
        "facts": person.get("facts") if isinstance(person.get("facts"), dict) else {},
        "notes": person.get("notes") or "",
        "thumbnail_ref": person.get("thumbnail_ref"),
        "immich_thumbnail_ref": person.get("immich_thumbnail_ref"),
        "immich_asset_count": int(person.get("immich_asset_count") or 0),
        "name_source": person.get("name_source") or "none",
        "last_immich_name": person.get("last_immich_name") or "",
        "sync": person.get("sync") if isinstance(person.get("sync"), dict) else {},
        "created_at": person.get("created_at"),
        "updated_at": person.get("updated_at"),
    }


def _public_remembered_capture(capture: dict[str, Any]) -> dict[str, Any]:
    return {
        "capture_id": capture.get("capture_id"),
        "session_id": capture.get("session_id"),
        "display_name": capture.get("display_name") or "",
        "aliases": capture.get("aliases") if isinstance(capture.get("aliases"), list) else [],
        "notes": capture.get("notes") or "",
        "status": capture.get("status"),
        "message": capture.get("message"),
        "immich_asset_id": capture.get("immich_asset_id"),
        "device_asset_id": capture.get("device_asset_id"),
        "filename": capture.get("filename"),
        "image_storage": capture.get("image_storage") or "immich_only",
        "pending_people_sync": bool(capture.get("pending_people_sync")),
        "created_at": capture.get("created_at"),
        "uploaded_at": capture.get("uploaded_at"),
        "updated_at": capture.get("updated_at"),
    }


def _extract_people_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("people", "items", "data", "results"):
            items = payload.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def _extract_asset_items_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    assets = payload.get("assets")
    if isinstance(assets, dict):
        items = assets.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    for key in ("items", "data", "results"):
        items = payload.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _normalize_immich_person(person: dict[str, Any], base_url: str) -> dict[str, Any]:
    person_id = _clean_text(person.get("id") or person.get("personId") or person.get("person_id"))
    thumbnail_ref = _clean_text(person.get("thumbnailRef"))
    if person_id:
        # Immich `thumbnailPath` is often an internal container filesystem path.
        # OpenVision should always dereference thumbnails through Immich's API.
        thumbnail_ref = f"{_clean_url(base_url)}/api/people/{parse.quote(person_id)}/thumbnail"
    asset_count = person.get("assetCount") or person.get("asset_count") or person.get("faceCount") or 0
    return {
        "immich_person_id": person_id,
        "display_name": _clean_text(person.get("name") or person.get("displayName") or person.get("display_name")),
        "thumbnail_ref": thumbnail_ref or None,
        "asset_count": _safe_int(asset_count),
        "is_hidden": bool(person.get("isHidden") or person.get("is_hidden")),
        "is_favorite": bool(person.get("isFavorite") or person.get("is_favorite")),
    }


def _immich_api_url(base_url: str, path: str, *, query: dict[str, str] | None = None) -> str:
    clean_base = _clean_url(base_url)
    if not clean_base:
        raise RuntimeError("Immich base URL is empty")
    clean_path = "/" + path.lstrip("/")
    base_has_api = parse.urlparse(clean_base).path.rstrip("/").endswith("/api")
    url = f"{clean_base}{clean_path if base_has_api else '/api' + clean_path}"
    if query:
        url = f"{url}?{parse.urlencode(query)}"
    return url


def _immich_ref_url(base_url: str, ref: str) -> str:
    clean_ref = _clean_text(ref)
    if not clean_ref:
        raise RuntimeError("Immich ref is empty")
    clean_base = _clean_url(base_url)
    parsed = parse.urlparse(clean_ref)
    if parsed.scheme in {"http", "https"}:
        if not _same_origin(clean_base, clean_ref):
            raise RuntimeError("Immich ref must stay on the configured Immich origin")
        return clean_ref
    if clean_ref.startswith("/api/"):
        return f"{clean_base}{clean_ref}"
    if clean_ref.startswith("api/"):
        return f"{clean_base}/{clean_ref}"
    return f"{clean_base}/api/{clean_ref.lstrip('/')}"


def _same_origin(base_url: str, candidate_url: str) -> bool:
    base = parse.urlparse(_clean_url(base_url))
    candidate = parse.urlparse(candidate_url)
    return (
        candidate.scheme in {"http", "https"}
        and candidate.scheme == base.scheme
        and candidate.hostname == base.hostname
        and (candidate.port or _default_port(candidate.scheme)) == (base.port or _default_port(base.scheme))
    )


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _clean_url(value: str) -> str:
    return _clean_text(value).rstrip("/")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_links(values: dict[str, Any]) -> dict[str, str]:
    clean: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        key = _clean_text(raw_key)
        value = _clean_text(raw_value)
        if key and value:
            clean[key] = value
    return clean


def _clean_facts(values: dict[str, Any]) -> dict[str, str]:
    clean: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        key = _clean_text(raw_key)
        value = _clean_text(raw_value)
        if key and value:
            clean[key] = value
    return clean


def _find_person_by_names(data: dict[str, Any], names: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    normalized_names = [_normalize_name(name) for name in names if _normalize_name(name)]
    if not normalized_names:
        return None, None
    for person in _people(data):
        person_names = [person.get("display_name"), *person.get("aliases", [])] if isinstance(person.get("aliases"), list) else [person.get("display_name")]
        normalized_person_names = [_normalize_name(str(name)) for name in person_names if _normalize_name(str(name))]
        if any(name in normalized_person_names for name in normalized_names):
            return person, "exact_name_or_alias"
    name_tokens = {token for name in normalized_names for token in name.split() if len(token) > 1}
    if not name_tokens:
        return None, None
    for person in _people(data):
        person_names = [person.get("display_name"), *person.get("aliases", [])] if isinstance(person.get("aliases"), list) else [person.get("display_name")]
        person_tokens = {
            token
            for name in person_names
            for token in _normalize_name(str(name)).split()
            if len(token) > 1
        }
        if name_tokens & person_tokens:
            return person, "token_overlap"
    return None, None


def _normalize_name(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFD", value.lower())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("đ", "d")
    return " ".join("".join(char if char.isalnum() else " " for char in normalized).split())


def _safe_filename(value: str) -> str:
    clean = _clean_text(value).replace("\\", "_").replace("/", "_")
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in clean)[:160]


def _image_extension(content_type: str) -> str:
    lowered = _clean_text(content_type).lower()
    if "png" in lowered:
        return "png"
    if "webp" in lowered:
        return "webp"
    return "jpg"


def _multipart_form_data(
    *,
    fields: dict[str, str],
    file_field: str,
    filename: str,
    content_type: str,
    file_bytes: bytes,
) -> tuple[bytes, str]:
    boundary = f"openvision-{hashlib.sha1(file_bytes).hexdigest()[:24]}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("ascii"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("ascii"),
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    return b"".join(chunks), boundary


def _merge_aliases(existing: Any, aliases: list[str] | None) -> list[str]:
    output: list[str] = []
    values = existing if isinstance(existing, list) else []
    for value in [*values, *(aliases or [])]:
        alias = _clean_text(value)
        if alias and alias not in output:
            output.append(alias)
    return output


def _person_id_for_immich(immich_person_id: str) -> str:
    digest = hashlib.sha1(f"immich:{immich_person_id}".encode("utf-8")).hexdigest()[:12]
    return f"person_{digest}"


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _ensure_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {"result": payload}


def _read_http_error_message(exc: error.HTTPError) -> str:
    try:
        raw = exc.read()
    except Exception:
        return exc.reason or "http_error"
    if not raw:
        return exc.reason or "http_error"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return raw.decode("utf-8", errors="replace")[:240]
    if isinstance(payload, dict):
        return str(payload.get("message") or payload.get("error") or payload)[:240]
    return str(payload)[:240]
