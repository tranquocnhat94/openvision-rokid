from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class FinalRouteResolution:
    duplicate: bool = False
    effective_transcript: str = ""
    effective_action: dict[str, Any] | None = None
    hold_transcript: str | None = None
    hold_reason: str | None = None
    clear_pending: bool = False


def resolve_final_route(
    *,
    transcript: str,
    source: str,
    now_ms: int,
    last_transcript: str,
    last_transcript_ms: int,
    pending_text: str,
    pending_ms: int,
    build_action: Callable[[str, str], dict[str, Any]],
    merge_transcript: Callable[[str, str], str],
    is_action_more_specific: Callable[[dict[str, Any], dict[str, Any]], bool],
    is_incomplete_command_prefix: Callable[[str, dict[str, Any]], bool],
    duplicate_window_ms: int = 6000,
    pending_window_ms: int = 4000,
) -> FinalRouteResolution:
    duplicate = bool(
        transcript == last_transcript
        and now_ms - last_transcript_ms < duplicate_window_ms
    )
    if duplicate:
        return FinalRouteResolution(duplicate=True)

    action = build_action(transcript, source)
    effective_transcript = transcript
    effective_action = action

    pending_active = bool(pending_text and now_ms - pending_ms <= pending_window_ms)
    if pending_active and pending_text != transcript:
        merged_transcript = merge_transcript(pending_text, transcript)
        if merged_transcript and merged_transcript != pending_text:
            merged_action = build_action(merged_transcript, source)
            if is_action_more_specific(merged_action, action):
                effective_transcript = merged_transcript
                effective_action = merged_action
            elif is_incomplete_command_prefix(merged_transcript, merged_action):
                return FinalRouteResolution(
                    effective_transcript=merged_transcript,
                    effective_action=merged_action,
                    hold_transcript=merged_transcript,
                    hold_reason="await_followup",
                )
    elif pending_text and not pending_active:
        if is_incomplete_command_prefix(effective_transcript, effective_action):
            return FinalRouteResolution(
                effective_transcript=effective_transcript,
                effective_action=effective_action,
                hold_transcript=effective_transcript,
                hold_reason="await_followup",
                clear_pending=True,
            )
        return FinalRouteResolution(
            effective_transcript=effective_transcript,
            effective_action=effective_action,
            clear_pending=True,
        )

    if is_incomplete_command_prefix(effective_transcript, effective_action):
        return FinalRouteResolution(
            effective_transcript=effective_transcript,
            effective_action=effective_action,
            hold_transcript=effective_transcript,
            hold_reason="await_followup",
        )

    return FinalRouteResolution(
        effective_transcript=effective_transcript,
        effective_action=effective_action,
    )
