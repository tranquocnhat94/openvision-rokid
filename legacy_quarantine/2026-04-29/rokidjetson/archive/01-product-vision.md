# 01. Product Vision

## 1. Bai toan can giai

Can xay mot app tren kinh Rokid co kha nang:

- mo camera
- stream video realtime sang Jetson trong cung LAN
- nhan ket qua xu ly AI tu Jetson
- hien thi overlay/HUD gon nhe tren kinh
- cho nguoi dung chon che do AI dang can

Y nghia thuc te:

- kinh nhe viec
- Jetson giai phan nang
- UI nam tren kinh
- AI nam tren edge node

## 2. Gia tri cua san pham

Neu lam dung, he thong nay co the tro thanh mot "vision assistant" cho nhieu use case:

- dem nguoi trong khu vuc
- dem xe
- dem mot loai vat the cu the
- nhan dien khuon mat theo danh sach noi bo
- canh bao co doi tuong can quan tam
- xem thong so live tren HUD

Ban dau khong can co tat ca use case. Chi can 1-2 use case chay that muot la du.

## 3. Nguyen tac san pham

1. Kinh khong la noi chay AI nang.
2. Jetson la edge brain, nhung chi chay nhung gi duoc bat.
3. Transport phai on dinh hon "dep ly thuyet".
4. Ket qua tra ve kinh phai ngan, ro, de doc trong HUD.
5. Moi che do AI phai co gioi han tai nguyen ro rang.
6. Neu mat mang hoac Jetson loi, app tren kinh van phai fail-safe.

## 4. Pham vi Phase 1

Chi tap trung vao LAN:

- Rokid va Jetson chung Wi-Fi/hotspot/router
- stream 1 video uplink tu Rokid sang Jetson
- Jetson tra metadata ve kinh
- khong bat buoc stream video nguoc lai
- khong dua cloud vao duong media

## 5. Vai tro cua tung ben

### Rokid app

Lam:

- camera capture
- hardware encode neu co
- gui media sang Jetson
- gui telemetry
- nhan result metadata
- render HUD
- cho chon che do AI
- hien ket noi, FPS, latency, thermal, session state

Khong nen lam:

- infer model nang lien tuc
- luu queue frame lon
- phan tich vision phuc tap

### Jetson service

Lam:

- nhan media stream
- decode
- quan ly session
- model orchestration
- tracking
- result fusion
- gui result lai cho Rokid
- logging va dashboard debug

## 6. Use case uu tien

Nen chon thu tu uu tien nhu sau:

### Muc 1: Dem nguoi

- de nhin gia tri
- data model pho bien
- HUD de hien thi
- de do latency va FPS

### Muc 2: Dem xe / object counter

- cung mot detector co the tai su dung
- khong can face database
- phu hop dem line crossing, zone count

### Muc 3: Face recognition

- co gia tri cao
- nhung nhay cam ve privacy
- workflow phuc tap hon
- can database embedding va nguong match

### Muc 4: Custom object mode

- nguoi dung chon mot profile
- Jetson nap model / label map tuong ung

## 7. Tuyen ngon kien truc

Du an nay nen duoc xem la:

`edge vision platform for smart glasses`

chu khong chi la:

`app stream video`

Vi phan kho nhat khong nam o stream, ma nam o:

- session
- control
- model scheduling
- HUD thong minh
- fallback
- logging
