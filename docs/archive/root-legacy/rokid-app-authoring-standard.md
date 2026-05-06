# Rokid App Authoring Standard

Ngay tong hop: `2026-04-14`

Muc tieu cua file nay la chot mot bo quy tac thuc chien de viet app cho `Rokid Glasses` man hinh xanh / HUD trong suot cho dung huong hon. Day khong phai tai lieu reverse-engineering tong quat, ma la `rulebook` de quyet dinh nhanh:

- nen chon kien truc nao
- UI hien thi ra sao de de doc tren kinh that
- app nen giao tiep bang cach nao
- can tranh nhung gi de app on dinh va ben bi hon

File nay duoc tong hop tu:

- `rokid-app-development-playbook.md`
- `rokid-display-experience-playbook.md`
- `rokid-glasses-network-connectivity-matrix.md`
- cac repo/app Rokid da phan tich truoc do
- ghi chu cong dong ve `Rokid YodaOS-Sprite` design spec

## 1. Ket luan nhanh

Neu chi nho 12 dieu, hay nho 12 dieu nay:

1. Kinh nen duoc coi la mot thiet bi `Android/YodaOS-Sprite` co HUD xanh don sac, khong phai dien thoai mini.
2. App tot tren Rokid thuong nho, ro, mot nhiem vu chinh, rat it man hinh.
3. UI phai `focus-based`, `gesture/key-based`, va `text-first`.
4. Canvas logic la `480 x 640`, nhung vung hien thi dep nhat thuong chi nen coi la `480 x 400`.
5. Khong duoc thiet ke nhu app dien thoai: khong toolbar day dac, khong bottom nav, khong form dai, khong thao tac touch phuc tap.
6. Mau mac dinh nen di theo HUD xanh `#40FF5E` voi cac muc opacity khac nhau.
7. Khong dung gradient, khong dung card sang lon, khong lam UI phu thuoc shadow.
8. Neu tinh nang can AI nặng, GPS, sync, notification, route, hay de `phone` hoac `backend` xu ly.
9. Neu app la utility, reader, shell, helper, viewer, thi chay native tren kinh la lua chon dep nhat.
10. Neu can backend rieng, uu tien `Wi-Fi LAN + WebSocket/HTTP`, khong nen ep app luon song qua stream lien tuc.
11. Tich hop voice/system scene cua Rokid co ton tai, nhung public API cho third-party van co gioi han; khong nen dat toan bo san pham len phan nay.
12. App ben vung nhat la app co `offline mode`, `retry`, `timeout`, `queue`, va `fallback state` ro rang.

## 2. Pham vi va su that nen mac dinh

### 2.1 Thiet bi dich

File nay ap dung cho:

- `Rokid Glasses`
- HUD xanh / transparent waveguide
- portrait app viewport
- form factor khong co touchscreen dien thoai

Khong ap dung nguyen xi cho:

- `Rokid Max`
- `Rokid Max 2`
- cac model display-only

### 2.2 Nen mac dinh ve he thong

- app la `native Android`
- `minSdk` an toan: `28`
- `targetSdk` hop ly hien tai: `34`
- `JVM target`: `17`
- `arm64-v8a` la ABI uu tien
- khong nen gia dinh co `Google Play Services`
- khong nen gia dinh co touchscreen day du
- khong nen gia dinh pin/man hinh/mang duoc phep "giong phone"

## 3. Chon kien truc truoc khi code

### 3.1 Kieu A: native utility tren kinh

Dung khi app la:

- file manager
- wifi helper
- shell
- note/reader
- teleprompter
- checklist
- lyric / score / subtitle viewer

Uu diem:

- gon
- nhanh
- khong can phone
- de test use case that

Nhuoc diem:

- khong hop cho AI nang
- khong hop cho workflow phu thuoc network/GPS lien tuc

### 3.2 Kieu B: glasses + phone companion

Dung khi can:

- mang 4G/5G ben vung
- GPS
- notification
- session manager/onboarding de hon
- giu backend connection lau
- STT/TTS ben vung hon

Uu diem:

- dung hang ngay ben hon
- bat duoc nhieu use case production

Nhuoc diem:

- phuc tap hon
- can app companion

### 3.3 Kieu C: glasses + backend truc tiep

Dung khi:

- app tren kinh la terminal mong
- xu ly nang nam o Jetson/PC/server
- moi tinh nang deu co the trigger theo yeu cau

Uu diem:

- khong can phone
- hop cho AI/vision/rag/remote command

Nhuoc diem:

- phu thuoc Wi-Fi/LAN
- can lam reconnect, timeout, cache tot

### 3.4 Quy tac chon nhanh

| Neu app la... | Nen chon |
| --- | --- |
| utility, reader, shell, checklist | `Kieu A` |
| navigation, notification, phone-linked workflow | `Kieu B` |
| AI/vision voi Jetson hoac backend rieng | `Kieu C` |
| always-on voice assistant de dung hang ngay | `Kieu B` tot hon `Kieu C` |

## 4. Display spec de app hien thi dung tren kinh

Day la phan quan trong nhat khi code UI.

### 4.1 Canvas va safe area

- Canvas logic: `480 x 640 px`
- Vung hien thi tot nhat nen coi la: `480 x 400 px`
- Khu top `160 px`: hien thi kem, dung rat than trong
- Khu bottom `80 px`: hien thi kem, dung rat than trong
- Left/right margin co the sat bien, nhung noi dung quan trong van nen co breathing room

Khuyen nghi bo cuc:

- Dat noi dung chinh trong vung giua
- Neu la text HUD dai, co the bias xuong thap hon tam hinh hoc
- Neu la subtitle/lyric/teleprompter, vi tri `0.72h -> 0.75h` thuong de doc hon

### 4.2 Typography

Community design spec cho thay cap co chu hop ly:

| Cap | Font size | Line height | Weight |
| --- | --- | --- | --- |
| 1 | `32px` | `40px` | Regular / Medium |
| 2 | `24px` | `32px` | Regular / Medium |
| 3 | `20px` | `26px` | Regular / Medium |
| 4 | `18px` | `24px` | Regular / Medium |
| 5 | `16px` | `22px` | Regular / Medium |

Khuyen nghi ap dung:

- text nho nhat de doc on: `16px`
- body/chinh: `18px -> 20px`
- title/chuyen trang thai chinh: `24px`
- heading lon / splash / state lon: `32px`

Font:

- Community spec de xuat `HarmonyOS Sans SC`
- Neu khong dam bao phan phoi font, can co fallback ro rang
- Uu tien font de doc tot o co nho, dau tieng Viet ro, khoang tho chu de chiu

### 4.3 Mau, border, shape

Gia tri mau HUD khuyen nghi:

- mau chinh: `#40FF5E`
- opacity dung de tao layer, khong can nhieu mau

Khong nen:

- dung gradient
- dung mảng high-brightness lon
- dung panel day dac chiem nhieu dien tich

Border/shape:

- border nho nhat: `>= 1.5px`
- border dung nhieu: `1.5px`, `2px`, `4px`
- corner radius dung nhieu: `12px`

Opacity theo trang thai:

| State | Border opacity |
| --- | --- |
| normal | `40%` |
| selected | `80%` |
| pressed | `100%` |

### 4.4 Icon spec

- Uu tien icon line-art
- Uu tien icon bam pixel-grid
- dung 2 muc opacity de tao layer thay vi nhieu mau

Size goi y:

| Loai icon | Size |
| --- | --- |
| app icon | `40 x 40` |
| regular icon | `20 x 20` |
| small icon | `16 x 16` |

### 4.5 Motion

- Motion phai phuc vu doc nhanh, khong phai de "dep"
- Tranh animation phuc tap
- Tranh blur, glow, shadow nang
- Neu can animation:
  - fade nhe
  - easing mem
  - khong thay doi nhieu thanh phan cung luc

### 4.6 Rule bo cuc thuc chien

- moi man hinh chi 1 muc tieu chinh
- khong qua 3 cap thong tin trong mot viewport
- menu phai ngan
- button/action khong qua nhieu
- text line dai can auto-fit hoac wrap khon ngoan
- noi dung quan trong phai hien ro ca khi nguoi dung liếc nhanh

## 5. UI patterns nen dung mac dinh

### 5.1 Pattern man hinh tot

- state screen lon: `Connected`, `Offline`, `Listening`, `Syncing`
- list ngan 3-7 item
- card outline mong
- top status nho + content chinh o giua
- HUD 3-vung: `status / main content / action row`

### 5.2 Pattern nen tranh

- dashboard day so lieu
- recycler list dai
- bottom sheet
- floating action button kieu phone
- multi-column
- text paragraph dai khong co hierarchy
- form input nhieu truong

### 5.3 Bo token UI nen dung cho app moi

```text
Canvas: 480 x 640
Preferred content zone: 480 x 400
Primary color: #40FF5E
Radius: 12
Stroke: 1.5 / 2 / 4
Text sizes: 16 / 18 / 20 / 24 / 32
Icon sizes: 16 / 20 / 40
Highlight strategy: opacity, not color explosion
```

## 6. Input va interaction rules

### 6.1 Nguon input can mac dinh

- touchpad / swipe
- tap / double-tap / long-press
- key event / D-pad style
- camera button / AI button tuy thiet bi
- voice trigger neu app co can

### 6.2 Rule input

- moi man hinh phai co duong `Back` ro rang
- root screen khong nen chan back mot cach ky quac
- swipe/scroll va focus phai nhat quan
- neu co long-press, phai co visual state ro rang
- neu co voice, phai co state `listening / processing / error`

### 6.3 Rule focus

- focus phai nhin thay duoc
- selected state nen the hien bang opacity/border
- khong de focus "mat tich"
- khong dat qua nhieu item focusable tren 1 screen

## 7. Networking va giao tiep

### 7.1 Cac duong giao tiep thuc te

- `Wi-Fi LAN + HTTP/WebSocket`
- `Bluetooth SPP`
- `Wi-Fi Direct / CXR`
- `AssistServer / system service`

### 7.2 Thu tu uu tien

1. `Wi-Fi LAN + WebSocket/HTTP`
2. `Bluetooth SPP`
3. `CXR`
4. `system integration` chi khi that can

### 7.3 Quy tac network de app ben

- phai co `reconnect`
- phai co `timeout`
- phai co `backoff`
- phai co `empty state`
- phai co `offline state`
- phai co `manual retry`

Neu app can backend:

- uu tien `request-based` hon la `always streaming`
- chuyen anh chup theo su kien thay vi stream lien tuc
- cache ket qua gan nhat
- gui payload nho, ro, de debug

## 8. Voice, scene va he thong Rokid

### 8.1 Dieu da biet

He Rokid co co che noi bo de:

- xu ly voice command
- map sang `scene`, `page`, `app`
- mo app/page/scene thong qua launcher/service noi bo

Cac manh ghep tung thay:

- `InstructService`
- `MasterAssistService`
- `SpriteLauncher`
- `control_scene`
- `open_app`

### 8.2 Dieu nen mac dinh khi viet app

- Khong nen gia dinh third-party app se dang ky duoc cau lenh voice tu do nhu app he thong
- Neu can "voice support", nen tu lam voice flow trong app hoac thong qua companion/backend
- Neu can mo app tu he thong, uu tien flow package/broadcast duoc xac nhan truoc
- Neu can tich hop sau voi system scene, coi day la nang cao va co rui ro version mismatch

## 9. Camera, audio, AI

### 9.1 Camera

- Camera tren kinh rat quy, de xung dot voi system service
- Neu app can camera, can thu nhe, fail-safe, va release tai nguyen dung luc
- Uu tien chup snapshot hon la preview/stream dai

### 9.2 Audio

- Always-on mic la huong rui ro cao cho pin va do ben
- Push-to-talk thuc te hon
- Voice app phai co debounce, timeout, cancel, va retry ro rang

### 9.3 AI

App AI phu hop nhat voi Rokid thuong theo mau:

```text
Glasses = UI + input + capture
Backend/Phone = STT/TTS + AI + DB + orchestration
```

Neu khong can phone:

- dung Jetson/PC backend trong LAN
- trigger theo su kien
- khong stream video/audio lien tuc neu khong that can

## 10. Performance, pin va do ben

### 10.1 Rule hieu nang

- khong tao object nang lien tuc trong draw/render
- khong animate qua nhieu lop
- khong decode anh lon tren main thread
- khong giu service song dai neu khong can
- giam tan suat polling

### 10.2 Rule pin

- tranh camera luon mo
- tranh mic luon mo
- tranh stream lien tuc
- tranh Wi-Fi keepalive qua hăng
- tranh re-render moi frame neu UI khong doi

### 10.3 Rule ben vung

- app phai song duoc khi:
  - mat mang
  - backend cham
  - backend chet
  - camera khong mo duoc
  - audio permission/co che voice loi
  - service he thong khong phan hoi

## 11. Cac loai app hop nhat voi Rokid

Rat hop:

- SSH terminal
- teleprompter
- checklist / SOP
- note viewer
- file utility
- HUD thong bao gon
- on-demand vision assistant
- score/lyric/subtitle viewer
- field assistant
- local tool cho Jetson/Pi/server

Can than trong:

- always-on assistant
- live translation lien tuc
- navigation phuc tap phu thuoc online
- remote desktop day du
- app can nhieu input text

## 12. Stack khuyen nghi cho du an moi

### 12.1 App native utility

- `Kotlin`
- `XML + ViewBinding` hoac `Compose` rat tiet che
- `OkHttp`
- `Gson` hoac `Kotlinx Serialization`
- `Room` neu can local data

### 12.2 App backend-connected

- `Kotlin`
- `Compose` neu UI can state ro
- `OkHttp WebSocket`
- `Coroutine + Flow`
- protocol JSON ro rang

### 12.3 App can phone companion

- phone:
  - network, AI, GPS, notification, TTS/STT
- glasses:
  - HUD, capture, gesture, confirm

## 13. Checklist truoc khi code app moi

1. App nay co that su can phone khong?
2. App nay co that su can backend khong?
3. App nay co can camera/mic lien tuc khong?
4. App nay co offline mode khong?
5. App nay co 1 viewport ro rang cho `480x640` chua?
6. Noi dung chinh da nam trong `safe area 480x400` chua?
7. Text nho nhat co lon hon hoac bang `16px` chua?
8. Back/focus/selected state da ro rang chua?
9. App co timeout/retry/reconnect chua?
10. App co empty state va error state ro rang chua?

## 14. Checklist truoc khi release

1. Test tren kinh that, khong chi emulator
2. Test ngoai troi va trong nha
3. Test nhin nhanh 1-2 giay xem co doc duoc thong tin chinh khong
4. Test mat mang
5. Test reconnect
6. Test sleep/wake
7. Test camera/mic fail
8. Test dung 15-20 phut lien tuc xem co moi mat khong
9. Test pin co bi rut qua nhanh khong
10. Test co thoat app duoc don gian khong

## 15. Prompt spec goi y cho AI IDE

Khi nho AI sinh UI/app cho Rokid, nen noi ro:

```text
Target device: Rokid Glasses HUD
Viewport: 480x640 portrait
Preferred safe area: 480x400 center zone
Interaction: swipe, tap, long-press, key-based focus
Visual style: monochrome green HUD, no gradients, no large bright fills
Typography: 16/18/20/24/32 px hierarchy
Borders: 1.5-2 px, radius 12 px
Icons: line icons at 16/20/40 px
Goal: low-distraction, readable in transparent AR display
Avoid: phone-style UI, dense dashboards, large cards, tiny text
```

## 16. Quan he voi cac file khac trong workspace

- `rokid-glasses-research.md`
  - dung khi can thong so nen tang, reverse-engineering, local device notes

- `rokid-app-development-playbook.md`
  - dung khi can so sanh kien truc, stack, repo mau, pattern ky thuat

- `rokid-display-experience-playbook.md`
  - dung khi can toi uu app HUD text-heavy nhu lyric, subtitle, teleprompter

- `rokid-glasses-network-connectivity-matrix.md`
  - dung khi can quyet dinh network path, vai tro phone, cloud, backend

- `rokid-app-ideas-catalog.md`
  - dung khi can tim y tuong app va doi chieu repo tham khao

## 17. Ket luan

Muong Viet app cho Rokid dung huong, hay mac dinh 3 nguyen tac:

1. `HUD first, phone second, backend when needed`
2. `Readability before beauty`
3. `Stability before cleverness`

Neu mot app nhin dep tren emulator nhung kho doc tren kinh that, thi xem nhu chua dat.
Neu mot app co AI rat hay nhung can camera/mic/mang luon mo va pin xuong nhanh, thi cung chua phai kien truc dung.

App Rokid tot la app `gon, ro, de doc, de thoat, de song chung voi gioi han cua kinh`.
