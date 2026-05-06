# 10. Current Working State Handoff

Updated: 2026-04-21

Status note:

- File nay duoc giu lai nhu `historical transitional handoff`.
- Khong dung no lam source-of-truth cho huong hien tai nua.
- Cac diem trong file da bi vuot qua gom:
  - `ImageAnalysis` tren kinh la pipeline chinh
  - `openai_realtime` transcription la voice path chinh
  - mode picker tren kinh la UX san pham chinh
- Khi can trang thai hien tai, uu tien:
  - `PROJECT_MEMORY.md`
  - `ROKID_CURRENT_STATE.md`
  - `ROKID_CODEX_EXECUTION_PACK.md`
  - `docs/reference/jetson-openai-realtime-skill-foundation.md`

## 1. Muc dich file nay

File nay duoc viet de:

- chot lai trang thai du an hien tai
- giup mo topic moi la hieu ngay du an dang o dau
- tranh lap lai cac loi da gap
- giup chuyen sang phase toi uu app tren kinh va gan AI that tren Jetson

File nay khong phai product spec y tuong.

Day la `handoff operational state`.

## 2. Tom tat nhanh

Hien tai du an da prove duoc cac diem sau:

1. `Rokid Glasses RV101 -> Jetson` stream video that da chay duoc.
2. Stream da chay duoc ca:
   - `LAN`
   - `Internet qua Tailscale`
3. `Jetson -> Rokid Glasses RV101` da gui duoc du lieu fake AI va HUD tren kinh da nhan dung.
4. Jetson web preview / dashboard da dung duoc va khong can local `ffplay` nua.
5. Tailscale tren Jetson da hoat dong on.
6. Backend Jetson da duoc cau hinh `systemd` de tu khoi dong sau reboot.
7. Voice da chuyen sang `OpenAI Realtime transcription` lam duong STT chinh.
8. HUD cua kinh da hien duoc `live caption` tro lai.
9. Schema HUD da co them `gallery`, `direction_hint`, `target_marker`.

Noi ngan gon:

`camera on Rokid -> encode H264 -> send to Jetson -> Jetson fake AI result -> HUD on glasses`

duong nay da thong, va hien tai da vuot qua muc fake AI don gian.

## 2.1 Dieu da pass / chua pass

### Da pass

- build Android app
- backend syntax check
- health Jetson `ok`
- split audio/video socket on dinh
- local `ffplay` da tat de tranh lag backend
- live caption tren kinh da co lai

### Dang pass mot phan

- `target_search` da route dung tren Jetson
- backend da tao duoc HUD scene kieu target search
- app kinh da parse duoc scene moi va co log `candidateVisible`

### Chua duoc xem la done

- target-search HUD chua duoc prove bang log moi nhat voi APK scene-priority moi nhat
- STT tieng Viet van chua muot nhu ngon ngu tu nhien
- nguon mic tren kinh da tot hon nhung chua pin on dinh han

## 3. Cau truc hien tai

### 3.1 App tren kinh

Project:

- `RokidVideoStream`

Vai tro:

- mo camera tren kinh
- encode `H264`
- gui video sang Jetson
- ket noi `WebSocket control/result`
- nhan fake AI result va hien thi HUD
- thao tac bang touchpad / key event cua Rokid

### 3.2 Backend Jetson

Source local:

- `rokidjetson/backend_mvp`

Deploy tren Jetson:

- `/mnt/ssd/ai-security-ds/rokid/apps/backend_mvp`

Vai tro:

- nhan `WebSocket control`
- tao session
- nhan video `tcp_h264`
- nhan audio `pcm` tren socket rieng
- ghi `.h264`
- giu web preview / dashboard
- voice runtime + OpenAI Realtime STT
- gui `hud_scene` semantic ve kinh

Luu y moi:

- khong coi Jetson la noi render bitmap HUD
- Jetson la `HUD authority`
- kinh la `thin HUD renderer`

## 4. Tailscale / VPN

### 4.1 Jetson

Jetson da cai Tailscale thanh cong.

Trang thai da verify:

- `tailscaled` active
- DNS: `<jetson-tailnet-name>.ts.net`
- IPv4 tailnet: `<jetson-tailnet-ip>`

### 4.2 Kinh

Kinh da cai Tailscale thanh cong.

Trang thai da thay trong tailnet:

- host: `<glasses-tailnet-name>.ts.net`
- IPv4 tailnet: `<glasses-tailnet-ip>`

### 4.3 Ket luan

Media va control da co the di qua Tailscale thay vi LAN thong thuong.

Khong can public port Jetson ra Internet.

## 5. Backend auto-start sau reboot

Day la mot bai hoc quan trong.

Da gap tinh huong:

- reboot Jetson
- Tailscale tu len
- backend Rokid khong tu len
- ket qua la kinh khong ket noi duoc du da co VPN

Da sua:

- tao `systemd` service:
  - `/etc/systemd/system/rokid-backend.service`

Trang thai hien tai:

- `enabled`
- sau reboot backend se tu len

Luu y:

- service nay dung `Type=oneshot`
- script that spawn backend qua `tmux`
- khong dung `Type=simple` vi se bi systemd restart loop

## 6. Port va host dang dung

Jetson backend health:

- `http://127.0.0.1:9080/health`

Control:

- `ws://<jetson-host>:9080/ws`

Media:

- host: `<jetson-host>`
- port: `9082`
- transport: `tcp_h264`

Voice hien tai:

- primary STT: `openai_realtime`
- model: `gpt-4o-mini-transcribe`

## 7. Trang thai app tren kinh

### 7.1 App hien tai

APK build moi nhat:

- `_apk/rokid-video-stream-only-debug.apk`

Project:

- `RokidVideoStream`

### 7.2 Nhung gi da hoat dong

- auto-connect Jetson qua Tailscale
- touchpad/key navigation
- chon mode:
  - `standby`
  - `face_memory`
  - `traffic_count`
  - `scene_monitor`
- HUD nhan fake result tu Jetson
- camera bind bang `ImageAnalysis` only
- stream khong can `Preview` use case
- live caption hien duoc tren strip duoi
- parse duoc `gallery`, `direction_hint`, `target_marker`
- co log `hud_render_applied`, `candidateVisible`, `candidateCount`

### 7.3 Nhung gi da sua gan day tren kinh

- khong de `speech_state` generic de len HUD de transcript de che mat scene quan trong
- bo sung candidate gallery overlay
- bo sung cache HUD ngan han de reconnect khong trang
- uu tien scene co nghia tu Jetson hon transcript song trong mot khoang ngan

### 7.4 Nhung gi van dang mo

- can log moi sau APK scene-priority moi nhat de xac nhan target-search HUD that su len tren kinh
- phan mic source van can toi uu tiep

### 7.3 Nhung gi can nho

Stream video tren kinh hien tai la:

- `ImageAnalysis -> MediaCodec -> TCP send`

Khong phai:

- screen capture
- preview render roi moi lay lai

## 8. Quy tac UI da rut ra cho Rokid Glasses RV101

Day la phan rat quan trong vi da tung di sai huong.

### 8.1 Cai da sai

Da tung lam:

- app giong man Android full-screen
- nen trong suot nhung de lo ra phan ngoai app
- hoac nen mo/opaque sai kieu tren see-through glasses
- card lon, giao dien day dac, khong hop HUD

Ket luan:

- khong duoc treat Rokid Glasses `RV101` nhu phone mini

### 8.2 Cai da chot

Da ghi rieng tai:

- `docs/reference/official-glass-ui-notes.md`

Rule quan trong:

1. `Rokid Glasses RV101` la HUD see-through, khong phai Rokid Max.
2. Public docs chi tiet nhat hien co den tu nhanh `Rokid Glass` cu, nen chi duoc dung nhu nguyen ly tham khao neu con khop voi `RV101`.
3. UI phai nho, gon, text-first, touchpad-first.
4. Public docs cua Rokid xac nhan:
   - `Touch pad`
   - `no preview`
   - `Glass style UI`
   - `alignment`
5. Android CameraX docs xac nhan `ImageAnalysis` co the chay doc lap, khong can `Preview`.

### 8.3 Bai hoc thuc te

Neu thay tren kinh:

- mot lop Android ro rang
- nen/mo/haze khong mong muon
- card to, day dac

thi dang di sai huong.

## 9. Fake AI mode da co

Jetson fake result hien tai da support shell san pham:

- `standby`
- `face_memory`
- `traffic_count`
- `scene_monitor`

Gia tri tra ve da tung chay duoc that tren kinh:

- `face label`
- `headline`
- `count`
- `alert`
- `detail lines`
- `latency`

Dieu nay rat quan trong vi no prove:

- schema control/result da hop ly
- HUD co the giu nguyen khi thay fake mode bang AI that

## 10. Viewer local tren Jetson

`ffplay` khong con la huong uu tien nua.

Ly do:

- no tung gay tranh CPU va lam web UI / backend path keo cham
- web preview da du cho debug hang ngay

Trang thai hien tai:

- `ROKID_ENABLE_LOCAL_PREVIEW=0`
- debug va preview nen uu tien web UI / MJPEG

## 11. Bai hoc moi rat quan trong

1. Khong duoc dung session sai de danh gia bug sai.

   - `sess_1bceb4aa` chu yeu la `assistant_query`, khong phai target-search session tot de danh gia HUD tim nguoi.

2. Khong duoc de `listening=true` suy dien thanh `live caption`.

   - day la mot trong nhung ly do lam HUD scene bi transcript de.

3. Neu `target_search` da vao router thi Jetson phai day placeholder HUD ngay.

   - vi neu doi YOLO/candidate thi nguoi dung se thay chi co transcript va nghi la HUD khong chay.

4. Tin PCM energy hon callback silence metadata.

   - callback silence tren kinh da tung dan den switch source sai.

## 12. Buoc hien tai cua du an

Buoc dung nhat hien nay la:

1. cai APK moi nhat len kinh
2. test lai mot session `tim nguoi ao vang`
3. doc log xem co:
   - `target_search_placeholder_queued`
   - `target_search_hud_queued`
   - `hud_render_applied` voi `candidateVisible=true` hoac `source=scene/target_search`
4. neu da qua buoc nay moi tiep tuc nang cap perception graph + cloud disambiguation

Neu thay khong co viewer:

1. kiem tra `video_connected`
2. kiem tra `video_frames` co tang khong
3. kiem tra `ffplay` process
4. nho rang neu khong co media vao thi viewer se khong bat

## 11. Cac loi da gap va ket luan

### 11.1 Chi co WebSocket nhung khong co video

Da gap tinh huong:

- `WebSocket /ws` open roi close
- Jetson khong nhan frame
- viewer khong mo

Ket luan:

- control path len khong co nghia la media path da len
- phai kiem tra rieng `video_connected`, `video_frames`, `video_peer`

### 11.2 Reboot Jetson xong kinh khong ket noi duoc

Nguyen nhan:

- Tailscale len
- backend khong tu len

Da fix bang `systemd`.

### 11.3 Preview / viewer local co process nhung nguoi dung van khong thay

Nguyen nhan:

- window title that te la `ffplay`
- co the bi nam sau cua so NoMachine khac
- khong phai luc nao cung ro rang nhu mot app native co title dep

### 11.4 Dung `Type=simple` cho systemd la sai

Nguyen nhan:

- script start spawn backend qua `tmux` roi thoat
- systemd hieu sai va restart loop

Da fix:

- chuyen sang `Type=oneshot`
- `RemainAfterExit=yes`

### 11.5 Treat Rokid Glasses RV101 nhu phone UI la sai

Nguyen nhan:

- hieu sai tinh chat see-through HUD
- app bi day dac, khong dung style kinh

Da chot:

- can toi uu theo `HUD`, `touchpad`, `small info blocks`

## 12. Thong so stream da tung do duoc

Trong cac phien chay that da tung thay:

- `MEDIUM` la mode can bang tot nhat
- fps thuong o tam:
  - `7 - 10 fps`
- `encodeMs` thuong:
  - `20 - 33 ms`
- `sendMs` thuong:
  - `1 - 2 ms`

Ket luan:

- du de prove hạ tang
- du de bat dau gan AI that
- van con du dia toi uu tiep phia app kinh

## 13. Nhung gi da on dinh va co the giu nguyen

Co the tiep tuc dua tren nhung phan sau ma khong can viet lai:

1. `Tailscale architecture`
2. `Jetson backend port layout`
3. `WebSocket control/result`
4. `HUD schema`
5. `TCP H264 ingest`
6. `local preview ffplay`
7. `systemd autostart`

## 14. Nhung gi nen toi uu tiep o topic moi

Day la danh sach hop ly cho topic tiep theo:

### 14.1 Phia kinh

- toi uu UI/HUD cho dung hon voi Rokid Glasses RV101
- giam bot phan debug con thua
- lam mode shell giong san pham that hon
- on dinh hoa hanh vi:
  - mo app
  - vao mode
  - bat stream
  - thoat mode
- giam drop / giam CPU / giam pin

### 14.2 Phia Jetson

- thay `fake result` bang `AI that`
- uu tien mode dau tien:
  - `face_memory`
  - hoac `scene_monitor`
  - hoac `traffic_count`

## 15. Cach tiep can AI that khuyen nghi

Khong nen sua HUD truoc.

Nen:

1. giu nguyen schema fake result
2. thay module fake bang output model that
3. cho mode nao on dinh roi moi mo rong them

Cach lam dung:

- `face_memory`:
  - detector + face embedding + local profile db
- `traffic_count`:
  - detector + tracker + line crossing rule
- `scene_monitor`:
  - detector object/person + compact counts

## 16. File quan trong can doc khi mo topic moi

1. Handoff operational state:
   - `rokidjetson/10-current-working-state-handoff.md`

2. Product spec archive:
   - `rokidjetson/archive/09-official-product-spec.md`

3. Touchpad va input:
   - `docs/reference/touchpad-and-input-reference.md`

4. UI note dung cho `RV101`:
   - `docs/reference/official-glass-ui-notes.md`

5. App project:
   - `RokidVideoStream`

6. Jetson backend source:
   - `rokidjetson/backend_mvp`

## 17. Ket luan cuoi

Du an da qua duoc giai doan kho nhat cua infrastructure:

- stream that
- VPN that
- HUD that
- Jetson result -> glasses that

Tu day tro di, trong topic moi nen tap trung vao:

- toi uu trai nghiem tren kinh
- thay fake AI bang AI that
- giu nguyen nhung phan ha tang da prove duoc

Khong nen quay lai tranh luan lai:

- co stream duoc khong
- Tailscale co chay duoc khong
- Jetson co gui du lieu nguoc ve kinh duoc khong

Vi tat ca nhung diem do da duoc prove roi.
