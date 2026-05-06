# Rokid Display Experience Playbook

Canh bao quan trong:

- File nay la `field playbook`, khong phai spec chinh thuc cua `Rokid Glasses RV101`.
- No gom kinh nghiem thuc chien, tham khao tu project khac, va ca doi chieu cheo voi mot vai he HUD ngoai Rokid.
- Dung file nay de rut `heuristic UI`, khong dung de xac dinh `hardware/runtime truth`.
- Neu can mot quyet dinh cho `RV101`, uu tien [rokid-display-foundation.md](docs/reference/rokid-display-foundation.md) truoc.

Tài liệu này tổng hợp kinh nghiệm thực chiến khi tối ưu UI realtime lyric cho kính Rokid, mục tiêu là tái sử dụng cho các phần mềm HUD khác (nhạc, teleprompter, subtitle, thông báo, v.v.).

## 1) Nền tảng hiển thị trên Rokid

- Ưu tiên UI kiểu HUD: nền trong suốt hoàn toàn, không dùng card mờ hoặc panel đặc.
- Màn hình thực tế nên coi là vùng nhìn hạn chế, không phải toàn bộ rectangle nhìn được rõ như điện thoại.
- Với layout portrait 480x640, vùng nội dung dễ nhìn ổn định thường nằm thấp hơn trung tâm hình học.
- Bài học quan trọng: thiết kế đẹp trên emulator chưa chắc đẹp trên kính thật, luôn chốt bằng test thiết bị thật.

## 2) Safe Zone và bố cục

- Đặt lyric chính ở lower-safe-zone thay vì giữa màn hình:
- Kinh nghiệm tốt: `centerY` khoảng `0.72h -> 0.75h` cho lyric app.
- Vùng hiển thị active line nên rộng vừa đủ để tránh cắt chữ:
- Kinh nghiệm tốt: `activeLayoutWidth ~ 0.88w -> 0.92w`.
- Chỉ hiển thị 3 dòng tại một thời điểm:
- `prev` (mờ), `current` (nổi bật), `next` (mờ vừa).
- Không hiển thị quá nhiều dòng mờ vì gây rối và giảm độ đọc.

## 3) Typography (Việt + Anh)

- Dùng font tách theo ngôn ngữ:
- Việt: font có dấu rõ, độ mở chữ tốt.
- Anh: font mềm hơn, weight thấp hơn một chút để bớt “cứng”.
- Active line dùng semibold; side lines dùng regular.
- Letter spacing nhỏ và ổn định (`0.001 -> 0.003`) để tránh cảm giác chữ bị giãn cơ học.
- Kích thước gợi ý cho lyric HUD:
- Active: khoảng `20px -> 29px` theo bề rộng màn hình.
- Side: khoảng `12px -> 16px`.

## 4) Auto-Fit chữ thông minh (rất quan trọng)

- Vấn đề thường gặp: câu dài bị cắt, đặc biệt câu Việt có dấu hoặc câu Anh dài.
- Cách xử lý tốt:
- Giữ `maxLines = 3`.
- Tìm cỡ chữ tốt nhất bằng binary search trong khoảng `[minActiveSize, baseActiveSize]`.
- Dùng `StaticLayout` đo thật và kiểm tra `ellipsisCount` từng line.
- Cache kết quả theo key `(language + width + text)` để không đo lại mỗi frame.
- Min size nên giữ đủ đọc được, ví dụ khoảng `>= 14px`.

## 5) Hiệu ứng chuyển lyric: mượt nhưng tối giản

- Tránh kiểu “nhảy index cứng” theo frame, dễ giật.
- Nên chạy theo timeline từng câu:
- `progress = (currentTime - lineTs) / (nextLineTs - lineTs)`.
- Dùng easing mềm (`easeInOutSine`) cho vertical shift.
- Alpha side lines thay đổi theo `progress` để chuyển cảnh êm.
- Hiệu ứng glow nên rất nhẹ:
- Dùng “breathing pulse” biên độ thấp.
- Shadow radius và alpha thay đổi nhỏ theo pulse.
- Nguyên tắc: hiệu ứng phải giúp chữ “sang hơn”, không được thu hút hơn nội dung chữ.

## 6) Đồng bộ lyric với audio (anti-jitter)

- Tick UI 16ms là ổn, nhưng không nên phụ thuộc hoàn toàn `player.currentPosition` mỗi frame.
- Dùng render clock nội bộ:
- Giữ `clockBasePosition + elapsedDelta`.
- Mỗi ~88ms lấy sample mới từ player.
- Tính drift và bù mềm (EMA + soft correction), chỉ hard-resync khi lệch lớn.
- Có thể thêm `lead` nhẹ (vài chục ms) để cảm giác lyric “bắt nhịp” tự nhiên hơn.
- Lead nên adaptive theo drift và/hoặc duration giữa 2 câu.

## 7) Parser và dữ liệu lyric

- Luôn lọc line rỗng trước khi render để tránh nhảy index sai.
- Hỗ trợ timestamp nhiều định dạng:
- `[mm:ss]`, `[mm:ss.xx]`, `[mm:ss.xxx]`.
- Tôn trọng metadata `offset` trong LRC, sau đó mới áp dụng soft lead runtime.
- Khi không có lyric sync:
- Hiển thị thông điệp ngắn, đặt đúng vùng lower-safe-zone (không đưa lên quá cao).

## 8) Tối ưu hiệu năng

- Cache `StaticLayout` cho active text.
- Cache `text size fit` cho từng câu.
- Không tạo object nặng liên tục trong `onDraw`.
- Không vẽ các thành phần ngoài viewport (ví dụ side line quá trên/dưới).
- Animation vừa phải, tránh shadow quá đậm hoặc blur quá lớn.

## 9) Những lỗi đã gặp và cách tránh

- Lỗi lệch trái / dồn góc:
- Nguyên nhân: wrap + align không nhất quán.
- Khắc phục: layout active line theo `StaticLayout` center trong vùng width cố định.
- Lỗi nhảy loạn:
- Nguyên nhân: index nội suy không ổn định.
- Khắc phục: timeline-based progress + easing.
- Lỗi cắt/mất chữ:
- Nguyên nhân: size cố định + width hẹp.
- Khắc phục: auto-fit + tăng width + maxLines hợp lý.
- Lỗi rối mắt:
- Nguyên nhân: quá nhiều dòng mờ và hiệu ứng mạnh.
- Khắc phục: chỉ giữ 1 prev + 1 next, alpha thấp, glow nhẹ.

## 10) Bộ thông số khởi điểm khuyến nghị (reusable)

- `centerY`: `0.74h`
- `activeWidth`: `0.90w`
- `sideWidth`: `0.82w`
- `activeSize`: `20 -> 29`
- `sideSize`: `12 -> 16`
- `lineSpacing`: `activeSize * 1.45 -> 1.50`
- `tick`: `16ms`
- `sample player position`: `~88ms`
- `hard drift reset`: `~300ms`
- `maxLines active`: `3`

## 11) Checklist trước khi phát hành app HUD mới cho Rokid

- Test ít nhất 3 kiểu bài:
- Câu ngắn, câu rất dài, bài có nhiều khoảng nghỉ.
- Test cả tiếng Việt có dấu và tiếng Anh.
- Test seek tua nhanh tới/lui, next/prev track nhiều lần.
- Test với file LRC có offset âm/dương.
- Test trong môi trường ánh sáng khác nhau (độ dễ đọc thay đổi rõ).
- Nếu nhìn đẹp trên kính thật trong 15-20 phút liên tục mà không mỏi mắt, coi như đạt.

## 12) Đối chiếu từ dự án khác (tham khao, khong phai authority cho RV101)

- `rokid/glass-docs`:
- UI SDK xác nhận 3 hướng quan trọng: `GlassAlignment`, `GlassButton`, `GlassDialog`.
- Có guideline về scale theo thiết kế qua manifest meta-data:
- `design_width_in_dp = 640`, `design_height_in_dp = 360` (theo bản thiết kế gốc).
- Ý nghĩa thực tế: luôn có “hệ quy chiếu thiết kế” trước khi scale runtime.

- `Anezium/awesome-rokid`:
- Cho thấy hệ sinh thái app Rokid đã rất rộng (AI, navigation, media, utility, learning).
- Ý nghĩa thực tế: khi làm app mới nên đối chiếu UX pattern theo nhóm use-case thay vì chỉ xem 1 repo lyric.

- `chartmann1590/Rokid-Maps` và `Anezium/Rokid-GMaps`:
- Khẳng định pattern HUD hiệu quả: nhiều layout mode (`Full`, `Corner`, `Mini`) và ưu tiên thông tin quan trọng trước.
- Dùng protocol phone ↔ glasses rõ ràng (JSON line-based), giúp realtime ổn định.
- Dùng cấu hình mô phỏng `480x640` để dev nhanh nhưng vẫn nhấn mạnh test thiết bị thật.
- Ý nghĩa thực tế cho lyric app: giữ HUD tối giản, tách “điều khiển” và “hiển thị” rõ tầng.

- `RealComputer/GlassKit` (các ví dụ Rokid):
- Nhấn mạnh rõ: UI trên Rokid nên “monochrome HUD” và mapping input phải tương thích touchpad.
- Có `RokidHudViewportLayout` 3:4 để tránh sai hình khi chạy trên phone/emulator.
- Có guideline thực dụng: không chặn hành vi back ở root screen vì đây là đường thoát chính.
- Ý nghĩa thực tế: mọi app Rokid nên có lớp viewport abstraction và input abstraction ngay từ đầu.

- `Vuzix/hud-resources` + `Vuzix/hud-actionmenu` (khác hãng, nhưng rất đáng học):
- Có phân loại loại màn hình `TRANSPARENT` vs `OCCLUDED`.
- Có API chuẩn cho touchpad/button type và menu behavior theo tương tác người dùng.
- Ý nghĩa thực tế: kiến trúc UI nên tách theo “display type” và “input type”, không hard-code cho một model duy nhất.

## 13) Quy tắc mới rút ra sau đối chiếu đa dự án

- Luôn tách 3 lớp:
- `Viewport/Layout policy` (safe zone, ratio, letterbox)
- `Input policy` (touchpad, key, voice, phone fallback)
- `Render policy` (font, animation, cadence, anti-jitter)

- Ưu tiên monochrome-first cho kính:
- Dù có hỗ trợ màu, phải thiết kế sao cho chạy tốt ở độ tương phản cao 1 màu.

- Phải có profile runtime theo thiết bị và display type:
- Ví dụ transparent waveguide và occluded viewfinder cần trọng số khác nhau cho vị trí/chữ.

- Motion phải “semantic”, không chỉ “trang trí”:
- Mỗi hiệu ứng phải phục vụ đọc nhanh và giảm mỏi mắt, không được chỉ để “đẹp”.

- Input có tính bắt buộc:
- Luôn giữ đường thoát/Back rõ ràng.
- Gesture mapping và key mapping nên nhất quán giữa kính thật và emulator/phone test.

- Ưu tiên architecture có thể mở rộng:
- Tách parser/sync/render để tái dùng sang subtitle, teleprompter, HUD notification mà không viết lại lõi.

## 14) Bài học mới từ `DK256/Rokid-Glasses-card`

Luu y:

- Day la nguon tham khao ve card language.
- Khong nen coi `480 x 400` trong repo nay la viewport spec chot cho `RV101` neu chua co test thiet bi that xac nhan.

Repo này không phải app Android hoàn chỉnh, mà là một `scene card library` cho Rokid theo hướng:

- card-based UI
- `480 x 400` canvas
- design tokens rõ ràng
- protocol sinh UI kiểu khai báo (`A2UI v0.8`)
- nhiều mẫu card cho các ngữ cảnh thực tế như weather, notify, music, express, driving, translation, meeting, shopping

Đây là nguồn tham khảo rất tốt để học `cách Rokid nên hiển thị card`, nhất là khi mình muốn app có UI "system-like" hơn thay vì chỉ là Android screen bị ép lên HUD.

### 14.1 Điều rất đáng chú ý

- Repo này chốt thẳng `card resolution = 480 x 400px`, đúng với trực giác trước đó rằng vùng đẹp nhất trên kính nên co lại thay vì dùng full `480 x 640`.
- Nó dùng bộ token rất nhất quán:
- `#40FF5E` là màu sáng chính
- `#000000` là nền page
- `#1C1C1C` là nền card
- `rgba(64,255,94,0.55)` là màu dim
- Card, button, divider, badge đều dùng cùng một hệ opacity và border.
- Typography được đẩy thành hẳn semantic system:
- `display 52/60`
- `title 24/30`
- `subtitle 20/26`
- `body 16/22`
- `caption 13/18`
- `button 15/20`
- Repo này còn cho thấy pattern quan trọng:
- page-level navigation nằm ngoài card
- bản thân card chỉ chứa nội dung của `một scene state`
- nhiều state của cùng một scene được preview song song bằng `state tabs`

### 14.2 Những rule hiển thị nên mượn lại

- Card nên được coi là `đơn vị UI chuẩn` cho Rokid:
- một card = một ngữ cảnh / một trạng thái / một tác vụ
- card có header, body, footer rất rõ
- dùng border để định khung thay vì fill mạnh

- Tách `page` và `card`:
- page background đen tuyệt đối
- card nền xám đậm
- card là nơi duy nhất mang phần lớn thông tin
- cách này giúp thông tin chính "nổi" lên mà vẫn tiết chế độ chói

- Dùng `dim text` nhiều hơn mình tưởng:
- thay vì chỉ xanh sáng và xanh mờ nhẹ, repo này dùng nhiều tầng opacity khá tốt
- kết quả là hierarchy rõ mà không cần thêm nhiều màu

- Header pattern rất hợp kính:
- icon nhỏ + label ngắn + status badge / time ở góc đối
- điều này rất hợp cho HUD vì người dùng chỉ cần liếc là hiểu ngữ cảnh

- Footer action row kiểu 1-2 nút lớn là pattern đẹp:
- các card như call/notify/express đều ưu tiên 1 hàng nút rõ ràng ở cuối
- đây là pattern nên dùng cho mọi app Rokid có thao tác xác nhận nhanh

### 14.3 Gợi ý mới cho app của mình

- Nếu app là utility hoặc assistant, đừng nghĩ theo "screen trước", hãy nghĩ theo `card trước`.
- Mỗi flow nên chia thành:
- `overview card`
- `processing card`
- `result card`
- `error / recovery card`

- Nếu cần nhiều trạng thái:
- dùng `same shell, different states`
- thay vì đổi layout hoàn toàn giữa từng state
- cách này vừa dễ đọc vừa dễ maintain

- Với app có dữ liệu thay đổi nhanh:
- ưu tiên render `stateful card` thay vì recycler/list dài
- nghĩa là mỗi thời điểm chỉ hiển thị mẩu thông tin quan trọng nhất

- Với app AI:
- mô hình card rất hợp cho:
- listening
- thinking
- answer summary
- follow-up actions

### 14.4 Điều có thể học về kiến trúc UI

Repo này rất đáng chú ý vì nó đi theo hướng `protocol -> renderer`, thay vì hard-code từng màn hình.

Ý nghĩa thực tế:

- Có thể nghĩ đến việc tách:
- `scene data`
- `scene schema`
- `scene renderer`

- Nếu sau này mình làm app riêng cho kính có nhiều card:
- nên có `design tokens` riêng
- nên có `card scaffold` riêng
- nên có `state renderer` riêng

- Với app AI/Jetson:
- rất có thể mình chỉ cần gửi JSON trạng thái gọn từ backend
- app trên kính map JSON đó thành card
- đây là cách tự nhiên để app trên kính nhẹ hơn rất nhiều

### 14.5 Những thứ cần dùng có chọn lọc

- `display 52px` rất đẹp cho số lớn, thời gian, speed, countdown
- nhưng không nên lạm dụng cho text dài

- `caption 13px` trong repo nhìn ổn ở HTML mockup
- nhưng khi lên kính thật, mình vẫn nên xem `16px` là mốc an toàn cho phần lớn nội dung
- `13px` chỉ nên dành cho metadata thật ngắn

- Nền card `#1C1C1C` có vẻ hợp cho card mô phỏng hoặc layer rõ ràng
- nhưng với một số app HUD text-heavy, nền trong suốt hoặc gần như trong suốt vẫn có thể dễ nhìn hơn
- nghĩa là pattern `card mode` rất tốt, nhưng không phải lúc nào cũng là đáp án duy nhất

### 14.6 Bộ nguyên tắc cập nhật sau khi xem repo này

- `480 x 400` nên được coi là viewport tham chiếu rất mạnh cho card UI
- nên xây sẵn một `RokidCardScaffold`
- nên có semantic typography thay vì chỉ hard-code font size
- nên dùng:
- page nền đen
- card nền đậm
- card viền xanh
- text xanh + dim opacity
- nên thiết kế theo `scene/state card`, không theo `phone screen`

## 14) Danh sách nguồn tham khảo khuyến nghị (ưu tiên cao)
## 15) Danh sách nguồn tham khảo khuyến nghị (ưu tiên cao)

- Rokid official docs:
- https://github.com/rokid/glass-docs
- https://rokid.github.io/glass-docs/

- Rokid community ecosystem:
- https://github.com/Anezium/awesome-rokid
- https://github.com/Anezium/Rokid-Lyrics
- https://github.com/chartmann1590/Rokid-Maps
- https://github.com/Anezium/Rokid-GMaps
- https://github.com/Anezium/Rokid-DragonBallScouter
- https://github.com/RealComputer/GlassKit
- https://github.com/DK256/Rokid-Glasses-card

- Cross-brand references (HUD engineering):
- https://github.com/Vuzix/hud-resources
- https://github.com/Vuzix/hud-actionmenu
- https://github.com/Vuzix/ultralite-sdk-android-sample

---

## 16) Tóm tắt nguyên tắc vàng

UI cho kính phải “ít nhưng đúng”: vị trí đúng safe zone, chữ luôn đọc được, chuyển động mềm, sync chắc, hiệu ứng chỉ làm nền cho nội dung.
