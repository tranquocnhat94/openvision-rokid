from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Callable


def _now_ms() -> int:
    return int(time.time() * 1000)


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _norm_text(value: str) -> str:
    lowered = _strip_accents(value).lower().replace("đ", "d")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def _shorten(value: str, limit: int = 96) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _extract_json_object(value: str) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_response_text(payload: dict[str, Any]) -> str:
    text = str(payload.get("output_text") or "").strip()
    if text:
        return text
    outputs = payload.get("output")
    if not isinstance(outputs, list):
        return ""
    pieces: list[str] = []
    for item in outputs:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for chunk in content:
            if not isinstance(chunk, dict):
                continue
            candidate = str(
                chunk.get("text")
                or chunk.get("output_text")
                or chunk.get("transcript")
                or ""
            ).strip()
            if candidate:
                pieces.append(candidate)
    return " ".join(piece for piece in pieces if piece).strip()


PERSON_QUERY_TOKENS = (
    "nguoi",
    "anh",
    "chi",
    "ong",
    "ba",
    "co",
    "chu",
    "ao",
    "quan",
    "kinh",
    "deo",
    "mu",
    "balo",
    "tui",
    "nam",
    "nu",
    "mat",
)

ATTRIBUTE_QUERY_TOKENS = (
    "vang",
    "den",
    "do",
    "xanh",
    "trang",
    "hong",
    "cam",
    "tim",
    "xam",
    "nau",
    "kinh",
    "deo",
    "mu",
    "balo",
    "tui",
    "nam",
    "nu",
    "tuoi",
)

ZONE_HINTS = {
    "left": ("ben trai", "phia trai", "trai", "left"),
    "right": ("ben phai", "phia phai", "phai", "right"),
    "ahead": ("phia truoc", "truoc mat", "o giua", "giua", "ahead", "center"),
}

class OpenAIVisionSkillRuntime:
    def __init__(
        self,
        *,
        config_provider: Callable[[], dict[str, Any]],
        log_handler: Callable[[str, str, dict[str, Any]], None],
    ) -> None:
        self._config_provider = config_provider
        self._log_handler = log_handler

    def resolve_target(
        self,
        *,
        session_id: str,
        target_query: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        cleaned_query = _shorten(str(target_query or "").strip(), limit=120)
        candidates = self._prefilter_candidates(cleaned_query, context.get("candidates"))
        if not candidates:
            return {
                "ok": True,
                "resolutionSource": "scan_pending",
                "candidateCount": 0,
                "statusText": _shorten(f"Dang tim {cleaned_query}.", limit=88),
            }

        if len(candidates) == 1 or not self._should_use_cloud(cleaned_query, len(candidates)):
            winner = candidates[0]
            return self._resolved_candidate_result(
                winner,
                candidate_count=len(candidates),
                source="local_narrowing",
                reason="Local candidate narrowing found a single best match.",
            )

        self._log_handler(
            session_id,
            "vision_skill_resolve_started",
            {
                "query": cleaned_query,
                "candidateCount": len(candidates),
                "model": str(self._config_provider().get("openaiVisionModel") or "gpt-5.4"),
            },
        )
        result = self._openai_pick_candidate(
            session_id=session_id,
            target_query=cleaned_query,
            context=context,
            candidates=candidates,
        )
        if result:
            self._log_handler(
                session_id,
                "vision_skill_resolve_result",
                {
                    "query": cleaned_query,
                    "candidateCount": len(candidates),
                    "resolutionSource": result.get("resolutionSource"),
                    "selectedTrackId": result.get("selectedTrackId"),
                    "selectedTargetSummary": result.get("selectedTargetSummary"),
                    "confidence": result.get("confidence"),
                },
            )
            return result

        fallback = candidates[0]
        fallback_result = self._resolved_candidate_result(
            fallback,
            candidate_count=len(candidates),
            source="fallback_local",
            reason="Cloud reasoning returned no confident match; keeping the strongest local candidate.",
        )
        self._log_handler(
            session_id,
            "vision_skill_resolve_result",
            {
                "query": cleaned_query,
                "candidateCount": len(candidates),
                "resolutionSource": fallback_result.get("resolutionSource"),
                "selectedTrackId": fallback_result.get("selectedTrackId"),
                "selectedTargetSummary": fallback_result.get("selectedTargetSummary"),
                "confidence": fallback_result.get("confidence"),
            },
        )
        return fallback_result

    def analyze_selected_target(
        self,
        *,
        session_id: str,
        question: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        selected = context.get("selectedTarget")
        if not isinstance(selected, dict):
            return {
                "ok": False,
                "error": "No selected target is available.",
                "statusText": "Chua co doi tuong dang duoc chon.",
            }
        evidence_images = selected.get("evidenceImages")
        if not isinstance(evidence_images, list) or not evidence_images:
            return {
                "ok": False,
                "error": "Selected target has no evidence images.",
                "statusText": "Doi tuong hien tai chua co anh bang chung ro.",
            }
        question_text = _shorten(str(question or "").strip(), limit=180)
        self._log_handler(
            session_id,
            "vision_skill_analyze_started",
            {
                "question": question_text,
                "selectedTrackId": selected.get("trackId"),
                "model": str(self._config_provider().get("openaiVisionModel") or "gpt-5.4"),
            },
        )
        prompt = (
            "You are a visual reasoning helper for Rokid glasses. "
            "The selected target has already been narrowed locally on Jetson. "
            "Answer only what is visually observable from the supplied images. "
            "Do not guess identity or history. Return JSON only with keys "
            '"answer", "attributes", and "confidence". '
            f"User question: {question_text}\n"
            f"Selected target summary: {selected.get('summary') or selected.get('label') or 'target'}"
        )
        response = self._openai_json_response(
            session_id=session_id,
            prompt=prompt,
            image_specs=evidence_images,
        )
        parsed = _extract_json_object(response) or {}
        answer = _shorten(str(parsed.get("answer") or response or "").strip(), limit=120)
        attributes = parsed.get("attributes") if isinstance(parsed.get("attributes"), list) else []
        confidence = float(parsed.get("confidence") or 0.0) if parsed else 0.0
        if not answer:
            answer = "Chua du bang chung de ket luan chac chan."
        result = {
            "ok": True,
            "answer": answer,
            "attributes": [str(item).strip() for item in attributes if str(item).strip()][:6],
            "confidence": round(max(0.0, min(1.0, confidence or 0.0)), 3),
            "selectedTrackId": str(selected.get("trackId") or ""),
            "statusText": answer,
        }
        self._log_handler(
            session_id,
            "vision_skill_analyze_result",
            {
                "question": question_text,
                "selectedTrackId": result["selectedTrackId"],
                "answer": answer,
                "confidence": result["confidence"],
            },
        )
        return result

    def _prefilter_candidates(self, query: str, raw_candidates: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_candidates, list):
            return []
        candidates = [item for item in raw_candidates if isinstance(item, dict)]
        normalized_query = _norm_text(query)
        if not normalized_query:
            return candidates

        for zone, hints in ZONE_HINTS.items():
            if any(hint in normalized_query for hint in hints):
                zoned = [item for item in candidates if _norm_text(str(item.get("zone") or "")) == zone]
                if zoned:
                    candidates = zoned
                break

        person_query = any(token in normalized_query for token in PERSON_QUERY_TOKENS)
        if person_query:
            people = [item for item in candidates if _norm_text(str(item.get("label") or "")) == "person"]
            if people:
                candidates = people

        candidates.sort(
            key=lambda item: (
                -float(item.get("confidence") or 0.0),
                str(item.get("trackId") or ""),
            )
        )
        limit = max(1, int(self._config_provider().get("openaiVisionMaxCandidates") or 3))
        return candidates[:limit]

    def _should_use_cloud(self, query: str, candidate_count: int) -> bool:
        config = self._config_provider()
        if not bool(config.get("openaiVisionReasoningEnabled", True)):
            return False
        if not str(config.get("openaiApiKey") or "").strip():
            return False
        if candidate_count <= 1:
            return False
        normalized_query = _norm_text(query)
        return any(token in normalized_query for token in ATTRIBUTE_QUERY_TOKENS)

    def _resolved_candidate_result(
        self,
        candidate: dict[str, Any],
        *,
        candidate_count: int,
        source: str,
        reason: str,
    ) -> dict[str, Any]:
        summary = _shorten(
            str(candidate.get("summary") or candidate.get("description") or candidate.get("label") or "target"),
            limit=84,
        )
        track_id = str(candidate.get("trackId") or "")
        label = str(candidate.get("displayLabel") or candidate.get("label") or "target").strip()
        return {
            "ok": True,
            "candidateCount": candidate_count,
            "selectedTrackId": track_id,
            "selectedTargetLabel": label,
            "selectedTargetSummary": summary,
            "resolutionSource": source,
            "statusText": _shorten(f"Da khoa {label}.", limit=88),
            "confidence": round(float(candidate.get("confidence") or 0.0), 3),
            "reason": reason,
        }

    def _openai_pick_candidate(
        self,
        *,
        session_id: str,
        target_query: str,
        context: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        image_specs: list[dict[str, Any]] = []
        candidate_lines: list[str] = []
        max_images = max(1, int(self._config_provider().get("openaiVisionMaxImages") or 3))
        for index, candidate in enumerate(candidates[:max_images], start=1):
            images = candidate.get("candidateImages")
            primary_image = images[0] if isinstance(images, list) and images else None
            if not isinstance(primary_image, dict) or not str(primary_image.get("imageB64") or "").strip():
                continue
            image_specs.append(primary_image)
            candidate_lines.append(
                f"Candidate {index}: trackId={candidate.get('trackId')}, "
                f"label={candidate.get('label')}, zone={candidate.get('zone')}, "
                f"confidence={candidate.get('confidence')}, summary={candidate.get('summary') or candidate.get('description') or ''}"
            )
        if not image_specs:
            return None
        prompt = (
            "You are the visual disambiguation layer for Rokid smart glasses. "
            "Jetson local perception has already narrowed the scene to a small candidate set. "
            "YOLO26 tracks people and coarse objects, but it cannot reliably understand fine-grained attributes "
            "like shirt color, glasses, gender presentation, or subtle accessories. "
            "Choose the best visible candidate for the user's request if one is clearly supported by the images. "
            "Return JSON only with keys "
            '"match_track_id", "match_confidence", "visible_attributes", and "reason".\n'
            f"User target request: {target_query}\n"
            f"Scene summary: {context.get('summary') or context.get('headline') or 'scene live'}\n"
            + "\n".join(candidate_lines)
        )
        response = self._openai_json_response(
            session_id=session_id,
            prompt=prompt,
            image_specs=image_specs,
        )
        parsed = _extract_json_object(response)
        if not parsed:
            return None
        match_track_id = str(parsed.get("match_track_id") or "").strip()
        if not match_track_id:
            return None
        match = next((item for item in candidates if str(item.get("trackId") or "") == match_track_id), None)
        if match is None:
            return None
        visible_attributes = parsed.get("visible_attributes")
        summary = ""
        if isinstance(visible_attributes, list):
            summary = ", ".join(str(item).strip() for item in visible_attributes if str(item).strip())
        if not summary:
            summary = str(parsed.get("reason") or match.get("summary") or "").strip()
        result = self._resolved_candidate_result(
            match,
            candidate_count=len(candidates),
            source="openai_vision",
            reason=str(parsed.get("reason") or "").strip() or "OpenAI chose the best candidate from narrowed crops.",
        )
        result["selectedTargetSummary"] = _shorten(summary or result["selectedTargetSummary"], limit=84)
        try:
            result["confidence"] = round(float(parsed.get("match_confidence") or result["confidence"] or 0.0), 3)
        except Exception:
            pass
        result["statusText"] = _shorten(
            f"Da khoa {result['selectedTargetLabel']} cho {target_query}.",
            limit=96,
        )
        return result

    def _openai_json_response(
        self,
        *,
        session_id: str,
        prompt: str,
        image_specs: list[dict[str, Any]],
    ) -> str:
        config = self._config_provider()
        api_key = str(config.get("openaiApiKey") or "").strip()
        if not api_key:
            return ""
        base_url = str(config.get("openaiBaseUrl") or "https://api.openai.com/v1").rstrip("/")
        model = str(config.get("openaiVisionModel") or "gpt-5.4").strip() or "gpt-5.4"
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for image in image_specs:
            image_b64 = str(image.get("imageB64") or "").strip()
            if not image_b64:
                continue
            mime_type = str(image.get("mimeType") or "image/jpeg").strip() or "image/jpeg"
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{mime_type};base64,{image_b64}",
                }
            )
        body: dict[str, Any] = {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
            "max_output_tokens": 300,
        }
        if model.startswith("gpt-5"):
            body["reasoning"] = {"effort": "medium"}
        request = urllib.request.Request(
            url=f"{base_url}/responses",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            self._log_handler(
                session_id,
                "vision_skill_openai_error",
                {
                    "error": str(error),
                    "model": model,
                },
            )
            return ""
        text = _extract_response_text(payload)
        self._log_handler(
            session_id,
            "vision_skill_openai_response",
            {
                "model": model,
                "text": _shorten(text, limit=220),
            },
        )
        return text
