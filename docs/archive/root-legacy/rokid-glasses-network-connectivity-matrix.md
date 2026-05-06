# Rokid Glasses Network Connectivity Matrix

Ap dung cho dong `Rokid Glasses` co man hinh xanh / HUD trong suot ma chung ta dang nghien cuu, khong ap dung cho `Rokid Max`, `Rokid Max 2`, hoac dong `display-free`.

Ngay tong hop: `2026-04-08`

## 1. Ket luan nhanh

- Kinh `Rokid Glasses` co `Wi-Fi 6` va `Bluetooth 5.3`, nen no co the tu ket noi mang ma khong bat buoc phai di qua dien thoai.
- Tuy vay, he sinh thai hien tai van dat `dien thoai + app Hi Rokid` vao vai tro quan trong cho pairing, settings, gallery, notification, mot phan navigation va cac tinh nang companion.
- Nhieu tinh nang AI va dich thuat nhieu kha nang van can cloud/backend, du tren giao dien nguoi dung no co cam giac nhu dang chay "ngay tren kinh".
- Voi app tu viet, nen xem kinh nhu mot thiet bi Android co the ket noi `Wi-Fi LAN`, `Bluetooth`, `hotspot`, `WebSocket/HTTP`, va trong mot so luong cong dong con co ca `SPP` va `Wi-Fi Direct`.

## 2. Bang tong hop theo dung dong kinh nay

| Hang muc | Kinh tu lam duoc? | Can dien thoai? | Can Internet / cloud? | Ghi chu thuc te |
| --- | --- | --- | --- | --- |
| Join Wi-Fi / len mang qua Wi-Fi | `Co` | `Khong bat buoc` | `Can` neu muon vao Internet | Tai lieu setup cua Rokid cho thay kinh co quy trinh ket noi Wi-Fi va hien bieu tuong Wi-Fi sau khi ket noi thanh cong. |
| Pair qua Bluetooth | `Co` | `Thuong co` | `Khong` | Bluetooth duoc dung de pair voi phone/PC va lam kenh dieu khien cho mot so workflow companion. |
| Chay app native tren kinh | `Co` | `Khong bat buoc` | `Tuy app` | Nhieu app cong dong chay thang tren kinh nhu Wi-Fi helper, SSH terminal, file manager, subtitle, game. |
| Goi API / WebSocket truc tiep tu kinh | `Co` | `Khong bat buoc` | `Can LAN/Internet` | Phu hop cho app kieu AI assistant, Jetson backend, terminal, remote HUD. |
| Cai APK tu phone theo official stack | `Co` | `Co` | `Thuong co ket hop BLE + Wi-Fi Direct` | Repo `Rokid-APKs` mo ta official flow dung BLE va Wi-Fi Direct de day APK vao kinh. |
| Cai APK qua companion local | `Co` | `Co` | `Khong bat buoc` | Co hai mode cong dong: `SPP / SLOW` khong can Wi-Fi va `WIFI LAN / FAST` dung chung Wi-Fi/hotspot. |
| Truyen file trong LAN | `Co` | `Khong bat buoc` | `Can LAN` | `Rokid-Shell` co HTTP server de chep file trong mang noi bo. |
| SSH/remote tool truc tiep tren kinh | `Co` | `Khong bat buoc` | `Can LAN/Internet` | `rokid-ssh-terminal` cho thay kinh co the vao mang va noi SSH toi may khac. |
| Navigation tren HUD | `Co phan glasses app` | `Thuong co` | `Thuong co` | Co glasses-side app va HUD, nhung route/location/companion van thuong phu thuoc phone hoac backend. |
| Notification/call bridge | `Co hien thi tren kinh` | `Thuong co` | `Khong nhat thiet` | Official material va app `Hi Rokid` cho thay phone la nguon thong bao, call, mot so tro ly. |
| AI assistant built-in | `Co giao dien va voice tren kinh` | `Khong bat buoc cho moi truong hop` | `Thuong co` | Official pages mo ta AI assistant tren kinh; thuc te cac tinh nang LLM/translation/object AI nhieu kha nang can cloud. |
| Realtime translation / live subtitles | `Co tren giao dien kinh` | `Khong bat buoc theo cach gioi thieu` | `Co kha nang cao la can cloud` | Official marketing noi feature nam "tren kinh"; nhung public evidence hien tai khong du de khang dinh toan bo pipeline chay offline. |
| Import photo/video/recording sang phone | `Khong` | `Co` | `Khong bat buoc` | `Hi Rokid` mo ta ro viec import media tu kinh sang dien thoai. |
| OTA / cai dat he thong | `Mot phan tren kinh` | `Thuong co app companion de quan ly` | `Can Internet` | App store listing cua `Hi Rokid` va changelog cho thay OTA la mot luong duoc ho tro ro rang. |

## 3. Cac duong ket noi ma cong dong da xac nhan

### 3.1 Wi-Fi truc tiep tren kinh

- Kinh co kha nang join Wi-Fi va vao mang rieng.
- Dieu nay rat quan trong vi no mo duong cho:
  - app goi HTTP API
  - WebSocket toi backend rieng
  - SSH
  - local LAN services
  - AI/backend tren Jetson, PC, NAS

### 3.2 Bluetooth pairing va companion control

- Bluetooth la lop ket noi rat trung tam trong he sinh thai Rokid.
- No xuat hien trong:
  - pairing phone <-> glasses
  - official install flow
  - SPP companion flow
  - notification/call/voice-assistant bridge

### 3.3 Wi-Fi Direct / CXR

- Official uploader flow dung `BLE + Wi-Fi Direct`.
- Day la mot kenh "he thong Rokid" hon la network app-level thong thuong.
- Neu viet app rieng, day khong phai luc nao cung la lua chon don gian nhat.

### 3.4 Bluetooth SPP

- Cong dong da chung minh co the dung `Bluetooth SPP` de noi app phone voi app tren kinh.
- Uu diem:
  - local
  - khong can cloud
  - khong can Wi-Fi trong mode cham
- Nhuoc diem:
  - cham hon
  - bang thong kem

### 3.5 Wi-Fi LAN / hotspot chung

- Day la kieu ket noi dep nhat neu chung ta muon tu viet app cho kinh.
- Kinh va phone hoac Jetson/PC cung nam trong cung mang:
  - home Wi-Fi
  - router du lich
  - phone hotspot
- Luc do minh co the dung:
  - HTTP
  - WebSocket
  - RTSP/RTMP/WebRTC
  - custom JSON protocol

## 4. Phan nao nen xem la "kinh tu xu ly", phan nao nen xem la "dien thoai / cloud"

### 4.1 Nhom kinh tu xu ly tot

- HUD UI
- launcher-like tools
- file browser
- local settings helper
- APK install confirmation
- simple viewers
- SSH client
- app noi backend rieng qua Wi-Fi

### 4.2 Nhom thuong can dien thoai

- gallery sync sang phone
- notification forwarding
- call-related integration
- mot so navigation workflows
- mot so voice-assistant bridge sang tro ly tren phone

### 4.3 Nhom thuong can cloud/backend

- LLM assistant
- object recognition / scene understanding
- live translation chat quality cao
- remote transcription
- face recognition backend rieng
- travel/navigation co routing online

## 5. Khuyen nghi cho du an rieng cua chung ta

Neu muc tieu la viet app rieng cho `Rokid Glasses` nay, thu tu uu tien nen la:

1. `Glasses native + Wi-Fi LAN backend`
- Tot nhat cho AI, vision, HUD, Jetson.
- Kinh chi can UI, camera/mic capture, display ket qua.

2. `Glasses native standalone`
- Tot cho tool nhe: viewer, shell, wifi helper, mini utility, player.

3. `Phone + glasses companion`
- Dung khi can GPS, contacts, notifications, hoac khi muon tan dung app phone lam "bo nao phu".

4. `Cloud-first`
- Chi nen dung khi tinh nang that su can model online.
- Neu latency quan trong, nen dua backend ve LAN/Jetson thay vi Internet xa.

## 6. Danh gia thuc chien cho nhung cau hoi hay gap

| Cau hoi | Câu tra loi ngan |
| --- | --- |
| Kinh co tu vao Internet duoc khong? | `Co`, qua Wi-Fi. |
| Co bat buoc phai co dien thoai moi chay duoc khong? | `Khong`, nhung nhieu feature he sinh thai van dung phone companion. |
| App tu viet co the noi backend rieng tren LAN khong? | `Co`, day la huong rat hop ly. |
| Co the lam app chi chay tren kinh khong? | `Co`, nhieu repo cong dong da lam roi. |
| Co the lam app offline hoan toan khong? | `Co`, neu feature don gian va khong can AI/router/cloud. |
| Co nen dua Jetson vao lam server LAN cho kinh khong? | `Co`, day la mot kien truc rat phu hop. |

## 7. Muc do chac chan cua tung nhan dinh

### Xac nhan kha chac

- Kinh co `Wi-Fi` va `Bluetooth`
- Kinh co the join mang va hien thi ket noi
- He sinh thai co `Hi Rokid` app companion
- Cong dong da dung `BLE`, `SPP`, `Wi-Fi LAN`, `Wi-Fi Direct`
- App tren kinh co the hoat dong khong can phone trong mot so use case

### Suy luan hop ly nhung can kiem chung them theo tung feature

- Feature translation/AI nao chay local, feature nao goi cloud
- Navigation cu the route duoc tinh tren phone, tren cloud, hay tren kinh
- Muc do mo cua cac API he thong Rokid cho third-party app

## 8. Nguon chinh

- Rokid product page: [Rokid Glasses](https://global.rokid.com/products/rokid-glasses)
- Rokid official article: [Rokid Glasses Connect – Sleek, Smart, and Ready to Wear](https://global.rokid.com/blogs/glasses/rokid-glasses-connect-sleek-smart-and-ready-to-wear)
- Rokid official article: [How to Use Rokid Glasses: Quick Setup & Controls Overview](https://global.rokid.com/blogs/glasses/how-to-use-rokid-glasses-quick-setup-controls-overview)
- Rokid official article: [Break Language Barriers: How to Use the Rokid Glasses Real-Time Translation Feature](https://global.rokid.com/blogs/glasses/break-language-barriers-how-to-use-the-rokid-glasses-real-time-translation-feature)
- Rokid official article: [Rokid Glasses Teases the Future of Smart Eyewear with ChatGPT Integration](https://global.rokid.com/blogs/news/rokid-glasses-teases-the-future-of-smart-eyewear-with-chatgpt-integration)
- App Store listing: [Hi Rokid - Rokid Glasses](https://apps.apple.com/us/app/hi-rokid-rokid-glasses/id6749669942)
- Community repo: [Rokid-APKs](https://github.com/Anezium/Rokid-APKs)
- Community repo: [awesome-rokid](https://github.com/Anezium/awesome-rokid)

## 9. Ghi chu cho cac topic sau nay

Khi minh ban tiep ve app rieng cho kinh nay, nen mac dinh 3 su that:

- Day la `Android smart glasses co Wi-Fi/Bluetooth that`, khong phai chi la man hinh ngoai.
- Kien truc tot nhat cho app AI/vision la `glasses UI + LAN backend`.
- Phone companion la `bo tro huu ich`, nhung khong phai luc nao cung nam tren duong xu ly chinh.
