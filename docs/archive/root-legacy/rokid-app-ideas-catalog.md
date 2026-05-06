# Rokid App Ideas Catalog

Ngày tổng hợp: 2026-04-08

Mục tiêu của file này là lưu lại một catalog thực dụng về:

- các app/prototype/public repo đã xuất hiện quanh hệ Rokid
- mỗi app dùng để làm gì
- app đó chạy kiểu nào: chỉ trên kính, cần điện thoại, hay cần backend
- những ý tưởng đáng học để sau này tự viết app riêng cho kính

File này không cố gắng chỉ ra "app nào tốt nhất", mà đóng vai trò nguồn tư liệu nhanh để:

1. tìm ý tưởng sản phẩm
2. học pattern kỹ thuật
3. học UX cho kính không cảm ứng
4. tránh viết trùng thứ người khác đã làm

---

## 1. Cách đọc file này

### 1.1 Nhãn kiến trúc

- `on-glasses`: chạy trực tiếp trên kính
- `glasses + phone`: kính có app riêng nhưng cần phone companion
- `glasses + backend`: kính nói trực tiếp với server/backend
- `glasses + phone + backend`: có đủ 3 lớp
- `tooling`: công cụ cài app, điều khiển, debug, không phải app end-user
- `catalog`: app có trang giới thiệu nhưng chưa thấy source repo công khai

### 1.2 Mục tiêu của catalog

Mỗi app được ghi ngắn, tập trung vào:

- app dùng để làm gì
- điều gì khiến nó đáng học

---

## 2. Các app utility và công cụ chạy trực tiếp trên kính

### `Rokid-Shell`

- Kiểu: `on-glasses`
- Link: <https://github.com/Anezium/Rokid-Shell>
- Chức năng: file explorer cho kính, duyệt thư mục, mở file, cài APK, chạy HTTP server để chép file qua LAN.
- Đáng học vì:
  - chứng minh app utility native trên kính là hướng rất thực tế
  - cách làm AR-friendly monochrome UI
  - cách kết hợp file manager + transfer server + package installer

### `Rokid_Wifi`

- Kiểu: `on-glasses`
- Link: <https://github.com/bcefghj/rokid-collection/tree/main/Rokid_Wifi>
- Chức năng: kết nối Wi‑Fi cho kính không có touchscreen, có nhập mật khẩu bằng điều hướng focus và giọng nói offline.
- Đáng học vì:
  - giải quyết một bài toán UX rất thật trên kính
  - dùng offline speech cho input ngắn
  - là mẫu tốt cho app settings/helper

### `photoDel4rokidglasses`

- Kiểu: `on-glasses`
- Link: <https://github.com/osagem/photoDel4rokidglasses>
- Chức năng: xem và xóa ảnh/video ngay trên kính.
- Đáng học vì:
  - use case đơn giản nhưng hữu ích hàng ngày
  - minh họa app quản lý media tối giản

### `rokid-ssh-terminal`

- Kiểu: `on-glasses`
- Link: <https://github.com/bzerk/rokid-ssh-terminal>
- Chức năng: terminal SSH trên kính, làm remote shell/tmux controller.
- Đáng học vì:
  - biến kính thành màn terminal đeo được
  - cực hợp cho dev, ops, homelab

### `tuner`

- Kiểu: `on-glasses`
- Link: <https://github.com/lvturner/tuner>
- Chức năng: guitar tuner tối giản cho Rokid, nhận pitch realtime và hiển thị note/tuning indicator.
- Đáng học vì:
  - app âm thanh realtime gọn nhẹ
  - UX tập trung đúng 1 nhiệm vụ

### `rokid-glasses-mouse`

- Kiểu: `on-glasses`
- Link: <https://github.com/Zothie/rokid-glasses-mouse>
- Chức năng: điều khiển chuột bằng head movement, click/scroll qua touch sensor.
- Đáng học vì:
  - cực nhiều giá trị về input alternative
  - có thể tái dùng cho launcher, browser, remote desktop

### `RTMPTest`

- Kiểu: `on-glasses`
- Link: <https://github.com/liheng1994/RTMPTest>
- Chức năng: livestream RTMP/RTMPS từ kính, có xử lý rotation riêng cho camera Rokid.
- Đáng học vì:
  - mở ra hướng live POV streaming
  - có thể dùng cho telepresence, field work, repair support

### `RoboControl`

- Kiểu: `on-glasses`
- Link: <https://github.com/bochristopher/RoboControl>
- Chức năng: điều khiển robot bằng MJPEG stream + WebSocket command trên kính.
- Đáng học vì:
  - ứng dụng kính như control HUD
  - hợp với robotics, Raspberry Pi, Jetson, drone/rover

### `Rokid-DragonBallScouter`

- Kiểu: `on-glasses`
- Link: <https://github.com/Anezium/Rokid-DragonBallScouter>
- Chức năng: scouter demo kiểu Dragon Ball, face tracking + angular HUD.
- Đáng học vì:
  - không chỉ vui mà còn gợi ý nhiều pattern cho computer vision HUD
  - có giá trị làm demo marketing hoặc proof-of-concept

### `rokid-lc-hot100`

- Kiểu: `on-glasses`
- Link: <https://github.com/bcefghj/rokid-collection/tree/main/rokid-lc-hot100>
- Chức năng: học LeetCode Hot100 offline trên kính.
- Đáng học vì:
  - chứng minh kính có thể làm learning HUD
  - hợp để làm flashcard, spaced repetition, micro-learning

### `rokid-music-score`

- Kiểu: `on-glasses`
- Link: <https://github.com/bcefghj/rokid-collection/tree/main/rokid-music-score>
- Chức năng: xem bản nhạc / piano score trên kính.
- Đáng học vì:
  - ý tưởng hỗ trợ performer rất hợp form factor AR glasses

### `rokid-bee-game`

- Kiểu: `on-glasses`
- Link: <https://github.com/icodelife/rokid-bee-game>
- Chức năng: game bắn máy bay cuộn dọc.
- Đáng học vì:
  - chứng minh game 2D đơn giản vẫn khả thi trên kính
  - có thể học layout, key input, score HUD

---

## 3. Navigation, mobility, HUD đời thật

### `Rokid-Maps`

- Kiểu: `glasses + phone`
- Link: <https://github.com/chartmann1590/Rokid-Maps>
- Chức năng: bản đồ và dẫn đường turn-by-turn, map HUD, route line, tile proxy, notification forwarding.
- Đáng học vì:
  - là một trong các repo thực chiến mạnh nhất
  - có shared protocol rất đáng học
  - cho thấy phone làm brain, kính làm HUD là kiến trúc rất hiệu quả

### `Rokid-GMaps`

- Kiểu: `glasses + phone`
- Link: <https://github.com/Anezium/Rokid-GMaps>
- Chức năng: navigation HUD dùng dữ liệu map và routing cho kính.
- Đáng học vì:
  - cho thêm một biến thể khác của bài toán dẫn đường

### `rokid-ar-navigation`

- Kiểu: `on-glasses`
- Link: <https://github.com/bcefghj/rokid-collection/tree/main/rokid-ar-navigation>
- Chức năng: tìm địa điểm gần đây, tìm điểm đến bằng giọng nói, HUD chỉ đường đi bộ.
- Đáng học vì:
  - native on-device navigation là một hướng rất khác với phone companion
  - cho thấy có thể dùng REST API nhẹ thay vì SDK map nặng

### `RokidSmartLife`

- Kiểu: `on-glasses`
- Link: <https://github.com/bcefghj/rokid-collection/tree/main/RokidSmartLife>
- Chức năng: app đời sống/POI và dẫn đường cơ bản.
- Đáng học vì:
  - ý tưởng local-life / nearby assistant rất hợp kính

### `Rokid_Subway`

- Kiểu: `on-glasses`
- Link: <https://github.com/bcefghj/rokid-collection/tree/main/Rokid_Subway>
- Chức năng: hướng dẫn tàu điện/subway bằng giọng nói.
- Đáng học vì:
  - niche nhưng thực dụng cho commuting

### `M365-Rokid-HUD`

- Kiểu: `glasses + BLE device`
- Link: <https://github.com/zero2005x/M365-Rokid-HUD>
- Chức năng: HUD telemetry cho scooter Xiaomi M365.
- Đáng học vì:
  - biến kính thành dashboard mobility
  - pattern BLE telemetry rất đáng học

### `Runsight`

- Kiểu: `on-glasses + BLE device`
- Link: <https://github.com/mouzhi/Runsight>
- Chức năng: hiện pace, distance, cadence, heart rate từ Garmin watch qua BLE.
- Đáng học vì:
  - ý tưởng sports HUD cực hợp với AR glasses
  - thể hiện rõ nhu cầu wearable-to-wearable integration

### `hudble`

- Kiểu: `on-glasses + BLE device`
- Link: <https://github.com/hanabix/hudble>
- Chức năng: HUD thể thao tối giản với BLE heart rate và running cadence.
- Đáng học vì:
  - một biến thể đơn giản hơn của sports HUD
  - tốt để học cách hiển thị data density thấp nhưng hữu ích

### `RideFlux`

- Kiểu: `mobile/vehicle HUD direction`
- Link: <https://github.com/zero2005x/RideFlux>
- Chức năng: dashboard cho xe điện, theo dõi speed, battery, diagnostics qua wireless.
- Đáng học vì:
  - không hẳn là app kính trực tiếp, nhưng ý tưởng HUD cho mobility rất đáng học

---

## 4. AI assistant, realtime vision, AR reasoning

### `openclaw-rokid`

- Kiểu: `glasses + backend`
- Link: <https://github.com/etdofreshai/openclaw-rokid>
- Chức năng: trợ lý AI voice-first, kính kết nối trực tiếp tới gateway qua Wi‑Fi, dùng camera + chat + TTS.
- Đáng học vì:
  - đúng kiểu glasses-native AI assistant
  - mở đường cho mô hình "không cần phone"

### `Clawsses`

- Kiểu: `glasses + phone/backend`
- Link: <https://github.com/dweddepohl/clawsses>
- Chức năng: wearable AI interface cho Rokid, kết nối OpenClaw.
- Đáng học vì:
  - một trong các mốc quan trọng của wearable AI quanh Rokid

### `RokidAIAssistant`

- Kiểu: `glasses + phone`
- Link: <https://github.com/zero2005x/RokidAIAssistant>
- Chức năng: trợ lý AI mã nguồn mở, voice interaction, photo analysis, multi-provider AI/STT.
- Đáng học vì:
  - cấu trúc module đẹp
  - phone là AI hub, kính là input/output terminal

### `NeuroGlasses`

- Kiểu: `glasses + phone`
- Link: <https://github.com/ECHO-HELLO-WORLD424/NeuroGlasses>
- Chức năng: bridge từ kính sang OpenAI-compatible API, hỗ trợ VLM, ASR, TTS.
- Đáng học vì:
  - cho thấy có thể dùng middleware để trừu tượng AI provider

### `GlassKit`

- Kiểu: `glasses + backend`
- Link: <https://github.com/RealComputer/GlassKit>
- Chức năng: bộ template/app mẫu cho realtime smart glasses app, có các demo vision, realtime audio, object detection, proactive assistant.
- Đáng học vì:
  - đây là nguồn template rất quan trọng để học pipeline camera + mic + backend
  - phù hợp nếu muốn phát triển app AI nghiêm túc

### `Claude Glasses Terminal`

- Kiểu: `glasses + phone + server`
- Link: <https://github.com/dweddepohl/claude-glasses-terminal>
- Chức năng: terminal đeo được để dùng Claude Code bằng gesture và voice.
- Đáng học vì:
  - biến kính thành coding HUD
  - gợi ý cực nhiều hướng app chuyên cho developer

### `Rokid_Rotebook`

- Kiểu: `glasses + phone + backend`
- Link: <https://github.com/twozeroone-1/Rokid_Rotebook>
- Chức năng: hỏi đáp tài liệu cá nhân, bridge sang Open-Notebook, AnythingLLM hoặc provider AI khác.
- Đáng học vì:
  - rất sát ý tưởng "personal knowledge HUD"
  - hợp để làm trợ lý công việc / SOP / manual lookup

### `Atmos_Rokid`

- Kiểu: `android client + local server`
- Link: <https://github.com/zs-andy/Atmos_Rokid>
- Chức năng: scene understanding dùng FastVLM + YOLO.
- Đáng học vì:
  - scene awareness cho người khiếm thị hoặc hỗ trợ đời sống

### `viseat`

- Kiểu: `glasses + phone + backend`
- Link: <https://github.com/xiceflame/viseat>
- Chức năng: trợ lý dinh dưỡng, theo dõi bữa ăn, ước lượng món ăn, lời khuyên cá nhân hóa.
- Đáng học vì:
  - là ví dụ rất tốt cho "AI vertical app" chứ không phải chat assistant chung chung

### `FaceTag`

- Kiểu: `glasses + server`
- Link: <https://github.com/itismejy/FaceTag>
- Chức năng: prototype nhớ tên người, nhận diện khuôn mặt, gắn thông tin rồi hiển thị HUD.
- Đáng học vì:
  - ý tưởng rất hợp networking/social use case
  - hữu ích làm tư liệu cho hệ Jetson + face recognition sau này
- Ghi chú:
  - hiện nên xem là prototype đang làm dở, không phải app hoàn thiện

### `RokidGlassesFacialRecognition`

- Kiểu: `sample / experimental`
- Link: <https://github.com/cpig/RokidGlassesFacialRecognition>
- Chức năng: sample app về facial recognition và nhiều tính năng CXR/teleprompter/translation khác.
- Đáng học vì:
  - có thể khai thác như kho sample kỹ thuật

### `FYPSENglasses`

- Kiểu: `prototype`
- Link: <https://github.com/Daniel03211-git/FYPSENglasses>
- Chức năng: prototype AI glasses với object detection, photo read, task guide, timer, voice control.
- Đáng học vì:
  - cho thấy một hướng “assistive workflow glasses”

---

## 5. Translation, subtitles, communication

### `rokid-ar-translator`

- Kiểu: `glasses app`
- Link: <https://github.com/Donald8511/rokid-ar-translator>
- Chức năng: dịch realtime trên kính.
- Đáng học vì:
  - use case translation rất phù hợp AR glasses

### `rokid-spain-trip`

- Kiểu: `glasses app`
- Link: <https://github.com/etdofreshai/rokid-spain-trip>
- Chức năng: app dịch realtime cho travel use case.
- Đáng học vì:
  - cho thấy AI/travel là một vertical rất hợp

### `live-subtitles-rokid-ar`

- Kiểu: `glasses/android`
- Link: <https://github.com/lhr0909/live-subtitles-rokid-ar>
- Chức năng: tạo phụ đề ngoài đời thực dùng Whisper.
- Đáng học vì:
  - đây là một trong các idea hay nhất cho AR glasses
  - rất hợp cho accessibility và meeting caption

### `Rokid-VideoCall`

- Kiểu: `glasses/phone system`
- Link: <https://github.com/njujiangxiang/Rokid-VideoCall>
- Chức năng: video call/WebRTC cho kính.
- Đáng học vì:
  - phù hợp telepresence, remote support, collaboration

---

## 6. Media, launcher, reader, daily-use apps

### `Rokid Lyrics`

- Kiểu: `glasses + phone`
- Link: <https://github.com/Anezium/Rokid-Lyrics>
- Chức năng: đẩy lyrics đồng bộ từ điện thoại lên kính.
- Đáng học vì:
  - ý tưởng media HUD rất vừa sức và vui
  - hợp để học Bluetooth data push

### `RokidAppMaker / GazeMou`

- Kiểu: `launcher / input tool`
- Link: <https://github.com/KUPdriveouter/RokidAppMaker/releases/tag/v1.6.0>
- Chức năng: launcher, favorites, app drawer, head-gesture cursor.
- Đáng học vì:
  - input/tooling layer cho kính rất đáng đầu tư

### `cursive-team/rokid-apps`

- Kiểu: `portfolio / multiple app ideas`
- Link: <https://github.com/cursive-team/rokid-apps>
- Chức năng: portfolio app cho RV101, gồm HelloHUD và roadmap cho NowCard, ARPet, Capture, SpeedReader, AgentHUD.
- Đáng học vì:
  - rất giàu ý tưởng nhỏ, phù hợp để bẻ ra thành MVP

### `spatial-workspace-android`

- Kiểu: `thin client`
- Link: <https://github.com/aluminumio/spatial-workspace-android>
- Chức năng: WebView thin client cho Spatial Workspace trên Rokid Max 2.
- Đáng học vì:
  - hướng “workspace thin client” cũng rất đáng cân nhắc
  - dù nghiêng về Max 2 hơn là RG-glasses xanh

### `Memora_rokid`

- Kiểu: `on-glasses`
- Link: <https://github.com/e7naq3y/Memora_rokid>
- Chức năng: học ngôn ngữ với HUD study flow và AI hỗ trợ.
- Đáng học vì:
  - learning/education là một vertical rất hợp form factor kính

---

## 7. Catalog web công khai nhưng chưa thấy source repo

Nguồn catalog: <https://eung.pe.kr/rokid/>

### `EK Pilot`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=ekpilot&type=RokidGlasses>
- Chức năng: game lái máy bay bằng head tilt.

### `EK Word Up`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=EKWordUp&type=RokidGlasses>
- Chức năng: học từ vựng hands-free.

### `TextHome`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=TextHome&type=RokidGlasses>
- Chức năng: launcher chữ, đồng hồ, thời tiết, pin.

### `EKReader`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=EKReader&type=RokidGlasses>
- Chức năng: ebook reader.

### `EK Live Cam`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=EKLiveCam&type=RokidGlasses>
- Chức năng: live camera utility.

### `EKHome`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=EKHome&type=RokidGlasses>
- Chức năng: custom launcher cho kính.

### `Persona`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=Persona&type=RokidGlasses>
- Chức năng: face/palm reading.

### `Rokid Connect HUD (Glasses)`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=RokidConnectHud2&type=RokidGlasses>
- Chức năng: HUD dẫn đường trên kính.

### `Rokid Connect HUD (Phone)`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=RokidConnectHud&type=RokidGlasses>
- Chức năng: phone companion cho HUD dẫn đường.

### `Text Translation`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=Trans&type=RokidGlasses>
- Chức năng: dịch văn bản offline.

### `EK Zoom`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=zoom&type=RokidGlasses>
- Chức năng: phóng to / zoom camera.

### `EK Arrow`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=EKArrow&type=RokidGlasses>
- Chức năng: mini game bắn cung.

### `EK Find Price`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=EKFind&type=RokidGlasses>
- Chức năng: chụp ảnh và tìm giá sản phẩm.

### `Matrix Vision`

- Kiểu: `catalog`
- Link: <https://eung.pe.kr/app-detail.html?app=MatrixVision&type=RokidGlasses>
- Chức năng: hiệu ứng camera kiểu Matrix.

---

## 8. Công cụ cài app, triển khai và điều khiển

### `RokidApkUploader`

- Kiểu: `tooling`
- Link: <https://github.com/Miniontoby/RokidApkUploader>
- Chức năng: sideload APK từ điện thoại lên kính bằng CXR-M.
- Đáng học vì:
  - deployment trên Rokid là một bài toán thật

### `Rokid-APKs`

- Kiểu: `tooling`
- Link: <https://github.com/Anezium/Rokid-APKs>
- Chức năng: upload APK qua official mode, Bluetooth SPP hoặc Wi‑Fi LAN.
- Đáng học vì:
  - rất hữu ích cho workflow triển khai không cần cáp dev

### `EUNG SOFT Web Install`

- Kiểu: `tooling`
- Link: <https://eung.pe.kr/web-install/>
- Chức năng: web installer sideload APK.

### `rokid-glasses-control`

- Kiểu: `tooling`
- Link: <https://github.com/bcefghj/rokid-collection/tree/main/rokid-glasses-control>
- Chức năng: ADB + scrcpy tooling để điều khiển kính từ macOS.
- Đáng học vì:
  - rất hữu ích cho debug và demo

---

## 9. Những idea đáng ăn cắp nhất

Đây là phần quan trọng nhất cho việc tự phát triển app riêng.

### 9.1 Nhóm idea rất hợp với form factor Rokid

- Sports HUD
  - chạy bộ, đạp xe, scooter, xe điện
  - chỉ cần BLE + layout gọn là đã có giá trị

- Navigation HUD
  - turn-by-turn, subway, POI gần đây
  - cực hợp vì user không phải cầm điện thoại

- Live subtitles / translation
  - meeting caption
  - du lịch
  - accessibility

- Personal assistant kiểu vertical
  - nutrition coach
  - field repair assistant
  - SOP/manual lookup
  - shopping price finder

- Developer / operator HUD
  - SSH terminal
  - Claude terminal
  - agent status
  - remote control robot/server

- Media HUD
  - lyrics
  - sheet music
  - teleprompter
  - reader

- Utility apps
  - file manager
  - Wi‑Fi helper
  - package installer
  - settings helper

### 9.2 Idea có thể làm tiếp nếu muốn khác đám đông

- HUD cho Raspberry Pi / Jetson diagnostics
- BLE dashboard cho máy móc công nghiệp
- Prompt runner cho work instructions
- Warehouse picker HUD
- Face recall / social memory assistant
- Shopping/retail price compare HUD
- Cooking checklist HUD
- Field sales/customer CRM prompt HUD
- Drone/robot teleop HUD
- Study card / flashcard HUD

---

## 10. Pattern kỹ thuật lặp lại nhiều nhất

### App đơn giản, utility

- native Android
- Kotlin hoặc Java
- XML/ViewBinding
- focus navigation + KeyEvent

### App AI hoặc data-heavy

- kính lo input/output
- phone hoặc backend lo phần nặng
- dùng WebSocket / HTTP / Bluetooth SPP / CXR

### App có nhiều thành phần

- `glasses-app`
- `phone-app`
- `common/shared`
- `backend`

### Điều rút ra

Muốn đi nhanh:

1. làm app utility on-glasses trước
2. nếu cần data/AI nặng thì thêm phone hoặc backend
3. chỉ khi cần mới tích hợp sâu CXR/AssistServer

---

## 11. Gợi ý dùng catalog này trong tương lai

Khi brainstorm app mới, nên hỏi:

1. Ý tưởng này gần repo nào nhất?
2. Nó giống kiểu `Rokid-Shell`, `Rokid-Maps`, hay `GlassKit`?
3. Nó cần chạy `on-glasses`, `glasses + phone`, hay `glasses + backend`?
4. Có vertical nào trong catalog gần giống không?
5. Có thể tái dùng pattern transport hoặc UI từ repo nào?

---

## 12. Repo đáng mở lại nhiều lần nhất

- `Rokid-Shell`
- `Rokid_Wifi`
- `Rokid-Maps`
- `GlassKit`
- `RokidAIAssistant`
- `openclaw-rokid`
- `Claude Glasses Terminal`
- `Runsight`
- `FaceTag`

---

## 13. Kết luận

Hệ sinh thái Rokid tuy còn nhỏ nhưng đã đủ rộng để rút ra mấy bài học quan trọng:

- app cho kính không cần phải quá phức tạp mới hữu ích
- utility app và HUD chuyên biệt thường có giá trị thực tế cao hơn “AI demo” chung chung
- kiến trúc tốt nhất thường là tách phần nặng ra phone hoặc backend
- input, focus navigation và monochrome HUD là thứ quyết định trải nghiệm thành bại

Catalog này nên được xem như "vườn ý tưởng" và "thư viện pattern" để sau này khi viết app riêng cho kính, chúng ta có thể mở ra đối chiếu rất nhanh.
