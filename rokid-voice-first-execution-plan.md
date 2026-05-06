# Rokid Voice-First Execution Plan

Updated: 2026-04-19

Tài liệu này là bản triển khai chi tiết tiếp theo của:

- [rokid-voice-first-product-refactor.md](rokid-voice-first-product-refactor.md)

Mục tiêu của file này:

- biến ý tưởng voice-first thành kế hoạch có thể thực hiện từng phase
- chỉ rõ module nào sẽ nằm ở kính, module nào ở Jetson
- chốt protocol nên có
- chốt guardrail an toàn để **không đụng hệ Ring**
- chốt cách tái dùng YOLO26 hiện có nếu phù hợp

## 1. Guardrail quan trọng nhất

Không được làm gì khiến hệ camera Ring hiện tại mất ổn định.

### 1.1 Những thứ tuyệt đối không đụng

- không sửa `jetson-phase2-ring.service`
- không sửa code inference đang phục vụ Ring nếu chưa có sandbox/branch riêng
- không đổi port, env, weights path, engine path mà Ring đang dùng
- không ghép request Rokid trực tiếp vào process production của Ring ở phase đầu

### 1.2 Những thứ được phép tái dùng

- TensorRT engine file YOLO26
- labels file
- class mapping
- một số preprocessing/postprocessing utility nếu có thể copy hoặc adapter lại
- kinh nghiệm vận hành và benchmark đang có trên Jetson

### 1.3 Cách tái dùng an toàn nhất

`shared artifact, isolated runtime`

Nghĩa là:

- dùng chung `engine`, `labels`, có thể dùng chung weight source
- nhưng Rokid chạy trong process/runtime riêng
- nếu Rokid lỗi, Ring không bị kéo theo

## 2. Kiến trúc đích chia theo 3 lớp

### 2.1 Glass Client

Vai trò:

- camera sender
- mic sender
- HUD renderer mỏng
- session client

### 2.2 Jetson Runtime

Vai trò:

- media ingest
- speech ingest
- perception
- orchestration
- cloud escalation
- HUD scene compose

### 2.3 Optional Cloud

Vai trò:

- reasoning ngôn ngữ tự nhiên
- query phức tạp
- explanation
- multimodal grounding khi local không đủ

## 3. Trạng thái hiện tại và điểm pivot

## 3.1 Đã có

Hiện tại đã có nền rất tốt:

- stream video từ kính sang Jetson ổn
- app kính đã nhẹ hơn nhờ `Camera2 + MediaCodec Surface`
- Jetson đã có raw frame bus
- Jetson đã chạy YOLO26 thật
- Jetson đã có logic mode-aware cơ bản

## 3.2 Cần pivot

Điểm cần đổi lớn:

- bỏ tư duy `feature picker on glasses`
- bỏ logic sản phẩm nằm trong app kính
- thêm audio path
- thêm voice understanding
- thay `mode result` bằng `task runtime`
- thay `feature-specific HUD` bằng `declarative HUD scene`

## 4. Module map chi tiết

## 4.1 Kính: module mới và module giữ lại

Base project:

- `RokidVideoStream`

### Giữ lại

- [SurfaceVideoStreamPipeline.kt](RokidVideoStream/app/src/main/java/com/example/cxrservicedemo/videostream/SurfaceVideoStreamPipeline.kt)
- [VideoStreamTransport.kt](RokidVideoStream/app/src/main/java/com/example/cxrservicedemo/videostream/transport/VideoStreamTransport.kt)
- phần session/control nền trong [VideoStreamActivity.kt](RokidVideoStream/app/src/main/java/com/example/cxrservicedemo/videostream/VideoStreamActivity.kt)

### Cần tách mới

Nên tạo các file/module mới:

- `app/.../voice/GlassAudioCapture.kt`
  - đọc mic
  - encode `Opus mono`
  - push-to-talk state

- `app/.../voice/GlassAudioTransport.kt`
  - gửi audio packet sang Jetson
  - có sequence/timestamp đơn giản

- `app/.../hud/HudScene.kt`
  - model cho scene graph nhận từ Jetson

- `app/.../hud/HudSceneRenderer.kt`
  - render chip/card/marker/tile theo safe zone Rokid

- `app/.../hud/HudStyleTokens.kt`
  - màu, cỡ chữ, spacing, line width theo phong cách Rokid

- `app/.../hud/HudTileCache.kt`
  - cache thumbnail/tile nếu Jetson gửi crop gallery

- `app/.../session/GlassSessionCoordinator.kt`
  - điều phối video + audio + control + hud

### Nên giảm dần / bỏ dần

- UI mode selector cứng trong `VideoStreamActivity.kt`
- feature-specific HUD binding logic
- enum `ProductFeature` theo kiểu app tool

Mục tiêu cuối:

- app chỉ còn session state, mic state, HUD scene render

## 4.2 Jetson: module mới và module giữ lại

Base project:

- `rokidjetson/backend_mvp`

### Giữ lại

- [main.py](rokidjetson/backend_mvp/app/main.py)
  - nhưng sẽ cần tách nhỏ
- [ai_runtime.py](rokidjetson/backend_mvp/app/ai_runtime.py)
  - giữ phần YOLO26 runtime và track stabilization

### Cần tách mới

Nên tạo cấu trúc mới kiểu:

- `app/media/video_ingest.py`
  - nhận video frame
  - giữ raw frame bus

- `app/media/audio_ingest.py`
  - nhận Opus audio
  - decode stream nhỏ cho speech

- `app/speech/asr_runtime.py`
  - ASR streaming/local ASR adapter

- `app/speech/intent_router.py`
  - map transcript -> task type + slots

- `app/perception/perception_graph.py`
  - shared state: tracks, labels, colors, zones, faces, OCR snippets

- `app/perception/attribute_runtime.py`
  - color/person attribute extraction

- `app/perception/ocr_runtime.py`
  - OCR on demand

- `app/tasks/task_registry.py`
  - đăng ký runtime theo task

- `app/tasks/traffic_task.py`
- `app/tasks/face_memory_task.py`
- `app/tasks/find_person_by_attribute_task.py`
- `app/tasks/scene_summary_task.py`
- `app/tasks/read_text_task.py`
- `app/tasks/follow_target_task.py`

- `app/orchestrator/task_orchestrator.py`
  - lifecycle task
  - activation/deactivation
  - scheduling

- `app/cloud/evidence_bundle.py`
  - tạo payload gọn để gửi cloud

- `app/cloud/chatgpt_escalation.py`
  - adapter gọi OpenAI API

- `app/hud/hud_scene_protocol.py`
  - schema scene graph

- `app/hud/hud_scene_composer.py`
  - từ task result -> HUD scene

- `app/hud/tile_encoder.py`
  - low-color tile/crop encoding nếu cần

### Mục tiêu refactor backend

- `main.py` chỉ còn vai trò:
  - wire server
  - route message
  - giữ session
  - gọi orchestrator

## 5. Protocol cần thiết kế

## 5.1 Control protocol mới

Giữ WebSocket control hiện tại, nhưng mở rộng thêm message type.

### Từ kính lên Jetson

- `client_hello`
- `ping`
- `device_telemetry`
- `encoder_stats`
- `stream_log`
- `ptt_down`
- `ptt_up`
- `audio_hello`
- `audio_stats`

### Từ Jetson về kính

- `session_accept`
- `mode_state` (giai đoạn chuyển tiếp, sau này đổi tên)
- `task_state`
- `hud_scene`
- `tile_manifest`
- `tile_chunk`
- `speech_state`
- `assistant_reply`

## 5.2 Audio transport

Khuyến nghị:

- audio transport riêng với video
- không cần sync chặt với video
- framing đơn giản như video nhưng message type khác

### Audio header tối thiểu

- `sessionId`
- `sequence`
- `captureTimestampMs`
- `codec = opus`
- `sampleRate`
- `channels`
- `isSpeechStart`
- `isSpeechEnd`

### Khuyến nghị triển khai

Phase đầu:

- TCP riêng tương tự video

Phase sau nếu cần:

- gộp sang QUIC/WebRTC khi network thực sự đòi hỏi

## 5.3 HUD Scene Protocol

Đây là protocol quan trọng nhất của sản phẩm.

Jetson không nên gửi “HTML UI” hay “Android layout”.

Jetson nên gửi scene graph có cấu trúc rõ:

```json
{
  "type": "hud_scene",
  "version": 1,
  "sessionId": "sess_xxx",
  "sceneId": "scene_123",
  "priority": "foreground",
  "layout": "rokid_hud_v1",
  "components": [
    {
      "kind": "chip",
      "id": "task_chip",
      "zone": "top_center",
      "text": "Finding yellow shirt",
      "tone": "active"
    },
    {
      "kind": "gallery",
      "id": "candidate_gallery",
      "zone": "upper_right",
      "items": [
        {"tileId": "yellow_1", "label": "yellow 1"},
        {"tileId": "yellow_2", "label": "yellow 2"}
      ]
    },
    {
      "kind": "answer_strip",
      "id": "answer",
      "zone": "lower_safe",
      "text": "I found 2 people in yellow."
    }
  ]
}
```

### Component tối thiểu nên hỗ trợ

- `chip`
- `answer_strip`
- `alert_burst`
- `guide_line`
- `focus_bubble`
- `marker`
- `gallery`
- `mini_face_card`
- `directional_pill`

## 5.4 Tile protocol

Khi cần crop ảnh thật, Jetson không nên gửi ảnh to/full-color.

Nên gửi:

- tile nhỏ
- 1-bit / 2-bit / 4-bit grayscale hoặc limited green palette
- update theo manifest + chunk

### Tile use cases

- face candidate
- yellow shirt candidate gallery
- OCR crop preview
- target thumbnail

## 6. Perception graph chi tiết

Perception graph là lớp shared-state trung tâm.

Mỗi `track` nên có:

- `trackId`
- `label`
- `confidence`
- `bbox`
- `zone`
- `center`
- `velocityHint`
- `dominantColor`
- `upperBodyColor`
- `isVehicle`
- `isPerson`
- `faceMatchLabel`
- `ocrSnippet`
- `firstSeenMs`
- `lastSeenMs`

### Lợi ích

- runtime khác nhau không phải chạy lại detector từ đầu
- có thể answer query phức tạp trên cùng một graph
- dễ bundle evidence lên cloud

## 7. Reuse YOLO26 hiện tại như thế nào

## 7.1 Reuse level khuyến nghị

Phase đầu chỉ nên reuse:

- engine
- labels
- class assumptions
- inference adapter tách biệt

### Không nên phase đầu

- cắm trực tiếp vào process Ring
- dùng chung queue/process/thread với Ring

## 7.2 Cách đóng gói hợp lý

Nên có adapter kiểu:

- `Yolo26SharedArtifactAdapter`

Nó sẽ:

- load từ shared engine path
- chạy trong process Rokid riêng
- read-only
- không sửa gì phía Ring

## 7.3 Khi nào mới cân nhắc sâu hơn

Chỉ sau khi hệ Rokid ổn định lâu và benchmark tốt thì mới cân nhắc:

- shared inference service cho Ring + Rokid

Nhưng đây là phase sau, không phải phase đầu.

## 8. Task orchestration chi tiết

## 8.1 Từ transcript đến task

Pipeline:

- `ASR transcript`
- `intent parse`
- `slot extraction`
- `task selection`
- `task activation`
- `HUD update`

Ví dụ:

`tim nguoi mac ao vang`

-> `find_person_by_attribute`

slots:

- `subject = person`
- `attribute = yellow shirt`

## 8.2 Task lifecycle

Mỗi task nên có state:

- `idle`
- `warming`
- `active`
- `waiting_cloud`
- `resolved`
- `expired`
- `cancelled`

### Task API nội bộ nên có

- `start(context)`
- `update(perception_graph)`
- `compose_scene()`
- `build_evidence_if_needed()`
- `stop(reason)`

## 8.3 Task priority

Nên có priority:

- `foreground_user_query`
- `background_watch`
- `silent_monitor`

Ví dụ:

- user vừa hỏi `tìm người áo vàng` -> foreground
- traffic watch nền -> background
- idle scene understanding -> silent

## 9. Local-first / Cloud-smart chi tiết

## 9.1 Rule quyết định có cần cloud không

Chỉ escalate khi:

- local detector/attribute đủ candidate nhưng chưa đủ chắc để trả lời
- query có nhiều điều kiện ngôn ngữ
- user hỏi giải thích/tóm tắt phức tạp
- OCR + scene + person + context cần hợp nhất

## 9.2 Evidence bundling chuẩn

Bundle chuẩn nên gồm:

- transcript
- task type
- current HUD context
- 1-4 crops liên quan
- top candidate metadata
- OCR text nếu có
- scene summary gọn

### Không gửi

- full raw stream
- toàn bộ lịch sử frame
- nhiều crop trùng lặp

## 9.3 Kết quả cloud trả về

Cloud reply nên được map về:

- `answer`
- `confidence`
- `candidate ordering`
- `next prompt`

Rồi Jetson tự chuyển thành `hud_scene`.

## 10. Style system cho renderer kính

Renderer mới phải bám các nguyên tắc Rokid:

- see-through first
- center mostly clear
- quiet by default
- monochrome-first
- low cognitive load

### Design token nên chốt sớm

- safe zone top
- safe zone lower
- edge margin
- headline size
- chip size
- answer strip height
- gallery thumb size
- line thickness
- priority tone

### Palette khuyến nghị

Phase đầu:

- limited green-first
- amber cho attention
- red cho danger
- white/gray rất hạn chế nếu cần

Lý do:

- nhẹ hơn
- hợp HUD hơn
- dễ kiểm soát độ chói

## 11. Lộ trình triển khai theo phase

## Phase A - Foundation docs and schema

Deliverable:

- spec protocol audio
- spec HUD scene
- spec tile encoding
- module tree

Không chạm Ring.

## Phase B - Audio ingest MVP

App kính:

- thêm `GlassAudioCapture`
- thêm `GlassAudioTransport`
- thêm push-to-talk UX rất nhỏ

Jetson:

- thêm `audio_ingest.py`
- lưu/đọc audio frame
- chưa cần ASR hoàn chỉnh nếu muốn smoke test trước

Success criteria:

- Jetson nhận được audio packet ổn định

## Phase C - ASR + intent router MVP

Jetson:

- local ASR hoặc ASR adapter
- parse câu lệnh đơn giản
- map sang task runtime

Success criteria:

- nói được vài lệnh cơ bản:
  - `find yellow shirt`
  - `count vehicles`
  - `who do I know here`

## Phase D - Task runtime migration

Jetson:

- map `traffic`, `face`, `visual search` sang task runtime
- bỏ dần mode picker logic

App kính:

- vẫn có thể giữ compatibility fallback trong giai đoạn đầu

Success criteria:

- task được kích hoạt bằng voice, không cần chọn mode

## Phase E - HUD Scene Protocol

App kính:

- build `HudSceneRenderer`
- render chip, strip, gallery, marker

Jetson:

- build `HudSceneComposer`

Success criteria:

- Jetson quyết định nội dung hiển thị
- kính không còn phụ thuộc logic feature-specific UI

## Phase F - Attribute search

Jetson:

- upper-body color
- person attribute filtering
- candidate gallery

Success criteria:

- query `yellow shirt` hoạt động được

## Phase G - Cloud escalation

Jetson:

- evidence bundler
- OpenAI API adapter

Success criteria:

- chỉ query phức tạp mới đi cloud

## 12. Rủi ro và cách giảm thiểu

### Rủi ro 1: audio làm tăng tải kính

Giảm thiểu:

- push-to-talk trước
- mono Opus
- VAD nhẹ

### Rủi ro 2: app kính lại trôi thành phone UI

Giảm thiểu:

- chỉ nhận HUD scene
- cấm thêm screen-specific product logic vào app

### Rủi ro 3: Jetson quá tải vì vừa speech vừa vision

Giảm thiểu:

- cadence perception theo task
- idle mode nhẹ
- cloud chỉ reasoning, không làm realtime detection

### Rủi ro 4: ảnh hưởng hệ Ring

Giảm thiểu:

- reuse artifact only
- isolated runtime
- benchmark riêng
- không sửa service Ring

## 13. Chốt kiến nghị thực thi ngay

Nếu bắt đầu code thật từ ngày mai, thứ tự nên là:

1. tạo `rokid_audio_protocol.md`
2. tạo `rokid_hud_scene_protocol.md`
3. thêm audio ingest MVP ở kính + Jetson
4. thêm `intent_router.py`
5. tách `task_orchestrator.py`
6. sau đó mới bắt đầu bỏ mode picker

Đây là thứ tự ít rủi ro nhất và bám đúng sản phẩm đích nhất.
