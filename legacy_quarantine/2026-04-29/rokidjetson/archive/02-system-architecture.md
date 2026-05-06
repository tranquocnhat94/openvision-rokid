# 02. System Architecture

## 1. Kien truc tong the

```text
Rokid Glasses
  -> Camera Capture
  -> Media Encoder
  -> Media Uplink
  -> Control Client
  -> HUD Renderer

LAN

Jetson
  -> Session Gateway
  -> Media Receiver
  -> Decoder
  -> Latest-Frame Queue
  -> AI Orchestrator
  -> Result Publisher
  -> Metrics Logger
```

## 2. Cac kenh giao tiep

Phai tach thanh 4 kenh:

### A. Media channel

- huong: `Rokid -> Jetson`
- chua video encoded
- uu tien latency
- khong tron voi JSON control

### B. Control channel

- hai chieu: `Rokid <-> Jetson`
- bat dau/ket thuc session
- doi mode AI
- bat/tat model
- doi threshold / profile
- ping/pong do RTT

### C. Result channel

- huong chinh: `Jetson -> Rokid`
- gui metadata gon
- object count
- alerts
- face match
- latency summary

### D. Telemetry channel

- hai chieu neu can
- device health
- FPS
- CPU/GPU/RAM
- thermal
- dropped frames

## 3. Kien truc app tren Rokid

Nen chia app thanh cac module logic sau:

### `capture`

- CameraX
- Preview an neu camera HAL can
- frame source on dinh

### `encoder`

- MediaCodec H264 truoc
- co the can H265 sau
- bitrate profile theo mode

### `transport`

- media uplink
- websocket control/result
- reconnect policy

### `hud`

- render overlay
- status panel
- count/result card
- alert state

### `session`

- pairing host
- session id
- selected AI mode
- metrics local

## 4. Kien truc service tren Jetson

### `gateway`

- nhan ket noi moi
- cap session id
- auth local phase 1 don gian
- auth that phase 2

### `receiver`

- nhan media stream
- track bitrate
- track jitter
- detect disconnect

### `decoder`

- hardware decode neu co
- dua frame vao queue ngan

### `frame-bus`

- latest-frame queue
- khong giu backlog dai
- drop frame cu khi AI chua xu ly kip

### `ai-orchestrator`

- xem mode dang bat
- load/unload model
- route frame den pipeline dang can

### `result-publisher`

- tra ket qua cho Rokid
- coalescing neu ket qua qua day
- uu tien thong tin moi nhat

### `metrics`

- log theo session
- dashboard local
- su kien reconnect

## 5. Kien truc duoc khuyen nghi cho Phase 1

### Media uplink de xuat

Huong de xuat cho Phase 1:

- `H264`
- `RTP/RTSP` hoac `gstreamer udp pipeline`
- control/result di bang `WebSocket`

Ly do:

- prove media nhanh
- debug tren Jetson de hon
- tach media khoi control ro rang
- phu hop LAN

### Huong doi sau khi can Internet

Huong doi cho Phase 2/3:

- media chuyen dan sang `WebRTC`
- control/result van giu `WebSocket/HTTPS`

Ly do:

- WebRTC hop hon cho Internet realtime
- nhung phuc tap hon cho MVP LAN

## 6. Luong du lieu chuan

1. Rokid app mo session voi Jetson.
2. Rokid gui `hello + capability + selected mode`.
3. Jetson tra `session accepted + stream params`.
4. Rokid bat media uplink.
5. Jetson decode va day frame vao latest-frame queue.
6. AI orchestrator xu ly frame moi nhat theo mode dang bat.
7. Result publisher gui metadata lai cho Rokid.
8. Rokid render HUD.
9. Neu nguoi dung doi mode, control message gui sang Jetson.
10. Jetson load/unload pipeline tuong ung ma khong restart toan bo app neu tranh duoc.

## 7. Nguyen tac hieu nang

- media phai chay duoc du 10-15 phut lien tuc
- AI co the bo qua frame, khong duoc de queue phinh ra
- HUD update 5-10 lan/giay la du, khong can moi frame
- result quan trong hon video preview nguoc
- reconnect phai nhanh hon restart full app
