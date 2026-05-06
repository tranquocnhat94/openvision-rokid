from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class TranscriptDecision:
    cleaned_text: str
    accepted_text: str
    discard_reason: str | None = None


def evaluate_transcript_candidate(
    transcript: str,
    *,
    cleaner: Callable[[str], str],
    is_spurious: Callable[[str], bool],
    is_language_script_mismatch: Callable[[str], bool],
) -> TranscriptDecision:
    cleaned = cleaner(transcript)
    if not cleaned:
        return TranscriptDecision(cleaned_text="", accepted_text="")
    if is_spurious(cleaned):
        return TranscriptDecision(
            cleaned_text=cleaned,
            accepted_text="",
            discard_reason="spurious",
        )
    if is_language_script_mismatch(cleaned):
        return TranscriptDecision(
            cleaned_text=cleaned,
            accepted_text="",
            discard_reason="language_script_mismatch",
        )
    return TranscriptDecision(
        cleaned_text=cleaned,
        accepted_text=cleaned,
    )
