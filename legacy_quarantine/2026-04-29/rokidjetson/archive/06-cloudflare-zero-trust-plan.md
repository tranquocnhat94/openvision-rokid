# 06. Cloudflare Zero Trust Plan

## 1. Nguyen tac quan trong nhat

Cloudflare Zero Trust khong nen duoc xem la media transport chinh cho realtime video.

No nen duoc xem la:

- access layer
- identity layer
- secure control plane
- dashboard/API exposure layer

Khong nen xem la:

- giai phap tu dong cho low-latency video
- thay the hoan toan WebRTC/STUN/TURN neu can Internet realtime

## 2. Thu tu mo rong dung

1. On dinh LAN.
2. Chot schema control/result.
3. Chot auth/session device.
4. Dua control plane qua Cloudflare Zero Trust.
5. Danh gia lai media over Internet.
6. Neu can realtime that, nang cap sang WebRTC/coturn.

## 3. Control plane qua Cloudflare

Nhung thu hop de di qua Cloudflare Zero Trust:

- dashboard Jetson
- HTTPS API
- WebSocket control
- session management
- device registration
- operator UI
- remote logs

## 4. Media plane qua Internet

Co 2 lua chon thuc te:

### Lua chon A: Van giu media local/LAN

Dung khi:

- Jetson va Rokid thuong o gan nhau
- Internet chi dung de quan ly tu xa

Day la cach an toan nhat.

### Lua chon B: Media realtime qua Internet

Dung khi:

- Rokid o xa Jetson
- van can latency thap

Huong dung hon:

- WebRTC media path
- signaling/API dat sau Cloudflare Access
- TURN server neu can relay

## 5. Kien truc Internet hop ly

```text
Rokid
  -> HTTPS/WebSocket via Cloudflare Access
  -> signaling / auth / session

Rokid
  -> WebRTC media path
  -> STUN/TURN
  -> Jetson or relay
```

## 6. Ranh gioi bao mat

Can co:

- device identity
- user identity
- session token ngan han
- role cho operator/admin
- log truy cap
- revoke device

## 7. Cach chuyen giai doan

### Giai doan 1

- hardcode LAN host de prove nhanh

### Giai doan 2

- them pairing code / saved host

### Giai doan 3

- them Cloudflare Access cho dashboard va control API

### Giai doan 4

- them Internet media that su neu can

## 8. Dieu khong nen lam som

- ep RTP/UDP thuan di xuyen Cloudflare tunnel roi ky vong realtime dep
- dua Internet vao truoc khi co metric LAN
- them auth phuc tap truoc khi chot protocol
