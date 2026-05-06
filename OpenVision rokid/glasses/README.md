# Glasses App

The Rokid app is the canonical product client and must stay thin.

For app-topic work, use `../../docs/openvision/27_ROKID_APP_CODEX_ROADMAP.md`
as the alignment contract. The iPhone simulator and backend contracts are the
lead references; the app should not rediscover voice, media, or HUD routes that
already exist.

It owns:

- camera capture;
- hardware H.264 encode;
- microphone PCM capture;
- transport;
- session state needed for transport/reconnect;
- compact HUD scene rendering;
- minimal diagnostics.

It does not own:

- heavy perception;
- tracking;
- skill routing;
- cloud routing;
- memory;
- OpenAI sessions;
- complex settings screens;
- old mode UI.

HUD should remain glanceable: small answer strips, chips, direction hints, target markers, alert bursts, and rare tiny galleries. Center vision should stay mostly clear.

Current RV101 baseline:

```text
session_accept drives session, media, audio, and voice-output setup
opening the app starts conversation_realtime by default
Cloud Realtime server_vad handles turns from the streamed mic audio
future wake_realtime can replace app-open stream with "Hey Vision" standby trigger
PTT/manual-turn remains debug/noisy fallback only
camera opens only for typed MediaCommand
display renders only hud_scene / DisplayCommand primitives
metadata from RV101 capture must include orientation/profile/FPS details
```

Avoid REST realtime bootstrap, Jetson/app-side voice gate, local STT, direct
OpenAI calls, app-side skill routing, and phone-style mode screens.
