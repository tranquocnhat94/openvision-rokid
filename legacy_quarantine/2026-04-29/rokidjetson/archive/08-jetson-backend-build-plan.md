# 08. Jetson Backend Build Plan

## 1. Jetson thuc te dang co

Backend plan nay dua tren may Jetson hien tai:

- hostname: `jay`
- OS: `Ubuntu 22.04.5 LTS`
- LAN IP hien tai: `<jetson-lan-ip>`
- user van hanh: `jay`
- workspace AI hien tai: `/mnt/ssd/ai-security-ds`
- SSD data root: `/mnt/ssd`

Day khong phai la Jetson "trang". Day la Jetson dang co he production Ring chay song song.

## 2. Rang buoc quan trong nhat

Ring dang la production.

Vi vay backend Rokid phai obey 4 nguyen tac:

1. Khong chiem port dang dung cua Ring/go2rtc/timeline/MQTT.
2. Khong lam anh huong `jetson-phase2-ring.service`.
3. Khong dua them DB/UI nang len Jetson.
4. Moi thanh phan Rokid phai co the tat doc lap neu co su co.

## 3. Tinh hinh tai nguyen hien tai

Theo file ghi chu ngay `2026-04-16`:

- RAM used: `3.4 - 3.7 GB / 7.6 GB`
- RAM available: khoang `3.6 GB`
- CPU tong: `90%+ idle`
- GPU: nhan luc nhan roi
- nhiet do: khoang `52C`
- cong suat: `4.6W - 5.1W`

Ket luan backend:

- du headroom cho 1 pipeline Rokid MVP
- chua phu hop de them nhieu pipeline nang cung luc
- can uu tien 1 detector + 1 tracker + 1 bus ket qua

## 4. Port va service phai tranh

Port dang dung:

- `1984` go2rtc UI/API
- `8554` RTSP public
- `8555` DeepStream Ring debug/output
- `8558` go2rtc WebRTC
- `1884` MQTT noi bo
- `8091` timeline UI
- `4000` NoMachine

Service dang dung:

- `jetson-phase2-ring.service`
- `jetson-event-bridge.service`
- `jetson-telegram-bridge.service`
- `jetson-timeline-recorder.service`
- `jetson-timeline-ui.service`
- `nxserver.service`

Ket luan:

- Rokid backend nen la 1 namespace rieng
- khong chen vao service Ring hien tai
- co the tai su dung MQTT `1884`, nhung media/control service nen tach rieng

## 5. Vai tro dung cua backend Jetson

Jetson backend nen chiu trach nhiem:

- ingest media tu Rokid
- decode va dat frame vao queue ngan
- chay AI mode duoc chon
- publish result metadata
- optional restream output neu can debug
- log metrics va health

Jetson backend khong nen chiu trach nhiem:

- quan tri nguoi dung lon
- dashboard admin phuc tap
- cloud sync phuc tap
- LLM/backend business logic nang

## 6. Kien truc backend de xuat

```text
Rokid App
  -> media uplink
  -> control websocket

Jetson
  -> rokid-session-gateway
  -> rokid-media-ingest
  -> rokid-frame-bus
  -> rokid-ai-runner
  -> rokid-result-publisher
  -> rokid-metrics/logger

Consumers
  -> Rokid HUD
  -> MQTT topics
  -> optional RTSP/WebRTC debug
  -> Home Assistant / Mini PC / app khac
```

## 7. Thu muc backend nen tao tren Jetson

Nen tach namespace rieng duoi:

- `/mnt/ssd/ai-security-ds/rokid/`

Ben trong de xuat:

- `apps/`
- `configs/`
- `models/`
- `runtime/`
- `logs/`
- `scripts/`
- `samples/`

So do thuc te:

```text
/mnt/ssd/ai-security-ds/rokid/
  apps/
  configs/
  models/
  runtime/
  logs/
  scripts/
  samples/
```

## 8. Cac service backend nen co

### `rokid-session-gateway`

Nhiem vu:

- nhan `client_hello`
- cap `sessionId`
- quan ly mode dang chon
- ping/pong
- control websocket

Khuyen nghi:

- service nhe
- Python FastAPI hoac Node nhe deu duoc
- uu tien API va WebSocket ro rang

### `rokid-media-ingest`

Nhiem vu:

- nhan stream tu Rokid
- RTSP/SRT/gstreamer UDP tu phase 1
- decode hoac day cho pipeline decode
- track bitrate/FPS/drop

MVP nen uu tien:

- `H264`
- `720p`
- `10-15 fps`

### `rokid-frame-bus`

Nhiem vu:

- giu latest frame
- bo frame cu khi worker chua xu ly kip
- chia frame cho AI runner

Muc tieu:

- tranh backlog
- giu feel realtime

### `rokid-ai-runner`

Nhiem vu:

- load/unload pipeline theo mode
- infer tren frame moi nhat
- thong ke latency

MVP mode dau tien:

- `people_count`

### `rokid-result-publisher`

Nhiem vu:

- gui ket qua ve Rokid qua WebSocket
- publish ra MQTT noi bo
- optional ghi event file

MQTT topic de xuat:

- `jetson/rokid/events`
- `jetson/rokid/alerts`
- `jetson/rokid/debug`
- `jetson/rokid/telemetry`

### `rokid-metrics`

Nhiem vu:

- log session
- log resource
- log model load/unload
- log reconnect
- health endpoint

## 9. Luong du lieu backend de xuat

1. Rokid mo WebSocket den Jetson.
2. Jetson tra `session_accept`.
3. Rokid bat media uplink.
4. `rokid-media-ingest` nhan va decode stream.
5. `rokid-frame-bus` giu frame moi nhat.
6. `rokid-ai-runner` infer theo mode dang bat.
7. `rokid-result-publisher` gui result JSON lai cho Rokid.
8. Cung luc, publisher day MQTT event neu can.
9. Neu can debug, Jetson restream output ra RTSP/WebRTC rieng.

## 10. Lua chon ky thuat cho backend MVP

### Media

Nen uu tien mot huong de prove nhanh:

- `RTSP ingest` neu sender Rokid de phat RTSP
- hoac `gstreamer udp/h264` neu sender app de day thang

Tam thoi chua uu tien:

- WebRTC media o ngay dau
- multi-stream
- transcode phuc tap

### Control plane

Nen dung:

- `WebSocket`
- `JSON schema`

Ly do:

- de debug
- de doi mode
- de tra telemetry/result

### Event bus

Nen tai su dung:

- MQTT local `127.0.0.1:1884`

Vi no da co san trong he hien tai.

## 11. Resource budget cho MVP

Backend MVP nen tu gioi han:

- 1 stream Rokid
- 1 pipeline AI
- 1 tracker
- 1 websocket session chinh
- 1 output MQTT

Khong nen mo ngay:

- 2-3 stream song song
- face recognition production
- restream output fulltime neu chua can
- luu clip dai lien tuc

## 12. Operational plan dung

### Stage 1: Safe ingest

Muc tieu:

- nhan duoc video Rokid ma khong anh huong Ring

Can co:

- port rieng cho Rokid
- process rieng
- log rieng

### Stage 2: Result loop

Muc tieu:

- Jetson tra packet gia lap ve Rokid

Can co:

- gateway
- websocket
- ping/pong
- health endpoint

### Stage 3: 1 AI mode that

Muc tieu:

- `people_count`

Can co:

- detector
- tracker
- count logic
- latency metric

### Stage 4: Integrate voi he hien tai

Muc tieu:

- publish event sang MQTT
- neu can moi expose cho HA/Mini PC

### Stage 5: Hardening

Muc tieu:

- systemd service
- auto-restart
- persistent logs
- retention rule cho logs/snapshots

## 13. Service names de xuat

De de quan ly, nen dat:

- `rokid-session-gateway.service`
- `rokid-media-ingest.service`
- `rokid-ai-runner.service`
- `rokid-result-publisher.service`

Neu muon gon trong MVP, co the gop thanh:

- `rokid-backend.service`

Sau khi on dinh moi tach nho ra.

## 14. Port namespace de xuat cho Rokid

De tranh xung dot, nen chon mot cum port rieng cho Rokid.

Vi du:

- `9080` HTTP health/API
- `9081` WebSocket control/result
- `9554` RTSP ingest/debug
- `9880` metrics/debug neu can

Day moi la de xuat namespace logic, chua phai lenh chot production.

## 15. Viec nen lam dau tien tren Jetson

Neu bat dau ngay tu backend, thu tu dung nhat la:

1. Tao namespace thu muc `/mnt/ssd/ai-security-ds/rokid/`
2. Dung 1 process `rokid-backend` duy nhat cho MVP
3. Mo `WebSocket + health endpoint`
4. Nhap 1 luong H264 don gian
5. Log receive FPS + decode latency
6. Tra fake result ve Rokid
7. Chi sau do moi nap `people_count`

## 16. Chot huong backend

Huong dung nhat voi Jetson hien tai la:

- xem Jetson nhu inference node sidecar
- dung headroom con lai, khong duoc cham vao Ring production
- backend MVP nho, ro, de tat
- result day qua WebSocket va MQTT
- UI nang / admin nang de o may khac neu sau nay can
