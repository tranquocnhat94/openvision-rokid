#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.voice_runtime import VoiceOrchestrator, _norm_text  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the Rokid command STT stack on a curated suite.")
    parser.add_argument(
        "--suite",
        default=str(ROOT / "benchmarks" / "stt_command_suite.json"),
        help="Path to suite JSON manifest.",
    )
    return parser.parse_args()


def levenshtein(seq_a: list[str], seq_b: list[str]) -> int:
    if not seq_a:
        return len(seq_b)
    if not seq_b:
        return len(seq_a)
    prev = list(range(len(seq_b) + 1))
    for i, item_a in enumerate(seq_a, start=1):
        curr = [i]
        for j, item_b in enumerate(seq_b, start=1):
            cost = 0 if item_a == item_b else 1
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def token_metrics(expected: str, actual: str) -> dict[str, Any]:
    expected_tokens = [token for token in _norm_text(expected).split(" ") if token]
    actual_tokens = [token for token in _norm_text(actual).split(" ") if token]
    expected_counter = Counter(expected_tokens)
    actual_counter = Counter(actual_tokens)
    overlap = sum((expected_counter & actual_counter).values())
    precision = overlap / len(actual_tokens) if actual_tokens else 0.0
    recall = overlap / len(expected_tokens) if expected_tokens else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else 0.0
    wer = (
        levenshtein(expected_tokens, actual_tokens) / len(expected_tokens)
        if expected_tokens else (0.0 if not actual_tokens else 1.0)
    )
    expected_chars = list(_norm_text(expected).replace(" ", ""))
    actual_chars = list(_norm_text(actual).replace(" ", ""))
    cer = (
        levenshtein(expected_chars, actual_chars) / len(expected_chars)
        if expected_chars else (0.0 if not actual_chars else 1.0)
    )
    return {
        "expectedTokens": expected_tokens,
        "actualTokens": actual_tokens,
        "tokenPrecision": round(precision, 3),
        "tokenRecall": round(recall, 3),
        "tokenF1": round(f1, 3),
        "wer": round(wer, 3),
        "cer": round(cer, 3),
    }


def required_token_pass(required_tokens: list[str], actual: str) -> bool:
    actual_norm_tokens = set(token for token in _norm_text(actual).split(" ") if token)
    required_norm_tokens = [token for token in (_norm_text(item) for item in required_tokens) if token]
    return all(token in actual_norm_tokens for token in required_norm_tokens)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parse_args()
    suite_path = Path(args.suite).expanduser().resolve()
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    voice_config = json.loads((ROOT / "config" / "voice_settings.json").read_text(encoding="utf-8"))

    orchestrator = VoiceOrchestrator(
        root_dir=ROOT,
        session_provider=lambda: {},
        scene_context_provider=lambda _session_id: {},
        vision_context_provider=lambda _session_id, _target_query, _selected_track_id: {},
        command_handler=lambda _payload: None,
        log_handler=lambda _session_id, _event, _payload: None,
        speech_handler=lambda _payload: None,
    )
    orchestrator.update_config(voice_config)

    strict_case_count = 0
    strict_transcript_exact = 0
    strict_required_token_pass = 0
    strict_command_pass = 0
    strict_overall_pass = 0
    results: list[dict[str, Any]] = []

    try:
        for index, case in enumerate(suite.get("cases") or [], start=1):
            wav_path = Path(str(case["wavPath"])).expanduser().resolve()
            wav_bytes = wav_path.read_bytes()
            session_id = f"bench_suite_{index}"
            transcript = orchestrator._transcribe_local_http(session_id, wav_bytes)
            action = orchestrator._build_action(
                session_id=session_id,
                transcript=transcript,
                source="local_http",
                scene_context={},
            )
            expected_transcript = str(case.get("expectedTranscript") or "")
            required_tokens = [str(item) for item in case.get("requiredTokens") or []]
            expected_intent = str(case.get("expectedIntent") or "")
            expected_mode = str(case.get("expectedMode") or "")
            expected_target_query = str(case.get("expectedTargetQuery") or "")
            actual_target_query = str(action.get("targetQuery") or "")

            metrics = token_metrics(expected_transcript, transcript) if expected_transcript else {
                "expectedTokens": [],
                "actualTokens": [token for token in _norm_text(transcript).split(" ") if token],
                "tokenPrecision": 0.0,
                "tokenRecall": 0.0,
                "tokenF1": 0.0,
                "wer": None,
                "cer": None,
            }
            transcript_exact = bool(expected_transcript) and _norm_text(transcript) == _norm_text(expected_transcript)
            required_pass = required_token_pass(required_tokens, transcript)
            intent_pass = (str(action.get("intent") or "") == expected_intent) if expected_intent else True
            mode_pass = (str(action.get("mode") or "") == expected_mode) if expected_mode else not bool(action.get("mode"))
            target_query_pass = (
                _norm_text(actual_target_query) == _norm_text(expected_target_query)
                if expected_target_query else not bool(actual_target_query)
            )
            command_pass = intent_pass and mode_pass and target_query_pass
            strict = bool(case.get("strict", True))
            overall_pass = command_pass and (required_pass or transcript_exact)

            if strict:
                strict_case_count += 1
                strict_transcript_exact += int(transcript_exact)
                strict_required_token_pass += int(required_pass)
                strict_command_pass += int(command_pass)
                strict_overall_pass += int(overall_pass)

            results.append(
                {
                    "id": case["id"],
                    "strict": strict,
                    "notes": str(case.get("notes") or ""),
                    "wavPath": str(wav_path),
                    "expectedTranscript": expected_transcript,
                    "actualTranscript": transcript,
                    "transcriptExact": transcript_exact,
                    "requiredTokens": required_tokens,
                    "requiredTokenPass": required_pass,
                    "expectedIntent": expected_intent,
                    "actualIntent": str(action.get("intent") or ""),
                    "expectedMode": expected_mode,
                    "actualMode": str(action.get("mode") or ""),
                    "expectedTargetQuery": expected_target_query,
                    "actualTargetQuery": actual_target_query,
                    "commandPass": command_pass,
                    "overallPass": overall_pass,
                    "metrics": metrics,
                    "action": {
                        "intent": action.get("intent"),
                        "mode": action.get("mode"),
                        "targetQuery": action.get("targetQuery"),
                        "confidence": action.get("confidence"),
                        "statusText": action.get("statusText"),
                    },
                }
            )
    finally:
        orchestrator.close()

    summary = {
        "suiteName": suite.get("suiteName"),
        "strictCaseCount": strict_case_count,
        "strictTranscriptExactRate": round(strict_transcript_exact / strict_case_count, 3) if strict_case_count else 0.0,
        "strictRequiredTokenRate": round(strict_required_token_pass / strict_case_count, 3) if strict_case_count else 0.0,
        "strictCommandPassRate": round(strict_command_pass / strict_case_count, 3) if strict_case_count else 0.0,
        "strictOverallPassRate": round(strict_overall_pass / strict_case_count, 3) if strict_case_count else 0.0,
        "config": {
            "asrBackend": voice_config.get("asrBackend"),
            "localRequestFormat": voice_config.get("localRequestFormat"),
            "localHotwords": voice_config.get("localHotwords"),
            "localPartialEnabled": voice_config.get("localPartialEnabled"),
        },
    }
    print(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
