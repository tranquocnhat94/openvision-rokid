# Capture

Capture owns camera and microphone acquisition.

Read first:

```text
../../docs/openvision/27_ROKID_APP_CODEX_ROADMAP.md
../../docs/openvision/18_ROKID_APP_RUNTIME_CONTRACT.md
```

Capture is hardware execution only. It does not choose skills, decide whether
visual context is needed, call cloud, or keep sensors on by itself.

Video:

- Camera2;
- hardware H.264;
- stable timestamps;
- keyframe hints;
- low CPU overhead.
- only after typed Jetson MediaCommand;
- bounded by command timeout, FPS budget, and resolution/profile choice.

Audio:

- PCM capture;
- source diagnostics;
- amplitude telemetry;
- stable source selection;
- no over-aggressive trimming.
- default RV101 app-open voice streams mic PCM for conversation_realtime.
- future wake_realtime may keep full cloud audio off until a lightweight local
  trigger such as "Hey Vision" opens the same Cloud server_vad path.
- push-to-talk manual-turn remains debug/fallback: ptt_down, PCM stream, stream close, ptt_up.

RV101 measured capture facts:

```text
MIC 16000 Hz is the measured stable input path.
The app resamples to the Jetson/Realtime 24000 Hz PCM contract.
PCM energy metrics are the source of truth; callback-silence flags are hints.
Camera2 may be denied when the Activity is not foreground/interactive.
```

Every snapshot, quality_gate, burst, and live-video path should report metadata
needed by Jetson preview/perception/scorecard:

```text
orientation
profile
rotation_degrees
source_width/source_height
selected_width/selected_height
requested_width/requested_height
sensorOrientationDegrees
cameraId
captureFpsMin/captureFpsMax
sentFpsEstimate
droppedFrames
```

Do not add always-on camera, background camera capture, local STT, direct cloud
upload, Jetson/app-side semantic voice gate, or app-side visual skill decisions.
