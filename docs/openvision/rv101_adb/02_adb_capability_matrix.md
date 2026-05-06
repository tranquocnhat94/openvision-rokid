# RV101 ADB Capability Matrix

Updated: 2026-04-29

This matrix separates confirmed RV101 behavior from Android-based inference.

## Confirmed Safe Read-Only Capabilities

These were performed successfully over the connected development cable:

| Capability | Evidence | Notes |
| --- | --- | --- |
| USB ADB connection | `adb devices -l` shows authorized `Rokid` device | Serial intentionally not recorded. |
| Exact model confirmation | `ro.product.rokid.oem.model=RV101` | Use this property for identity. |
| Android/build inspection | `getprop` selected properties | Android 12 / API 32 / user release build. |
| Shell access | `adb shell id` | Non-root `uid=2000(shell)`. |
| Display inspection | `wm size`, `wm density`, `dumpsys display` | 480x640, 240 dpi, 60 Hz. |
| Camera inspection | `dumpsys media.camera` | One public camera; Camera2 metadata visible. |
| Audio inspection | `dumpsys audio` | Audio route and mic state visible. |
| Sensor inspection | `dumpsys sensorservice` | Motion/proximity/fused sensors visible. |
| Input-device inspection | `getevent -lp` | Touchpad/button device exposes key events. |
| Package inventory | `pm list packages`, `pm list packages -3` | Third-party apps already exist. |
| Feature inventory | `cmd package list features` | Android feature flags visible. |
| Log buffer sizing | `logcat -g` | Readable log buffers exist. |
| Forward/reverse inventory | `adb forward --list`, `adb reverse --list` | No active mappings at capture time. |

## Safe With Care

These are normal Android/ADB capabilities for this device class, but should be
used intentionally because they can expose private data or change visible state.

| Capability | Confidence | Why it matters | Guardrail |
| --- | --- | --- | --- |
| `adb logcat` | High | Debug app crashes, media, audio, camera, network | Prefer filtered logs; do not archive raw private logs. |
| `adb exec-out screencap -p` | High, Android standard | Capture HUD/app screenshots without writing to device storage | Ask first if private content may be visible. |
| `adb shell screenrecord` | High, Android standard | Record app behavior | Avoid unless needed; it writes a file and can capture private HUD. |
| `adb pull` app-owned/exported files | High | Retrieve debug artifacts | Pull only known debug paths. |
| `adb push` to `/sdcard/` | High | Copy test fixtures/APKs/media | Avoid overwriting user media. |
| `adb install -r <apk>` | High, Android standard and community documented | Deploy OpenVision RV101 thin client | Only install signed builds from this workspace; never install unknown APKs casually. |
| `adb uninstall <third_party_pkg>` | High but state-changing | Remove our own test app | Only for packages we own and the user approves. |
| `adb shell am start ...` | High but visible | Launch our test activity | Use explicit component names; do not change launcher defaults. |
| `adb reverse` / `adb forward` | Medium-high | Connect RV101 app to local/Jetson dev services | Remove mappings after testing; document ports. |
| Runtime permission grants for our app | Medium-high | Avoid awkward on-glass permission prompts for dev builds | Only grant permissions to our own debug package. |
| `run-as <debuggable_package>` | Medium | Inspect our own debug app data | Works only if the package is debuggable. |

## Android-Based Inference

Because this RV101 runs Android 12 / API 32:

- Standard Android app sideloading/debugging workflows should apply when ADB is
  authorized.
- Android's official docs say Android 11+ supports wireless debugging, but this
  RV101 currently had Wi-Fi off and no ADB TCP port set.
- Camera, microphone, sensors, WebView, networking, and storage should be used
  through Android app APIs, not through permanent ADB scripts.

## Not Verified In This Session

These may be possible, but were intentionally not tried:

- installing a new APK;
- launching or stopping user apps;
- granting/revoking permissions;
- taking screenshots or screen recordings;
- enabling Wi-Fi or ADB-over-TCP;
- running live key-event capture;
- reading raw logcat contents;
- pulling user media or app private data.

## Off Limits Without Explicit Recovery Plan

Do not run these on the RV101:

```text
adb root
adb remount
adb disable-verity
adb reboot bootloader
adb reboot recovery
fastboot ...
edl / Qualcomm emergency download tools
dd, flash_image, mkfs, mount -o rw/remount
setprop persist.* or setprop vendor.* for product behavior
settings put ... for global/secure/system settings
pm disable / pm uninstall --user 0 for system packages
cmd package compile / clear / trim-caches on system packages
svc wifi enable/disable unless the user asks for network bring-up
input keyevent/tap/swipe unless testing input behavior explicitly
```

Reason:

- Rokid has not provided us a public firmware restore image.
- The device is a consumer `user` build with SELinux enforcing.
- The OpenVision architecture does not need system modification. It needs a
  thin Android client and typed Jetson-owned runtime.

## Product Implication For OpenVision

ADB gives us a safe development path to:

- deploy a clean RV101 thin-client APK;
- collect app logs and crash evidence;
- verify camera/audio/HUD behavior;
- inspect device capabilities;
- create one-time dev port mappings;
- validate RV101 sessions against Jetson.

ADB should not become:

- the product command path;
- a hidden runtime dependency;
- a replacement for typed MediaCommand/DisplayCommand contracts;
- a firmware modification route.
