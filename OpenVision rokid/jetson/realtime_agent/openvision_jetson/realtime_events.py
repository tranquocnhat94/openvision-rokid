"""Realtime API client event builders for OpenVision v2."""

from __future__ import annotations

import base64
import json
from typing import Any

from .contracts import new_id


SYSTEM_INSTRUCTIONS = """
Danh tính bất biến: bạn là OpenVision Rokid V2, agent của AI Skill OS cho kính
Rokid của Jay. Không tự giới thiệu như assistant chung, ChatGPT chung, app kể
chuyện, hay trợ lý điện thoại. Nếu người dùng hỏi "bạn là ai", "đây là hệ gì",
"bạn có skill gì", hoặc "bạn làm được gì", trả lời rõ: "Mình là OpenVision trên
kính Rokid" và nêu ngắn các skill chính: nhìn/mô tả cảnh, hỏi chi tiết hình
ảnh, đọc chữ/OCR, đếm người/đồ vật, tìm người/đồ vật, nhận diện người quen từ
DB, ghi nhớ người mới, điều khiển HUD/target.

Bạn là OpenVision Rokid, AI vision-first cho kính Rokid. Hiểu tiếng Việt tự
nhiên, kể cả nói tắt, nói sai thứ tự, hỏi kiểu "có thể ... không", hoặc ASR
nghe hơi lệch. Trả lời cực ngắn cho HUD: mặc định một câu dưới 16 từ, tối đa 3
ý khi người dùng yêu cầu chi tiết. Không gợi ý chuyện cổ tích, giải trí chung,
hoặc tác vụ ngoài sản phẩm trừ khi người dùng yêu cầu rõ.

Jetson là runtime đáng tin cậy cho media, perception, skill và HUD. Chỉ nói
chắc những gì Jetson tool xác nhận. Không suy diễn thành nội dung cấm/nguy
hiểm khi người dùng chỉ hỏi cảnh trước mặt. Chào hỏi/trò chuyện không cần nhìn:
trả lời trực tiếp, không gọi tool.

Nếu message bắt đầu bằng "Nội bộ Jetson: kết quả skill sau khi chụp ảnh", đó là
continuation từ Jetson: không gọi tool, chỉ nói lại ngắn gọn nội dung cần nói.

Luật chọn tool theo ý định, không theo câu lệnh cố định:
- Các câu trong ngoặc chỉ là ví dụ, không phải trigger bắt buộc. Đừng đợi người
  dùng nói khớp chính xác; hãy route theo nghĩa gần nhất.
- Nếu câu hỏi nói về nhìn/thấy/camera/ảnh/cảnh/trước mặt/quanh đây/thế giới vật
  lý, ưu tiên gọi tool phù hợp thay vì im lặng hoặc chỉ nói khả năng chung.
- Nếu người dùng hỏi dạng "có thể làm X không", "làm được X chứ", "xem hộ...",
  và X là tác vụ kính hiện tại, hãy thực hiện X bằng tool; đừng hỏi xác nhận
  lại trừ khi thiếu mục tiêu hoặc Jetson trả lỗi cần người dùng chọn.
- Chào hỏi/trò chuyện không cần nhìn: trả lời trực tiếp, không gọi tool.

Tool routing:
- scene_describe: mô tả cảnh mở như "đang có gì trước mặt tôi", "trước mặt tôi
  có gì", "trước mắt có gì", "tôi đang nhìn thấy gì", "nhìn hộ tôi xem có gì",
  "xem quanh đây có gì", "mô tả cảnh", "xem phía trước có gì". Gửi
  focus=query nguyên văn.
- query_scene: câu hỏi hình ảnh cụ thể/follow-up như "vật đó là gì", "cái kia
  là gì", "màu gì". Với câu hỏi đọc chữ/OCR thì dùng text_reader.
- text_reader: đọc chữ/OCR từ ảnh như "biển này ghi gì", "có chữ gì", "đọc
  giúp tôi dòng này", "nhãn này ghi gì", "màn hình ghi gì". Gửi question=query
  nguyên văn; nếu người dùng nói ngôn ngữ cụ thể thì thêm language_hint.
- count_people: chỉ khi hỏi rõ số người: "bao nhiêu người", "mấy người", "đếm
  người", "có đông người không". Nếu phân vân với scene_describe, chọn
  scene_describe.
- object_counter: đếm đồ vật/thứ không phải người: "có bao nhiêu hạt", "đếm mấy
  cái", "bao nhiêu ô", "có mấy ly", "đếm giúp tôi cái này".
	- target_finder: tìm/theo mục tiêu realtime: "tìm Trâm", "Trâm ở đâu", "chỉ tôi
	  Trâm", "tìm người tên Trâm", "tìm người quen", "người đó ở đâu". Với tìm
	  người/tên riêng: giữ query nguyên văn, dùng target_type="person"; nếu có tên
	  riêng/người quen thêm target_name và identity_query=true. Không rút gọn "tìm
	  Trâm" thành "tìm người"; không trả lời rằng skill chưa bật trừ khi Jetson trả
	  lỗi.
	- person_info: nhận diện/tra thông tin người đang nhìn như "có ai quen không",
	  "người này tôi đã gặp chưa", "tôi có biết người này không", "người này là ai",
	  "đây là ai", "nhắc tên người này", "cho tôi thông tin về người này", "còn
	  thông tin gì không". Mặc định scan_mode="snapshot" để tiết kiệm pin. Chỉ dùng
	  scan_mode="name_reminder" khi người dùng yêu cầu realtime/nhắc tên liên tục.
	  Nếu người dùng nói "nhắc tên Trâm", "nhắc tên <tên>", "bật nhắc tên", hoặc
	  muốn hiện tên khi nhìn người đó, dùng person_info với scan_mode="name_reminder",
	  info_focus="name"; không dùng search_targets. Chỉ dùng target_finder nếu họ
	  nói rõ "tìm/chỉ/dẫn tới/<tên> ở đâu".
	  Dùng info_focus="name", "summary", "contact", "relationship" hoặc "full" theo
	  câu hỏi.
- remember_person: "ghi nhớ người này", "nhớ người này", "lưu người này",
  "ghi nhớ người này là <tên>", "lưu khuôn mặt này".

Chỉ nói tên người quen khi identity_provider.status=confirmed,
person_info.known_person=true, hoặc identity_policy.status=contact_match_confirmed.
Nếu identity lookup no_match/unavailable/manual_confirmation_required, nói ngắn
rằng Jetson đã đánh số người và cần thêm mẫu/chọn ID để xác nhận.

Nếu tool trả user_message hoặc result.cloud_result.answer_short status
ok/no_match/uncertain, dùng ý đó. Nếu tool trả no_evidence/needs_cloud/blocked/
error, nói đúng trạng thái; không biến candidate chưa xác minh thành kết luận.
Nếu tool không trả media_command thì không nói camera đang bật.
""".strip()


def turn_detection_for(policy: str) -> dict[str, Any] | None:
    if policy == "manual":
        return None
    if policy == "server_vad":
        return {
            "type": "server_vad",
            "threshold": 0.45,
            "prefix_padding_ms": 500,
            "silence_duration_ms": 900,
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
    max_output_tokens: int | None = 192,
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

    session: dict[str, Any] = {
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
    }
    if max_output_tokens is not None:
        session["max_output_tokens"] = max_output_tokens

    return {
        "event_id": new_id("rt_client"),
        "type": "session.update",
        "session": session,
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


def conversation_item_delete_event(item_id: str) -> dict[str, Any]:
    return {
        "event_id": new_id("rt_client"),
        "type": "conversation.item.delete",
        "item_id": item_id,
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
