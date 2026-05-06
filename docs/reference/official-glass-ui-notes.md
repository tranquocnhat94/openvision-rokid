# Legacy Rokid Glass UI Notes

Updated: 2026-04-22

Canh bao quan trong:

- File nay khong phai spec truc tiep cho `Rokid Glasses RV101`.
- Day la note rut ra tu public docs cua dong `Rokid Glass / Glass 2` cu.
- Tu nay ve sau, chi dung file nay nhu `nguyen ly hien thi/input tham khao` cho `RV101`.
- Neu mot chi tiet trong file nay mau thuan voi hanh vi thiet bi that `RV101`, uu tien `RV101` va [rokid-display-foundation.md](docs/reference/rokid-display-foundation.md).

Nguon chinh:

- https://rokid.github.io/glass-docs/
- https://rokid.github.io/glass-docs/2-sdk/5-ui-sdk/
- https://developer.android.com/training/camerax/architecture

## Ket luan nhanh cho dung dong kinh see-through

- Cac note duoi day den tu nhom docs `Rokid Glass` cu, khong phai bo docs xac nhan rieng cho `RV101`.
- Chung van huu ich vi cung mo ta mot lop kinh HUD see-through, khong phai `Rokid Max` hay man hinh Android kin.
- App tren kinh phai coi nhu `HUD trong suot`, khong phai `phone UI`.
- Tai lieu chinh thuc ghi ro:
  - `Touch screen -> Touch pad`
  - `co preview -> khong preview`
  - can `Glass style UI`
  - can `alignment` khi ve marker tren the gioi that

## Rule can nho

1. Khong dung full-screen background den/opague neu khong that su can thiet.
2. Khong render preview camera len kinh cho use case AI stream.
3. UI nen co cac khoi nho, chu ngan, do phan tam thap.
4. Input phai theo `KeyEvent/touchpad`, khong theo touch phone.
5. Neu can overlay marker dung the gioi that, phai tinh `alignment`.
6. Manifest nen co:
   - `design_width_in_dp = 640`
   - `design_height_in_dp = 360`

## Ghi chu ve API va SDK

- Public docs cu co nhac den cac helper/API nhu `RokidSystem`, `GlassButton`, `GlassDialog`.
- Chua coi chung la API da duoc xac nhan cho `RV101` trong du an nay.
- Khong nen dua vao file nay de quyet dinh them dependency/API moi cho runtime neu chua kiem chung tren `RV101`.

## Huong ap dung cho RokidVideoStream

- Stream app la `no-preview stream sender + compact HUD`.
- HUD nen dung `small card` va `chip`, nen trong suot o cap window.
- Video stream gui sang Jetson phai tach khoi phan hien thi tren kinh.
- Neu ve line count / boxes / ROI sau nay, can them lop `alignment` thay vi ve theo toa do Android thong thuong.

## Camera stream khong can preview

Android CameraX docs xac nhan:

- `Every use case can work on its own.`
- app co the dung `ImageAnalysis` ma khong can `Preview`
- dieu nay phu hop voi `RV101` khi can stream camera sang Jetson nhung khong muon render camera tren HUD
