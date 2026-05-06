# 07. Roadmap and Checklists

## 1. Roadmap tong quan

### Stage 0: Design freeze nho

Can chot:

- 1 use case dau tien
- 1 transport media MVP
- 1 result schema
- 1 cach connect host

Deliverable:

- tai lieu nay duoc thong qua

### Stage 1: Rokid sender

Can lam:

- camera capture on dinh
- preview an neu can
- H264 encode
- config host/IP
- metrics local

Deliverable:

- app Rokid gui stream sang Jetson duoc

### Stage 2: Jetson receiver

Can lam:

- media receive
- decode
- live preview/debug
- session log

Deliverable:

- Jetson nhan va hien stream on

### Stage 3: Result loop

Can lam:

- websocket control
- fake result publisher
- HUD tren Rokid
- ping/pong

Deliverable:

- loop hai chieu hoat dong

### Stage 4: 1 AI mode that

Can lam:

- people detector
- tracker
- result summary
- latency metrics

Deliverable:

- people count hien on tren kinh

### Stage 5: Mode manager

Can lam:

- UI chon mode
- pipeline load/unload
- telemetry Jetson

Deliverable:

- switch mode khong crash

### Stage 6: Internet control plane

Can lam:

- Cloudflare Access
- session auth
- remote dashboard

Deliverable:

- quan ly tu xa an toan

### Stage 7: Internet media neu can

Can lam:

- WebRTC signaling
- STUN/TURN
- test latency that

Deliverable:

- streaming ngoai LAN co metric ro rang

## 2. Checklist cho Stage 1

- mo camera on dinh
- preview an van giu pipeline
- co setting host/IP
- co start/stop stream
- co log session
- co HUD debug co ban

## 3. Checklist cho Stage 2

- Jetson nhan duoc media
- decode on
- co xem FPS that
- co save sample clip neu can
- co metric queue/drop

## 4. Checklist cho Stage 3

- websocket ket noi on
- ping/pong do RTT
- fake result len HUD
- disconnect co thong bao ro
- reconnect co gioi han va backoff

## 5. Checklist cho Stage 4

- 1 model duy nhat
- 1 tracker duy nhat
- count khong nhay qua muc
- infer latency co log
- end-to-end latency co log

## 6. Decision gate truoc khi sang Internet

Chi sang Internet khi:

- LAN test on 10-15 phut lien tuc
- mode switch khong crash
- metrics day du
- da hieu ro bottleneck
- co session auth design

## 7. Ket luan hanh dong

Neu muon bat dau ngay, thu tu code dung nhat la:

1. Sender media tren Rokid.
2. Receiver + debug dashboard tren Jetson.
3. WebSocket control/result.
4. Fake result HUD.
5. People count mode.
6. Mode switching.
7. Cloudflare Access cho control plane.
8. WebRTC chi khi can Internet realtime that.
