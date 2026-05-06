# RV101 AI App/Scene Launch And Vietnamese Support

Updated: 2026-04-29
Device target: Rokid Glasses RV101

## Bottom Line

For RV101, Rokid's AI app-opening behavior appears to be a structured instruct
system, not a raw natural-language-to-Android-intent system.

The strongest static evidence says:

```text
online AI/NLU result
  -> JSON command such as control_app or control_playback
  -> RV101 OnLineManager action map
  -> whitelisted first-party scene/page or Bluetooth/media action
```

The app/scene command shape is effectively:

```json
{
  "command": "control_app",
  "params": {
    "action": "open",
    "name": "Navigation"
  }
}
```

`control_app` only proves support for known names such as `Navigation`,
`AI Chat`, `Translator`, `Camera`, `Recorder`, `Prompter`, `Subtitles`,
`Lyric`, `MixRecord`, `Settings`, and `Caexpo`. It does not prove generic
opening of any installed Android app by Vietnamese name.

## Why Vietnamese Support Is Partial

Some Vietnamese commands work because they are fixed offline commands in
`values-vi`, with local handlers for actions such as play music, pause, next
track, answer call, change volume/brightness, take photo, record audio/video,
check battery, check time, and exit.

Some richer Vietnamese commands likely work only when Rokid's upstream AI/NLU or
a phone-side assistant maps the phrase into a supported structured command.

Unsupported Vietnamese phrases likely fail because one of these is missing:

```text
Vietnamese NLU intent
supported command id
a supported action/name pair
a whitelisted first-party scene
a visible/allowed launcher package mapping
```

## Navigation/Home Nuance

Navigation support itself is proven: `control_app` maps `Navigation` to the
`navigation` scene, and Launcher has a Vietnamese navigation prompt and page
name.

This pass does not prove that RV101 locally parses a "home" destination. If a
Vietnamese phrase like "navigate home" works, the safest model is:

```text
Vietnamese speech
  -> upstream Rokid AI/NLU or phone navigation layer
  -> structured navigation scene/tool action
  -> RV101 navigation scene
```

## OpenVision Rule

OpenVision should implement this pattern openly and safely, not by depending on
Rokid private internals:

```text
Vietnamese voice
  -> Cloud Realtime typed tool call
  -> Jetson validates allowed target, privacy, budget, and confirmation policy
  -> Rokid receives only a thin display/media/app command
```

Recommended typed tools:

```text
open_skill(skill_id, reason)
open_scene(scene_id, reason)
start_navigation(destination, destination_kind, confidence)
control_media(action)
control_phone_assistant(action)
open_android_package(package_name, reason)   # debug/allowlisted only
```

Do not allow natural language to open arbitrary Android packages without an
allowlist and, where needed, user confirmation.

## Deep-Dive Evidence

Full static-analysis notes are in:

```text
device_research/rv101_system_apks_2026-04-29/rokid_jsai_wake_research/05_app_scene_launch_and_language_support.md
```

Key decoded APK files:

```text
_tmp/RokidSpriteAssistServer_apktool_full/smali_classes2/com/rokid/os/sprite/assist/instruct/online/OnLineManager.smali
_tmp/RokidSpriteAssistServer_apktool_full/smali_classes2/com/rokid/os/sprite/assist/instruct/online/ControlAppOrSceneAction.smali
_tmp/RokidSpriteAssistServer_apktool_full/smali_classes2/com/rokid/os/sprite/assist/instruct/online/ControlPlaybackAction.smali
_tmp/RokidSpriteAssistServer_apktool_full/res/values-vi/strings.xml
_tmp/RokidSpriteLauncher_apktool_full/smali_classes2/com/rokid/os/sprite/launcher/global/app/AppSearchManager.smali
_tmp/RokidSpriteLauncher_apktool_full/smali_classes2/com/rokid/os/sprite/launcher/global/app/AppDataManager.smali
```

## Safety

No ADB action, app launch, private service call, firmware operation, or system
state change was performed for this note. This is static, read-only APK research.
