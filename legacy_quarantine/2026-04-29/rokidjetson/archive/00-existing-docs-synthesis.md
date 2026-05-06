# 00. Existing Docs Synthesis

File nay tom tat nhung gi da hoc duoc tu cac tai lieu co san trong workspace, dac biet:

- `RokidHandTrackingDemo/steamvideo.Md`
- `RokidHandTrackingDemo/PROJECT_MEMORY.md`
- `RokidHandTrackingDemo/PROTOCOL_MOUSE_HAND.md`
- `rokid-glasses-network-connectivity-matrix.md`
- `rokid-app-authoring-standard.md`

Muc tieu cua file nay la giu lai "diem tuat" cho du an moi, tranh lap lai nhung bai hoc da ton nhieu thoi gian.

## 1. Dieu da duoc chung minh

Tu cac tai lieu cu, co the xem nhung dieu sau la da duoc prove:

- Rokid co the chay app Android tu viet.
- Rokid co the mo camera va giu pipeline camera on dinh neu thiet ke dung.
- Rokid co the stream du lieu qua Wi-Fi trong LAN.
- May ben ngoai co the nhan du lieu do trong thoi gian gan realtime.
- Logging hai dau da tung rat huu ich va nen duoc giu.

Ket luan:

- huong `Rokid -> LAN -> may nhan` la huong thuc te
- van de tiep theo la kien truc va toi uu, khong phai "co lam duoc hay khong"

## 2. Bai hoc ky thuat quan trong

### Camera

- Preview an co the quan trong hon viec bo preview de "dep kien truc".
- Camera HAL tren kinh co the nhay cam, nen fail-safe va logging la bat buoc.

### Hieu nang

- GPU co the chay AI tren kinh, nhung nhiet va pin la bai toan that.
- Vi vay offload AI nang sang Jetson la huong hop ly.

### Network

- UDP JSON da duoc prove cho payload nhe.
- Hardcode IP la cach nhanh de test nhung mong manh.
- App moi can co co che host config, pairing, hoac discovery.

### Logging

- Khong co log thi rat kho biet lag nam o camera, encode, network, decode hay AI.
- App moi phai co session logging tren ca Rokid va Jetson.

## 3. Bai hoc kien truc quan trong

`steamvideo.Md` da cho thay huong nghi dung:

- tach transport khoi AI
- log moi thu co the log
- prove LAN truoc khi mo rong Internet
- dung Jetson nhu edge brain thay vi ep Rokid infer nang
- tach `media`, `control`, `telemetry`, `debug`

File `rokid-app-authoring-standard.md` cung cung co mot nguyen tac rat hop:

`Glasses = UI + input + capture`

`Backend/Jetson = AI + orchestration + logic nang`

## 4. Bai hoc san pham quan trong

Khong nen bat dau bang mot du an qua rong.

Nen bat dau bang:

- 1 media uplink
- 1 result loop
- 1 mode AI
- 1 HUD de doc

Khong nen bat dau bang:

- nhieu model cung luc
- cloud-first
- face recognition la feature dau tien
- Internet media truoc khi LAN on

## 5. Ket luan thua ke cho du an moi

Du an `rokidjetson` nen ke thua 5 nguyen tac:

1. Rokid la sender + HUD, khong phai AI node nang.
2. Jetson la noi decode, infer, tracking va quan ly mode.
3. Logging va telemetry hai dau la mandatory.
4. Result metadata can nhe, ro, va duoc chuan hoa.
5. Cloudflare Zero Trust chi nen vao sau khi LAN da vung.
