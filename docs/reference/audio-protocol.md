# Rokid Audio Protocol

Updated: 2026-04-20

## Goal

Add a lightweight voice path from glasses to Jetson without touching the current video stream path.

## Transport

- dedicated TCP socket for audio
- framed like video
- backend advertises `audioHost` and `audioPort` in `session_accept`
- current backend may reuse the same TCP listener port as video, but audio must use its own socket

## Frame types

- `3` = `audio_hello`
- `4` = `audio_sample`

## audio_hello header

```json
{
  "sessionId": "sess_xxx",
  "deviceId": "rokid-...",
  "appVersion": "0.0.0",
  "codec": "pcm_s16le",
  "sampleRateHz": 16000,
  "channels": 1,
  "bytesPerSample": 2
}
```

## audio_sample header

```json
{
  "sessionId": "sess_xxx",
  "sequence": 42,
  "captureTimestampMs": 1710000000000,
  "payloadBytes": 2560
}
```

Payload:

- raw PCM bytes for MVP

## Phase roadmap

### MVP

- `pcm_s16le`
- continuous voice
- Jetson stores/logs audio

### Phase 2

- switch to `Opus mono`
- add VAD
- add streaming ASR

## Guardrail

- audio path is isolated from Ring
- no change to Ring services
- video path remains as-is
