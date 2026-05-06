from __future__ import annotations

from typing import Callable


def next_local_partial_text(
    previous_text: str,
    next_text: str,
    *,
    merge_local_partial_text: Callable[[str, str], str],
) -> str | None:
    merged = merge_local_partial_text(previous_text, next_text)
    if not merged or merged == previous_text:
        return None
    return merged


def next_route_partial_text(previous_partial_text: str, cleaned_text: str) -> str | None:
    if not cleaned_text or cleaned_text == previous_partial_text:
        return None
    return cleaned_text


def next_live_partial_text(
    committed_text: str,
    last_text: str,
    cleaned_text: str,
    *,
    merge_incremental_transcript: Callable[[str, str], str],
) -> str | None:
    merged = merge_incremental_transcript(committed_text, cleaned_text)
    if not merged or merged == last_text:
        return None
    return merged


def next_live_final_text(
    committed_text: str,
    last_text: str,
    cleaned_text: str,
    *,
    merge_incremental_transcript: Callable[[str, str], str],
) -> str | None:
    merged = merge_incremental_transcript(committed_text, cleaned_text)
    if not merged:
        return None
    if merged == last_text and merged == committed_text:
        return None
    return merged
