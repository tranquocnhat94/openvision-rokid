# 04. Protocol Design

## 1. Muc tieu protocol

Protocol phai ho tro 4 viec:

- khoi tao session
- stream media
- doi mode AI
- tra result metadata realtime

Protocol can uu tien:

- de debug
- de do latency
- de mo rong schema
- tach ro media va control

## 2. Session model

Moi phien lam viec co:

- `sessionId`
- `deviceId`
- `appVersion`
- `jetsonNodeId`
- `startedAt`
- `selectedMode`

## 3. Control messages

De xuat dung `JSON` cho control/result o giai doan dau.

### `client_hello`

Rokid gui:

```json
{
  "type": "client_hello",
  "deviceId": "rokid-01",
  "appVersion": "0.1.0",
  "supportedModes": ["people_count", "vehicle_count", "face_mode"],
  "videoCodec": "h264",
  "resolution": {"width": 1280, "height": 720},
  "telemetry": {"batteryPercent": 87, "thermal": "normal"}
}
```

### `session_accept`

Jetson tra:

```json
{
  "type": "session_accept",
  "sessionId": "sess_123",
  "controlHeartbeatMs": 1000,
  "resultThrottleMs": 150,
  "media": {
    "transport": "rtsp",
    "url": "rtsp://192.168.1.10:8554/rokid/sess_123"
  }
}
```

### `mode_change`

Rokid gui:

```json
{
  "type": "mode_change",
  "sessionId": "sess_123",
  "mode": "people_count",
  "options": {
    "zoneId": "entrance_a",
    "confidenceThreshold": 0.45
  }
}
```

### `mode_state`

Jetson tra:

```json
{
  "type": "mode_state",
  "sessionId": "sess_123",
  "mode": "people_count",
  "status": "active",
  "loadedPipelines": ["detector_person", "tracker_main"],
  "warmupMs": 420
}
```

## 4. Result message

Jetson gui metadata ve Rokid:

```json
{
  "type": "vision_result",
  "sessionId": "sess_123",
  "mode": "people_count",
  "timestampMs": 1760000000000,
  "frameSeq": 812,
  "latency": {
    "captureToReceiveMs": 40,
    "decodeMs": 8,
    "inferMs": 32,
    "publishMs": 12,
    "endToEndMs": 92
  },
  "summary": {
    "primaryValue": 5,
    "label": "people"
  },
  "counts": {
    "person": 5
  },
  "alerts": [
    {"code": "zone_entered", "label": "Entrance occupied"}
  ],
  "detections": [
    {
      "id": "trk_21",
      "class": "person",
      "score": 0.93,
      "box": {"x": 0.12, "y": 0.18, "w": 0.21, "h": 0.46}
    }
  ]
}
```

## 5. Face mode result

```json
{
  "type": "vision_result",
  "sessionId": "sess_123",
  "mode": "face_mode",
  "summary": {
    "primaryValue": 1,
    "label": "matched_faces"
  },
  "faces": [
    {
      "trackId": "face_7",
      "matchLabel": "Nguyen Van A",
      "matchScore": 0.81,
      "confidence": 0.94
    }
  ]
}
```

## 6. Telemetry message

### Rokid -> Jetson

```json
{
  "type": "device_telemetry",
  "sessionId": "sess_123",
  "captureFps": 24.2,
  "encodeFps": 24.0,
  "txKbps": 2100,
  "batteryPercent": 84,
  "batteryTempC": 39.2,
  "thermalStatus": "moderate"
}
```

### Jetson -> Rokid

```json
{
  "type": "node_telemetry",
  "sessionId": "sess_123",
  "rxFps": 24.0,
  "decodeMs": 8,
  "gpuPercent": 67,
  "cpuPercent": 41,
  "ramMb": 2890,
  "activePipelines": ["detector_person", "tracker_main"]
}
```

## 7. Heartbeat va reconnect

Can co:

- `ping`
- `pong`
- `lastResultAt`
- `lastFrameAt`
- `reconnectAttempt`

Rule de xuat:

- 1 giay khong co `pong` thi danh dau `degraded`
- 3-5 giay khong co `pong` thi chuyen `reconnecting`
- media mat nhung websocket con song thi van giu session trong thoi gian ngan

## 8. Versioning

Moi message can co:

- `type`
- `version`
- `sessionId`

Vi du:

- `version = 1`

De tranh sau nay doi schema lam vo app cu.
