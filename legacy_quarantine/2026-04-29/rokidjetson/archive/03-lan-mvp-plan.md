# 03. LAN MVP Plan

## 1. Muc tieu MVP that su

MVP khong phai la "AI hoan hao". MVP la:

1. Rokid stream video on dinh sang Jetson trong LAN.
2. Jetson nhan, decode va chay duoc 1 mode AI.
3. Jetson tra metadata ve kinh theo thoi gian gan realtime.
4. Kinh hien thi dung state, count va canh bao co ban.
5. Session chay on 10-15 phut ma khong vo pipeline.

## 2. Tieu chi thanh cong

MVP duoc xem la dat neu:

- ket noi duoc bang IP/host config
- thoi gian vao session < 5 giay
- media khong dong bang trong test LAN co ban
- latency tong the o muc chap nhan duoc cho HUD
- doi mode AI khong can cai lai session
- khi Jetson mat ket noi, app tren kinh thong bao ro va thu reconnect

## 3. Thu tu lam viec dung

### Phase A: Transport only

Chua them AI.

Lam:

- app Rokid mo camera
- encode H264
- stream sang Jetson
- Jetson live preview + ghi metrics

Thanh cong khi:

- thay frame den Jetson lien tuc
- co so do bitrate / FPS / drop

### Phase B: Result loop

Chua them model that.

Lam:

- Jetson tra lai packet gia lap
- Rokid render HUD theo packet do

Vi du:

- `person_count = 3`
- `alert = zone_entered`
- `latency_ms = 140`

Thanh cong khi:

- da chung minh duoc loop hai chieu
- UI tren kinh khong phu thuoc vao model that

### Phase C: 1 mode AI that

Chi nap 1 pipeline AI.

De xuat:

- person detector + tracker

Thanh cong khi:

- count nguoi cap nhat on
- FPS va latency do duoc
- Jetson khong bi phinh RAM/VRAM

### Phase D: Mode switching

Them chon che do tu app tren kinh.

De xuat:

- `People Count`
- `Vehicle Count`
- `Face Mode`

Thanh cong khi:

- bat/tat mode tu Rokid
- Jetson chuyen pipeline khong crash
- tai nguyen giam khi tat mode

## 4. Man hinh / UX can co tren kinh

### Screen 1: Connect

- host/IP
- port
- nut connect
- trang thai Wi-Fi
- session state

### Screen 2: Live HUD

- ten mode AI
- count chinh
- sub-metrics
- latency
- tx bitrate
- jetson status
- reconnect notice

### Screen 3: Mode Select

- danh sach mode
- mo ta ngan
- ghi chu tai nguyen

### Screen 4: Debug

- capture FPS
- encode FPS
- send FPS
- result FPS
- device temp/battery

## 5. Logging can co ngay tu MVP

### Tren Rokid

- session id
- selected mode
- connect/disconnect
- capture FPS
- encode latency
- send bitrate
- battery
- thermal
- dropped frame
- ping RTT

### Tren Jetson

- receive FPS
- decode latency
- latest-frame queue depth
- AI inference latency
- result publish latency
- GPU/CPU/RAM
- model load/unload event

## 6. Ranh gioi MVP

Khong dua vao MVP lan dau:

- cloud auth that
- multi-user
- multi-camera
- video return stream tu Jetson
- face database lon
- OCR/ASR/LLM cung luc

## 7. Ranh gioi ky thuat can nho

- neu stream chua on, dung them AI
- neu result chua on, dung them UI dep
- neu mode switch chua on, dung them nhieu model
- neu log chua du, dung toi uu vo blind
