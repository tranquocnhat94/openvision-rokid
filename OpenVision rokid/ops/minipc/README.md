# Mini PC PhoWhisper Debug STT Sidecar

This folder is the source-controlled copy of the optional Mini PC PhoWhisper worker used by Ops Console debug transcript visibility.

It is sidecar-only:

- does not route product commands;
- does not update HUD;
- does not mutate Jetson skill state;
- only accepts completed audio turns from Jetson.

Security rules:

- bind is allowed on LAN only for Jetson/Mac debugging;
- Windows firewall should restrict port `9460` to trusted hosts when the route/profile allows it;
- all HTTP endpoints require `X-OpenVision-Debug-STT-Token` when `--auth-token-file` is configured;
- token files live outside git, normally in `run/debug_stt_token.txt` on Mini PC and `ops/secrets/debug_stt_token` on Jetson.

Canonical Mini PC task:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\Tranq\rokid_stt_probe\run\start_phowhisper_detached.ps1
```

Keep only one scheduled task active: `OpenVisionPhoWhisper`.
