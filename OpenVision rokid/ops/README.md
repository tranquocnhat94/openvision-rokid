# Ops

Operations notes live here.

Topics:

- Jetson service layout;
- environment variables;
- secret storage;
- startup scripts;
- logs;
- redacted debug bundle export;
- production readiness checklist.

Secrets must be referenced by status/path only, never written into docs.

Current production-facing defaults:

- OpenAI key: `OPENAI_API_KEY_FILE` points to a restricted Jetson-only file.
- Cloud visual verifier: `OPENVISION_CLOUD_VERIFY_ENABLED=0` by default; enable only through Jetson-local env when captured previews should go through CloudGateway/OpenAI Responses.
- YOLO26 adapter: `OPENVISION_YOLO26_MODE=disabled` in the checked-in example; set Jetson-local env to `external_stream` only for the separate OpenVision/Rokid detector path.
- YOLO26 worker: product live YOLO26 uses `OPENVISION_DEEPSTREAM_YOLO26_WORKER_ENABLED=1` on Jetson with the separate OpenVision DeepStream service. The old preview-polling worker is not part of the active product tree.
- Face identity adapter: `OPENVISION_FACE_IDENTITY_MODE=external_stream` accepts only OpenVision/Rokid/iPhone sources for local face bbox + embedding frames.
- Face identity worker: `OPENVISION_FACE_WORKER_ENABLED=0` until OpenCV deps and YuNet/SFace model files exist under `runtime/face/`.
- Contact identity DB: local user-managed samples live under `runtime/identity/` and can be enrolled from saved crops for `target_finder` name reminders.
- People Registry: `runtime/people/people_registry.json` stores names, aliases, phone/address/link notes, and Immich person references. Photos and thumbnails stay in Immich. Sync uses `OPENVISION_IMMICH_BASE_URL` plus `OPENVISION_IMMICH_API_KEY_FILE`; the current Mini PC host is `http://192.168.8.105:2283` when Immich is exposed on its standard LAN port.
- v2 Tailscale HTTPS uses `:8443` so the existing root proxy can remain untouched.
- Debug STT: optional mini PC sidecar for Ops Console text visibility only.

Do not place API keys, private LAN credentials, or raw tokens in docs or checked-in env files.
