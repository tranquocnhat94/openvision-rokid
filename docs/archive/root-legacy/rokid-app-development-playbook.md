# Rokid App Development Playbook

Ngày tổng hợp: 2026-04-07

Mục tiêu của file này là biến danh sách dự án trong `awesome-rokid` thành một tài liệu làm việc thực dụng: khi cần tự viết app cho kính Rokid, chúng ta có thể mở file này ra để quyết định nhanh kiến trúc, stack, giao tiếp, UI, input, và cách debug.

File này bổ sung cho `rokid-glasses-research.md`: file cũ nghiêng về thông số nền tảng và reverse-engineering tổng quát, còn file này nghiêng về "cách cộng đồng đang thật sự viết app cho Rokid".

## 1. Kết luận nhanh

Nếu chỉ cần nắm tinh thần chung, đây là 10 điểm quan trọng nhất:

1. `Rokid Glasses` hiện nên được xem như một thiết bị `Android 12 / YodaOS-Sprite`, màn hình `480x640` dọc, low-RAM, không có touchscreen thật.
2. Hầu hết app cộng đồng chạy tốt đều là `native Android app`, chủ yếu bằng `Kotlin`, đôi khi `Java`.
3. Hai kiến trúc thành công nhất là:
   - `glasses-native app`
   - `phone + glasses companion` qua `CXR` hoặc `Bluetooth SPP`
4. Nếu app cần AI nặng, gần như ai cũng đẩy phần thông minh ra `phone` hoặc `backend`, còn kính chỉ lo `capture + HUD + input`.
5. Nếu app chỉ là utility/HUD đơn giản, chạy native trực tiếp trên kính là hợp lý nhất.
6. Không nên giả định có `GMS/Google Play Services`; nhiều repo tránh hoàn toàn Google SDK.
7. UI phải đi theo tư duy `focus-based`, `D-pad / KeyEvent`, chữ to, ít thông tin, nền tối, màu xanh/đơn sắc.
8. Stack thư viện lặp lại nhiều nhất: `CameraX`, `OkHttp`, `Retrofit`, `Gson/Kotlinx Serialization`, `CXR client-m`, `Room`, `osmdroid`, `NanoHTTPD`, `Vosk`, `sherpa-onnx`.
9. Với app cần tích hợp sâu vào hệ, có 3 cửa chính:
   - `CXR-M` trên điện thoại
   - `CXR-S` trên kính
   - `AssistServer` / service nội bộ của hệ thống
10. Trên Rokid, thành công thường đến từ app nhỏ, rõ, một nhiệm vụ mỗi màn hình; thất bại thường đến từ app quá nặng, phụ thuộc touch, hoặc phụ thuộc GMS.

## 2. Hệ sinh thái trong `awesome-rokid` cho thấy gì?

Khi gom các repo lại, hệ sinh thái hiện chia thành 6 nhóm rất rõ:

### 2.1 Native app chạy trực tiếp trên kính

Các ví dụ:

- `Rokid-Shell`
- `Rokid_Wifi`
- `rokid-ar-navigation`
- `RokidSmartLife`
- `photoDel4rokidglasses`
- `rokid-ssh-terminal`

Đây là nhóm tốt nhất nếu chúng ta muốn viết app "chạm trực tiếp" vào trải nghiệm trên kính: file explorer, HUD, settings helper, Wi-Fi helper, terminal, học tập, viewer.

### 2.2 Phone + glasses companion

Các ví dụ:

- `Rokid-Maps`
- `Rokid-GMaps`
- `RokidAIAssistant`
- `Clawsses`
- `NeuroGlasses`
- `Rokid Lyrics`

Pattern chung:

- Phone làm phần nặng: GPS, route, AI, network, DB, notification, upload APK.
- Kính làm phần nhẹ: hiển thị HUD, nhận input, camera, mic, loa, xác nhận thao tác.

### 2.3 Glasses-native + backend AI

Các ví dụ:

- `openclaw-rokid`
- `GlassKit` examples

Pattern chung:

- App trên kính kết nối trực tiếp Wi-Fi/WebSocket/WebRTC tới backend.
- Kính stream camera/mic và nhận text hoặc audio trả về.
- Không phụ thuộc phone nếu use case cho phép.

### 2.4 Bộ bridge/server/protocol

Các ví dụ:

- `openclaw-rokid-glasses`
- `rokid-ar-agent`
- `rokid_ai_agent`
- `rokid_ai_vision_rag`

Đây là lớp "trí tuệ" hoặc "dịch giao thức", rất hợp khi muốn biến kính thành terminal mỏng cho AI/vision/RAG.

### 2.5 Tài nguyên dev và reverse-engineering

Các ví dụ:

- `rokid-docs`
- `rokid-glasses-analysis`
- `rokid-glasses-control`
- `rokid-openvoice-sdk`

Đây là nhóm quan trọng nhất để viết phần mềm đúng kiểu Rokid thay vì viết Android chung chung.

### 2.6 Công cụ cài app / triển khai

Các ví dụ:

- `RokidApkUploader`
- `Rokid-APKs`
- `EUNG SOFT Web Install`

Thực tế này rất quan trọng: community xem `install/update app` là một problem riêng. Điều đó nói lên việc deployment trên kính vẫn cần quy trình riêng, không nên giả định "cắm cáp rồi chạy như điện thoại".

## 3. Bức tranh kỹ thuật chung của Rokid hiện nay

Từ `rokid-docs`, `rokid-glasses-analysis`, local notes và các repo app:

- Hệ điều hành: `YodaOS-Sprite`, Android-based.
- Dấu vết reverse-engineered hiện chỉ rất mạnh về nhánh `Android 12`, `SDK 32`, Qualcomm QSSI.
- Màn hình app nên mặc định theo `480x640`, `portrait`.
- Thiết bị ở trạng thái `low-RAM`, nên phải tiết kiệm object, ảnh, background work và service sống dai.
- `Google Play Services` không phải nền tảng mặc định đáng tin cậy.
- Nhiều hệ thống capability nằm sau `system app`, `AIDL`, `hidden service`, `CXR`, hoặc `AssistServer`.

Điểm rất đáng nhớ:

- `rokid-docs` mô tả `CXR-M` là SDK cho app điện thoại làm việc với kính.
- `rokid-docs` mô tả `CXR-S` là SDK on-device cho app chạy trực tiếp trên kính.
- `sprite-assist` cho thấy hệ có một service hub trung tâm `com.rokid.os.sprite.assistserver`, có thể điều phối camera, audio, Bluetooth, TTS, file transfer, v.v.

## 4. 4 kiểu kiến trúc app nên chọn

### 4.1 Kiểu A: native utility chạy trên kính

Dùng khi:

- app nhỏ
- thao tác trực tiếp trên kính
- không cần AI nặng
- không cần GPS thật từ điện thoại

Ví dụ phù hợp:

- file manager
- Wi-Fi helper
- image/video cleaner
- notes viewer
- teleprompter đơn giản
- terminal

Repo mẫu:

- `Rokid-Shell`
- `Rokid_Wifi`
- `photoDel4rokidglasses`

### 4.2 Kiểu B: phone là não, kính là HUD

Dùng khi:

- cần GPS, notification, routing, database, internet ổn định
- cần tận dụng phần cứng/UX có sẵn của phone
- muốn giảm tải cho kính

Repo mẫu:

- `Rokid-Maps`
- `RokidAIAssistant`
- `NeuroGlasses`
- `Rokid Lyrics`

Đây là kiểu an toàn nhất cho app production đầu tiên.

### 4.3 Kiểu C: kính nối thẳng backend

Dùng khi:

- app chủ yếu là AI assistant / scene understanding
- người dùng muốn không cần phone
- chấp nhận phụ thuộc Wi-Fi

Repo mẫu:

- `openclaw-rokid`
- `GlassKit`

Kiểu này mạnh nhưng dễ vấp các vấn đề pin, camera pipeline, reconnect, và backend latency.

### 4.4 Kiểu D: app native + tích hợp sâu với hệ thống Rokid

Dùng khi:

- cần trigger scene hệ thống
- cần dùng khả năng camera/audio/AI sẵn có của hệ
- cần giao tiếp chính thức với companion app

Mấu chốt là:

- `CXR-M`
- `CXR-S`
- `AssistServer`

Kiểu này mạnh nhất nhưng cũng dễ bị giới hạn quyền và version mismatch nhất.

## 5. Những thông số dev mà chúng ta nên coi là "baseline"

Từ các repo thực tế, baseline hợp lý hiện tại là:

- `minSdk`: thường `28` hoặc `29`
- `targetSdk`: thường `34`
- `compileSdk`: `34` đến `36`
- `Java/Kotlin JVM target`: `17`
- `ABI`: ưu tiên `arm64-v8a`
- `UI`: `ViewBinding + XML` hoặc `Jetpack Compose`

Những con số lặp lại:

- `Rokid-Shell`: `minSdk 28`, `compileSdk 34`, `JVM 17`
- `Rokid-Maps`: `minSdk 28`, `compileSdk 34`, `JVM 17`
- `Rokid_Wifi`: `minSdk 29`, `compileSdk 34`, `arm64-v8a`
- `GlassKit feature demo`: `minSdk 28`, `compileSdk 36`, `JVM 17`
- `RokidAIAssistant`: `minSdk 28`, `targetSdk 34`, `compileSdk 36`

Khuyến nghị thực dụng cho dự án mới của chúng ta:

- bắt đầu với `minSdk 28`
- đặt `targetSdk 34`
- dùng `compileSdk 34` nếu muốn ổn định
- lên `compileSdk 36` khi cần thư viện mới hơn hoặc Compose mới
- chuẩn hóa `JDK 17`

## 6. Input và UX: đây là luật chơi quan trọng nhất

### 6.1 Đừng thiết kế như app điện thoại

Rokid không phải touch-first device. Cả `rokid-glasses-analysis` lẫn `GlassKit feature demo` đều xác nhận tư duy đúng là:

- `focus navigation`
- `KeyEvent`
- `tap/double-tap/swipe` map sang semantic action

### 6.2 Mapping input thực tế

Pattern lặp lại nhiều nhất:

- `KEYCODE_ENTER`: chọn / xác nhận
- `KEYCODE_BACK`: back / thoát
- `KEYCODE_DPAD_DOWN`: next / forward swipe
- `KEYCODE_DPAD_UP`: previous / back swipe

Ngoài ra tài liệu reverse-engineered còn chỉ ra:

- `SPRITE_DOUBLE_TAP = 202`
- `SPRITE_SWIPE_FORWARD = 183`
- `SPRITE_SWIPE_BACK = 184`

Và có các broadcast action cho function key:

- `com.android.action.ACTION_SPRITE_BUTTON_UP`
- `com.android.action.ACTION_SPRITE_BUTTON_LONG_PRESS`
- `com.android.action.ACTION_AI_START`

### 6.3 Luật UI nên áp dụng mặc định

1. Mọi control phải `focusable`.
2. Focus state phải cực rõ.
3. Một màn hình chỉ nên làm một việc.
4. Chữ to, ít text, line length ngắn.
5. Dùng nền đen, xanh hoặc thang xám phù hợp HUD.
6. Đừng ẩn đường thoát app; nút back thường là cách duy nhất để thoát.
7. Nếu có list dài, thêm debounce và feedback âm thanh.

### 6.4 Thực tế từ repo

- `GlassKit feature demo` còn map thêm touch trên phone/emulator để giả lập trải nghiệm kính.
- `Rokid_Wifi` thiết kế keyboard vòng tròn/cyclic cho password input, rất hợp với thiết bị không touch.
- `Rokid-Shell` chủ động xử lý `KEYCODE_BACK` để đưa focus ra vùng an toàn trước khi thoát.

## 7. Mô hình giao tiếp thường gặp

### 7.1 CXR-M / CXR-S

Đây là đường chính thức nhất.

- `CXR-M`: app điện thoại nói chuyện với kính
- `CXR-S`: app trên kính nói chuyện với mobile side

Từ `rokid-docs`:

- `CXR-M` giúp lấy hardware info, trigger AI flow, file transfer, audio record, photo.
- `CXR-S` hỗ trợ message/data channel hai chiều giữa app kính và app mobile.

Dependency thực tế thấy trong repo:

```kotlin
implementation("com.rokid.cxr:client-m:1.0.4")
```

### 7.2 Bluetooth SPP + JSON line protocol

Đây là pattern community ưa dùng vì đơn giản và kiểm soát được.

Repo tiêu biểu nhất là `Rokid-Maps`:

- phone mở server Bluetooth
- glasses làm client
- mỗi message là một JSON object trên một dòng
- shared module định nghĩa protocol

Các loại message mà `Rokid-Maps` đã chứng minh hữu ích:

- `state`
- `route`
- `step`
- `settings`
- `steps_list`
- `wifi_creds`
- `tile_req` / `tile_resp`
- `apk_start` / `apk_chunk` / `apk_end`
- `notification`

Kết luận:

- nếu chúng ta muốn làm companion app mà không bị khóa quá chặt bởi SDK chính thức, `SPP + shared protocol module` là hướng rất đáng dùng.

### 7.3 Wi-Fi direct / Wi-Fi LAN / WebSocket / WebRTC

Thấy ở:

- `Rokid-APKs`
- `openclaw-rokid`
- `GlassKit`

Rất hợp khi:

- truyền file lớn
- stream mic/camera
- cần low latency hơn HTTP polling

### 7.4 AssistServer / system services

Nếu cần tích hợp sâu hơn nữa:

- bind `MasterAssistService`
- đăng ký client
- gửi `controlMsgJson`

Theo `sprite-assist`, service này có thể route command tới:

- media
- Bluetooth
- TTS
- file transfer
- QR scan
- system scene

Nhưng cần nhớ:

- đây là system surface
- version có thể đổi
- third-party app có thể bị chặn bởi quyền hoặc export policy

## 8. Camera, audio, AI: cách cộng đồng đang làm

### 8.1 Camera

Pattern phổ biến:

- dùng `CameraX` hoặc `Camera2`
- chụp snapshot hoặc stream frame chọn lọc
- không cố render AR 3D nặng

Repo dùng rõ:

- `GlassKit`
- `openclaw-rokid`
- `RokidAIAssistant`

Lưu ý từ reverse-engineering:

- camera có thể xung đột với `AssistServer` hoặc service hệ thống đang giữ camera.

### 8.2 Audio / voice

Có 3 nhánh chính:

1. Dùng service hệ thống Rokid / OpenVoice / speech stack
2. Dùng `SpeechRecognizer` / `TextToSpeech` của Android
3. Dùng offline ASR riêng như `Vosk` hoặc `sherpa-onnx`

Ví dụ:

- `rokid-openvoice-sdk`: SDK speech chính thức, thiên về Android/Linux/C++
- `GlassKit feature demo`: `Vosk`
- `Rokid_Wifi`: `sherpa-onnx`
- `rokid-ar-navigation`: `SpeechRecognizer` + `TextToSpeech`

Kết luận:

- nếu cần app nhẹ, offline command nhỏ: dùng `Vosk` hoặc `sherpa-onnx`
- nếu cần tận dụng ecosystem Rokid: nghiên cứu `OpenVoice` và `AssistServer`
- nếu chỉ cần demo nhanh: `SpeechRecognizer` + `TTS` đủ để đi tiếp

### 8.3 AI

Pattern thắng cuộc hiện nay:

- app kính lo `capture + input + HUD`
- AI thật chạy ở `phone` hoặc `backend`

Ví dụ:

- `RokidAIAssistant`: phone làm AI hub đa provider
- `NeuroGlasses`: app Android bridge sang API tương thích OpenAI
- `openclaw-rokid`: kính nói thẳng với gateway
- `GlassKit`: backend riêng cho realtime vision/audio

Nếu chúng ta tự làm app AI, nên mặc định nghĩ theo 3 lớp:

1. `glasses client`
2. `protocol layer`
3. `AI backend / phone brain`

## 9. Thư viện và công nghệ đáng chú ý

### 9.1 Nhóm Android core

- `androidx.core:core-ktx`
- `androidx.appcompat:appcompat`
- `androidx.activity`
- `androidx.recyclerview`
- `ConstraintLayout`
- `ViewBinding`

### 9.2 Nhóm modern UI

- `Jetpack Compose`
- `Material 3`

Compose xuất hiện mạnh ở app AI mới như:

- `RokidAIAssistant`
- `openclaw-rokid`

Trong khi utility/HUD nhỏ vẫn thiên về XML:

- `Rokid-Shell`
- `Rokid_Wifi`
- `rokid-ar-navigation`
- `Rokid-Maps`

### 9.3 Nhóm network / protocol

- `OkHttp`
- `Retrofit`
- `Gson`
- `kotlinx-serialization-json`
- `org.json`

### 9.4 Nhóm media / sensor / vision

- `CameraX`
- `androidx.camera.camera2`
- `androidx.camera.lifecycle`
- `osmdroid`

### 9.5 Nhóm speech

- `com.alphacephei:vosk-android`
- `sherpa-onnx`
- `rokid-openvoice-sdk`

### 9.6 Nhóm local data / state

- `Room`
- `DataStore`
- `Security Crypto`

### 9.7 Nhóm utility cực hữu ích

- `NanoHTTPD` cho local transfer server
- `FileProvider` cho APK install / file share

## 10. Bài học rút ra từ từng repo tiêu biểu

### 10.1 `GlassKit`

Học được:

- Rokid rất hợp với mô hình `thin client + AI backend`
- Có thể dev trên emulator nếu map đúng `480x640` và input
- Voice command local demo có thể làm bằng `Vosk`
- Realtime app cho kính nên tách ví dụ theo use case, không nhồi một app khổng lồ

### 10.2 `Rokid-Maps`

Học được:

- Companion architecture là chiến lược cực mạnh cho navigation
- `shared protocol module` đáng giá hơn viết tắt logic vào từng app
- SPP + JSON line protocol đủ khỏe cho state sync, tile proxy, notification, thậm chí update APK
- Tránh phụ thuộc API key/GMS bằng OSM stack là quyết định đúng cho Rokid

### 10.3 `Rokid-Shell`

Học được:

- Utility app trên kính có thể rất "Android chuẩn" nhưng vẫn phải HUD-friendly
- `NanoHTTPD + FileProvider + REQUEST_INSTALL_PACKAGES` là combo triển khai/cài app rất thực dụng
- File explorer là một use case thật, không phải demo

### 10.4 `Rokid_Wifi`

Học được:

- Password input trên kính là một bài toán UX riêng
- Offline ASR rất hữu ích cho thao tác nhập liệu khó
- Nên khóa `arm64-v8a` nếu phụ thuộc native libs nặng

### 10.5 `rokid-ar-navigation`

Học được:

- Với thiết bị low-RAM, `REST API + 2D HUD` thường khôn hơn `SDK map nặng + 3D`
- Có thể bỏ hẳn Unity/OpenXR cho nhiều use case thực tế
- Native Java/Kotlin vẫn là con đường ít rủi ro nhất

### 10.6 `RokidAIAssistant`

Học được:

- Multi-module `phone-app / glasses-app / common` là cấu trúc đẹp và nên học
- AI provider nên được abstraction thành service layer
- CXR vẫn là đường tốt cho phone-to-glasses integration

### 10.7 `openclaw-rokid`

Học được:

- Có thể làm `glasses-direct` app không cần phone
- `Compose + CameraX + WebSocket` là stack đủ đẹp cho AI assistant mới
- Tư duy self-update bằng loader/dynamic code có thể hữu ích, nhưng cần cân nhắc bảo mật và độ ổn định

## 11. Những ràng buộc rất dễ làm app hỏng

1. Thiết kế UI theo touch thay vì focus navigation.
2. Dùng thư viện phụ thuộc `GMS` hoặc Google Maps SDK mà không có fallback.
3. Coi kính như điện thoại mạnh, bỏ qua low-RAM.
4. Mở camera/mic liên tục mà không quản pin/thermal.
5. Không chuẩn bị cho reconnect Bluetooth/Wi-Fi.
6. Đóng gói một app vừa AI, vừa map, vừa media, vừa settings ngay từ đầu.
7. Dùng backend nặng nhưng không có degraded mode khi mạng yếu.
8. Phụ thuộc hoàn toàn vào hidden/system API mà không có path fallback.

## 12. Khuyến nghị stack cho dự án mới của chúng ta

### 12.1 Nếu app là utility native trên kính

Khuyến nghị:

- `Kotlin`
- `XML + ViewBinding`
- `minSdk 28`
- `compileSdk 34`
- `JDK 17`
- `CameraX` nếu cần camera
- `OkHttp` nếu cần network
- `NanoHTTPD` nếu cần transfer local

### 12.2 Nếu app là companion phone + glasses

Khuyến nghị:

- 3 module:
  - `phone-app`
  - `glasses-app`
  - `common`
- giao thức:
  - ưu tiên `SPP + JSON`
  - hoặc `CXR` nếu cần integrate chính thức
- mọi schema message nên đặt ở `common`

### 12.3 Nếu app là AI assistant

Khuyến nghị:

- `glasses client`: capture, HUD, input
- `backend`: AI, memory, tools, prompt orchestration
- `transport`: `WebSocket` hoặc `WebRTC`
- local/offline command ngắn:
  - `Vosk`
  - hoặc `sherpa-onnx`

## 13. Skeleton repo nên dùng

Nếu chúng ta bắt đầu một repo mới, cấu trúc nên như sau:

```text
my-rokid-app/
├── docs/
│   ├── architecture.md
│   ├── protocol.md
│   └── device-notes.md
├── common/               # shared models/protocol
├── glasses-app/          # app native trên kính
├── phone-app/            # nếu có companion
├── backend/              # nếu có AI/server
├── tools/
│   ├── adb/
│   └── install/
└── README.md
```

Nếu là app thuần trên kính thì đơn giản hơn:

```text
my-rokid-utility/
├── app/
├── docs/
├── screenshots/
└── README.md
```

## 14. Checklist trước khi code app mới

1. App này là `native`, `phone+glasses`, hay `glasses+backend`?
2. Có cần `CXR` không, hay `Bluetooth SPP` là đủ?
3. Có cần `camera`, `mic`, `speaker`, `Wi-Fi`, `install APK`, `notification`, `location` không?
4. Nếu mạng yếu hoặc mất mạng thì app degrade thế nào?
5. Nếu không có GMS thì app còn chạy được không?
6. Toàn bộ flow có dùng được chỉ bằng `KeyEvent` không?
7. Mỗi màn hình có giữ đúng nguyên tắc "một nhiệm vụ" chưa?
8. Có cần permission đặc biệt hoặc grant qua ADB không?
9. Có cần phone đóng vai trò proxy cho network/file/update không?
10. Có cần test trên emulator `480x640` trước khi đẩy lên kính thật không?

## 15. Khuyến nghị roadmap cho chính chúng ta

Thứ tự hợp lý nhất:

1. Viết một `glasses-native utility` rất nhỏ để chốt UI/input baseline.
2. Tách một `common protocol module`.
3. Nếu cần data/AI nặng, thêm `phone-app` hoặc `backend`.
4. Cuối cùng mới nghiên cứu sâu `CXR` và `AssistServer` cho integration nâng cao.

Nói ngắn gọn:

- bắt đầu như `Rokid-Shell` hoặc `Rokid_Wifi`
- mở rộng kiến trúc như `Rokid-Maps`
- chỉ lên stack AI lớn kiểu `GlassKit` hoặc `openclaw-rokid` khi use case thật sự cần

## 16. Tài liệu và repo nên xem lại nhiều nhất

### Cốt lõi

- `awesome-rokid`
- `rokid-docs`
- `rokid-glasses-analysis`
- `rokid-glasses-research.md` trong workspace này

### Mẫu app rất đáng học

- `GlassKit`
- `Rokid-Maps`
- `Rokid-Shell`
- `Rokid_Wifi`
- `RokidAIAssistant`
- `openclaw-rokid`

### Công cụ triển khai và điều khiển

- `rokid-glasses-control`
- `RokidApkUploader`
- `Rokid-APKs`

## 17. Nguồn tham khảo

- Awesome list: <https://github.com/Anezium/awesome-rokid>
- GlassKit: <https://github.com/RealComputer/GlassKit>
- Rokid Maps: <https://github.com/chartmann1590/Rokid-Maps>
- Rokid Shell: <https://github.com/Anezium/Rokid-Shell>
- Rokid collection:
  - <https://github.com/bcefghj/rokid-collection/tree/main/rokid-glasses-analysis>
  - <https://github.com/bcefghj/rokid-collection/tree/main/rokid-glasses-control>
  - <https://github.com/bcefghj/rokid-collection/tree/main/rokid-ar-navigation>
  - <https://github.com/bcefghj/rokid-collection/tree/main/Rokid_Wifi>
- Rokid AI Assistant: <https://github.com/zero2005x/RokidAIAssistant>
- OpenClaw Rokid: <https://github.com/etdofreshai/openclaw-rokid>
- NeuroGlasses: <https://github.com/ECHO-HELLO-WORLD424/NeuroGlasses>
- Rokid docs: <https://github.com/buildwithfenna/rokid-docs>
- Rokid OpenVoice SDK: <https://github.com/rokid/rokid-openvoice-sdk>
- Local notes:
  - `rokid-glasses-research.md`
  - `_tmp_rokid_apks/README.md`
  - `_tmp_miniontoby_uploader/README.md`

## 18. Kết luận cuối

Từ toàn bộ ecosystem hiện tại, chiến lược phát triển phần mềm cho kính Rokid nên là:

- coi đây là `Android device chuyên dụng`, không phải "AR platform nặng"
- ưu tiên `native Android app` nhỏ, rõ, tối ưu cho `KeyEvent + HUD`
- đưa phần nặng ra `phone` hoặc `backend`
- chỉ dùng integration sâu với `CXR / AssistServer` khi thật sự cần

Nếu làm đúng hướng này, chúng ta có thể xây app ổn định và lặp nhanh hơn rất nhiều so với việc bắt đầu bằng AR stack phức tạp hoặc các framework quá nặng.
