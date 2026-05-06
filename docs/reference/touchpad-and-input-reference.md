# Rokid Touchpad And Input Reference

Updated: 2026-04-22

Canh bao quan trong:

- File nay khong phai spec input chinh thuc da duoc xac nhan rieng cho `Rokid Glasses RV101`.
- Nguon public chi tiet nhat hien co van la docs cua dong `Rokid Glass` cu.
- Vi vay, file nay chi nen duoc dung nhu `legacy reference + field note`.
- Neu can mot quyet dinh runtime cho `RV101`, uu tien hanh vi thiet bi that, log app, va [rokid-display-foundation.md](docs/reference/rokid-display-foundation.md).

Muc tieu file nay:

- luu lai tai lieu tham chieu cho thao tac tren kinh Rokid
- tach ro phan `official docs` va `community / field notes`
- dung lam chuan khi thiet ke app tren kinh sau nay

## 1. Legacy public Rokid sources da doi chieu

### 1.1 Developer docs

- Rokid Glass docs home:
  - https://rokid.github.io/glass-docs/
- System config:
  - https://rokid.github.io/glass-docs/1-system/
- Glass UI SDK:
  - https://rokid.github.io/glass-docs/2-sdk/5-ui-sdk/
- OS design guideline entry:
  - https://rokid.github.io/glass-docs/5-design/

### 1.2 Nhung diem chot tu public docs cu

Theo Rokid Glass docs:

- app tren kinh can chuyen tu tu duy `touch screen` sang `touch pad`
- mot so control can tu xu ly `focus`
- UI nen theo phong cach kinh Rokid, uu tien giao dien it lop, it thao tac, it preview

Theo trang `System config`, Rokid cong bo ro bang map thao tac -> `KeyEvent / Intent`.

## 2. Legacy key mapping baseline

Nguon goc:

- https://rokid.github.io/glass-docs/1-system/

Luu y:

- Bang map duoi day la baseline tu docs cu, khong phai bang mapping da duoc verify day du tren `RV101`.
- Chi cac key app da thuc su bat duoc trong runtime moi nen coi la on dinh cho du an nay.

### 2.1 Bang map thao tac -> event

| Thao tac | Y nghia | Event / key |
|---|---|---|
| Back single | quay lai | `KEYCODE_BACK = 4` |
| Back long | gui intent | `com.rokid.glass.homekey.longpress` |
| Back double | tuy che do | `0 = no-op`, `1 = launcher`, `2 = broadcast` |
| TP swipe right | di chuyen phai | `KEYCODE_DPAD_RIGHT = 22` |
| TP swipe left | di chuyen trai | `KEYCODE_DPAD_LEFT = 21` |
| TP quick swipe right | right + single down | `KEYCODE_DPAD_RIGHT` + `KEYCODE_DPAD_DOWN = 20` |
| TP quick swipe left | left + single up | `KEYCODE_DPAD_LEFT` + `KEYCODE_DPAD_UP = 19` |
| TP single tap | xac nhan | `KEYCODE_DPAD_CENTER = 23` |
| TP long press | custom | `KEYCODE_TV = 170` |
| TP double tap | custom | `KEYCODE_ENTER = 66` |
| Power | nguon | `KEYCODE_POWER = 26` |
| Volume+ | tang am luong | `KEYCODE_VOLUME_UP = 24` |
| Volume- | giam am luong | `KEYCODE_VOLUME_DOWN = 25` |

### 2.2 Cac y quan trong tu official docs

- `TP swipe left/right` co the phat sinh nhieu key lien tiep.
- `TP quick swipe left/right` co them mot key `UP` hoac `DOWN` don le.
- `Back long` mac dinh bi tro ly giong noi chiem, co tro ly thi khong nen dua vao no cho app.
- `TP long press` va `TP double tap` la hai input hop ly de gan thao tac custom cua app.

## 3. Legacy UI guidance lien quan den input

Nguon goc:

- https://rokid.github.io/glass-docs/
- https://rokid.github.io/glass-docs/2-sdk/5-ui-sdk/

### 3.1 Tu duy UI dung cho kinh

Rokid docs nhan manh:

- `Touch screen -> Touch pad`
- mot so control can `focus control` rieng
- khong nen mang nguyen tu duy giao dien phone vao kinh

### 3.2 Glass UI SDK

Rokid co `Glass UI SDK`:

- dependency:

```gradle
implementation 'com.rokid.glass:ui:1.5.4'
```

- co `GlassButton`
- co `GlassDialog`
- co helper `RokidSystem` cho alignment / mapping camera-preview -> window

Canh bao:

- Chua coi bo helper nay la dependency/runtime contract cua `RV101` trong repo hien tai.
- Neu sau nay can dung den, phai verify lai tren may that truoc.

### 3.3 Screen adaptation

Rokid docs khuyen khai bao trong `AndroidManifest.xml`:

```xml
<meta-data
    android:name="design_width_in_dp"
    android:value="640"/>
<meta-data
    android:name="design_height_in_dp"
    android:value="360"/>
```

Y nghia:

- khi thiet ke HUD/app tren kinh, nen xem `640 x 360 dp` la mot moc tham chieu

## 4. Kieu lap trinh nen dung trong app

Ket luan tu docs chinh thuc:

- uu tien `focus-based UI`
- nhan input qua `KeyEvent`
- khong nen dua vao touch coordinates
- coi touchpad cua kinh nhu mot bo `D-pad + confirm + extra actions`

### 4.1 Mapping khuyen nghi cho app tren kinh

Neu la app utility / vision / HUD:

- `KEYCODE_DPAD_CENTER`
  - confirm, bat/tat, play/pause, chon item
- `KEYCODE_ENTER`
  - secondary action
  - mo panel phu
  - doi mode nhanh
- `KEYCODE_TV`
  - menu nhanh
  - mo command sheet
  - giu de vao setting / debug
- `KEYCODE_DPAD_LEFT / RIGHT`
  - doi tab
  - tang / giam tham so
  - di focus trai/phai
- `KEYCODE_DPAD_UP / DOWN`
  - next / previous action nhanh
  - scroll item lon
  - volume / brightness / zoom tuy app
- `KEYCODE_BACK`
  - huy / dong panel / quay lai

### 4.2 Rule UX minh nen theo

- single tap la hanh dong chinh
- double tap la hanh dong phu
- long press la menu / advanced
- back single luon phai an toan va de doan
- khong nhoi qua nhieu chuc nang vao cung mot gesture

## 5. Community / field notes

Phan nay khong phai official spec. Day la thong tin thuc chien co gia tri de tham khao.

### 5.1 Reddit: touchpad vat ly dang la nguon input quan trong nhat

Threads da xem:

- https://www.reddit.com/r/rokid_official/comments/1s8o7j3/gazemou_headtracking_mouse_cursor_for_rokid/
- https://www.reddit.com/r/rokid_official/comments/1salpls/gazemou_ver140_release/
- https://www.reddit.com/r/rokid_official/comments/1pepbwd/rokid_glasses_keyboard_mapping_it_work/

Nhung diem rut ra:

- tren mot so doi tuong su dung, touchpad ben phai duoc mo ta la strip ngang hep, left/right thuong dang tin hon thao tac dung chieu doc
- co dev cong dong bao launcher cua Rokid co the bo qua input inject bang phan mem (`dispatchGesture`, `input keyevent`, `sendevent`) va chi dap ung voi touchpad vat ly
- dieu nay rat quan trong neu sau nay muon lam tro giup / accessibility / automation: nen kiem chung tren phan cung that, khong suy tu emulator

### 5.2 Nghia thuc dung cho du an cua minh

- doi voi app noi bo cua minh, nen bat dau tu `onKeyDown / onKeyUp`
- neu can dieu khien launcher he thong, phai coi day la bai toan rieng, khong mac dinh input software se thay duoc input vat ly
- can uu tien thao tac `left/right/center/enter/back`

## 6. Local code examples trong workspace nay

### 6.1 Rokid Lyrics Player

File:

- `Rokid Lyrics Player/app/src/main/java/com/rokid/lyricsplayer/PlayerActivity.kt`

No da map san:

- single tap -> `KEYCODE_DPAD_CENTER`
- double tap -> `KEYCODE_ENTER`
- quick swipe right -> `KEYCODE_DPAD_DOWN`
- quick swipe left -> `KEYCODE_DPAD_UP`

Va xu ly trong `onKeyDown(...)`.

Day la mot vi du thuc te rat tot de tai su dung pattern cho app moi.

## 7. Khuyen nghi cho app Rokid + Jetson sau nay

### 7.1 Menu thao tac nen co

Cho app vision stream / AI HUD:

- single tap:
  - pause / resume stream
  - ack thong bao
- double tap:
  - doi mode AI
  - debug page tiep theo
- long press:
  - mo command sheet
  - chon `people / vehicle / face / object`
- swipe left/right:
  - chuyen panel
  - tang / giam threshold
  - next / previous option
- quick swipe left/right:
  - brightness / volume / zoom / compact action
- back:
  - dong overlay / thoat app / quay lai

### 7.2 Nguyen tac thiet ke

- dung `focus` ro rang
- moi man hinh chi nen co rat it item co the focus
- phai co state `selected / focused / inactive` rat de nhin
- nen co `HUD mode` va `menu mode` tach nhau
- trong HUD mode, gioi han thao tac de tranh bam nham

## 9. Cac diem can xac minh them tren kinh that

Day la checklist test thiet bi that, vi docs + cong dong chua the thay cho test runtime:

- `KEYCODE_TV = 170` co on dinh tren model kinh dang dung khong
- `KEYCODE_ENTER = 66` co luon map voi double tap tren firmware hien tai khong
- quick swipe co on dinh tren moi profile FPS / nong may khong
- khi app fullscreen HUD, system bars / focus haze co xuat hien khong
- Tailscale / network overlay co anh huong den input latency khong

## 10. Ket luan thuc dung

Ket luan cho du an:

- nen lap trinh input tren Rokid theo huong `KeyEvent-first`
- xem touchpad nhu `D-pad + confirm + long press + double tap`
- dung `GlassButton / focus UI` neu can menu
- khong nen dua vao input inject de gia lap launcher/system behavior
- voi app AI tren kinh, hay giu thao tac it, ro, va theo nhip `center / enter / left / right / back`

## 11. Ghi chu ve nguon

Phan `official` trong file nay dua tren:

- Rokid Glass docs home
- Rokid Glass system config
- Rokid Glass UI SDK

Mình da tim them tren Reddit / GitHub / search cong khai de lay community notes.
Mình khong tim thay mot public developer forum post cua Rokid co bang key mapping chi tiet hon trang `System config`, nen trang official tren `rokid.github.io/glass-docs` dang la nguon chinh de bam theo.
