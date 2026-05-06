# RV101 ADB Sources And Confidence

Updated: 2026-04-29

This file explains how to weigh future claims about the RV101.

## Source Ladder

Highest confidence:

1. Direct ADB observations from the user's actual RV101.
2. Official Rokid pages for the current `Rokid Glasses` product and security
   support.
3. Official Android developer documentation for generic ADB behavior.
4. Public Rokid developer docs for older Rokid Glass / Glass 2 generations,
   used only when they match RV101 observations.
5. Community posts and third-party notes, used as practical hints only.

## Current Direct Evidence

The connected device itself proves:

```text
ro.product.rokid.oem.model=RV101
ro.product.rokid.oem.id=101
ro.product.model=RG-glasses
Android 12 / SDK 32
user / release-keys build
SELinux Enforcing
non-root adb shell
480x640 display
one public Camera2 camera
microphone/audio output features
Rokid touchpad key input device
```

## Official Rokid Evidence

Rokid product/security pages support the broad hardware identity:

- `Rokid Glasses` is the product family for RV101/RV102 in Rokid's security
  support table.
- Rokid's product page lists Snapdragon AR1/RT600, Wi-Fi 6, BT 5.3, 2 GB RAM,
  32 GB storage, 12 MP Sony IMX681 camera, four microphones, and dual speakers.

Use official hardware pages for broad capabilities, but prefer ADB for exact
software/build state.

## Official Android Evidence

Android's ADB docs establish generic capabilities:

- `adb` communicates with connected devices, installs/debugs apps, and provides
  a Unix shell.
- Android 11+ supports wireless debugging in principle.
- `screencap` and `screenrecord` are standard shell utilities.
- `logcat` dumps system/app log buffers.

Apply this to RV101 only inside the limits observed on the device:

- non-root shell;
- user/release build;
- SELinux enforcing;
- no ADB TCP port active at capture time.

## Community Evidence

The Marcin Miazga development-cable note matches the user's current successful
setup:

- the charging cable is not enough for ADB;
- a 5-pin development cable is used;
- ADB debugging is enabled through Hi Rokid/Rokid app;
- `adb devices` should then show the glasses;
- `adb install` is the expected third-party APK path.

Treat this as community confirmation, not manufacturer policy.

## Claims To Avoid

Do not claim:

- root access;
- firmware flashability;
- bootloader recovery safety;
- system partition mutability;
- production-quality OpenVision RV101 app success;
- real camera/audio/HUD stream success through OpenVision V2.

Those need explicit tests and, for firmware operations, a recoverable firmware
image from Rokid.
