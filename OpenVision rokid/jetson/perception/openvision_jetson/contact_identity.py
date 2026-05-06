"""User-managed local contact identity reminders for target finding.

The first backend is intentionally small and local: it stores user-enrolled
contact samples in the OpenVision runtime directory and compares live target
crops with a deterministic image fingerprint. A stronger face embedding backend
can replace the fingerprint later without changing the skill/runtime contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any
import unicodedata

from .contracts import new_id, utc_now
from .event_store import InMemoryEventStore


SCHEMA_VERSION = "openvision.contact_identity_db.v1"
PROVIDER_NAME = "openvision_local_contact_identity"
DEFAULT_MIN_CONFIDENCE = 0.86
DEFAULT_SFACE_MIN_CONFIDENCE = 0.45
DEFAULT_MIN_IDENTITY_FACE_SIDE_PX = 56.0
FORBIDDEN_SOURCE_MARKERS = ("ring", "security", "surveillance")


@dataclass(frozen=True, slots=True)
class IdentityMatch:
    target_id: str
    contact_id: str
    display_name: str
    confidence: float
    sample_id: str | None = None
    sample_provider: str | None = None
    track_id: str | None = None
    anonymous_id: str | None = None
    alias: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateIdentityVector:
    vector: list[float]
    provider: str
    quality: str = "ok"
    face_min_side_px: float | None = None
    quality_reasons: tuple[str, ...] = ()


class ContactIdentityStore:
    def __init__(
        self,
        *,
        runtime_dir: Path | None = None,
        db_path: Path | None = None,
        events: InMemoryEventStore | None = None,
        min_confidence: float | None = None,
        sface_min_confidence: float | None = None,
        min_identity_face_side_px: float | None = None,
    ) -> None:
        self.runtime_dir = (runtime_dir or _default_runtime_dir()).expanduser()
        self.db_path = (db_path or _configured_db_path(self.runtime_dir)).expanduser()
        self.events = events
        self.min_confidence = (
            float(min_confidence)
            if min_confidence is not None
            else _env_float("OPENVISION_IDENTITY_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE)
        )
        self.sface_min_confidence = (
            float(sface_min_confidence)
            if sface_min_confidence is not None
            else _env_float("OPENVISION_IDENTITY_SFACE_MIN_CONFIDENCE", DEFAULT_SFACE_MIN_CONFIDENCE)
        )
        self.min_identity_face_side_px = (
            float(min_identity_face_side_px)
            if min_identity_face_side_px is not None
            else _env_float("OPENVISION_IDENTITY_MIN_FACE_SIDE_PX", DEFAULT_MIN_IDENTITY_FACE_SIDE_PX)
        )

    def status(self) -> dict[str, Any]:
        data = self._read()
        contacts = _contacts(data)
        sample_count = sum(len(_samples(contact)) for contact in contacts)
        status = "ready" if sample_count else "ready_empty"
        return {
            "schema_version": "openvision.contact_identity_status.v1",
            "status": status,
            "provider": PROVIDER_NAME,
            "contact_count": len(contacts),
            "sample_count": sample_count,
            "min_confidence": self.min_confidence,
            "sface_min_confidence": self.sface_min_confidence,
            "min_identity_face_side_px": self.min_identity_face_side_px,
            "db_exists": self.db_path.is_file(),
            "runtime": "openvision_runtime_only",
            "message": (
                "Local contact identity DB is ready."
                if sample_count
                else "Local contact identity DB is ready but has no enrolled samples yet."
            ),
        }

    def list_contacts(self) -> list[dict[str, Any]]:
        return [_public_contact(contact) for contact in _contacts(self._read())]

    def create_contact(
        self,
        *,
        display_name: str,
        aliases: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        name = _clean_text(display_name)
        if not name:
            raise ValueError("display_name is required")
        data = self._read()
        contacts = _contacts(data)
        normalized_name = _normalize(name)
        existing = next(
            (
                contact
                for contact in contacts
                if _normalize(str(contact.get("display_name") or "")) == normalized_name
            ),
            None,
        )
        if existing is not None:
            existing["aliases"] = _merge_aliases(existing.get("aliases"), aliases)
            if notes:
                existing["notes"] = _clean_text(notes)
            existing["updated_at"] = utc_now()
            self._write(data)
            return _public_contact(existing)

        contact = {
            "contact_id": _contact_id_for(name),
            "display_name": name,
            "aliases": _merge_aliases([], aliases),
            "notes": _clean_text(notes or ""),
            "samples": [],
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        contacts.append(contact)
        data["contacts"] = contacts
        self._write(data)
        self._event("contact_created", {"contact_id": contact["contact_id"], "display_name": name})
        return _public_contact(contact)

    def enroll_sample(
        self,
        *,
        display_name: str | None = None,
        contact_id: str | None = None,
        aliases: list[str] | None = None,
        notes: str | None = None,
        image_ref: str | None = None,
        image_path: str | None = None,
        vector: list[float] | None = None,
        source_note: str | None = None,
    ) -> dict[str, Any]:
        if vector is None:
            resolved = self.resolve_image_ref(image_ref or image_path or "")
            if resolved is None:
                raise ValueError("image_ref/image_path must point inside OpenVision runtime")
            vector = fingerprint_image_file(resolved)
            source_ref = image_ref or image_path
        else:
            source_ref = source_note or "provided_vector"
        clean_vector = _normalize_vector(vector)
        if not clean_vector:
            raise ValueError("identity vector is empty")
        sample_provider = _sample_provider_for_source(source_ref, vector_dim=len(clean_vector))

        data = self._read()
        contact = self._find_or_create_contact(
            data=data,
            contact_id=contact_id,
            display_name=display_name,
            aliases=aliases,
            notes=notes,
        )
        sample = {
            "sample_id": new_id("idsample"),
            "provider": sample_provider,
            "vector": [round(value, 6) for value in clean_vector],
            "vector_dim": len(clean_vector),
            "source_ref": source_ref,
            "created_at": utc_now(),
        }
        samples = contact.setdefault("samples", [])
        if not isinstance(samples, list):
            samples = []
            contact["samples"] = samples
        if isinstance(samples, list) and source_ref:
            samples[:] = [
                existing
                for existing in samples
                if str(existing.get("source_ref") or "") != str(source_ref)
            ]
        samples.append(sample)
        contact["aliases"] = _merge_aliases(contact.get("aliases"), aliases)
        if notes:
            contact["notes"] = _clean_text(notes)
        contact["updated_at"] = utc_now()
        self._write(data)
        self._event(
            "sample_enrolled",
            {
                "contact_id": contact["contact_id"],
                "display_name": contact["display_name"],
                "sample_id": sample["sample_id"],
            },
        )
        return {
            "status": "enrolled",
            "contact": _public_contact(contact),
            "sample": _public_sample(sample),
        }

    def match_candidates(
        self,
        *,
        candidates: list[dict[str, Any]],
        query: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        data = self._read()
        contacts = _contacts(data)
        contacts_with_samples = [contact for contact in contacts if _samples(contact)]
        if not contacts_with_samples:
            return self._match_payload(
                status="no_samples",
                message="No enrolled local contact samples yet.",
                candidates=candidates,
                contacts=[],
                matches=[],
            )

        contact_pool = _contacts_for_query(contacts_with_samples, query)
        if not contact_pool:
            contact_pool = contacts_with_samples if _generic_identity_query(query) else []
        if not contact_pool:
            return self._match_payload(
                status="no_requested_contact",
                message="No enrolled contact name or alias matched this query.",
                candidates=candidates,
                contacts=[],
                matches=[],
            )

        matches: list[IdentityMatch] = []
        vector_count = 0
        low_quality_count = 0
        quality_reasons: dict[str, int] = {}
        best_score = 0.0
        best_overall: IdentityMatch | None = None
        for candidate in candidates:
            if str(candidate.get("label") or "") not in {"person", "people"}:
                continue
            candidate_vector = self._candidate_vector(candidate)
            if not candidate_vector:
                continue
            if _identity_quality_is_low(candidate_vector.quality):
                low_quality_count += 1
                for reason in candidate_vector.quality_reasons or (candidate_vector.quality,):
                    quality_reasons[reason] = quality_reasons.get(reason, 0) + 1
                continue
            vector_count += 1
            best = self._best_contact_match(candidate_vector, contact_pool)
            if best and best.confidence > best_score:
                best_score = best.confidence
                best_overall = best
            if best and best.confidence >= _match_threshold_for(
                candidate_vector,
                sample_provider=best.sample_provider,
                default_min_confidence=self.min_confidence,
                sface_min_confidence=self.sface_min_confidence,
            ):
                matches.append(
                    IdentityMatch(
                        target_id=str(candidate.get("target_id") or ""),
                        track_id=str(candidate.get("track_id")) if candidate.get("track_id") else None,
                        anonymous_id=str(candidate.get("anonymous_id")) if candidate.get("anonymous_id") else None,
                        contact_id=best.contact_id,
                        display_name=best.display_name,
                        confidence=best.confidence,
                        sample_id=best.sample_id,
                        sample_provider=best.sample_provider,
                        alias=best.alias,
                    )
                )
        status = (
            "confirmed"
            if matches
            else "no_match"
            if vector_count
            else "low_quality_face"
            if low_quality_count
            else "no_candidate_vectors"
        )
        message = (
            "Matched live candidate against the local contact DB."
            if matches
            else "Local contact DB was checked, but no candidate crossed the confidence threshold."
            if vector_count
            else _quality_message(quality_reasons)
            if low_quality_count
            else "Candidates have no identity vectors or readable crop refs yet."
        )
        payload = self._match_payload(
            status=status,
            message=message,
            candidates=candidates,
            contacts=contact_pool,
            matches=[_match_to_json(match) for match in matches],
            session_id=session_id,
            candidate_vector_count=vector_count,
            low_quality_candidate_count=low_quality_count,
            quality_reasons=quality_reasons,
            best_score=round(best_score, 4) if best_score else None,
            best_match=_match_to_json(best_overall) if best_overall else None,
        )
        if matches:
            self._event(
                "match_confirmed",
                {
                    "session_id": session_id,
                    "match_count": len(matches),
                    "contacts": [match.display_name for match in matches],
                },
            )
        return payload

    def resolve_image_ref(self, ref: str) -> Path | None:
        cleaned = str(ref or "").strip()
        if not cleaned:
            return None
        lowered = cleaned.lower()
        if any(marker in lowered for marker in FORBIDDEN_SOURCE_MARKERS):
            return None
        if cleaned.startswith("/api/crops/"):
            parts = [part for part in cleaned.split("/") if part]
            if len(parts) != 4:
                return None
            session_id = _safe_segment(parts[2])
            image_name = _safe_image_name(parts[3])
            if not session_id or not image_name:
                return None
            return _inside_or_none(self.runtime_dir / "crops" / session_id / image_name, self.runtime_dir)
        path = Path(cleaned).expanduser()
        if not path.is_absolute():
            path = self.runtime_dir / cleaned
        return _inside_or_none(path, self.runtime_dir)

    def _candidate_vector(self, candidate: dict[str, Any]) -> CandidateIdentityVector | None:
        attributes = candidate.get("attributes") if isinstance(candidate.get("attributes"), dict) else {}
        raw_vector = candidate.get("identity_vector") or attributes.get("identity_vector")
        if isinstance(raw_vector, list):
            vector = _normalize_vector(raw_vector)
            if vector:
                face_min_side_px = _to_float(attributes.get("face_min_side_px"))
                quality = str(attributes.get("identity_quality") or "ok")
                quality_reasons = _identity_quality_reasons(attributes, quality=quality)
                if face_min_side_px is not None and face_min_side_px < self.min_identity_face_side_px:
                    quality = "too_small_for_identity"
                    quality_reasons = _append_unique_reason(quality_reasons, quality)
                return CandidateIdentityVector(
                    vector=vector,
                    provider=_candidate_vector_provider(attributes),
                    quality=quality,
                    face_min_side_px=face_min_side_px,
                    quality_reasons=quality_reasons,
                )
        crop_ref = candidate.get("crop_ref")
        if not isinstance(crop_ref, str):
            return None
        path = self.resolve_image_ref(crop_ref)
        if path is None or not path.is_file():
            return None
        try:
            vector = _normalize_vector(fingerprint_image_file(path))
        except RuntimeError:
            return None
        return CandidateIdentityVector(vector=vector, provider="fingerprint_v1") if vector else None

    def _find_or_create_contact(
        self,
        *,
        data: dict[str, Any],
        contact_id: str | None,
        display_name: str | None,
        aliases: list[str] | None,
        notes: str | None,
    ) -> dict[str, Any]:
        contacts = _contacts(data)
        if contact_id:
            existing = next((contact for contact in contacts if contact.get("contact_id") == contact_id), None)
            if existing is None:
                raise ValueError(f"Unknown contact_id: {contact_id}")
            return existing
        name = _clean_text(display_name or "")
        if not name:
            raise ValueError("display_name is required when contact_id is not provided")
        normalized_name = _normalize(name)
        existing = next(
            (
                contact
                for contact in contacts
                if _normalize(str(contact.get("display_name") or "")) == normalized_name
            ),
            None,
        )
        if existing is not None:
            return existing
        contact = {
            "contact_id": _contact_id_for(name),
            "display_name": name,
            "aliases": _merge_aliases([], aliases),
            "notes": _clean_text(notes or ""),
            "samples": [],
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        contacts.append(contact)
        data["contacts"] = contacts
        return contact

    def _best_contact_match(self, candidate_vector: CandidateIdentityVector, contacts: list[dict[str, Any]]) -> IdentityMatch | None:
        best: IdentityMatch | None = None
        for contact in contacts:
            display_name = str(contact.get("display_name") or "").strip()
            for sample in _samples(contact):
                sample_vector = sample.get("vector")
                if not isinstance(sample_vector, list):
                    continue
                sample_provider = str(sample.get("provider") or "fingerprint_v1")
                sample_norm = _normalize_vector(sample_vector)
                if not _identity_vectors_compatible(candidate_vector, sample_norm, sample_provider):
                    continue
                confidence = _cosine(candidate_vector.vector, sample_norm)
                if best is None or confidence > best.confidence:
                    best = IdentityMatch(
                        target_id="",
                        contact_id=str(contact.get("contact_id") or ""),
                        display_name=display_name,
                        confidence=round(confidence, 4),
                        sample_id=str(sample.get("sample_id")) if sample.get("sample_id") else None,
                        sample_provider=sample_provider,
                        alias=_best_query_alias(contact),
                    )
        return best

    def _match_payload(
        self,
        *,
        status: str,
        message: str,
        candidates: list[dict[str, Any]],
        contacts: list[dict[str, Any]],
        matches: list[dict[str, Any]],
        session_id: str | None = None,
        candidate_vector_count: int = 0,
        low_quality_candidate_count: int = 0,
        quality_reasons: dict[str, int] | None = None,
        best_score: float | None = None,
        best_match: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": "openvision.contact_identity_match.v1",
            "status": status,
            "provider": PROVIDER_NAME,
            "session_id": session_id,
            "candidate_count": len(candidates),
            "candidate_vector_count": candidate_vector_count,
            "low_quality_candidate_count": low_quality_candidate_count,
            "quality_reasons": quality_reasons or {},
            "requested_contact_count": len(contacts),
            "match_count": len(matches),
            "min_confidence": self.min_confidence,
            "sface_min_confidence": self.sface_min_confidence,
            "min_identity_face_side_px": self.min_identity_face_side_px,
            "best_score": best_score,
            "best_match": best_match,
            "matches": matches,
            "message": message,
        }

    def _read(self) -> dict[str, Any]:
        if not self.db_path.is_file():
            return {"schema_version": SCHEMA_VERSION, "contacts": [], "updated_at": utc_now()}
        try:
            payload = json.loads(self.db_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            quarantine_path = self._quarantine_corrupt_db(reason=exc.__class__.__name__)
            return {
                "schema_version": SCHEMA_VERSION,
                "contacts": [],
                "updated_at": utc_now(),
                "read_error": True,
                "quarantined_path": str(quarantine_path) if quarantine_path else None,
            }
        if not isinstance(payload, dict):
            quarantine_path = self._quarantine_corrupt_db(reason="invalid_root")
            return {
                "schema_version": SCHEMA_VERSION,
                "contacts": [],
                "updated_at": utc_now(),
                "read_error": True,
                "quarantined_path": str(quarantine_path) if quarantine_path else None,
            }
        payload.setdefault("schema_version", SCHEMA_VERSION)
        payload.setdefault("contacts", [])
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
            self.events.add("identity", event_type, payload)


def fingerprint_image_file(path: Path) -> list[float]:
    try:
        from PIL import Image, ImageOps  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency availability.
        raise RuntimeError("Pillow is required for image fingerprint enrollment/matching.") from exc
    try:
        with Image.open(path) as image:
            gray = ImageOps.grayscale(image).resize((16, 16))
            pixels = [float(value) / 255.0 for value in gray.getdata()]
    except Exception as exc:
        raise RuntimeError(f"Could not fingerprint image: {exc.__class__.__name__}") from exc
    mean = sum(pixels) / len(pixels)
    centered = [value - mean for value in pixels]
    return _normalize_vector(centered or pixels)


def _default_runtime_dir() -> Path:
    return Path(os.getenv("OPENVISION_RUNTIME_DIR") or Path(__file__).resolve().parents[3] / "runtime")


def _configured_db_path(runtime_dir: Path) -> Path:
    value = os.getenv("OPENVISION_IDENTITY_DB_PATH")
    if value:
        return Path(value)
    return runtime_dir / "identity" / "contacts.json"


def _contacts(data: dict[str, Any]) -> list[dict[str, Any]]:
    contacts = data.get("contacts")
    if not isinstance(contacts, list):
        return []
    return [contact for contact in contacts if isinstance(contact, dict)]


def _samples(contact: dict[str, Any]) -> list[dict[str, Any]]:
    samples = contact.get("samples")
    if not isinstance(samples, list):
        return []
    return [sample for sample in samples if isinstance(sample, dict)]


def _public_contact(contact: dict[str, Any]) -> dict[str, Any]:
    samples = [_public_sample(sample) for sample in _samples(contact)]
    return {
        "contact_id": contact.get("contact_id"),
        "display_name": contact.get("display_name"),
        "aliases": contact.get("aliases") if isinstance(contact.get("aliases"), list) else [],
        "notes": contact.get("notes") or "",
        "sample_count": len(samples),
        "samples": samples,
        "created_at": contact.get("created_at"),
        "updated_at": contact.get("updated_at"),
    }


def _public_sample(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": sample.get("sample_id"),
        "provider": sample.get("provider"),
        "vector_dim": sample.get("vector_dim"),
        "source_ref": sample.get("source_ref"),
        "created_at": sample.get("created_at"),
    }


def _match_to_json(match: IdentityMatch) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "target_id": match.target_id,
            "track_id": match.track_id,
            "anonymous_id": match.anonymous_id,
            "contact_id": match.contact_id,
            "display_name": match.display_name,
            "confidence": match.confidence,
            "sample_id": match.sample_id,
            "sample_provider": match.sample_provider,
            "alias": match.alias,
            "identity_match": "contact_db",
            "match_status": "identity_confirmed",
        }.items()
        if value is not None
    }


def _contacts_for_query(contacts: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    normalized_query = _normalize(query)
    if not normalized_query:
        return []
    query_tokens = set(_significant_name_tokens(normalized_query))
    matched: list[dict[str, Any]] = []
    for contact in contacts:
        names = [str(contact.get("display_name") or ""), *[str(alias) for alias in contact.get("aliases") or []]]
        for name in names:
            normalized_name = _normalize(name)
            if not normalized_name:
                continue
            if normalized_name in normalized_query:
                matched.append(contact)
                break
            name_tokens = set(_significant_name_tokens(normalized_name))
            if query_tokens and name_tokens and query_tokens & name_tokens:
                matched.append(contact)
                break
    return matched


def _significant_name_tokens(normalized_text: str) -> list[str]:
    stop_tokens = {
        "tim",
        "nguoi",
        "ten",
        "trong",
        "dam",
        "dong",
        "muc",
        "tieu",
        "id",
        "nao",
        "la",
        "ai",
        "quen",
        "toi",
        "giup",
        "voi",
    }
    return [
        token
        for token in normalized_text.split()
        if len(token) > 1 and token not in stop_tokens
    ]


def _generic_identity_query(query: str) -> bool:
    normalized = _normalize(query)
    return any(
        token in normalized
        for token in (
            "nguoi quen",
            "co ai quen",
            "ai quen",
            "tim nguoi",
            "tim mot nguoi",
            "nguoi phia truoc",
            "nguoi trong dam dong",
            "quen ai",
            "da gap chua",
            "gap chua",
            "da gap",
            "ten gi",
            "la ai",
            "ai vay",
            "nguoi nay",
            "nguoi do",
            "thong tin ve nguoi",
            "thong tin nguoi",
            "con thong tin",
            "thong tin gi",
            "cho toi thong tin",
            "toi co biet",
            "co biet nguoi",
            "quet mat",
            "scan mat",
            "scan face",
            "face scan",
            "who is",
            "recognize",
            "nhan dien",
        )
    )


def _best_query_alias(contact: dict[str, Any]) -> str | None:
    aliases = contact.get("aliases") if isinstance(contact.get("aliases"), list) else []
    return str(aliases[0]) if aliases else None


def _sample_provider_for_source(source_ref: str | None, *, vector_dim: int) -> str:
    source = str(source_ref or "").lower()
    if source.startswith("opencv_sface:") or "sface" in source:
        return "sface_v1"
    if vector_dim == 128:
        return "provided_vector_v1"
    return "fingerprint_v1" if source and source != "provided_vector" else "provided_vector_v1"


def _candidate_vector_provider(attributes: dict[str, Any]) -> str:
    embedding_model = str(attributes.get("embedding_model") or "").strip().lower()
    detector = str(attributes.get("detector") or "").strip().lower()
    if embedding_model.startswith("sface") or "sface" in detector:
        return "sface_v1"
    provider = str(attributes.get("identity_provider") or attributes.get("vector_provider") or "").strip().lower()
    return provider or "provided_vector_v1"


def _match_threshold_for(
    candidate: CandidateIdentityVector,
    *,
    sample_provider: str | None,
    default_min_confidence: float,
    sface_min_confidence: float,
) -> float:
    if candidate.provider == "sface_v1" and sample_provider == "sface_v1":
        return sface_min_confidence
    return default_min_confidence


def _identity_quality_reasons(attributes: dict[str, Any], *, quality: str) -> tuple[str, ...]:
    output: list[str] = []
    raw = attributes.get("identity_quality_reasons")
    if raw is None:
        raw = attributes.get("face_quality_flags")
    if isinstance(raw, list):
        for item in raw:
            reason = _clean_quality_reason(item)
            if reason and reason not in output:
                output.append(reason)
    quality_reason = _clean_quality_reason(quality)
    if quality_reason and quality_reason != "ok" and quality_reason not in output:
        output.append(quality_reason)
    return tuple(output)


def _append_unique_reason(reasons: tuple[str, ...], reason: str) -> tuple[str, ...]:
    cleaned = _clean_quality_reason(reason)
    if not cleaned or cleaned in reasons:
        return reasons
    return (*reasons, cleaned)


def _identity_quality_is_low(quality: str) -> bool:
    cleaned = _clean_quality_reason(quality)
    return bool(cleaned and cleaned != "ok")


def _quality_message(reasons: dict[str, int]) -> str:
    if reasons.get("too_small_for_identity"):
        return "Detected face candidates are too small for reliable identity matching."
    if reasons.get("too_dark_for_identity") or reasons.get("low_light_for_identity"):
        return "Detected face candidates are too dark for reliable identity matching."
    if reasons.get("low_contrast_for_identity"):
        return "Detected face candidates have too little contrast for reliable identity matching."
    if reasons.get("too_soft_for_identity") or reasons.get("too_blurry_for_identity"):
        return "Detected face candidates are too blurry for reliable identity matching."
    return "Detected face candidates are not clear enough for reliable identity matching."


def _clean_quality_reason(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    return cleaned if cleaned else ""


def _identity_vectors_compatible(
    candidate: CandidateIdentityVector,
    sample_vector: list[float],
    sample_provider: str,
) -> bool:
    if len(candidate.vector) != len(sample_vector):
        return False
    if sample_provider == candidate.provider:
        return True
    # Operator/API-enrolled vectors may not carry a model-specific provider yet;
    # same-dimensional vectors are still allowed so existing DBs keep working.
    return sample_provider.startswith("provided_vector") or candidate.provider.startswith("provided_vector")


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_vector(values: list[Any]) -> list[float]:
    vector: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            vector.append(number)
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 1e-9:
        return []
    return [value / norm for value in vector]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    count = min(len(a), len(b))
    if count <= 0:
        return 0.0
    score = sum(a[index] * b[index] for index in range(count))
    return max(0.0, min(1.0, score))


def _contact_id_for(display_name: str) -> str:
    digest = hashlib.sha1(f"{display_name}:{time.time_ns()}".encode("utf-8")).hexdigest()[:12]
    return f"contact_{digest}"


def _clean_text(value: str | None) -> str:
    return str(value or "").strip()


def _merge_aliases(existing: Any, aliases: list[str] | None) -> list[str]:
    output: list[str] = []
    for value in [*(existing if isinstance(existing, list) else []), *(aliases or [])]:
        alias = _clean_text(str(value))
        if alias and alias not in output:
            output.append(alias)
    return output


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.lower())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    replacements = {
        "đ": "d",
        "á": "a",
        "à": "a",
        "ả": "a",
        "ã": "a",
        "ạ": "a",
        "ă": "a",
        "â": "a",
        "é": "e",
        "è": "e",
        "ẻ": "e",
        "ẽ": "e",
        "ẹ": "e",
        "ê": "e",
        "í": "i",
        "ì": "i",
        "ỉ": "i",
        "ĩ": "i",
        "ị": "i",
        "ó": "o",
        "ò": "o",
        "ỏ": "o",
        "õ": "o",
        "ọ": "o",
        "ô": "o",
        "ơ": "o",
        "ú": "u",
        "ù": "u",
        "ủ": "u",
        "ũ": "u",
        "ụ": "u",
        "ư": "u",
        "ý": "y",
        "ỳ": "y",
        "ỷ": "y",
        "ỹ": "y",
        "ỵ": "y",
    }
    for source, replacement in replacements.items():
        normalized = normalized.replace(source, replacement)
    return " ".join("".join(char if char.isalnum() else " " for char in normalized).split())


def _inside_or_none(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except OSError:
        return None
    if not _is_relative_to(resolved, root_resolved):
        return None
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_segment(value: str) -> str | None:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-"})
    return cleaned or None


def _safe_image_name(value: str) -> str | None:
    base = value.removesuffix(".jpg")
    cleaned = _safe_segment(base)
    return f"{cleaned}.jpg" if cleaned else None


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default
