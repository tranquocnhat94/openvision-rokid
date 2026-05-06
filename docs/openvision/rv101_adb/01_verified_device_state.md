# Verified RV101 Device State

Captured: 2026-04-29

This file summarizes read-only ADB observations from the connected Rokid
Glasses RV101. Serial numbers, MAC addresses, seeds, and device-unique tokens
are intentionally omitted.

## Host ADB

```text
adb path: /opt/homebrew/bin/adb
adb version: 37.0.0-14910828
host: Darwin arm64
```

USB ADB sees one authorized device:

```text
product:glasses
model:RG_glasses
device:glasses
transport: usb
```

## Identity

```text
ro.product.rokid.oem.model=RV101
ro.product.rokid.oem.id=101
ro.product.model=RG-glasses
ro.product.device=glasses
ro.product.name=glasses
ro.product.brand=Rokid
ro.product.manufacturer=Rokid
ro.rokid.product.model=RG-glasses
```

Conclusion:

- This is the RV101 class device for this project.
- The generic Android model string is not enough; use
  `ro.product.rokid.oem.model`.

## Android Build

```text
Android release: 12
SDK: 32
first API level: 31
build id: SKQ1.240613.001
incremental: 1.17.012-20260414-150201
fingerprint: Rokid/glasses/glasses:12/SKQ1.240613.001/1.17.012-20260414-150201:user/release-keys
security patch: 2024-07-05
build type: user
build tags: release-keys
CPU ABI: arm64-v8a, with armeabi-v7a and armeabi compatibility
```

Security posture:

```text
adb shell id: uid=2000(shell), context=u:r:shell:s0
ro.secure=1
ro.debuggable=0
ro.adb.secure=1
SELinux=Enforcing
ro.boot.vbmeta.device_state=unlocked
```

Interpretation:

- ADB shell is normal non-root Android `shell`.
- This is not a userdebug build.
- Do not treat `ro.boot.vbmeta.device_state=unlocked` as permission to flash,
  root, or reboot into bootloader. It is only a read property here.

ADB/developer settings observed:

```text
global adb_enabled=1
global development_settings_enabled=0
persist.adb.tcp.port=<empty>
service.adb.tcp.port=<empty>
```

Interpretation:

- ADB was enabled, likely through Rokid or Hi Rokid UI rather than normal
  Android Developer Options.
- ADB-over-TCP was not enabled at capture time.

## Display

```text
wm size: 480x640
wm density: 240
display mode: 480x640 @ 60 Hz
display type: internal
orientation at capture: portrait / rotation 0
reported app bounds: 480x640
```

Observed display state:

- `dumpsys display` reported the physical display state as `OFF`.
- `vendor.rkd.glasses.is_take_on=0` was present in properties.

Interpretation:

- The display can be off because the glasses are not being worn.
- A screen-off state during ADB inspection does not prove a display failure.

## Camera

Camera service:

```text
normal camera devices: 1
public camera devices visible to API1: 1
camera id: 0
API1 facing: Back
orientation: 270
flash: false
```

Camera2 highlights:

```text
sensor/output max listed size: 4032x3024
lens aperture: f/2.25
focal length: 1.9
available AF modes: OFF only
available target FPS ranges include 15, 24, 30, and 60 fps buckets
available capabilities include RAW, MANUAL_SENSOR, BURST_CAPTURE,
MANUAL_POST_PROCESSING, YUV/PRIVATE reprocessing
```

Interpretation:

- Treat the RV101 camera as one outward camera for OpenVision.
- Official Rokid product specs say AF is not supported; Camera2 metadata also
  exposes only AF off. Ignore `android.hardware.camera.autofocus` until an app
  test proves otherwise.
- High-resolution still capture is exposed by Camera2, but stable product
  capture settings must still be tested by a thin RV101 client.

## Audio

Feature list confirms:

```text
android.hardware.microphone
android.hardware.audio.output
android.hardware.audio.low_latency
android.hardware.audio.pro
```

`dumpsys audio` showed:

- speaker and earpiece routes;
- single-volume behavior;
- microphone not muted;
- Rokid sound assets loaded for touch, AI, camera, record, navigation, volume,
  notification, payment, and wear/take-off sounds.

Interpretation:

- App-level audio capture should be possible through standard Android runtime
  permission flow.
- Product audio must still follow the OpenVision V2 policy: RV101 captures and
  transports; Cloud Realtime orchestrates; Jetson validates and executes.

## Sensors

`dumpsys sensorservice` reported 16 hardware sensors, including:

```text
accelerometer wakeup/non-wakeup, 1-500 Hz
gyroscope wakeup/non-wakeup, 1-500 Hz
proximity wakeup/non-wakeup
gravity
linear acceleration
game rotation vector
uncalibrated accelerometer
uncalibrated gyroscope
```

Observed vendors:

```text
TDK-Invensense for accelerometer/gyroscope
Sensortek for proximity
QTI/AOSP for fused sensors
```

Interpretation:

- Basic head-motion and wear/proximity state are observable from Android APIs.
- Do not build product logic directly on raw ADB sensor dumps; use an app-side
  typed telemetry contract if the product needs these signals.

## Input

`getevent -lp` reported:

```text
/dev/input/event1: ROKID,PSOC-TP-R
  KEY_ENTER
  KEY_UP
  KEY_LEFT
  KEY_RIGHT
  KEY_DOWN
  KEY_PROG1
  KEY_PROG2
  KEY_BACK
  KEY_F13
  KEY_F14
  KEY_PROG3
  KEY_DASHBOARD

/dev/input/event0: qpnp_pon
  KEY_VOLUMEDOWN
  KEY_MENU
```

Interpretation:

- The touchpad/button surface appears as key-style input.
- Future app tests should log Android `KeyEvent` mappings without changing
  global input settings.

## Network And Storage

At capture time:

```text
wifi_on=0
bluetooth_on=1
airplane_mode_on=0
location_mode=3
wlan0 state=DOWN
/data size: about 19 GB, about 17 GB free
```

Interpretation:

- Wi-Fi was off during this ADB session.
- ADB-over-Wi-Fi was not active.
- The device has usable app/data storage for sideloaded development APKs.

## Packages

System packages include:

```text
com.rokid.os.sprite.launcher
com.rokid.os.sprite.assistserver
com.rokid.os.sprite.live
com.rokid.os.master.screenstream
com.rokid.cxrservice
com.rokid.glass.ota
com.rokid.sysconfig
com.android.camera2
com.android.settings
com.android.webview
```

Third-party packages already present at capture time:

```text
com.example.advancedsettingsmanager
com.tailscale.ipn
io.github.bzerk.rokidsettingshelper
com.rokid.lyricsplayer
com.rokidapks.glasses
nextapp.fx
com.example.rokidmousehand
info.plateaukao.einkbro
com.example.rokidvideostream
com.rokid.shell
```

Interpretation:

- This RV101 is not factory-clean.
- Do not uninstall, disable, or modify these packages without an explicit task.
- The presence of third-party packages supports the practical sideloading path,
  but this session did not install anything new.

## Active Launcher

Current home activity observed by `dumpsys activity`:

```text
com.rokid.os.sprite.launcher/.main.SpriteMainActivity
baseDir=/product/app/RokidSpriteLauncher/RokidSpriteLauncher.apk
```

Interpretation:

- The stock Rokid Sprite launcher is active.
- OpenVision should remain a thin client app and should not replace the system
  launcher.
