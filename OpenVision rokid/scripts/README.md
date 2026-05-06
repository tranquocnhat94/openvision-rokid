# Scripts

Utility scripts will live here.

Scripts should be small, explicit, and safe:

- schema validation;
- local dev startup;
- redacted debug bundle export;
- simulator certificate helper;
- test runner.
- Jetson-only secret directory preparation.
- RV101 live-video no-restart scorecard.
- RV101 product signoff harness.
- session replay/scorecard export with retention.
- iPhone-simulator backend readiness signoff while the glasses app is still in
  parallel development.
- OpenVision/Rokid YOLO26 TensorRT engine preparation under the separate
  `runtime/yolo26/` path.

Avoid destructive device/service commands unless explicitly requested.

`prepare_jetson_secrets.sh` creates the ignored `ops/secrets/` directory and can write the OpenAI key file interactively without echoing it into shell history or source files.

`prepare_openvision_yolo26_engine.sh` builds the separate OpenVision/Rokid
YOLO26 TensorRT engine with `trtexec`. It refuses Ring/security/surveillance
paths and writes to `/home/jay/openvision-rokid-v2/runtime/yolo26/` by default.

`deploy_to_jetson.sh` syncs the V2 workspace, bootstraps the Jetson venv,
restarts `openvision-jetson.service`, then runs the iPhone-simulator backend
readiness signoff. The deploy fails if backend readiness fails, so the Jetson
does not look "deployed" while typed sessions, media, skills, HUD, replay, or
adapter ingress are broken.

Typical Jetson deploy:

```bash
JETSON_HOST=192.168.8.178 \
JETSON_USER=jay \
bash scripts/deploy_to_jetson.sh
```

Useful deploy controls:

```bash
OPENVISION_RESTART_SERVICE=0 bash scripts/deploy_to_jetson.sh
OPENVISION_RUN_IPHONE_SIGNOFF=0 bash scripts/deploy_to_jetson.sh
OPENVISION_SIGNOFF_CLOUD_VISUAL=1 bash scripts/deploy_to_jetson.sh
```

`score_rv101_live_no_restart.py` is read-only by default. It samples Jetson
`/api/health` before/after a wait window and fails if the runtime epoch changes.
Use `--start-live` only during an intentional, foreground RV101 live-video smoke
test.

`export_session_replay.py` is read-only against Jetson HTTP and writes local
artifacts under ignored `runtime/replays/`. It exports `/api/replay` plus
`/api/scorecard`, including skill-level eval gates for typed tool calls, media
evidence, cloud evidence, identity checks, HUD output, and skill latency.
Use `--session-id` after a test session, or `--input-replay` to re-score a saved
replay offline. Retention defaults to 14 days and the latest 100 bundles.

`score_iphone_backend_readiness.py` is the simulator-first backend signoff when
the RV101 app is not ready yet. It creates `iphone_simulator` sessions through
Jetson HTTP, uploads a private synthetic preview frame, records media metrics,
injects local perception, checks `count_people`/`object_counter`, verifies
snapshot MediaCommand budgets for `person_info` and `scene_describe`, and checks
bounded `target_finder` live adapter ingress when the OpenVision YOLO26/face
identity adapters are ready. It closes its synthetic sessions after scoring so
`/api/sessions` and health do not accumulate fake active clients. It does not
use ADB, a real camera, Immich writes, or any Ring/security runtime.

Typical Jetson backend readiness check:

```bash
python3 scripts/score_iphone_backend_readiness.py \
  --base-url http://192.168.8.178:8765
```

Add `--exercise-cloud-visual` only when intentionally testing the configured
cloud visual verifier path; the default avoids cloud vision calls.

RV101 H.264 live preview decode is controlled by
`OPENVISION_RV101_H264_PREVIEW`. Keep it off until no-restart scorecards are
passing, then enable it for a bounded smoke test and verify `/api/preview` before
using `live_video` as skill evidence.

`score_rv101_product_signoff.py` is a bounded real-device harness for the
OpenVision RV101 app. It only uses ADB user-space commands, app launch, typed
Jetson DisplayCommand/MediaCommand requests, and cleanup checks. It never roots
the glasses, deletes system files, changes firmware, or holds Wi-Fi awake.

Typical USB tunnel signoff:

```bash
python3 scripts/score_rv101_product_signoff.py \
  --route tunnel \
  --adb-reverse \
  --force-stop-app \
  --json-output glasses/android_client/signoff_tunnel_latest.json
```

The product voice gate in this harness is `session_accept` declaring
`voiceMode=conversation_realtime`, `turnPolicy=server_vad`, and a direct
`/ws/realtime/{session_id}/audio` voice-output path. Add
`--exercise-ptt-fallback --ptt-seconds 4 --ptt-say "xin chao OpenVision"` only
when intentionally testing the debug/noisy PTT fallback.

The tunnel route requires local SSH forwards plus ADB reverse for all three
ports: `8765` control/HTTP, `8770` H.264 video, and `8771` PCM audio. The
harness checks those ports and can create missing local SSH forwards using
`--ssh-target` unless `--no-ssh-tunnel` is set. A tunnel report with status
`warn` can still be a valid app/backend contract pass when the only warning is
that the route is not the normal RV101 tailnet path.
