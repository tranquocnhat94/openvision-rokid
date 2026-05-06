# RV101 JsAi Wake And Agent Runtime

Updated: 2026-04-29

This note points future OpenVision work to the local static analysis of RV101's
AI wake, AI assistant, and JsAi mini-program runtime paths.

Primary research folder:

```text
device_research/rv101_system_apks_2026-04-29/rokid_jsai_wake_research/
```

## Key Conclusion

RV101 supports AI wake through a vendor scene/instruct pipeline, not just a plain
Android app launch.

Static evidence shows this shape:

```text
offline wake phrase / touchpad long-press / phone or CXR command
  -> RokidSpriteAssistServer InstructService / Bluetooth managers
  -> scene key such as ai_assist, ai_chat, or jsai
  -> optional CXR audio stream named AI_assistant
  -> Launcher AI UI or JsAi Ink mini-program runtime
```

The most useful OpenVision lesson is session reuse:

```text
If no active AI owner exists:
  wake opens ai_assist.

If JsAiActivity is already open:
  it registers an offline activation interceptor, receives onInstructCall(...),
  and forwards the wake event into the running Ink runtime with
  InkView.dispatchVoiceWakeup(name, timestamp).
```

For OpenVision, this maps to:

```text
ActivationEvent
  -> Jetson session authority
  -> open or focus Cloud Realtime voice session
  -> dispatch repeated wake into the active session
  -> stream microphone only while the approved voice mode is active
  -> keep camera off unless a typed MediaCommand requests it
```

## Evidence Highlights

Confirmed by static APK analysis:

- `RokidSpriteAssistServer` is a privileged persistent system app with camera,
  microphone, Bluetooth, network, and system permissions.
- `InstructService` exposes offline activation, online instruct, scene status,
  voice recognition, speech scene, and voice power APIs.
- `OffActivationAction` opens `ai_assist` when no interceptor owns the wake.
- `JsAiActivity` registers an `IActivationInstructInterceptor` and dispatches
  later wake events to `InkView.dispatchVoiceWakeup(...)`.
- `JsAiService` implements `IJsAiServer`, opens `JsAiActivity` with a
  `miniprogram_path`, stores/downloads native-agent packages under `/sdcard/jsai`,
  and marks the `jsai` scene running.
- `RokidAIManager` can call `openAIFunction(...)`, open `ai_assist`, and start a
  CXR audio stream with function name `AI_assistant`.
- Launcher resources explicitly mention waking AI by saying `Hi Rokid` or by
  long-pressing the touchpad.

Not tested dynamically in this pass:

- wake phrase runtime logs;
- touchpad runtime logs;
- private AI scene launch;
- private JsAi page launch;
- CXR audio packet behavior.

ADB currently reports no attached device in this session, so this is static APK
evidence only.

## Product Guidance

Do not build OpenVision around these private surfaces:

```text
com.rokid.os.sprite.assist.instruct.InstructService
com.rokid.os.sprite.jsai.JsAiService
com.rokid.os.sprite.jsai.JsAiActivity
com.rokid.sprite.bluetooth.RokidAIManager
CXRServiceBridge.startAudioStream(...)
cmd_open_scene_with_ignore_tips
com.rokid.os.sprite.jsai.OPEN_PAGE
```

Instead, implement a normal-app/Jetson-owned equivalent:

```text
RV101 app detects explicit wake/PTT/touch action when available
  -> sends typed ActivationEvent to Jetson
  -> Jetson validates privacy, budget, timeout, current session state
  -> Jetson starts or focuses Cloud Realtime
  -> RV101 opens mic stream only after Jetson accepts
  -> display is only through DisplayCommand/HUD scene protocol
```

Wake is not camera permission. A wake event should default to:

```text
media_mode = none
```

Camera activation remains a typed `MediaCommand` concern.

## Files

- `README.md` - scope, main conclusion, confidence, and safety rule.
- `01_manifest_and_services.md` - package identity, permissions, services,
  launcher AI components, and scene keys.
- `02_activation_scene_flow.md` - offline activation, wake phrase, touch hints,
  `ai_assist`, CXR audio stream, and safe ADB observation commands.
- `03_jsai_runtime_and_agent_capabilities.md` - JsAi service/activity,
  native-agent metadata, Ink capabilities, audio recording, photo, and networking.
- `04_openvision_architecture_takeaways.md` - proposed `ActivationEvent` and
  `AiSessionCommand` contracts plus product rules and acceptance tests.
