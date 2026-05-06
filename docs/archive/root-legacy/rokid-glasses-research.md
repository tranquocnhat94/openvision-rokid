# Rokid Glasses Research Notes

Ngày tổng hợp: 2026-04-06

## 1. Nhận diện đúng mẫu kính

Dựa trên mô tả của bạn "kính Rokid có màn hình hiển thị màu xanh", gần như chắc chắn đây là **Rokid Glasses** bản có màn hình AR màu xanh lá/green monochrome trong tròng kính, không phải:

- `Rokid Max / Air / Joy / Spatial`: đây là kính hiển thị ngoài kiểu màn hình lớn, không phải AI glasses tự chạy app.
- `Rokid AI Glasses Style`: đây là bản AI glasses **không có màn hình**.

Nguồn chính thức hiện tại của Rokid còn xác nhận dòng **Rokid Glasses** có model `RV101`, `RV102`, ngày phát hành `2025-06-30`, và thời hạn hỗ trợ bảo mật đến `2028-12-31`.

## 2. Thông số phần cứng chính thức hiện tìm được

Từ các trang sản phẩm và trang cấu hình kỹ thuật chính thức của Rokid, bộ thông tin hiện khớp nhất cho `Rokid Glasses` là:

- Kích thước: `155 x 49 x 44 mm`
- Khối lượng: `49 g`
- SoC chính: `Snapdragon AR1 Gen 1`
- MCU/companion chip: `NXP RT600 (MIMXRT685SFAWBR)`
- Wi-Fi: `Wi‑Fi 6`
- Bluetooth: `BT 5.3`
- RAM: `2 GB`
- ROM: `32 GB`
- Pin trong kính: `210 mAh`
- Quang học: `Micro-LED + diffraction waveguide`, `dual-eye display`
- Độ sáng: `up to 1500 nits`
- FOV: `30°`
- Eye relief: `18 mm`
- Độ phân giải hiển thị: `480 x 640`
- Camera: `12 MP Sony IMX681`
- Ảnh camera: `3024 x 4032`
- Khẩu độ: `F2.25`
- Góc nhìn camera: `H:77 / V:94 / D:109`
- AF: `không hỗ trợ`
- Camera tilt inwards: `3°`
- Mic: `4 mic` định hướng
- Loa: `2 directional hi-fi speakers`
- Có `IMU`
- Có `wear detection`
- Điều khiển vật lý: `1 nút chụp ảnh`, `1 touchpad`
- Có `camera indicator light`

## 3. Các tính năng người dùng nổi bật

Những nguồn marketing chính thức của Rokid đang mô tả `Rokid Glasses` như một kính AI + AR dùng hằng ngày, tập trung vào:

- AI assistant kích hoạt bằng giọng nói `Hi Rokid`
- Dịch thời gian thực, live subtitle
- Ghi chú giọng nói và meeting transcription
- Nhận diện vật thể / object recognition
- Điều hướng AR / Google Maps
- Teleprompter
- Chụp ảnh và quay video góc nhìn thứ nhất
- Thông báo, ghi âm, đồng bộ với app điện thoại

Một số con số/tuyên bố chính thức hiện có khác nhau giữa các bài và trang:

- Một bài của Rokid nói kính hỗ trợ **dịch 89 ngôn ngữ**.
- Trang sản phẩm khác của Rokid nói **supports 15 languages**.
- Một bài của Rokid ghi `23-degree field of view`, trong khi trang spec và trang kỹ thuật ghi `30°`.
- Bài marketing ghi `IPX4`, nhưng trang spec chính hiện mình kiểm tra không luôn hiển thị IP rating đó.

Kết luận: có vài điểm marketing chưa thống nhất giữa các trang của chính Rokid, nên khi làm app/mod mình nên ưu tiên **thông tin thực đo từ ADB/getprop trên máy thật** hơn là tin tuyệt đối vào brochure.

## 4. Pin và thời lượng dùng

Các nguồn chính thức mình thấy hiện mô tả:

- Pin trong kính là `210 mAh`
- Có thể dùng khoảng `6 giờ` khi nghe nhạc
- Có thể quay video khoảng `45 phút`

Ngoài ra Rokid còn bán phụ kiện:

- `Rokid Glasses Power Capsule`: `1700 mAh`, quảng cáo `6+ charges`
- `Rokid Glasses Charging Case`: `3000 mAh`, quảng cáo `10+ full recharges`

Điều này gợi ý rằng kính bản thân rất nhẹ, pin trong thân nhỏ, và trải nghiệm "all-day" phụ thuộc khá nhiều vào case/power capsule.

## 5. Hệ điều hành và nhánh phần mềm hiện tại

Điểm quan trọng nhất cho hướng dev là companion app `Hi Rokid` đang nhắc trực tiếp tới một system branch tên:

- `YodaOS-Sprite`

Từ changelog app `Hi Rokid` gần đây:

- Có yêu cầu hệ thống `YodaOS-Sprite System "1.15.004-20260228-150202"` để app hoạt động đúng.
- App đã thêm/nhấn mạnh các tính năng như:
  - `Gemini available globally`
  - `Google Maps navigation upgraded`
  - `Teleprompter file search`
  - `AR screen recording`

Suy luận hợp lý từ các nguồn này:

- `Rokid Glasses` chạy trên một biến thể hệ điều hành của Rokid tên `YodaOS-Sprite`
- Hệ này rất có thể vẫn là **Android-based system** vì:
  - kính bật được `ADB`
  - có companion app quản lý thiết bị
  - hệ sinh thái SDK/dev cũ của Rokid rõ ràng là Android

Đây là **suy luận**, không phải câu trích chính thức từ Rokid.

## 6. Developer surface hiện tại của Rokid

Những bề mặt dev chính thức/công khai mình xác nhận được:

- `https://ar.rokid.com/`
- `https://rokid.yuque.com/`
- GitHub org `RokidGlass`
- GitHub org `rokid`
- App `Hi Rokid`
- Security Center chính thức của Rokid

Repo/tài liệu công khai quan trọng:

### 6.1 `RokidGlass/glass2-docs`

Thông tin repo:

- Repo: `https://github.com/RokidGlass/glass2-docs`
- Default branch: `master`
- Tạo: `2019-12-13`
- Push cuối: `2023-05-07`

Các branch công khai thấy được:

- `master`
- `gh-pages`
- `dev_sunchao`
- `dev/wangjunjie`
- `dev_wwb`
- một số branch `dependabot/...`

Đây là repo giá trị nhất cho "nhánh dev" hiện public, dù nó thuộc đời `Glass 2` cũ hơn.

### 6.2 `RokidGlass/UXR-docs`

Thông tin repo:

- Repo: `https://github.com/RokidGlass/UXR-docs`
- Default branch: `main`
- Trạng thái: `archived`
- Push cuối: `2021-09-09`

README của repo này ghi rõ:

- các bản phát hành UXR SDK về sau được chuyển sang:
  - `https://rokid.yuque.com/...`
  - `https://ar.rokid.com/`

Nói cách khác:

- `GitHub public docs cũ` -> đã bị đóng băng
- `Yuque + AR platform` -> là hướng docs mới của Rokid

## 7. Những gì tài liệu dev cũ cho thấy về cách Rokid xây hệ của họ

Mình tách phần này riêng vì nó rất hữu ích cho việc làm app/mod, nhưng phải nhớ rằng đây là **legacy docs**, không chắc 100% tương thích với `RV101/RV102`.

### 7.1 Có thể thay launcher mặc định

Tài liệu `glass2-docs` mô tả có thể set launcher mặc định qua:

```sh
adb shell setprop persist.boot.defaultlauncher YourPackageName
adb shell setprop persist.boot.defaultactivity MainActivityName
adb reboot
```

Điều này cực kỳ đáng chú ý, vì nó cho thấy ít nhất ở nhánh Glass 2 cũ, Rokid cho phép kiểu kiosk/app-first deployment.

### 7.2 App có thể auto-start sau khi boot

Docs mô tả có thể đăng ký `BOOT_COMPLETED` để tự mở app sau boot. Đây là dấu hiệu tốt cho các use case:

- launcher riêng
- agent/app chạy nền
- kiosk mode
- app cầu nối Jetson

### 7.3 Có system app và intent nội bộ

Docs cũ ghi rõ các app hệ thống và package name như:

- `com.rokid.glass.camera`
- `com.rokid.glass.gallery`
- `com.rokid.glass.document`
- `com.rokid.glass.appstroe`
- `com.rokid.glass.settings`

Ngoài ra còn có ví dụ gọi system apps bằng `Intent`, ví dụ:

- gọi `Quick Scan` để scan QR / cấu hình Wi‑Fi
- gọi `Document` để mở file cục bộ trong `/sdcard/...`

Đây là mẫu rất hay cho việc reverse-engineer app hiện tại: nếu `Rokid Glasses` mới vẫn giữ cùng triết lý, chúng ta có thể:

- tận dụng app hệ thống qua intent
- hoặc ít nhất dùng `pm list packages`, `cmd package resolve-activity`, `dumpsys package` để tìm activity/exported service tương tự

### 7.4 Có SDK UI / IMU / Record / Voice / USB-mobile solution

Legacy docs public của Rokid cho thấy họ từng phát hành hoặc tài liệu hóa:

- UI SDK:
  - artifact `com.rokid.glass:ui:1.6.2`
- Record SDK:
  - artifact `com.rokid.glass:recordlib:1.0.X-SNAPSHOT`
- Voice/offline instruction SDK:
  - artifact `com.rokid.ai.glass:instructsdk:1.1.8+`
- USB/mobile glass hardware SDK:
  - artifact `com.rokid.alliance.usbcamera:usbcamera:1.1.16`
- Maven repo:
  - `http://maven.rokid.com/repository/maven-public/`

Các docs cũ còn mô tả:

- `IMUView` cho head-controlled list scrolling
- record camera/screen/audio
- voice assistant theo solution config riêng
- map tọa độ preview camera sang vùng hiển thị quang học

Nếu Rokid chưa public SDK mới cho `RV101`, những docs cũ này vẫn giúp ta hiểu:

- cách họ đặt package
- cách họ đóng gói SDK
- cách họ thiết kế overlay/alignment/IMU UX

## 8. Hệ sinh thái app companion

App companion hiện mình tìm được:

- iOS package: `com.rokid.global.rokidglasses`
- Android package: `com.rokid.sprite.global.aiapp`
- Tên app: `Hi Rokid - Rokid Glasses`

Những gì app mô tả:

- quản lý cài đặt kính
- import photo/video/recording từ kính
- AI assistant selection
- intelligent translation

Đây là một đầu mối rất mạnh cho reverse engineering cấp ứng dụng:

- sniff luồng network
- phân tích manifest / deep links
- xem app có chức năng push APK lên kính hay không
- kiểm tra có bridge protocol giữa phone và glasses hay không

## 9. ADB, cable và thực trạng dev hiện tại

### 9.1 Kết quả kiểm tra cục bộ trên máy này

Mình đã tự cài `adb` bản mới ngay trong môi trường làm việc:

- `adb version`: `36.0.2-14143358`

Sau đó chạy:

```sh
/tmp/android_platform_tools/platform-tools/adb devices -l
```

Kết quả tại thời điểm 2026-04-06:

- **không thấy thiết bị nào attach**

Tức là hiện tại:

- hoặc kính chưa nối vào máy tính bằng đường dữ liệu
- hoặc chưa authorize ADB
- hoặc đang dùng nhầm cable chỉ sạc

### 9.2 Điểm rất quan trọng: khả năng cao bạn cần dev cable riêng

Nguồn community và một bài trả lời trên subreddit chính thức của Rokid cho thấy:

- cable đi kèm khi giao máy thường là **3-pin charging cable**
- để làm dev/ADB cần **5-pin development cable**

Một trả lời trên `r/rokid_official` còn ghi rõ:

- "the cable shipped with order is NOT data cable"
- có thể email `liang@rokid.com` để được hướng dẫn dev

Một bài community khác mô tả dev cable được bán riêng và dùng để:

- chạy `adb devices`
- cài APK bằng `adb install`

Trong khi đó, trang phụ kiện chính thức của Rokid cho `Rokid Glasses Charging Cable` cũng ghi rõ đây là:

- `3-pin magnetic connector`
- mục tiêu là `charging`

Kết luận thực dụng:

- nếu bạn chỉ "đã bật ADB trên kính" nhưng máy vẫn không thấy device, thì **nghi ngờ số 1 là cable/data path**, không phải do ADB toggle.

## 10. Root / bootloader / firmware mod

Trong các nguồn chính thức mình kiểm tra ở lượt này:

- **chưa thấy** tài liệu public của Rokid về:
  - unlock bootloader
  - fastboot flow
  - userdebug image
  - root
  - custom firmware flashing

Vì vậy hướng an toàn hiện tại là:

- ưu tiên `app-layer mod`
- sideload APK
- phân tích package / intent / service
- làm bridge giữa app trên kính và Jetson

thay vì giả định có thể root hay flash firmware ngay.

## 11. Điều này có nghĩa gì cho hướng làm app/mod/Jetson của chúng ta

Với thông tin hiện có, lộ trình khả thi nhất là:

### 11.1 Giai đoạn 1: xác minh máy thật

Khi có data cable/dev cable đúng, việc đầu tiên nên lấy từ chính kính:

```sh
adb shell getprop ro.product.model
adb shell getprop ro.product.device
adb shell getprop ro.build.display.id
adb shell getprop ro.build.version.release
adb shell getprop ro.build.fingerprint
adb shell wm size
adb shell wm density
adb shell pm list packages
adb shell dumpsys package
```

Mục tiêu:

- chốt đúng model
- chốt đúng Android/API level
- liệt kê package hệ thống
- xem có app/bridge/service của Rokid nào hữu dụng

### 11.2 Giai đoạn 2: sideload APK tối thiểu

Sau khi ADB hoạt động:

- cài một APK cực nhỏ chỉ để test:
  - launch
  - touchpad / key event
  - network
  - camera permission
  - overlay / fullscreen UI

### 11.3 Giai đoạn 3: bridge với Jetson

Kiến trúc nhiều khả năng sẽ là:

- app Android trên kính kết nối tới Jetson bằng `Wi‑Fi`
- truyền dữ liệu qua `WebSocket`, `HTTP`, `gRPC`, `MQTT`, hoặc `WebRTC`
- Jetson xử lý:
  - vision
  - ASR/TTS
  - LLM tool-calling
  - object detection / OCR / SLAM phụ
- app trên kính chỉ làm:
  - giao diện
  - capture event
  - hiển thị overlay
  - audio/camera bridge

Nếu third-party app được dùng `Camera2` hoặc access camera pipeline:

- hoàn toàn có thể làm bài toán:
  - kính chụp frame
  - gửi sang Jetson
  - Jetson suy luận
  - trả về bbox/text/action
  - app trên kính render lại dưới dạng AR overlay

## 12. Những điểm còn thiếu phải lấy từ máy thật

Đây là các khoảng trống mình **chưa thể chốt chỉ bằng web**:

- Android API level thật trên kính của bạn
- build fingerprint / firmware version thật
- danh sách package hệ thống hiện tại
- có hay không tính năng cài APK trực tiếp từ app điện thoại
- có hay không exported activities/services cho camera, note, teleprompter, navigation
- mức mở của ADB shell
- có `pm install`, `run-as`, `logcat`, `screenrecord`, `dumpsys`, `cmd package` đầy đủ hay bị khóa

## 13. Kết luận ngắn

Hiện tại mình đánh giá:

- Bạn gần như chắc đang dùng **Rokid Glasses RV101/RV102**.
- Đây là một thiết bị AI+AR chạy trên nhánh hệ thống `YodaOS-Sprite`, Android-based theo suy luận rất mạnh.
- Hệ dev public hiện tại của Rokid bị phân mảnh:
  - docs cũ trên GitHub
  - docs mới dồn về `ar.rokid.com` và `rokid.yuque.com`
- Dev/app mod là hướng **khả thi**.
- Root/firmware mod hiện **chưa có bằng chứng public rõ ràng** trong các nguồn mình đã kiểm tra.
- Nút thắt số 1 trước mắt là **data/development cable** để ADB thấy thiết bị thật.

## 14. Sources

### Official

- Rokid product page: https://global.rokid.com/products/rokid-glasses
- Rokid JP product page with full spec snippet: https://global.rokid.com/en-jp/products/rokid-glasses
- Rokid Chinese technical spec page: https://glasses.rokid.com/profile
- Rokid Security Center: https://global.rokid.com/pages/security-center
- Rokid news launch article: https://global.rokid.com/blogs/news/rokid-launches-worlds-lightest-full-function-ai-ar-smart-glasses
- Rokid CES 2025 highlights: https://global.rokid.com/blogs/news/ces-2025-highlights-how-rokid-nbsp-ai-and-ar-nbsp-innovation-redefine-smart-glasses
- Rokid article on translation/live subtitles: https://global.rokid.com/blogs/articles/rokids-ai-glasses-can-translate-languages-show-live-subtitles
- Rokid charging cable page: https://global.rokid.com/products/rokid-glasses-charging-cable
- Rokid charging case page: https://global.rokid.com/products/rokid-glasses-charging-case
- Rokid power capsule page: https://global.rokid.com/products/rokid-glasses-power-capsule
- Rokid open platform root: https://ar.rokid.com/
- Rokid Glass 2 docs repo: https://github.com/RokidGlass/glass2-docs
- Rokid UXR docs repo: https://github.com/RokidGlass/UXR-docs

### Secondary / community / aggregator

- Hi Rokid iOS listing: https://iphone.apkpure.com/app/hi-rokid/com.rokid.global.rokidglasses
- Hi Rokid Android listing: https://apkpure.com/hi-rokid/com.rokid.sprite.global.aiapp
- Official/community Reddit thread about dev cable: https://www.reddit.com/r/rokid_official/comments/1phoc5r/rokid_app_development/
- Community note on dev cable: https://marcinmiazga.com/rokid-development-cable

## 15. Local verification log

Những gì mình đã làm trực tiếp trên máy local:

- Cài `adb` tạm thời vào `/tmp/android_platform_tools/platform-tools/adb`
- Chạy `adb devices -l`
- Kết quả: chưa thấy thiết bị nào attach

File này sẽ là tài liệu nền cho các bước tiếp theo. Khi bạn nối đúng dev cable và để mình đọc được `adb shell`, mình sẽ cập nhật tiếp phần:

- fingerprint thật của máy
- package map
- service map
- khả năng sideload
- hướng reverse engineering/app bridge với Jetson

## 16. Live Device Notes (Pi 5 Android Bridge)

Đây là phần mình đã **xác nhận trực tiếp bằng ADB** sau khi dựng Android trên `Raspberry Pi 5` để làm bridge/dev host:

- Thiết bị:
  - `model`: `Pi 5 Model B Rev 1.1`
  - `device`: `rpi5`
  - `manufacturer`: `Raspberry`
  - `hardware`: `rpi5`
- Build:
  - `fingerprint`: `Raspberry/aosp_rpi5/rpi5:16/BP4A.251205.006/eng.tuomas:userdebug/dev-keys`
  - `build type`: `userdebug`
  - `ro.debuggable=1`
  - `SELinux`: `Permissive`
- Kernel:
  - `Linux 6.12.60-g65276c95d493-v8`
- Display:
  - `1920x1080`
  - density `240`
- Launcher / packages:
  - home activity resolve về `com.android.launcher3/.uioverrides.QuickstepLauncher`
  - có các package quan trọng:
    - `com.android.launcher3`
    - `com.android.launcher3.rpi`
    - `com.android.settings`
    - `com.android.settings.rpi`
    - `com.konstakang.settings.device`
    - `com.android.providers.settings`
    - `com.android.providers.settings.rpi`

### 16.1. Headless Bring-up Result

Những gì mình đã làm thành công:

- patch offline vào `userdata` để Pi 5 tự join Wi-Fi
- xác nhận Pi lên mạng tại:
  - `<LAN_IP>`
- mở được `ADB` qua `USB-C -> MacBook`
- từ đó bật thành công `ADB over Wi-Fi`
- sau reboot, thiết bị vẫn quảng bá:
  - `adb-ab00c134037e7d86	_adb._tcp	<LAN_IP>:5555`

### 16.2. ADB State

Những gì đã xác nhận từ máy đang chạy:

- `adb_enabled=1`
- `wifi_on=1`
- `wifi_saved_state=1`
- `persist.adb.tcp.port=5555`
- `service.adb.tcp.port=5555`

### 16.3. Useful Local Helpers

Mình đã tạo sẵn:

- `connect-pi5-adb.sh`
- `pi5-scrcpy.sh`

Tại:

- `connect-pi5-adb.sh`
- `pi5-scrcpy.sh`

Mục đích:

- `connect-pi5-adb.sh`: reconnect nhanh ADB Wi-Fi tới Pi
- `pi5-scrcpy.sh`: mở remote UI của Pi bằng `scrcpy`

### 16.4. Rokid-APKs on Pi 5

Mình đã cài thành công bản phone app `Rokid-APKs` lên Pi 5 qua ADB:

- package: `io.github.miniontoby.rokidapkuploader`
- activity chính: `.MainActivity`
- release đã dùng: `v1.1.0`

Những gì đã xác nhận trực tiếp:

- app đã được grant các quyền runtime cần thiết:
  - `ACCESS_FINE_LOCATION`
  - `ACCESS_COARSE_LOCATION`
  - `BLUETOOTH_CONNECT`
  - `BLUETOOTH_SCAN`
  - `NEARBY_WIFI_DEVICES`
- Bluetooth trên Pi đang `ON`
- Location services trên Android đã được bật bằng lệnh hệ thống:
  - `cmd location set-location-enabled true`
- app đã mở được đúng mode bootstrap:
  - `CXR / OFFICIAL`

### 16.5. Current Bootstrap Blocker

Sau khi bật đủ quyền và system settings trên Pi, mình đã kiểm tra source của `Rokid-APKs` và xác nhận:

- bước `SCAN` của `CXR / OFFICIAL` dùng BLE scan filter theo service UUID:
  - `00009100-0000-1000-8000-00805f9b34fb`
- scan trên Pi **đã chạy**
- nhưng hiện vẫn trả về:
  - `0 DEV`
  - `No device found`

Điều đó nghĩa là nút thắt hiện tại **không còn nằm ở Pi setup** nữa.
Nó nằm ở một trong các khả năng sau:

- kính chưa ở trạng thái BLE discoverable đúng kiểu mà `Rokid-APKs` cần
- kính đang bị giữ bởi flow khác / app khác
- hoặc firmware/dev-state hiện tại của kính không quảng bá đúng service UUID trên

Nói ngắn gọn:

- `Pi 5 Android bridge`: đã chạy được
- `ADB + Wi-Fi + scrcpy`: đã ổn
- `Rokid-APKs phone app`: đã cài và chạy được
- blocker hiện tại: **làm sao để kính thật sự xuất hiện trong BLE scan của app**
