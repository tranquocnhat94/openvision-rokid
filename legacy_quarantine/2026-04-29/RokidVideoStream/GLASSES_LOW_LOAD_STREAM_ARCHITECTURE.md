# Glasses Low-Load Stream Architecture

## Mục tiêu

Kiến trúc này là đường chuẩn hiện tại cho app kính Rokid khi stream sang Jetson.

Mục tiêu ưu tiên theo thứ tự:

1. giảm tải tối đa cho kính
2. giữ nhiệt và pin thấp nhất có thể
3. giữ full FOV thực dụng, không crop vô lý
4. giữ preview/AI trên Jetson mượt và ổn định
5. chỉ để kính làm những việc thật sự cần thiết

Nguyên tắc cốt lõi:

- kính không làm AI
- kính không xử lý pixel từng frame nếu không bắt buộc
- kính không decode lại video của chính nó
- kính không tự động đổi profile hoặc restart camera giữa chừng
- mọi phần nặng phải đẩy sang Jetson

## Kiến trúc chuẩn

```text
Camera sensor
  -> Camera2 CaptureSession
  -> MediaCodec H.264 encoder (input Surface)
  -> TCP video transport
  -> Jetson ingest/decode/AI/overlay
  -> WebSocket result/control
  -> HUD text trên kính
```

Phía kính chỉ giữ 4 nhóm việc:

- mở camera
- encode H.264 bằng phần cứng
- gửi video sang Jetson
- nhận kết quả và vẽ HUD nhẹ

## Vì sao kiến trúc này đúng

Kiến trúc cũ dùng:

```text
CameraX ImageAnalysis
  -> ImageProxy
  -> copy/convert YUV bằng CPU
  -> MediaCodec
```

Điểm yếu của đường cũ:

- app phải chạm vào từng pixel của mọi frame
- tốn CPU và memory bandwidth rất nhiều
- dễ rớt FPS
- dễ nóng máy và hao pin
- dễ bị lệch resolution do CameraX/HAL chọn stream ngoài ý muốn
- khi thêm các cơ chế tự tối ưu sai hướng sẽ gây restart camera và nhảy quality

Đường mới dùng:

```text
Camera2
  -> MediaCodec Surface input
```

Điểm mạnh:

- không còn copy YUV frame-by-frame trong app
- không còn `ImageAnalysis` trong hot path
- giảm rõ CPU và native heap
- ổn định resolution hơn
- Jetson nhận stream đều hơn, preview mượt hơn

## Bằng chứng từ log thật

Session xác nhận tốt nhất hiện tại:

- Jetson session: `sess_d05f7fc7`
- log file:
  - `/mnt/ssd/ai-security-ds/rokid/logs/sess_d05f7fc7.jsonl`

Các dấu hiệu tốt trong log:

- `camera_started` báo rõ:
  - `pipeline = camera2_surface`
- `video_hello` giữ ổn định:
  - `width = 800`
  - `height = 600`
  - không có nhảy sang `1512x2016` hay tự tụt `480x640`
- `encoder_stats`:
  - `inputLayout = Surface`
  - `colorFormat = Surface`
  - `analyzerDrops = 0`
  - `encoderDrops = 0`
- `device_telemetry` gần cuối session:
  - `appCpuPercent ≈ 44.8%`
  - `javaHeapMb ≈ 5.1`
  - `nativeHeapMb ≈ 21.8`
  - `totalPssMb ≈ 58.6`
  - `captureFps ≈ 15.0`
  - `encodeFps ≈ 15.2`
- Jetson:
  - `rx_fps ≈ 25.6`
  - local preview mượt hơn rõ rệt

Đây là tín hiệu mạnh cho thấy kiến trúc mới đúng hướng.

### Baseline mới hơn sau khi giảm `video_hello` và telemetry

Session xác nhận mới hơn:

- Jetson session: `sess_862088eb`
- log file:
  - `/mnt/ssd/ai-security-ds/rokid/logs/sess_862088eb.jsonl`

Điểm nổi bật:

- `video_hello` không còn spam theo frame
  - chỉ xuất hiện lúc đầu phiên và sau đó khoảng mỗi `15s`
- `device_telemetry` thưa hơn rõ rệt
  - khoảng `3s` một lần
- `encoder_stats` thưa hơn
  - khoảng `4s` một lần
- `inputLayout = Surface`
- `colorFormat = Surface`
- `analyzerDrops = 0`
- `encoderDrops = 0`
- `encodeMs` đã về mức hợp lý cho nhánh Surface
  - thường quanh `0.26 - 0.48 ms`
- `captureFps` ổn định quanh `15 fps`
- `encodeFps` ổn định quanh `15 - 16 fps`
- `appCpuPercent` nền thường quanh `35 - 45%`
- `totalPssMb` cuối phiên khoảng `61.9 MB`

Ý nghĩa:

- transport metadata đã gọn hơn
- logging/telemetry không còn quấy nhiễu nhiều như trước
- chỉ số `encodeMs` không còn ảo kiểu hàng trăm ms
- baseline vận hành trên kính sạch hơn và đáng tin hơn để tối ưu tiếp

## Lưu ý về resolution thực tế

Profile app hiện tại là logical profile, nhưng size thực camera HAL có thể chọn khác một chút nếu đó là size video an toàn hơn.

Ví dụ session tốt hiện tại:

- profile yêu cầu: `MEDIUM 720x960`
- size thực camera/encoder chọn: `800x600`

Điều này chấp nhận được nếu:

- cùng aspect hợp lý
- không crop méo
- stream ổn định
- preview Jetson đẹp hơn

Ưu tiên là stability và low load, không phải cố ép camera ra một size danh nghĩa bằng mọi giá.

## Những gì tuyệt đối không nên quay lại

- không đưa `ImageAnalysis` quay lại main stream path
- không copy `ImageProxy` YUV sang `ByteArray` cho mọi frame
- không auto profile downgrade khi đang stream
- không đổi resolution giữa session nếu không có lý do rất rõ
- không làm blur/filter bằng CPU trên kính
- không render UI theo mọi frame camera
- không để debug logs chạy dày mặc định
- không thêm local AI hoặc local object detection trên kính

## Phân bổ trách nhiệm đúng giữa kính và Jetson

### Kính

- capture
- hardware encode
- transport
- control
- HUD text
- telemetry chậm

### Jetson

- decode
- AI inference
- tracking
- counting
- overlay bbox
- preview cho người xem
- ghi log và quản lý session

## Chi phí tài nguyên cần giữ thấp trên kính

### CPU

Phải giữ thấp nhất có thể vì ảnh hưởng trực tiếp tới:

- nhiệt
- pin
- độ mượt tổng thể

Quy tắc:

- chỉ dùng CPU cho orchestration và network
- không cho CPU xử lý pixel đường dài

### RAM / native heap

Cần tránh:

- frame buffer lớn bị giữ nhiều bản
- alloc `ByteArray` theo frame
- converter buffer cho mọi nhánh không cần thiết

### Memory bandwidth

Đây là loại chi phí rất dễ bị quên nhưng rất đắt.

Copy YUV toàn frame nhiều lần sẽ làm:

- nóng máy
- tụt FPS
- hao pin nhanh

Surface path giải quyết tốt nhất điểm này.

### Pin

Pin của kính nhỏ, nên mọi tối ưu phải ưu tiên:

- ít CPU wake-up hơn
- ít copy hơn
- ít background logging hơn
- ít restart camera hơn

## Quy tắc vận hành profile

Nguyên tắc hiện tại:

- profile là fixed
- không tự đổi giữa session
- nếu cần đổi thì đổi bằng hành động chủ động của người dùng hoặc debug

Gợi ý profile:

- `LOW`: khi cần pin lâu hoặc mạng yếu
- `MEDIUM`: mode mặc định thực dụng
- `HIGH`: chỉ dùng khi cần thêm chi tiết

Không chase độ phân giải danh nghĩa nếu log cho thấy size HAL khác nhưng stream chạy mượt hơn.

## Kết quả mong muốn khi kiểm tra log

Một session tốt nên có:

- `pipeline = camera2_surface`
- `inputLayout = Surface`
- `colorFormat = Surface`
- `analyzerDrops = 0`
- `encoderDrops = 0`
- không có `profile_auto_downgrade`
- không có `camera_bind_failed`
- không có restart resolution giữa session
- `captureFps` và `encodeFps` ổn định
- CPU app và `totalPss` không tăng mất kiểm soát theo thời gian

## Known caveat hiện tại

Metric `encodeMs` trong session `camera2_surface` hiện chưa phản ánh chính xác pure codec cost.

Nó vẫn đang bị tính theo kiểu gần với độ trễ từ timestamp capture tới lúc app xử lý sample output, nên có thể thấy giá trị cao bất thường dù stream thực tế vẫn mượt.

Điều này không phủ định kiến trúc mới.
Nhưng nếu cần benchmarking sâu hơn, phải sửa riêng cách đo `encodeMs`.

## File code liên quan

- app activity:
  - `RokidVideoStream/app/src/main/java/com/example/cxrservicedemo/videostream/VideoStreamActivity.kt`
- pipeline mới:
  - `RokidVideoStream/app/src/main/java/com/example/cxrservicedemo/videostream/SurfaceVideoStreamPipeline.kt`
- transport:
  - `RokidVideoStream/app/src/main/java/com/example/cxrservicedemo/videostream/transport/JetsonMediaStreamClient.kt`
- encoded sample models:
  - `RokidVideoStream/app/src/main/java/com/example/cxrservicedemo/videostream/EncodedVideoSample.kt`

## Hướng tối ưu tiếp theo

1. giữ nguyên kiến trúc này làm baseline
2. sửa metric `encodeMs` cho đúng nghĩa
3. nếu cần tiết kiệm thêm:
   - giảm tần suất telemetry
   - giảm churn `video_hello`
   - giảm debug path khi không dùng dev panel
4. chỉ sau đó mới cân nhắc tối ưu transport

## Kết luận

Đây là kiến trúc đúng để phát triển tiếp.

Nếu mục tiêu vẫn là:

- pin lâu hơn
- kính mát hơn
- video sang Jetson mượt hơn
- AI chạy chủ yếu ở Jetson

thì phải tiếp tục giữ triết lý:

`glasses do less, Jetson does the heavy work`
