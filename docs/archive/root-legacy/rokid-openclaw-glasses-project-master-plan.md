# Rokid + OpenClaw Glasses-Only Master Plan

## 0. Snapshot quyết định

| Hạng mục | Kết luận ngắn |
| --- | --- |
| Hướng sản phẩm | `GO`, nhưng chỉ theo hướng `glasses-only` |
| Kiến trúc đúng | `Rokid -> app native trên kính -> STT/backend riêng -> OpenClaw` |
| STT nên chọn | `streaming ASR trên server` làm chính |
| STT fallback | `sherpa-onnx`, sau đó mới cân nhắc `Vosk` |
| Repo nên mod | `einkbro`, `openclaw-rokid-glasses`, `openclaw-secure-stack` |
| Repo chỉ nên học | `RokidAIAssistant`, `rokid-openvoice-sdk` |
| Độ khó tổng thể | `trung bình đến cao` nếu mod đúng nền, `rất cao` nếu tự viết từ số 0 |
| Rủi ro lớn nhất | cố làm full on-device STT, cố phụ thuộc phone, hoặc cố dùng browser đầy đủ |
| Vòng lặp MVP phải chứng minh | `bấm nói -> text hiện -> gửi OpenClaw -> nhận trả lời -> gửi ảnh khi cần` |
| Tiêu chí dừng sớm | nếu voice loop không mượt sau MVP core, không mở rộng thêm tính năng |

## 1. Mục tiêu của dự án

Mục tiêu là xây một hệ thống AI cho `Rokid Glasses` hoạt động **tự chủ trên kính**, không phụ thuộc vào:

- app companion trên iPhone
- bridge qua điện thoại Android
- SDK phone-side của Rokid
- luồng voice/AI mặc định của `Hi Rokid`

Mục tiêu thực tế hơn:

- kính tự kết nối Wi-Fi
- app chạy trực tiếp trên kính
- người dùng nói trên kính
- audio được xử lý và đẩy về backend của chúng ta
- backend trả transcript và phản hồi AI về lại kính
- kính có thể lấy ảnh/file gần đây để gửi lên backend

Tư duy đúng cho dự án này là:

`Rokid -> app native trên kính -> backend riêng -> OpenClaw`

không phải:

`Rokid -> iPhone/Android companion -> backend`

---

## 2. Ràng buộc cứng của dự án

### 2.1. Ràng buộc người dùng

- Người dùng chính đang dùng `iPhone`.
- Vì vậy dự án **không nên** dựa vào app Android companion làm não chính.
- iOS cũng không phải hướng phù hợp để tự viết app bridge sâu cho Rokid trong giai đoạn này.

### 2.2. Ràng buộc thiết bị

Theo các ghi chú hiện có trong workspace, `Rokid Glasses` nên được xem như:

- thiết bị Android-based / `YodaOS-Sprite`
- màn hình nhỏ kiểu HUD
- low-RAM
- không phải touch-first device
- phù hợp với app nhỏ, rõ, ít trạng thái, ít animation nặng

### 2.3. Ràng buộc kỹ thuật

- Không nên build một app quá nặng, quá nhiều màn hình, hoặc phụ thuộc sâu vào GMS.
- Không nên đặt cược toàn bộ vào dịch vụ speech hệ thống của Rokid, vì API public cho nhánh kính mới còn phân mảnh.
- Không nên để WebView tự gánh phần khó nhất như STT, file access, media capture.
- Không nên dùng iPhone như thành phần bắt buộc trong runtime.

---

## 3. Câu hỏi quyết định của dự án

### 3.1. Chúng ta có nên làm không?

Có, nhưng chỉ nếu chấp nhận một định nghĩa dự án rõ ràng:

- `glasses-only`
- app native mỏng trên kính
- backend chịu phần AI/STT chính
- client ưu tiên ổn định hơn là “all-in-one”

### 3.2. Chúng ta có nên tự xây từ số 0 hoàn toàn không?

Không.

Đường đúng là:

- fork hoặc mod lại phần `browser shell`
- fork hoặc học lại phần `OpenClaw bridge`
- chỉ tự viết phần đặc thù nhất cho dự án:
  - STT pipeline
  - native bridge trên kính
  - auth/session cho thiết bị
  - glass-friendly UI

---

## 4. Kiến trúc đề xuất đã chốt

## 4.1. Kiến trúc tổng thể

```text
Rokid Glasses
  -> OpenClaw Glass Shell App
     -> Native audio capture
     -> Push-to-talk hoặc VAD
     -> Streaming audio lên backend
     -> Native media/file bridge
     -> Single-site WebView hoặc UI native tối giản
  -> Cloudflare Tunnel / Auth layer
  -> STT Gateway
  -> OpenClaw Bridge
  -> openclaw-secure-stack / OpenClaw backend
```

## 4.2. Phân vai từng lớp

### A. App trên kính

Chịu trách nhiệm:

- mở mic
- xử lý `push-to-talk` hoặc `tap-to-talk`
- streaming audio
- hiển thị partial/final transcript
- lấy ảnh/file gần đây
- upload ảnh/file
- hiển thị UI chat chuẩn kính

Không nên chịu trách nhiệm:

- reasoning nặng
- speech recognition chính
- session business logic phức tạp
- memory dài hạn

### B. STT Gateway

Chịu trách nhiệm:

- nhận audio stream từ kính
- chạy ASR tiếng Việt dạng streaming
- trả `partial transcript`
- chốt `final transcript`

### C. OpenClaw Bridge

Chịu trách nhiệm:

- nhận transcript/final query
- chuẩn hóa request cho `openclaw-secure-stack`
- quản lý session mức thiết bị
- stream response về kính

### D. OpenClaw backend

Chịu trách nhiệm:

- reasoning
- tool calling
- memory
- vision
- agent orchestration

---

## 5. Chốt lựa chọn STT

## 5.1. Kết luận chiến lược

Hướng STT phù hợp nhất là:

- **chính**: `streaming audio lên server ASR`
- **phụ/fallback**: on-device STT cho lệnh ngắn hoặc khi mất mạng

Đây là điểm rất quan trọng. Không nên lấy on-device STT làm lõi ngay từ đầu.

## 5.2. Vì sao không nên lấy full on-device STT làm lõi

- tiếng Việt hội thoại tự do khó hơn command ngắn
- kính là thiết bị low-RAM
- dễ bị tăng nhiệt, tăng pin, tăng latency chốt câu
- khó nâng cấp model khi đã đóng gói vào app
- khó debug hơn server-side ASR

## 5.3. Phương án STT được ưu tiên

### Phương án 1: Streaming ASR trên server

Đây là hướng nên chọn làm chính.

Ưu điểm:

- độ chính xác tiếng Việt tốt hơn
- dễ thay model
- dễ quan sát log
- dễ tinh chỉnh VAD/end-of-speech
- giảm gánh nặng cho kính

Nhược điểm:

- phụ thuộc mạng
- cần backend ASR vận hành ổn định

### Phương án 2: `sherpa-onnx` làm fallback/local command

Đây là lựa chọn on-device tốt nhất hiện tại để cân nhắc cho kính.

Phù hợp với:

- lệnh ngắn
- fallback khi mất mạng
- command cơ bản như:
  - mở menu
  - chụp ảnh
  - gửi ảnh
  - thoát

Ưu điểm:

- offline
- Android-friendly
- cộng đồng kỹ thuật tốt
- có hướng realtime + VAD

Nhược điểm:

- vẫn cần kiểm chứng thực tế trên Rokid
- không nên kỳ vọng thay thế hoàn toàn server ASR

### Phương án 3: `Vosk` cho command set rất nhẹ

Chỉ hợp nếu:

- cần cực nhẹ
- command grammar nhỏ
- chấp nhận chất lượng hội thoại tự do không cao

### Phương án 4: Speech stack hệ thống của Rokid / OpenVoice

Chỉ nên nghiên cứu như một hướng tăng tốc nếu móc được.

Không nên coi đây là nền tảng chính cho dự án vì:

- tài liệu public chưa đồng đều
- nguy cơ phụ thuộc firmware/system service
- dễ bị lock-in vào behavior của Rokid

## 5.4. Chốt kỹ thuật STT

Chốt cho giai đoạn đầu:

- `Push-to-talk` trước
- audio `16kHz mono`
- streaming lên `STT Gateway`
- server trả `partial + final transcript`

Chưa nên làm ngay:

- wake word phức tạp
- voice always-on
- tự động hội thoại rảnh tay hoàn toàn

---

## 6. Độ trễ kỳ vọng

Nếu pipeline được làm đúng theo hướng streaming:

- partial transcript: khoảng `300-700ms`
- final transcript: khoảng `0.8-1.8s`
- command ngắn có thể cho cảm giác gần như tức thì

Độ trễ sẽ xấu nếu:

- ghi âm xong mới upload nguyên file
- backend ở quá xa
- auth quá nhiều lớp cho mỗi lần nói
- VAD kết thúc câu quá chậm

Kết luận:

- dự án **có thể đủ nhanh để dùng thật**
- nhưng chỉ khi đi theo `streaming`
- không nên dùng kiểu `record-then-upload`

---

## 7. Những gì có thể tận dụng từ cộng đồng

## 7.1. Những repo đáng dùng làm nền

### 1. `einkbro`

Vai trò nên dùng:

- donor tốt nhất cho `single-site shell app`
- WebView shell
- mic permission
- file chooser
- JavaScript bridge
- nền Android app đủ trưởng thành để mod

Điểm mạnh:

- không phụ thuộc phone
- chạy on-device
- gần nhất với thứ ta cần ở client

Điểm yếu:

- là browser đầy đủ, nên phải cắt bỏ khá nhiều
- không sinh ra riêng cho Rokid/OpenClaw

Kết luận:

- **nên fork/mod**

### 2. `openclaw-rokid-glasses`

Vai trò nên dùng:

- donor cho backend bridge
- chuyển request thiết bị thành OpenAI-style request
- SSE relay
- auth/rate limit/history/image handling

Điểm mạnh:

- nhỏ
- dễ hiểu
- hợp để fork nhanh

Điểm yếu:

- không có app kính
- không có STT
- giả định text đã có sẵn

Kết luận:

- **nên fork phần backend**

### 3. `openclaw-secure-stack`

Vai trò nên dùng:

- lớp backend an toàn hơn cho OpenClaw
- governance / sanitize / audit

Điểm mạnh:

- hợp production hơn
- giữ backend thành phần rõ ràng

Điểm yếu:

- không giải quyết client kính

Kết luận:

- **nên giữ làm backend nền nếu đã quen stack này**

### 4. `RokidAIAssistant`

Vai trò nên dùng:

- donor tham khảo cho pattern app AI trong hệ Rokid
- xem cách họ tổ chức modules `phone-app / glasses-app / common`
- học cách xử lý photo/AI interaction trong ecosystem Rokid

Điểm mạnh:

- gần thế giới Rokid
- có nhiều tính năng AI thật

Điểm yếu:

- lệ thuộc mạnh vào phone-side pattern
- không hợp với mục tiêu `iPhone + glasses-only`

Kết luận:

- **chỉ nên học kiến trúc / UI / flow**
- **không nên lấy làm nền chính**

### 5. `rokid-openvoice-sdk`

Vai trò nên dùng:

- reference cho OpenVoice / speech chain hệ thống Rokid

Điểm mạnh:

- sát với speech stack chính chủ

Điểm yếu:

- rủi ro phụ thuộc private/system behavior
- không chắc bám được branch firmware hiện tại

Kết luận:

- **chỉ nên nghiên cứu tăng tốc**
- **không nên đặt cược cả dự án**

### 6. `RokidClaw`

Vai trò nên dùng:

- donor tốt nhất hiện tại cho `voice loop direct on-glasses`
- tham khảo cách dùng `AudioRecord`
- tham khảo cách gửi audio thô lên server STT
- tham khảo vòng lặp tối thiểu `record -> transcribe -> ask -> speak`

Điểm mạnh:

- chứng minh hướng `app trực tiếp trên kính + server STT` là làm được
- đã tránh phụ thuộc vào `SpeechRecognizer` hệ thống
- có code Kotlin Android thật, không chỉ là ý tưởng

Điểm yếu:

- vẫn là prototype, chưa phải production app
- bridge server còn thô, thiên về lab/local LAN
- chưa có streaming partial transcript
- cấu hình và locale đang thiên về tiếng Trung

Kết luận:

- **rất nên lấy làm donor cho phần audio capture / PTT / TTS**
- **không nên dùng nguyên xi làm nền sản phẩm**

### 7. `rokid-lingzhu-openclaw`

Vai trò nên dùng:

- donor tốt nhất hiện tại cho `official custom-agent path`
- bridge SSE giữa hệ chính thức của Rokid và OpenClaw
- tham khảo mapping giữa tool calls của OpenClaw và action trong hệ Rokid

Điểm mạnh:

- là đường nhanh nhất để đưa OpenClaw vào hệ chính thức của Rokid
- code plugin rõ ràng, nhỏ, dễ đọc
- hỗ trợ `agentId`, session key, heartbeat, tool call, follow-up

Điểm yếu:

- phụ thuộc `Lingzhu platform`
- phụ thuộc `Rokid AI App`
- không phải hướng `glasses-only autonomy`
- không giải quyết STT/app native riêng

Kết luận:

- **nên giữ làm nhánh thử nghiệm official/fallback**
- **không nên thay thế kiến trúc đích nếu mục tiêu là tự chủ**

### 8. `rokid-direct-openclaw-plan`

Vai trò nên dùng:

- donor tốt nhất hiện tại cho `kiến trúc client native dài hạn`
- tham khảo WebSocket state machine
- tham khảo history/session/reconnect/notification design
- tham khảo protocol draft cho chat/sync/history

Điểm mạnh:

- rất gần với kiến trúc chúng ta đang định làm
- tách rõ `transport / session / sync / local DB / notification`
- giúp giảm rủi ro thiết kế sai ở giai đoạn sau

Điểm yếu:

- hiện chủ yếu là plan + skeleton
- chưa có STT thật
- chưa có media/TTS/history hoàn chỉnh
- chưa phải repo có thể fork xong chạy ngay

Kết luận:

- **rất nên dùng làm tài liệu thiết kế tham khảo**
- **chưa đủ để làm nền implementation chính**

## 7.2. Tổng kết reuse

Những phần có thể mod lại:

- browser shell: `einkbro`
- backend bridge: `openclaw-rokid-glasses`
- backend security/governance: `openclaw-secure-stack`
- Rokid-specific ideas: `RokidAIAssistant`, `Rokid-Maps`, `Rokid_Wifi`, `Rokid-Shell`
- voice loop donor: `RokidClaw`
- official custom-agent donor: `rokid-lingzhu-openclaw`
- native client architecture donor: `rokid-direct-openclaw-plan`

Những phần phải tự viết:

- app flow riêng cho OpenClaw trên kính
- STT streaming pipeline
- native media bridge
- auth/session giữa kính và backend
- UI chuẩn kính cho dự án này

---

## 8. Đánh giá cộng đồng hỗ trợ

## 8.1. Mức độ cộng đồng Rokid

Cộng đồng có thật, nhưng nhỏ và phân mảnh.

Điều tốt:

- có nhiều repo nhỏ chứng minh app on-device là khả thi
- có mẫu cho HUD, Wi-Fi helper, shell, maps, AI assistant, uploader

Điều không tốt:

- API public không đồng nhất giữa các đời thiết bị
- tài liệu mới và cũ bị phân mảnh
- ít repo “production-ready” trọn gói

Kết luận:

- cộng đồng đủ để **giảm công khám phá**
- chưa đủ để “fork 1 cái là xong”

## 8.2. Mức độ cộng đồng OpenClaw

Cộng đồng OpenClaw có ích chủ yếu ở backend, proxy, skill, deploy, orchestration.

Điều tốt:

- dễ tái sử dụng tầng agent/backend
- có thể giữ nguyên triết lý OpenClaw

Điều không tốt:

- không có sẵn client Rokid hoàn chỉnh đúng nhu cầu

Kết luận:

- OpenClaw giúp nhiều ở backend
- gần như không giúp được phần app kính nếu không tự xây

## 8.3. Lingzhu là gì trong bài toán này

`Lingzhu` là luồng dev mà Rokid mở ra cho cộng đồng để tích hợp `custom agent` vào hệ chính thức của kính / Rokid AI App.

Hiểu đúng vai trò của `Lingzhu`:

- nó là `official custom-agent integration path`
- nó không phải SDK thay thế cho app native trên kính
- nó không phải cách để kiểm soát toàn bộ stack của kính

Nếu đi qua `Lingzhu`, luồng thực tế sẽ là:

`Voice -> Rokid stack / Rokid AI App -> Lingzhu platform -> server của bạn -> OpenClaw -> SSE trả ngược lại`

Điều này có nghĩa:

- bạn có thể thay `AI brain` trả lời bằng backend/model của bạn
- nhưng bạn không chắc thay được toàn bộ speech pipeline gốc của Rokid
- bạn không có cùng mức kiểm soát như khi tự viết app native

Kết luận:

- `Lingzhu` là đường official rất tốt để validate backend AI
- nhưng không phải đích cuối nếu mục tiêu là hệ `glasses-only` tự chủ

## 8.4. Rủi ro bảo mật và riêng tư khi đi qua Lingzhu

Đi qua `Lingzhu` sẽ làm chuỗi trust dài hơn:

`kính -> Rokid stack -> Lingzhu -> server của bạn -> OpenClaw`

Rủi ro tăng lên ở các điểm:

- transcript hoặc context đi qua hạ tầng Rokid trước khi đến server của bạn
- bạn phải mở public endpoint cho platform gọi vào
- auth chủ yếu ở dạng `AK/Bearer`, cần tự tăng cường thêm reverse proxy / rate limit / TLS / logging
- mức kiểm soát dữ liệu thấp hơn so với luồng direct-native

Kết luận:

- `Lingzhu` phù hợp cho:
  - PoC
  - lab
  - cá nhân
  - dữ liệu không quá nhạy cảm
- `Lingzhu` không phải lựa chọn tối ưu nếu:
  - cần tự chủ dữ liệu
  - cần kiểm soát end-to-end
  - cần production/privacy cao

## 8.5. Lingzhu làm được gì và không làm được gì

Từ các repo đã xem, `Lingzhu` hiện làm tốt:

- request/response AI theo phiên hỏi đáp
- SSE streaming response
- một số `tool_call` như:
  - `take_photo`
  - `take_navigation`
  - `control_calendar`
  - `notify_agent_off`
- `follow_up` suggestions
- truyền một phần context thiết bị

Nhưng hiện **chưa có bằng chứng public chắc tay** rằng `Lingzhu` hỗ trợ:

- server chủ động nhắn tin như push tùy ý
- đánh thức kính từ trạng thái ngủ như một push/wake channel độc lập
- proactive notifications hoàn chỉnh cho custom agent

Kết luận:

- `Lingzhu` mạnh ở custom AI trong luồng chính thức
- `native app` mạnh ở background, proactive messaging, wake, notification và full control

---

## 9. Lựa chọn sản phẩm nên chốt

## 9.1. Sản phẩm không nên làm ngay

- trợ lý always-on
- wake word full-time
- đa màn hình phức tạp
- browser đầy đủ
- desktop-like shell
- phụ thuộc phone

## 9.2. Sản phẩm nên làm trước

Một app rất nhỏ với đúng 4 nhóm chức năng:

- `push-to-talk`
- `stream transcript`
- `chat AI`
- `gửi ảnh vừa chụp / ảnh gần đây`

Nếu 4 nhóm này chạy mượt, dự án sống.

Nếu 4 nhóm này không mượt, không nên mở rộng thêm.

## 9.3. Hai nhánh chiến lược có thể đi song song

### Nhánh A: Official shortcut

Mục tiêu:

- validate nhanh backend AI/OpenClaw
- không tự viết app kính ở giai đoạn đầu

Làm bằng:

- `rokid-lingzhu-openclaw`

Ưu điểm:

- nhanh nhất
- ít công nhất
- dùng flow chính thức

Nhược điểm:

- phụ thuộc Rokid stack
- ít tự chủ
- rủi ro riêng tư cao hơn

### Nhánh B: Native long-term

Mục tiêu:

- tự chủ thật sự
- kiểm soát speech, UI, media, privacy

Làm bằng:

- `RokidClaw` + `einkbro` + `rokid-direct-openclaw-plan` + backend của riêng bạn

Ưu điểm:

- đúng đích dài hạn
- kiểm soát tốt hơn

Nhược điểm:

- khó hơn
- lâu hơn
- nhiều việc hơn

Kết luận:

- `Nhánh A` hợp để kiểm chứng nhanh
- `Nhánh B` là đích cuối nếu vẫn quyết theo hướng tự chủ

---

## 10. Roadmap từng bước

## Giai đoạn 0: Kiểm chứng sống còn

Mục tiêu:

- xác nhận kính chạy app Android on-device ổn
- xác nhận mic/camera/file/WebView dùng được trong app mod
- xác nhận networking trực tiếp từ kính lên backend riêng

Việc cần làm:

1. Fork `einkbro`.
2. Biến thành app chỉ mở đúng 1 domain.
3. Loại bỏ tab, bookmark, search, history, menu nặng.
4. Giữ lại:
   - WebView
   - mic permission
   - file chooser
   - JS bridge
5. Build APK và cài lên kính.
6. Xác nhận:
   - app mở được
   - load được web của bạn
   - có thể xin mic permission
   - có thể chọn file/ảnh

Tiêu chí pass:

- app stable trên kính tối thiểu 10-15 phút
- không crash liên tục
- load được 1 domain duy nhất

Độ khó:

- thấp đến trung bình

Khả thi:

- cao

## Giai đoạn 1: MVP voice loop

Mục tiêu:

- từ kính nói được
- transcript final hiện về
- câu hỏi được gửi lên OpenClaw
- câu trả lời quay về kính

Việc cần làm:

1. Thêm `push-to-talk`.
2. Native app thu audio `16kHz mono`.
3. Stream audio lên `STT Gateway`.
4. Nhận `partial/final transcript`.
5. Final transcript gửi sang `OpenClaw Bridge`.
6. Stream phản hồi AI về UI.

Tiêu chí pass:

- partial text có cảm giác nhanh
- final transcript ổn
- end-to-end roundtrip đủ mượt để dùng

Độ khó:

- trung bình đến cao

Khả thi:

- cao nếu backend ASR ổn

## Giai đoạn 2: media bridge

Mục tiêu:

- gửi ảnh gần đây hoặc ảnh vừa chụp lên backend

Việc cần làm:

1. Thêm native action:
   - lấy ảnh gần nhất
   - mở picker ảnh
   - upload ảnh
2. Backend nhận ảnh.
3. OpenClaw gọi vision flow.

Tiêu chí pass:

- ảnh được gửi với ít thao tác
- phản hồi vision quay về kính rõ ràng

Độ khó:

- trung bình

Khả thi:

- trung bình đến cao

## Giai đoạn 3: polish cho trải nghiệm kính

Mục tiêu:

- tối ưu UI/UX thật sự cho HUD

Việc cần làm:

1. Tối ưu font, contrast, line-length.
2. Chuyển response thành dạng ngắn.
3. Tối ưu focus/key events.
4. Giảm animation, giảm rerender.
5. Bổ sung trạng thái:
   - listening
   - thinking
   - speaking
   - upload image

Tiêu chí pass:

- dùng được ngoài đời
- không “web quá”, không “browser quá”

Độ khó:

- trung bình

Khả thi:

- cao

## Giai đoạn 4: fallback offline

Mục tiêu:

- thêm command ngắn khi mất mạng hoặc khi muốn giảm roundtrip

Việc cần làm:

1. Tích hợp `sherpa-onnx` hoặc `Vosk`.
2. Chỉ map cho command ngắn.
3. Không dùng để thay toàn bộ server ASR.

Tiêu chí pass:

- command ngắn hoạt động offline

Độ khó:

- trung bình đến cao

Khả thi:

- trung bình

---

## 11. Độ khó tổng thể

## 11.1. Nếu tự xây từ số 0

Độ khó: `rất cao`

Rủi ro:

- mất nhiều tuần chỉ để dựng nền client
- dễ sa vào app architecture chung chung
- dễ build sai form factor kính

## 11.2. Nếu mod đúng các repo nền

Độ khó: `trung bình đến cao`

Đây là mức chấp nhận được.

Lý do:

- tận dụng được shell app
- tận dụng được bridge backend
- chỉ tập trung vào phần đặc thù nhất

## 11.3. Ước lượng thực tế

Nếu làm gọn, không lan man:

- Giai đoạn 0 + 1: khả thi trong vài tuần
- Giai đoạn 2: thêm vài tuần
- Giai đoạn 3 + 4: tùy độ polish

Nếu cố làm full sản phẩm ngay từ đầu:

- rất dễ kéo dài và mơ hồ

---

## 12. Các ngõ cụt cần tránh

### 1. Xây browser đầy đủ rồi cố “biến thành AI app”

Sai hướng vì:

- quá nhiều tính năng thừa
- UX nặng
- khó khóa hành vi

Chỉ nên làm `single-site shell`, không phải browser đầy đủ.

### 2. Cố dùng iPhone làm thành phần runtime bắt buộc

Sai hướng vì:

- trái với mục tiêu tự chủ của kính
- tăng độ phức tạp pairing/bridge

### 3. Đặt cược hoàn toàn vào STT on-device

Sai hướng vì:

- tiếng Việt khó
- dễ chậm
- khó bảo trì

### 4. Đặt cược hoàn toàn vào speech stack hệ thống Rokid

Sai hướng vì:

- khó đoán độ bền của API
- dễ phụ thuộc branch firmware

### 5. Làm wake-word / always-listening quá sớm

Sai hướng vì:

- tăng độ khó lớn
- đốt pin
- tăng lỗi false trigger

---

## 13. Checkpoint ra quyết định để tránh mất thời gian

## Checkpoint A: sau Giai đoạn 0

Hỏi:

- app shell mod từ `einkbro` có chạy ổn trên kính không?
- mic, file, WebView có hoạt động không?

Nếu `không`:

- dừng hoặc pivot sang app native tối giản không dùng WebView làm trung tâm

## Checkpoint B: sau Giai đoạn 1

Hỏi:

- end-to-end voice loop có đủ nhanh không?
- transcript có đủ ổn cho tiếng Việt không?

Nếu `không`:

- đổi backend ASR trước
- chưa được thì dừng mở rộng

## Checkpoint C: sau Giai đoạn 2

Hỏi:

- media bridge có mượt không?
- người dùng có gửi ảnh dễ dàng không?

Nếu `không`:

- đơn giản hóa flow ảnh
- không mở rộng sang vision phức tạp

## Checkpoint D: trước khi thêm offline STT

Hỏi:

- online flow đã đủ tốt chưa?

Nếu `chưa`:

- không nên thêm offline STT, vì sẽ chỉ tăng hỗn loạn

---

## 14. Đánh giá khả thi cuối cùng

## 14.1. Đánh giá tổng thể

### Khả thi kỹ thuật

`Cao`

Lý do:

- Rokid là thiết bị Android-based
- đã có nhiều app on-device từ cộng đồng
- có Wi-Fi
- có thể chạy app riêng
- có donor repo đủ tốt để mod

### Khả thi sản phẩm

`Trung bình đến cao`

Lý do:

- use case rất rõ
- form factor kính phù hợp với assistant ngắn gọn
- nếu tập trung vào voice + ảnh + chat thì phạm vi đủ chặt

### Khả thi cộng đồng / tái sử dụng

`Trung bình đến cao`

Lý do:

- hiện đã có donor rõ hơn cho từng lớp:
  - `RokidClaw` cho audio loop
  - `rokid-lingzhu-openclaw` cho official custom-agent path
  - `rokid-direct-openclaw-plan` cho native architecture
- vẫn chưa có repo nào cover trọn gói thành sản phẩm hoàn chỉnh

### Khả thi STT

`Cao` nếu dùng server ASR

`Trung bình` nếu cố full on-device ngay từ đầu

### Khả thi của hướng `native streaming voice app`

`Trung bình đến cao` ở mức MVP

`Trung bình` ở mức app hoàn chỉnh/polished

Lý do:

- đã có bằng chứng cộng đồng rằng `AudioRecord -> server STT` chạy được trên kính
- khó nhất không còn là “có stream được voice hay không”
- khó nhất là ghép các phần:
  - STT loop
  - HUD/UI
  - history
  - reconnect
  - background
  - media bridge

Kết luận:

- hướng `stream voice qua server` **không phải ngõ cụt**
- nhưng chỉ nên nhắm tới `MVP mạnh` trước, chưa nên nhắm ngay app hoàn chỉnh

---

## 14.2. Mức độ có nguy cơ đi vào ngõ cụt không?

Có nguy cơ, nhưng **không cao** nếu giữ đúng phạm vi.

Ngõ cụt sẽ xảy ra nếu:

- cố phụ thuộc phone
- cố dùng full browser
- cố làm full on-device ASR
- cố tích hợp quá sâu vào API private của Rokid

Ngược lại, dự án **không phải ngõ cụt** nếu:

- lấy `glasses-only` làm trục
- app trên kính chỉ là thin client mạnh vừa đủ
- backend gánh STT + AI chính
- dùng repo sẵn có để rút ngắn quãng khám phá
- chấp nhận `Lingzhu` như nhánh official tạm thời nếu cần validate backend nhanh

---

## 15. Kết luận cuối cùng

### Kết luận ngắn

Đây là dự án **nên làm**, với điều kiện:

- bắt đầu nhỏ
- đi theo `glasses-only`
- dùng `server ASR` làm lõi
- lấy `RokidClaw` làm donor cho audio loop
- lấy `einkbro` làm donor cho shell/WebView khi cần
- lấy `rokid-direct-openclaw-plan` làm donor cho session/reconnect design
- dùng `rokid-lingzhu-openclaw` như nhánh official/fallback để test backend nhanh
- fork `openclaw-rokid-glasses` cho backend bridge nếu cần lớp adapter riêng
- giữ `openclaw-secure-stack` cho lớp backend nếu cần governance

### Kết luận quyết định

`GO`, nhưng theo lộ trình hẹp, có checkpoint dừng sớm, và nên tách rõ:

- nhánh official để validate nhanh
- nhánh native để đi tới tự chủ thật sự

### Câu chốt quan trọng nhất

Không nên hỏi:

- “làm được full hệ thống hoàn chỉnh ngay không?”

Mà nên hỏi:

- “chúng ta có tạo được một vòng lặp cực nhỏ nhưng dùng thật được không?”

Vòng lặp đó là:

`bấm nói -> text hiện -> gửi OpenClaw -> nhận trả lời -> gửi ảnh khi cần`

Nếu vòng lặp này chạy mượt, dự án sống.

Nếu vòng lặp này không mượt, nên dừng trước khi đầu tư thêm.

---

## 16. Hành động khuyến nghị ngay bây giờ

1. Nếu muốn ra kết quả nhanh nhất:
   - thử `rokid-lingzhu-openclaw` để validate backend/agent/tool flow trước
2. Nếu muốn đi đúng đích dài hạn:
   - lấy `RokidClaw` để dựng `push-to-talk + AudioRecord + server STT`
3. Sau đó:
   - lấy `rokid-direct-openclaw-plan` để thiết kế session/reconnect/history
4. Chỉ khi cần WebView shell / file bridge rõ ràng hơn:
   - fork `einkbro`
5. Cuối cùng mới hợp nhất thành:
   - `OpenClaw Glass Shell`
   - `STT Gateway`
   - `OpenClaw Bridge`

Đây là thứ tự có xác suất thành công cao nhất và ít rủi ro mất thời gian nhất sau khi đã đối chiếu thêm các repo cộng đồng mới.
