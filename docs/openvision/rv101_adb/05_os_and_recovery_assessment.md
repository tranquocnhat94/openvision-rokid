# RV101 OS And Recovery Assessment

Updated: 2026-04-29

This file records what the connected RV101 appears to run, what Rokid customized,
and whether we currently have enough material to restore the glasses if system
software is damaged.

## Short Answer

The connected RV101 runs a Rokid-customized Android 12 build. It is not a
generic AOSP image, and we do not currently have a safe full restore image for
this exact device/build.

Practical rule:

- We can safely recover from most OpenVision app-layer mistakes by uninstalling
  or replacing our own APK.
- We should not assume we can recover from system/boot/vendor/OTA damage.
- Do not modify system partitions, boot images, verified boot state, OTA state,
  vendor properties, or Rokid system packages.

## Direct OS Evidence From The Device

Identity:

```text
ro.product.rokid.oem.model=RV101
ro.product.rokid.oem.id=101
ro.product.model=RG-glasses
ro.product.device=glasses
```

Android build:

```text
Android release: 12
SDK: 32
build id: SKQ1.240613.001
build incremental: 1.17.012-20260414-150201
build description: glasses-user 12 SKQ1.240613.001 1.17.012-20260414-150201 release-keys
build flavor: qssi_lite-user
build type: user
build tags: release-keys
security patch: 2024-07-05
first API level: 31
```

Kernel/platform:

```text
kernel: Linux 5.10.209-perf
kernel build suffix: ab1.17.012-20260414-150201
hardware: qcom
board platform: neo
baseband: apq
GPU stack: adreno
```

Boot/update structure:

```text
ro.build.ab_update=true
ro.boot.dynamic_partitions=true
ro.virtual_ab.enabled=true
active boot slot: _b
super partition present
dynamic logical partitions: system, system_ext, product, vendor, vendor_dlkm, odm
AVB/verified partitions present
SELinux=Enforcing
ro.debuggable=0
ADB shell uid=2000(shell), not root
```

Important: device-unique boot seed, USB serial, and other identifiers were
observed during inspection but are intentionally omitted from this document.

## What Rokid Customized

The device is Android-based, but the product experience is heavily Rokid-owned.
Observed customizations include:

- Product identity and OEM properties for `RV101` / `RG-glasses`.
- Rokid "Sprite" app family:
  - `com.rokid.os.sprite.launcher`
  - `com.rokid.os.sprite.assistserver`
  - `com.rokid.os.sprite.live`
- Rokid services and system packages:
  - `com.rokid.cxrservice`
  - `com.rokid.os.master.screenstream`
  - `com.rokid.glass.ota`
  - `com.rokid.sysconfig`
- Rokid resource overlays:
  - `android.overlay.common.rkd`
  - `com.android.wifi.resources.overlay.rkd`
  - `com.android.networkstack.overlay.rkd`
- Rokid boot animation:
  - `/product/media/bootanimation_101.zip`
- Rokid OTA endpoint properties:
  - `ro.rokid.ota.check_url=https://ota.rokid.com`
  - `ro.rokid.ota.check_api=/v1/extended/ota/check`
- Rokid touch/proximity/debug behavior properties:
  - `rokid.debug.two_finger_click`
  - `rokid.debug.two_finger_flick`
  - `rokid.debug.touch_evt_disable`
  - `rokid.debug.touch_evt_reverse`
  - `rokid.psensor.mode`
- Rokid-specific input hardware:
  - `/dev/input/event1: ROKID,PSOC-TP-R`

The current product path should therefore treat RV101 as a customized Android
device with a normal app surface, not as an open development board.

## What We Have Locally Now

We have useful research materials:

```text
docs/openvision/rv101_adb/
device_research/rv101_system_apks_2026-04-29/
```

The local APK extraction contains selected Rokid system APKs, checksums,
package paths, and `aapt` manifest/resource summaries.

These are useful for:

- understanding component names, permissions, resources, and app behavior;
- writing an OpenVision app that fits the RV101 environment;
- restoring our own app-layer state if we install a bad OpenVision APK.

These are not enough for:

- flashing a full stock image;
- rebuilding Rokid's signed boot/vendor/product/system images;
- restoring protected partitions after a bad fastboot/bootloader operation;
- recovering from a failed OTA, corrupted `super`, bad `boot`, bad `vendor_boot`,
  bad `vbmeta`, or damaged Qualcomm boot chain.

## Why We Do Not Have A Full Recovery Image

Direct device constraints:

- ADB is non-root.
- System partitions are mounted read-only and verified.
- Block devices exist, but reading/restoring raw partitions is not available
  through normal safe ADB shell.
- Android Verified Boot and A/B dynamic partitioning mean a valid restore image
  must match signatures, rollback state, slots, and partition layout.

Public source constraints:

- Rokid's current public product/security pages confirm RV101/RV102 support,
  but do not provide a public RV101 factory image in the pages checked.
- An older Rokid Glass FAQ contains a `full_image.zip` for an old `Rokid_Glass`
  manual flashing flow under an `msm8998` directory. That is not this RV101
  Android 12 / Qualcomm `neo` build and must not be used for this device.
- Some community reports discuss firmware/OTA extraction, but they are not an
  official, user-safe recovery path.

## OTA Cache Check

Read-only inspection on 2026-04-29 did not find a usable cached OTA package.

What was checked:

- `persist.rokid.sprite.ota.running=false`
- `update_engine` service was running, but logs only showed normal
  `CleanupPreviousUpdateAction` startup work.
- Recent update-engine logs repeatedly reported:
  - `Can't find any snapshot to merge.`
  - `ActionProcessor: finished last action CleanupPreviousUpdateAction with code ErrorCode::kSuccess`
- No OTA-like files were visible in the readable external-storage locations
  checked, including `/sdcard/Download` and common `/sdcard/ota` / `/sdcard/update`
  style paths.
- Protected OTA/cache paths exist or are referenced, but normal ADB shell could
  not read their contents:
  - `/data/ota_package`
  - `/data/ota`
  - `/data/misc/update_engine`
  - `/metadata/ota`
  - `/data/cache`
  - `/data/user/0/com.rokid.glass.ota`

Interpretation:

- There is no visible `payload.bin`, OTA zip, or full update package available
  to us through safe ADB.
- The presence of update-engine logs and dynamic-partition metadata does not
  equal a recoverable OTA package.
- We should not rely on the device itself as a firmware backup source.

## What Would Count As A Real Recovery Kit

For RV101, a useful recovery kit would need at least one of these:

- an official Rokid RV101 full factory image for this exact hardware/region;
- an official RV101 OTA package plus documented recovery/sideload procedure;
- documented fastboot flashing commands from Rokid for RV101;
- a service tool from Rokid or an authorized repair channel;
- enough signed partition images to restore `boot`, `vendor_boot`, `dtbo`,
  `vbmeta`, `vbmeta_system`, `super`, and relevant Qualcomm firmware partitions.

Without that, our safest position is:

```text
Do app-layer development only.
Never modify boot/system/vendor/OTA state.
Keep all OpenVision work uninstallable.
```

## Safe Backup Strategy We Can Actually Do

Keep:

- exact build fingerprint and version metadata;
- package inventory and system APK research copies;
- checksums of pulled APKs;
- OpenVision APK versions and signing keys;
- our own app logs/configs/test fixtures;
- screenshots/logs only when privacy-safe;
- `pm path`, `pm list packages`, `cmd overlay list`, `lpdump`, and mount
  metadata for future comparison.

Avoid:

- raw partition dumps;
- bootloader/fastboot experiments;
- root attempts;
- Magisk/boot image patching;
- OTA endpoint probing beyond read-only property inspection;
- changing persistent/vendor/system properties.

## Sources

- Direct ADB observations from the user's RV101.
- [Rokid Glasses product page](https://global.rokid.com/en-jp/products/rokid-glasses)
- [Rokid Security Center](https://global.rokid.com/pages/security-center)
- [Older Rokid Glass FAQ, not RV101 recovery authority](https://rokid.github.io/glass-docs/0-faq/)
- [Android dynamic partitions documentation](https://source.android.com/docs/core/ota/dynamic_partitions)
- [Android Virtual A/B documentation](https://source.android.com/docs/core/ota/virtual_ab)
- [Android Verified Boot documentation](https://android.googlesource.com/platform/external/avb/+/android11-release/README.md)
