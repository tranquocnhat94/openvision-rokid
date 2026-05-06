# RV101 ADB Field Notes

Updated: 2026-04-29

This folder records what was actually verified through ADB on the user's
Rokid Glasses, plus conservative Android-based conclusions for future
OpenVision RV101 work.

## Device Identity

This device is confirmed as the RV101 target, not a guessed Rokid family
member.

Direct ADB evidence:

```text
adb devices -l
  product:glasses model:RG_glasses device:glasses

adb shell getprop ro.product.rokid.oem.model
  RV101

adb shell getprop ro.product.rokid.oem.id
  101
```

Important nuance:

- `ro.product.model` reports `RG-glasses`.
- The RV101-specific proof is the Rokid OEM property
  `ro.product.rokid.oem.model=RV101`.
- Do not identify this device from `adb devices -l` alone.

Official source alignment:

- Rokid's security center lists `Rokid Glasses` models `RV101` and `RV102`
  with support dates from `2025-06-30` to `2028-12-31`.
- Rokid's product page for `Rokid Glasses` lists the same hardware class seen
  in ADB: Snapdragon AR1 family, RT600 companion chip, 2 GB RAM, 32 GB storage,
  Wi-Fi 6, Bluetooth 5.3, 12 MP Sony IMX681 camera, 4 microphones, and dual
  speakers.

Sources:

- [Rokid Glasses product page](https://global.rokid.com/products/rokid-glasses)
- [Rokid Security Center](https://global.rokid.com/pages/security-center)
- [Android Debug Bridge docs](https://developer.android.com/tools/adb)
- [Android Logcat docs](https://developer.android.com/tools/logcat)
- [Community dev-cable note by Marcin Miazga](https://marcinmiazga.com/rokid-development-cable)

## Files

- [01_verified_device_state.md](01_verified_device_state.md): exact ADB
  observations from the connected RV101.
- [02_adb_capability_matrix.md](02_adb_capability_matrix.md): what the cable
  can do, what needs approval, and what must stay off limits.
- [03_safe_workflow.md](03_safe_workflow.md): safe command patterns for future
  bring-up, app install, logging, and Jetson integration.
- [04_sources_and_confidence.md](04_sources_and_confidence.md): source ladder
  and confidence notes.
- [05_os_and_recovery_assessment.md](05_os_and_recovery_assessment.md):
  Android/Rokid OS identity, customization surface, and recovery-image risk
  assessment.
- [06_rokid_sprite_live_deep_dive.md](06_rokid_sprite_live_deep_dive.md):
  pointer to the static `RokidSpriteLive` analysis for RV101 media capture,
  including the safe OpenVision app interpretation.
- [07_jsai_wake_and_agent_runtime.md](07_jsai_wake_and_agent_runtime.md):
  pointer to the static `RokidSpriteAssistServer` / `RokidSpriteLauncher`
  analysis for RV101 AI wake, `ai_assist`, `jsai`, and safe OpenVision
  activation-session architecture.
- [08_ai_app_scene_launch_language_support.md](08_ai_app_scene_launch_language_support.md):
  pointer to the static RV101 analysis of AI app/scene launch, the
  `control_app` scene whitelist, playback/mobile-assistant commands, and why
  Vietnamese support is partial rather than generic.
- [09_third_party_app_ai_launchability.md](09_third_party_app_ai_launchability.md):
  pointer to the static RV101 analysis of whether a normal OpenVision APK
  manifest is enough for native Rokid AI voice launch, and what manifest/deep
  link declarations are still useful.

## Local Research Artifacts

A read-only system APK extraction was created at:

```text
device_research/rv101_system_apks_2026-04-29/
```

That folder contains selected Rokid system APKs, generated ADB pull metadata,
SHA-256 checksums, and `aapt` manifest/badging summaries. APK binaries are
ignored by git and should remain local/proprietary research artifacts.

The `RokidSpriteLive` deep-dive notes live at:

```text
device_research/rv101_system_apks_2026-04-29/rokid_sprite_live_research/
```

The `JsAi` / AI wake research notes live at:

```text
device_research/rv101_system_apks_2026-04-29/rokid_jsai_wake_research/
```

That folder now also records the RV101 AI app/scene launch command surface and
Vietnamese support limits, plus the third-party app launchability boundary for
an OpenVision APK.

## Safety Rule

Treat ADB as a diagnostic and app-deployment interface only. Do not use it as a
firmware, root, bootloader, partition, or persistent system-modification path
unless Rokid publishes a recovery image and the user explicitly approves the
risk.

No destructive or state-changing device commands were run while creating these
notes. The session used read-only commands such as `getprop`, `pm list`,
`cmd package list features`, `dumpsys`, `settings get`, `df`, and `ip addr show`.
