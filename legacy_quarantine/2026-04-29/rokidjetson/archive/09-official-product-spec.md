# 09. Official Product Spec

Updated: 2026-04-18

## 1. Mục tiêu tài liệu

Tài liệu này không nhằm chốt cứng thiết kế cuối cùng.

Mục tiêu là:

- hệ thống lại ý tưởng sản phẩm hiện tại
- chuyển từ app debug sang app chính thức
- làm rõ trải nghiệm trên kính và cơ chế AI trên Jetson
- giúp các bước code sau này đi đúng hướng, ít sửa lớn

Đây là bản `product spec giai đoạn đầu`, không phải bản đóng băng yêu cầu.

## 2. Tầm nhìn sản phẩm

Thiết bị hoạt động như sau:

- kính Rokid luôn là thiết bị người dùng đeo và nhìn HUD
- Jetson là bộ não AI chính
- kính gửi video liên tục sang Jetson
- Jetson chỉ bật đúng pipeline AI theo mode người dùng chọn
- Jetson trả kết quả gọn, dễ đọc, ít gây phân tâm
- kính hiển thị thông tin theo từng mode rất tối giản, phù hợp giao tiếp trực tiếp ngoài đời

Nói ngắn gọn:

`Rokid = camera + selection UI + HUD`

`Jetson = AI orchestrator + inference + result publisher`

## 3. Mục tiêu UX chính

### 3.1 Khi vào app

App mở lên sẽ:

- tự động kết nối Jetson như hiện tại
- tự động kết nối control/result/video như hiện tại
- không ép người dùng vào màn debug
- chỉ hiện một trạng thái rất ngắn ở trên cùng:
  - `connecting...`
  - `connected`
  - `vpn connected`
  - `reconnecting`

Trạng thái này phải:

- nhỏ
- gọn
- không chiếm tầm nhìn
- không làm người đeo mất tập trung

### 3.2 Màn chính

Màn chính không còn là màn debug metrics.

Màn chính sẽ là:

- thanh trạng thái kết nối nhỏ ở trên cùng
- khu vực chọn tính năng ở dưới / giữa màn hình
- UI tối giản, focus-based, tối ưu cho touchpad Rokid

### 3.3 Khi chọn tính năng

Khi người dùng chọn một tính năng:

- kính gửi `mode_change` sang Jetson
- Jetson bật đúng pipeline tương ứng
- các pipeline khác ngủ / unload / disable
- HUD trên kính chuyển sang layout tối ưu riêng cho mode đó

## 4. Nguyên tắc sản phẩm

### 4.1 Ưu tiên trải nghiệm thật hơn debug

Giai đoạn debug dày đã cho đủ dữ liệu ban đầu.

Từ đây:

- bỏ phần debug không cần thiết khỏi màn hình chính
- giữ log nền ở mức vừa phải
- chỉ bật debug sâu khi cần

### 4.2 Jetson không được chạy tất cả model cùng lúc

Nguyên tắc vận hành:

- chỉ bật mode đang dùng
- mode không dùng phải ngủ hoặc bị dừng
- tránh đốt GPU/RAM vô ích
- tránh nóng máy và giảm độ ổn định

### 4.3 HUD phải theo từng mode

Không dùng một HUD chung cho mọi thứ.

Mỗi mode cần một cách hiển thị riêng:

- face mode: thông tin người quen ở dưới
- vehicle line count: đường đếm và tổng đếm rõ ràng
- object / scene mode: label và count dạng card gọn

### 4.4 Người dùng vẫn phải nhìn và tương tác với thế giới thật

Đây là nguyên tắc cực quan trọng.

Thông tin trên kính phải:

- ngắn
- dễ hiểu
- không che mặt người đối diện
- không phá giao tiếp tự nhiên

## 5. Các tính năng sản phẩm giai đoạn đầu

## 5.1 Face recognition cho người quen

### Ý tưởng chính

Khi nhìn vào người quen, Jetson nhận diện khuôn mặt và trả về một gói thông tin ngắn để kính nhắc nhớ.

### Dữ liệu lưu trên Jetson

Mỗi hồ sơ người quen có thể gồm:

- `personId`
- `name`
- `age`
- `job`
- `relationship`
- `lastSeenAt`
- `shortNotes`
- `avatarRef` hoặc `embeddingRef`

### Thông tin hiển thị trên kính

HUD nên nằm ở vùng dưới của màn hình để người đeo vẫn nhìn được khuôn mặt thật.

Ví dụ:

- `Anh Minh`
- `34 • kiến trúc sư`
- `đã gặp tuần trước`
- `thích nói về dự án nhà thông minh`

### Mục tiêu UX

- giúp nhớ tên
- giúp nhớ bối cảnh ngắn
- không hiển thị quá dài
- không làm người đeo phải đọc nhiều

### Ghi chú triển khai

- chỉ hiển thị khi match đủ chắc
- nếu chưa chắc thì chỉ báo:
  - `possible match`
  - hoặc không hiện gì
- phần dữ liệu hồ sơ phải lưu ở Jetson, không nhét lên kính

## 5.2 Vehicle line counting

### Ý tưởng chính

Jetson nhận diện xe, theo dõi xe và tăng bộ đếm khi xe đi qua một vạch đếm đã định nghĩa.

### Mục đích

- đếm lưu lượng xe
- biết tổng số xe đi qua một vạch
- có thể tách theo loại xe nếu cần

### UI trên kính

HUD riêng cho mode này nên có:

- một đường ngang hoặc vạch đếm
- tổng số xe đã qua
- có thể thêm:
  - `car`
  - `motorbike`
  - `truck`

Ví dụ:

- `Traffic Count`
- `Total 18`
- `Car 11 | Bike 6 | Truck 1`

### Điểm cần làm rõ sau này

- vạch đếm sẽ cấu hình ở đâu:
  - trên Jetson web tool
  - hay calibration mode trên kính
- chỉ đếm 1 chiều hay 2 chiều
- có cần nhiều vùng/vạch không

### Ghi chú triển khai

- mode này nên có tracker
- count chỉ tăng khi đối tượng cắt vạch theo rule rõ ràng
- tránh double count

## 5.3 People / object counting

### Ý tưởng chính

Jetson đếm người và các vật thể quan tâm trong khung hình.

Đầu ra phù hợp HUD:

- `person = 3`
- `bag = 1`
- `helmet = 2`
- `chair = 4`

### Hướng kỹ thuật

Phần object recognition có thể tận dụng model YOLO đang ổn định trên Jetson, ví dụ model bạn đang gọi là `yolo26` nếu nó thực sự đang sẵn sàng và đủ nhanh trên máy.

Ở giai đoạn thiết kế này, chưa cần chốt tên model cuối cùng.

### UI trên kính

Mode này nên hiển thị:

- tên mode ngắn
- count chính
- 2-4 object quan trọng nhất
- alert nếu có

Ví dụ:

- `Scene Monitor`
- `People 4`
- `Bag 2 | Helmet 1`
- `alert: unattended object`

## 6. Kiến trúc mode trên Jetson

## 6.1 Jetson là AI mode orchestrator

Jetson cần có một lớp điều phối:

- nhận `selected mode` từ kính
- quyết định pipeline nào được phép chạy
- load / warmup / unload model
- publish result về lại kính

### Khối logic đề xuất

- `session gateway`
- `mode manager`
- `pipeline registry`
- `result publisher`

## 6.2 Trạng thái pipeline

Mỗi pipeline nên có các trạng thái:

- `inactive`
- `warming`
- `active`
- `cooldown`
- `error`

### Hành vi đề xuất

- app mở nhưng chưa chọn mode:
  - chỉ giữ kết nối, chưa bật AI nặng
- chọn mode:
  - pipeline vào `warming`
  - HUD trên kính hiện `starting...`
- xong warmup:
  - pipeline vào `active`
  - HUD chuyển sang layout thật
- đổi mode:
  - pipeline cũ `cooldown / inactive`
  - pipeline mới `warming`

## 6.3 Chính sách tiết kiệm tài nguyên

Nguyên tắc sản phẩm:

- chỉ 1 heavy mode active tại một thời điểm
- mode không dùng không được tiếp tục inference nền
- nếu có thành phần dùng chung được thì tái sử dụng:
  - decoder
  - tracker
  - frame bus
- nhưng model head riêng phải ngủ khi không dùng

## 7. Thiết kế app chính thức trên kính

## 7.1 Bỏ những gì khỏi bản debug hiện tại

Khỏi màn hình chính:

- dòng metric dài
- CPU/RAM/PSS
- payload bytes
- sentSamples
- file log path
- debug codec/color
- analyzer/encoder drops

Những thứ này chỉ nên:

- ghi log nền
- hoặc nằm trong `developer panel`

## 7.2 Giữ lại những gì ở mức sản phẩm

Trên màn người dùng chỉ nên còn:

- trạng thái kết nối ngắn ở trên cùng
- vùng chọn tính năng
- HUD riêng theo mode

## 7.3 Màn chính đề xuất

### Phần trên cùng

- text rất ngắn:
  - `connecting`
  - `vpn connected`
  - `jetson ready`

### Phần chọn tính năng

Một menu dạng card hoặc list focus-based:

- `Face Memory`
- `Traffic Count`
- `Scene / Object`

Sau này có thể thêm:

- `OCR`
- `Open Vocabulary`
- `Assistant`

### Phần dưới cùng

- hint điều khiển ngắn nếu cần
- hoặc để trống cho sạch

## 7.4 Điều khiển bằng touchpad Rokid

Dựa trên tài liệu input đã tổng hợp trong:

- `rokid-touchpad-and-input-reference.md`

Đề xuất thao tác:

- `single tap`
  - chọn / confirm
- `double tap`
  - đổi mode nhanh / next panel
- `left / right`
  - chuyển card tính năng
- `long press`
  - mở menu phụ / setting / developer tools
- `back`
  - quay lại màn chọn mode

## 8. HUD riêng cho từng tính năng

## 8.1 HUD cho Face Memory

Vị trí:

- phía dưới màn hình

Lý do:

- giữ vùng giữa thoáng để nhìn mặt người đối diện

Nội dung:

- tên
- nghề nghiệp
- ghi chú ngắn
- độ chắc của match nếu cần

Không nên:

- hiện quá nhiều text
- hiện cả hồ sơ dài

## 8.2 HUD cho Traffic Count

Vị trí:

- vùng giữa hoặc hơi thấp

Nội dung:

- đường đếm ngang
- tổng số xe
- phân loại xe ngắn

Có thể thêm:

- mũi tên chiều đếm
- vùng đếm highlight khi xe đi qua

## 8.3 HUD cho Scene / Object Count

Vị trí:

- card nhỏ ở cạnh hoặc phía dưới

Nội dung:

- label count chính
- 2-4 class quan trọng
- alert nếu có

Ví dụ:

- `People 3`
- `Bag 1`
- `Helmet 2`
- `alert: left object`

## 9. Dữ liệu và protocol mức sản phẩm

## 9.1 Control

Kính cần gửi:

- `client_hello`
- `mode_change`
- `ping`

Jetson cần trả:

- `session_accept`
- `mode_state`
- `vision_result`
- `node_state`

## 9.2 Result schema mức sản phẩm

Result trả về nên có cấu trúc ổn định:

- `mode`
- `headline`
- `summary`
- `counts`
- `alerts`
- `faces` hoặc `objects`
- `latency`

Ý tưởng là:

- app kính không cần biết model nào đang chạy
- app chỉ cần render theo schema mode

## 10. Chuyển từ prototype sang product

## 10.1 Phase A

Mục tiêu:

- làm lại màn hình chính thành product UI
- bỏ bớt debug
- giữ tự động kết nối như hiện tại
- làm menu chọn tính năng

## 10.2 Phase B

Mục tiêu:

- mode selection thật
- Jetson bật / tắt pipeline theo mode
- fake result vẫn đủ để test UX

## 10.3 Phase C

Mục tiêu:

- thay fake result bằng AI thật cho từng mode
- ưu tiên:
  - object / people count
  - traffic line count
  - face memory

## 10.4 Phase D

Mục tiêu:

- tinh chỉnh HUD riêng từng mode
- ẩn developer data
- giữ dev menu ẩn bằng long press

## 11. Những quyết định chưa cần chốt ngay

Những điểm sau chưa cần khóa ở giai đoạn này:

- model face cuối cùng là gì
- model vehicle/object cuối cùng là gì
- có dùng YOLO hiện tại hay đổi model khác
- đường đếm xe cấu hình trên kính hay trên Jetson
- hồ sơ người quen có thêm trường nào nữa
- có cần nhiều mode chạy song song ở mức nhẹ không

## 12. Kết luận thực dụng

Từ những gì đã có, hướng sản phẩm chuẩn hiện tại là:

- app mở lên tự kết nối Jetson như bây giờ
- màn hình chính tối giản, không còn đầy debug
- người dùng chọn mode trên kính
- Jetson chỉ bật đúng AI mode được chọn
- HUD thay đổi theo đúng nhiệm vụ của mode đó
- dữ liệu người quen và metadata đều nằm ở Jetson

Đây là hướng phù hợp nhất để đi từ:

- `stream/debug prototype`

sang:

- `Rokid + Jetson product shell`
