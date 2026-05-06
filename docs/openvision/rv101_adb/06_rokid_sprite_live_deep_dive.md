# RV101 RokidSpriteLive Deep Dive

Updated: 2026-04-29

This note points future OpenVision work to the local static analysis of the
RV101 system app `com.rokid.os.sprite.live`.

Primary research folder:

```text
device_research/rv101_system_apks_2026-04-29/rokid_sprite_live_research/
```

Key conclusion:

```text
RokidSpriteLive is a privileged background camera/microphone live-stream daemon.
It uses Camera2, AudioRecord, MediaCodec H.264/AAC, optional EGL rotation, FLV
packaging, and native librtmp.so to publish to RTMP.
```

Privacy/activation conclusion:

```text
The reviewed RV101 APK evidence shows a real live-broadcast capability, but not
an always-on hardcoded Rokid backend stream. The RTMP destination appears to be
provided dynamically as rtmpPushUrl by RokidSpriteAssistServer/live-broadcast
scene flow, with Launcher UI/status resources for live preparing/running/paused/
ended states. Treat it as privacy-sensitive capability, not proven silent
monitoring, until runtime ADB/appops/log/network evidence says otherwise.
```

OpenVision use:

```text
Use it as RV101 media-pipeline evidence for our own thin glasses app.
Do not call or depend on its private Binder/broadcast service in production.
Do not copy vendor decompiled code.
Do not stream directly to cloud from RV101.
```

The OpenVision app should implement typed `MediaCommand` capture and report
`MediaEvent` status to Jetson. Jetson remains the media, privacy, perception,
display, and cloud-escalation authority.
