"""Realtime API client event builders for OpenVision v2."""

from __future__ import annotations

import base64
import json
from typing import Any

from .contracts import new_id


SYSTEM_INSTRUCTIONS = """
Bạn là OpenVision Rokid, agent AI vision-first cho kính Rokid.
Hiểu tiếng Việt tự nhiên, trả lời ngắn gọn để phù hợp HUD kính.
Jetson là runtime đáng tin cậy cho media, perception graph, selected target,
typed skills và HUD; bạn chỉ được nói chắc những gì Jetson tool đã xác nhận.
Khi người dùng hỏi về cảnh trước mặt, số người, đối tượng, tìm mục tiêu,
hoặc mục tiêu đang chọn, hãy gọi typed Jetson tools trước khi trả lời.
Nếu tool trả status no_evidence hoặc needs_cloud, hãy nói ngắn gọn đúng trạng thái:
chưa có dữ liệu hình ảnh, hoặc Jetson mới có ứng viên và cần cloud/skill tiếp theo
để xác minh thuộc tính như màu áo, đeo kính, đứng/ngồi. Không biến candidate
chưa xác minh thành kết luận đã thấy đúng đối tượng. Nếu tool trả user_message,
hãy dùng đúng ý đó; không nói "có thể mặc áo xanh" khi màu áo chưa được xác minh.
""".strip()


def turn_detection_for(policy: str) -> dict[str, Any] | None:
    if policy == "manual":
        return None
    if policy == "server_vad":
        return {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 500,
            "create_response": True,
            "interrupt_response": False,
        }
    if policy == "semantic_vad":
        return {
            "type": "semantic_vad",
            "eagerness": "low",
            "create_response": True,
            "interrupt_response": False,
        }
    raise ValueError(f"Unsupported turn policy: {policy}")


def session_update_event(
    *,
    model: str,
    voice: str,
    tools: list[dict[str, Any]],
    turn_policy: str,
    output_modalities: list[str],
) -> dict[str, Any]:
    audio_input: dict[str, Any] = {
        "format": {
            "type": "audio/pcm",
            "rate": 24000,
        },
        "noise_reduction": {
            "type": "near_field",
        },
        "turn_detection": turn_detection_for(turn_policy),
    }

    return {
        "event_id": new_id("rt_client"),
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": model,
            "output_modalities": output_modalities,
            "instructions": SYSTEM_INSTRUCTIONS,
            "audio": {
                "input": audio_input,
                "output": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": 24000,
                    },
                    "voice": voice,
                },
            },
            "tools": tools,
            "tool_choice": "auto",
        },
    }


def text_item_event(text: str) -> dict[str, Any]:
    return {
        "event_id": new_id("rt_client"),
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": text,
                }
            ],
        },
    }


def response_create_event(*, output_modalities: list[str] | None = None) -> dict[str, Any]:
    response: dict[str, Any] = {}
    if output_modalities:
        response["output_modalities"] = output_modalities
    return {
        "event_id": new_id("rt_client"),
        "type": "response.create",
        "response": response,
    }


def append_audio_event(pcm_bytes: bytes) -> dict[str, Any]:
    return {
        "event_id": new_id("rt_client"),
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(pcm_bytes).decode("ascii"),
    }


def commit_audio_event() -> dict[str, Any]:
    return {
        "event_id": new_id("rt_client"),
        "type": "input_audio_buffer.commit",
    }


def clear_audio_event() -> dict[str, Any]:
    return {
        "event_id": new_id("rt_client"),
        "type": "input_audio_buffer.clear",
    }


def function_call_output_event(*, call_id: str, output: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": new_id("rt_client"),
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(output, ensure_ascii=False),
        },
    }


def parse_function_calls(server_event: dict[str, Any]) -> list[dict[str, Any]]:
    if server_event.get("type") != "response.done":
        return []
    response = server_event.get("response")
    if not isinstance(response, dict):
        return []
    calls: list[dict[str, Any]] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue
        args_raw = item.get("arguments") or "{}"
        try:
            args = json.loads(args_raw)
        except json.JSONDecodeError:
            args = {"_invalid_json": args_raw}
        calls.append(
            {
                "call_id": item.get("call_id"),
                "name": item.get("name"),
                "arguments": args,
            }
        )
    return calls
