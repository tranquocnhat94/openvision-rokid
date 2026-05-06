# Safe RV101 ADB Workflow

Updated: 2026-04-29

This is the default workflow for future RV101 ADB sessions. It assumes the
development cable is connected and ADB is enabled in the Rokid/Hi Rokid app.

## Session Rules

1. Start read-only.
2. Confirm model with `ro.product.rokid.oem.model`.
3. Redact serials, MAC addresses, seeds, account IDs, and raw private logs.
4. Do not change settings, packages, Wi-Fi, launcher, display density, or boot
   state unless the task explicitly asks for it.
5. Keep RV101 as a thin client; Jetson remains runtime authority.

## Baseline Read-Only Check

Use this first:

```sh
adb devices -l
adb shell getprop ro.product.rokid.oem.model
adb shell getprop ro.product.model
adb shell getprop ro.build.version.release
adb shell getprop ro.build.version.sdk
adb shell getprop ro.build.version.incremental
adb shell getprop ro.build.fingerprint
adb shell getprop ro.debuggable
adb shell getprop ro.secure
adb shell getprop ro.adb.secure
adb shell getenforce
adb shell id
adb shell wm size
adb shell wm density
```

Expected RV101 anchors from the current device:

```text
ro.product.rokid.oem.model=RV101
ro.product.model=RG-glasses
Android=12
SDK=32
build incremental=1.17.012-20260414-150201
ro.debuggable=0
SELinux=Enforcing
shell uid=2000
display=480x640 @ 240 dpi
```

## Capability Inventory

Safe read-only inventory commands:

```sh
adb shell cmd package list features
adb shell pm list packages
adb shell pm list packages -3
adb shell dumpsys display
adb shell dumpsys window displays
adb shell dumpsys media.camera
adb shell dumpsys sensorservice
adb shell dumpsys audio
adb shell getevent -lp
adb shell df -h
adb shell logcat -g
adb forward --list
adb reverse --list
```

Avoid dumping all `getprop` or raw `logcat` into committed files. Some values
are device-unique or privacy-sensitive.

## App Development Path

For OpenVision, use ADB to deploy a normal Android app, not to modify the
system.

Recommended flow for a future clean RV101 app:

```sh
adb install -r path/to/openvision-rv101-debug.apk
adb shell am start -n com.openvision.rokid/.MainActivity
adb logcat -v time OpenVision:D AndroidRuntime:E '*:S'
```

Only after the user approves installation:

- install or replace our own OpenVision debug package;
- grant runtime permissions only to our own package;
- launch only our own activity;
- collect filtered logs.

Do not replace the stock Rokid launcher.

## Jetson Connectivity Tests

Preferred product path:

```text
RV101 app -> network transport -> Jetson -> typed runtime -> HUD/display commands
```

ADB can help during development:

```sh
adb reverse tcp:PORT tcp:PORT
adb forward tcp:PORT tcp:PORT
adb reverse --list
adb forward --list
```

Guidelines:

- Prefer normal Wi-Fi/LAN paths for real RV101 signoff.
- Use ADB `reverse` only as a local dev convenience.
- Remove temporary mappings after the test:

```sh
adb reverse --remove-all
adb forward --remove-all
```

These remove commands are state-changing on the ADB session but do not mutate
firmware or Android system settings.

## Screenshots And Logs

Use only when needed:

```sh
adb exec-out screencap -p > rv101-screen.png
adb shell logcat -v time -d OpenVision:D AndroidRuntime:E '*:S'
```

Rules:

- Do not commit screenshots containing private user content.
- Prefer `exec-out screencap` over writing `/sdcard/screen.png`.
- Prefer filtered logcat over raw full-device logcat.
- Never clear logs with `logcat -c` unless explicitly requested.

## Permission Grants For Our App

Only for our own debug package, and only after installation is approved:

```sh
adb shell pm grant com.openvision.rokid android.permission.CAMERA
adb shell pm grant com.openvision.rokid android.permission.RECORD_AUDIO
```

Do not grant permissions to unknown third-party packages.

## Stop Conditions

Stop immediately and ask before continuing if:

- ADB reports an unauthorized or different device.
- `ro.product.rokid.oem.model` is not `RV101`.
- a command requires root, remount, bootloader, recovery, or firmware tools;
- a command would modify global/secure settings;
- a command would disable/uninstall a system package;
- logs show repeated system crashes after a test launch.
