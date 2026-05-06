# 05. Jetson AI Strategy

## 1. Nguyen tac cot loi

Jetson khong nen chay tat ca moi thu cung luc.

Phai co:

- mode-based activation
- model lifecycle ro rang
- shared tracking layer neu co the
- limit tai nguyen theo profile

Muc tieu la:

- nguoi dung chon che do tren kinh
- Jetson chi nap pipeline can thiet
- khi doi mode, giai phong tai nguyen mode cu neu khong can dung chung

## 2. Mo hinh to chuc AI hop ly

Nen chia thanh 4 lop:

### A. Input layer

- frame da decode
- resize / colorspace
- ROI neu can

### B. Detector layer

- person/vehicle/object detector
- face detector

### C. Tracker / association layer

- track ID qua frame
- zone entry/exit
- count logic

### D. Task logic layer

- person counting
- vehicle counting
- custom object counting
- face recognition

## 3. Cac mode nen co

### `people_count`

Can:

- person detector
- tracker
- zone counter tuy chon

### `vehicle_count`

Can:

- object detector co class xe
- tracker
- line/zone logic

### `object_count`

Can:

- detector theo label duoc chon
- tracker

### `face_mode`

Can:

- face detector
- face embedding
- matcher voi local database

## 4. Goi y model ban dau

Day la goi y de quy hoach, chua phai chot cuoi:

### Detector chung

- YOLO nho / TensorRT-optimized cho `person`, `car`, `motorbike`, `bus`, `truck`

### Tracker

- ByteTrack hoac mot tracker nhe tuong duong

### Face mode

- face detector rieng
- embedding model rieng
- local vector store nho

### Custom object

- co the dung cung detector chung neu label nam trong bo class co san
- neu khong, tao profile model rieng sau

## 5. Quy tac bat/tat pipeline

### Khi vao `people_count`

Bat:

- detector_person
- tracker_main

Tat:

- face_embedder
- custom_object_pipeline

### Khi vao `face_mode`

Bat:

- face_detector
- face_embedder
- face_matcher

Tat hoac giam:

- detector chung neu khong can

## 6. Resource policy

Nen co 3 profile:

### `eco`

- resolution thap hon
- FPS AI thap hon
- 1 pipeline

### `balanced`

- day la default
- 1 detector + 1 tracker
- HUD muot

### `performance`

- cho test ngan
- cho phep pipeline nang hon
- khong nen de lam mac dinh

## 7. Scheduler chay frame

Jetson nen xu ly theo nguyen tac:

- AI worker luon lay frame moi nhat
- bo frame cu neu hang doi da co frame moi
- khong can infer moi frame decode

Vi du:

- decode 24 FPS
- AI xu ly 8-12 FPS
- HUD cap nhat 5-10 FPS

Neu lam duoc nhu vay he thong van cho cam giac realtime.

## 8. Khuyen nghi MVP AI

MVP nen chon:

- `people_count`

Ly do:

- de chung minh gia tri
- detector/tracker pho bien
- HUD ro rang
- it nhay cam hon face recognition

Chi sau khi mode nay on moi them:

- `vehicle_count`
- `face_mode`

## 9. Face recognition can than

Mode nay can them quy dinh:

- local-only database neu co the
- co co che dang ky khuon mat ro rang
- co log su kien match
- co nguong confidence va nguong match rieng
- co option tat hoan toan mode nay

## 10. Dau ra can chuan hoa

Moi pipeline deu nen tra ve dang chuan:

- `summary`
- `counts`
- `detections`
- `alerts`
- `latency`

Nho vay HUD tren Rokid khong can biet tung model cu the.
