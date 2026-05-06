from __future__ import annotations

import re
from typing import Callable, Iterable


def merge_incremental_transcript(
    stable_text: str,
    next_piece: str,
    *,
    cleaner: Callable[[str], str],
    normalizer: Callable[[str], str],
) -> str:
    base = cleaner(stable_text)
    piece = cleaner(next_piece)
    if not piece:
        return base
    if not base:
        return piece

    base_norm = normalizer(base)
    piece_norm = normalizer(piece)
    if piece_norm.startswith(base_norm):
        return piece

    max_overlap = min(len(base), len(piece), 48)
    overlap = 0
    for size in range(max_overlap, 2, -1):
        if normalizer(base[-size:]) == normalizer(piece[:size]):
            overlap = size
            break
    suffix = piece[overlap:].lstrip()
    if not suffix:
        return base
    separator = "" if base.endswith(" ") or suffix.startswith((".", ",", "!", "?", ";", ":")) else " "
    return f"{base}{separator}{suffix}".strip()


def merge_local_partial_text(
    previous_text: str,
    next_text: str,
    *,
    cleaner: Callable[[str], str],
    normalizer: Callable[[str], str],
) -> str:
    previous = cleaner(previous_text)
    current = cleaner(next_text)
    if not current:
        return previous
    if not previous:
        return current

    previous_norm = normalizer(previous)
    current_norm = normalizer(current)
    if current_norm == previous_norm:
        return previous
    if current_norm.startswith(previous_norm):
        return current
    if previous_norm.startswith(current_norm):
        return previous

    merged = merge_incremental_transcript(
        previous,
        current,
        cleaner=cleaner,
        normalizer=normalizer,
    )
    if normalizer(merged) == previous_norm:
        return current if len(current) >= len(previous) else previous
    return merged


def trim_live_caption_hint(transcript: str, *, cleaner: Callable[[str], str], max_chars: int = 160) -> str:
    cleaned = cleaner(transcript)
    if len(cleaned) <= max_chars:
        return cleaned
    return f"…{cleaned[-(max_chars - 1):]}".strip()


def build_live_caption_prompt_markers(prompts: Iterable[str]) -> tuple[str, ...]:
    markers = {
        "live-caption ongoing spoken vietnamese",
        "live caption ongoing spoken vietnamese",
        "stream stable vietnamese words with diacritics as early as possible",
        "stream stable vietnamese words with",
        "prefer incremental captions over perfect punctuation",
        "ignore brief english filler or unrelated foreign words",
        "ignore brief english filler or",
        "return empty string when speech is too unclear",
        "return an empty string when speech is too unclear",
        "return an empty string",
        "transcribe spoken vietnamese only",
        "transcribe ongoing spoken vietnamese only",
        "return concise vietnamese text with proper diacritics",
        "return only the spoken vietnamese transcript with proper diacritics",
        "do not repeat instructions english prompt text or system text",
        "if the audio is unclear fragmented or not vietnamese return an empty string",
    }
    for prompt in prompts:
        prompt_text = str(prompt or "").strip()
        if not prompt_text:
            continue
        prompt_norm = normalize_prompt_marker(prompt_text)
        if prompt_norm:
            markers.add(prompt_norm)
        for fragment in re.split(r"[\.\n]+", prompt_text):
            fragment_norm = normalize_prompt_marker(fragment)
            if not fragment_norm:
                continue
            markers.add(fragment_norm)
            words = fragment_norm.split()
            for prefix_len in (4, 5, 6):
                if len(words) >= prefix_len:
                    markers.add(" ".join(words[:prefix_len]))
    return tuple(sorted((marker for marker in markers if marker), key=len, reverse=True))


def normalize_prompt_marker(prompt: str) -> str:
    return re.sub(r"\s+", " ", str(prompt or "").strip().lower())


def strip_live_caption_prompt_echo(
    transcript: str,
    *,
    cleaner: Callable[[str], str],
    prompt_markers: Iterable[str],
) -> str:
    cleaned = cleaner(transcript)
    if not cleaned:
        return ""
    lowered = normalize_prompt_marker(cleaned)
    earliest_index: int | None = None
    for marker in prompt_markers:
        index = lowered.find(marker)
        if index < 0:
            continue
        if earliest_index is None or index < earliest_index:
            earliest_index = index
    if earliest_index is None:
        return cleaned
    if earliest_index == 0:
        return ""
    prefix = cleaned[:earliest_index].strip(" .,!?:;-_")
    if not prefix:
        return ""
    return cleaner(prefix)


def sanitize_live_caption_transcript(
    transcript: str,
    *,
    cleaner: Callable[[str], str],
    normalizer: Callable[[str], str],
    has_vietnamese_markers: Callable[[str], bool],
    prompt_markers: Iterable[str],
) -> str:
    cleaned = cleaner(transcript)
    if not cleaned:
        return ""
    sanitized = strip_live_caption_prompt_echo(
        cleaned,
        cleaner=cleaner,
        prompt_markers=prompt_markers,
    )
    if not sanitized:
        return ""
    norm = normalizer(sanitized)
    if not norm:
        return ""
    if norm in {"live", "stream stable", "ignore brief english filler or", "return an empty string"}:
        return ""
    if not has_vietnamese_markers(sanitized):
        short_english_prompt = {"live", "stream", "stable", "ignore", "brief", "english", "filler", "return"}
        tokens = [token for token in re.findall(r"[a-z']+", norm) if token]
        if tokens and len(tokens) <= 3 and any(token in short_english_prompt for token in tokens):
            return ""
    return sanitized


def should_emit_local_partial_text(
    transcript: str,
    *,
    normalizer: Callable[[str], str],
    command_hints: Iterable[str],
) -> bool:
    norm = normalizer(transcript)
    if not norm:
        return False
    return any(hint in norm for hint in command_hints)
