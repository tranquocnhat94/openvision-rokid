# Jetson Deploy Notes

Target Jetson:

- host: `JETSON_LAN_IP`
- user: `JETSON_USER`
- deploy path: `/home/jay/openvision-rokid-v2`

Do not write the Jetson password or OpenAI key into this repo.

## Deploy

```bash
cd "/Users/tranquocnhat/Documents/codex/rokid/OpenVision rokid"
JETSON_HOST=JETSON_LAN_IP JETSON_USER=JETSON_USER bash scripts/deploy_to_jetson.sh
```

The deploy script preserves Jetson-local runtime state:

- `.venv/`
- `runtime/`
- `ops/openvision.env`
- `ops/secrets/`

## Current v2 URLs

- LAN HTTP: `http://JETSON_LAN_IP:8765`
- Tailnet HTTPS: `https://TAILNET_HOST:8443`
- iPhone simulator: `https://TAILNET_HOST:8443/simulator/`
- API docs: `https://TAILNET_HOST:8443/ops/api`

Tailscale Serve is configured on Jetson with:

```bash
tailscale serve --bg --https 8443 8765
```

The default Tailscale HTTPS root without port is not used by v2 because it was already pointing at another local service.

## Install systemd Service On Jetson

```bash
sudo cp /home/jay/openvision-rokid-v2/ops/systemd/openvision-jetson.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now openvision-jetson
sudo systemctl status openvision-jetson --no-pager
```

The production service starts Uvicorn with `--no-access-log` so worker polling
does not flood journald. Error logs and explicit application telemetry remain
available through `journalctl` and `/api/events`.

## Secret Setup

v2 supports `OPENAI_API_KEY_FILE` so the key can stay in a Jetson-only file with restricted permissions.

```bash
cd /home/jay/openvision-rokid-v2
bash scripts/prepare_jetson_secrets.sh
bash scripts/prepare_jetson_secrets.sh --write-openai-key
sudo systemctl restart openvision-jetson
```

Expected redacted checks:

```bash
curl -s http://127.0.0.1:8765/api/settings
curl -s http://127.0.0.1:8765/api/health
```

`openai_key_present` should become `true`, and `openai_key_source` should be `file`. The API must never return the key value.

## Cloud Visual Verifier

The OpenAI Responses visual verifier is opt-in and uses the same restricted
OpenAI key source. Enable it only in Jetson-local `ops/openvision.env`:

```bash
OPENVISION_CLOUD_VERIFY_ENABLED=1
OPENVISION_CLOUD_VERIFY_MODEL=gpt-4.1-mini
OPENVISION_CLOUD_VERIFY_IMAGE_DETAIL=low
```

When enabled, captured preview refs are resolved inside Jetson to data URLs
before CloudGateway calls OpenAI. Do not expose `/api/preview/...` publicly just
for cloud verification.

## YOLO26 Adapter Setup

v2 exposes a separate adapter surface for Rokid perception snapshots:

- status: `GET /api/adapters/yolo26`
- worker status: `GET /api/adapters/yolo26/worker`
- snapshot ingress: `POST /api/adapters/yolo26/{session_id}/detections`
- stream bbox ingress: `POST /api/adapters/yolo26/{session_id}/stream`

Default mode is `disabled` so v2 does not accidentally touch the existing Ring / security YOLO26 runtime. For a separate Rokid-specific detector process, set:

```bash
OPENVISION_YOLO26_MODE=external_snapshot
```

For live iPhone/Rokid stream bbox frames from a separate OpenVision detector worker, set:

```bash
OPENVISION_YOLO26_MODE=external_stream
```

The external runtime posts normalized detections into v2, and v2 updates the perception graph plus HUD-facing skill layer. Do not point v2 at the Ring runtime process.

The product RV101 path should use the separate OpenVision DeepStream worker on
Jetson. It does not reuse or stop the Ring/security process. It creates an
OpenVision RTSP relay from RV101 H.264 samples, launches a per-session
`deepstream-app` pipeline, consumes DeepStream MQTT detection messages, and
posts normalized bbox frames back to `/api/adapters/yolo26/{session_id}/stream`.
When YOLO26 is active, the same pipeline also publishes a DeepStream OSD RTSP
output. The worker relays that annotated H.264 stream back to Jetson so Sensor
Preview can show the real DeepStream-rendered video instead of a JavaScript bbox
overlay or MJPEG workaround.

Install the DeepStream worker as an OpenVision/Rokid runtime:

```bash
sudo cp /home/jay/openvision-rokid-v2/ops/systemd/openvision-deepstream-yolo26-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Enable it from Jetson-local `ops/openvision.env`:

```bash
OPENVISION_YOLO26_MODE=external_stream
OPENVISION_DEEPSTREAM_YOLO26_WORKER_ENABLED=1
OPENVISION_DEEPSTREAM_YOLO26_SOURCE=openvision_rv101_yolo26_deepstream
OPENVISION_DEEPSTREAM_YOLO26_ENGINE_PATH=/home/jay/openvision-rokid-v2/runtime/yolo26/openvision_yolo26.engine
OPENVISION_DEEPSTREAM_YOLO26_ONNX_PATH=/home/jay/DeepStream-Yolo/yolo26s.onnx
OPENVISION_DEEPSTREAM_YOLO26_CUSTOM_LIB_PATH=/home/jay/DeepStream-Yolo/nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so
OPENVISION_DEEPSTREAM_YOLO26_LABELS_PATH=/home/jay/openvision-rokid-v2/runtime/yolo26/yolo26_labels.txt
OPENVISION_DEEPSTREAM_YOLO26_RTSP_PORT=8785
OPENVISION_DEEPSTREAM_YOLO26_ANNOTATED_RTSP_ENABLED=1
OPENVISION_DEEPSTREAM_YOLO26_ANNOTATED_RTSP_PORT=8795
OPENVISION_DEEPSTREAM_YOLO26_ANNOTATED_UDP_PORT=5600
OPENVISION_DEEPSTREAM_YOLO26_ANNOTATED_BITRATE=2500000
OPENVISION_DEEPSTREAM_YOLO26_MQTT_HOST=127.0.0.1
OPENVISION_DEEPSTREAM_YOLO26_MQTT_PORT=1884
OPENVISION_DEEPSTREAM_YOLO26_STREAM_WIDTH=800
OPENVISION_DEEPSTREAM_YOLO26_STREAM_HEIGHT=600
OPENVISION_DEEPSTREAM_YOLO26_STREAM_FPS=15
sudo systemctl enable --now openvision-deepstream-yolo26-worker
```

The service uses the normal OpenVision venv plus system GStreamer bindings via
`/usr/lib/python3/dist-packages`, because DeepStream/RTSP integration needs
NVIDIA's GStreamer Python bindings on Jetson. The generated DeepStream configs,
engine output, and status live under
`/home/jay/openvision-rokid-v2/runtime/deepstream_yolo26_openvision/`.

Build the OpenVision-specific TensorRT engine without touching Ring:

```bash
cd /home/jay/openvision-rokid-v2
OPENVISION_YOLO26_SOURCE_ONNX=/home/jay/DeepStream-Yolo/yolo26s.onnx \
  ./scripts/prepare_openvision_yolo26_engine.sh
```

The expected output is
`/home/jay/openvision-rokid-v2/runtime/yolo26/openvision_yolo26.engine`.
Do not point this script or the worker at Ring/security model paths. The older
preview-polling YOLO26 worker has been removed from the product tree; deploy
still stops and removes any previously installed
`openvision-yolo26-stream-worker.service` unit to avoid stale bbox writers.

## Face Identity Worker Setup

For named-contact reminders such as `tìm Trâm`, v2 has a separate local face
identity path instead of sharing the Ring YOLO26 runtime:

- adapter status: `GET /api/adapters/face-identity`
- worker status: `GET /api/adapters/face-identity/worker`
- stream ingress: `POST /api/adapters/face-identity/{session_id}/stream`

The worker polls active `target_finder` live-video sessions, runs OpenCV
YuNet/SFace locally, writes face crops to `runtime/crops/`, and posts face bbox
plus `identity_vector` into the perception graph. `scripts/bootstrap_jetson.sh`
installs the optional Python deps when `face_identity_requirements.txt` exists;
keep the service disabled until model files also exist:

```bash
mkdir -p /home/jay/openvision-rokid-v2/runtime/face
# place face_detection_yunet_2023mar.onnx and face_recognition_sface_2021dec.onnx here
sudo cp /home/jay/openvision-rokid-v2/ops/systemd/openvision-face-identity-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Environment:

```bash
OPENVISION_FACE_IDENTITY_MODE=external_stream
OPENVISION_FACE_WORKER_ENABLED=1
OPENVISION_FACE_WORKER_DETECTOR_MODEL=/home/jay/openvision-rokid-v2/runtime/face/face_detection_yunet_2023mar.onnx
OPENVISION_FACE_WORKER_RECOGNIZER_MODEL=/home/jay/openvision-rokid-v2/runtime/face/face_recognition_sface_2021dec.onnx
OPENVISION_FACE_WORKER_MAX_FPS=2
OPENVISION_FACE_WORKER_DETECTION_TARGET_SIZE=1280
OPENVISION_FACE_WORKER_MIN_IDENTITY_FACE_SIDE_PX=56
sudo systemctl enable --now openvision-face-identity-worker
```

`scripts/deploy_to_jetson.sh` syncs the OpenVision systemd unit files by
default and restarts the face worker when `OPENVISION_FACE_WORKER_ENABLED=1`.
For YOLO26, DeepStream is the only product worker. Deploy enables the
DeepStream worker when `OPENVISION_DEEPSTREAM_YOLO26_WORKER_ENABLED=1`, and
stops/removes the old preview-polling service if it exists from an earlier
experiment. It also terminates unmanaged OpenVision worker processes first so
there is only one worker owner: systemd. Use `OPENVISION_SYNC_SYSTEMD=0` only
for a manual service experiment.

This path is on-demand and independent: it does not stop, import, or point at
the Ring/security YOLO26 runtime.

## RV101 Recording Storage

Product review recordings should live on the Jetson NVMe SSD, not under the
repo runtime on eMMC/root. Keep the recording root separate from identity and
people DB files so video retention can be tuned without moving the whole
OpenVision runtime:

```bash
mkdir -p /mnt/ssd/openvision-rokid-v2/recordings
OPENVISION_RV101_STREAM_RECORDING=1
OPENVISION_RV101_STREAM_RECORDING_DIR=/mnt/ssd/openvision-rokid-v2/recordings
OPENVISION_RV101_STREAM_RECORD_RAW_VIDEO=1
OPENVISION_RV101_STREAM_RECORD_RAW_AUDIO=1
OPENVISION_RV101_STREAM_RECORD_PROCESSED_PREVIEW=1
OPENVISION_RV101_STREAM_RECORD_PLAYABLE_VIDEO=1
OPENVISION_FFMPEG=/usr/bin/ffmpeg
```

The backend finalizes playable `video.mp4` and `preview_annotated.mp4` files on
session close. `/recordings.html` plays those files directly from Jetson rather
than replaying MJPEG as a polling/debug stream.

## Local Contact Identity DB

`target_finder` can use a Jetson-local contact identity DB for reminders such
as `tìm Trâm trong đám đông`. The DB is user-managed and stored in the
OpenVision runtime directory:

```bash
OPENVISION_IDENTITY_DB_PATH=/home/jay/openvision-rokid-v2/runtime/identity/contacts.json
OPENVISION_IDENTITY_MIN_CONFIDENCE=0.86
OPENVISION_IDENTITY_SFACE_MIN_CONFIDENCE=0.45
OPENVISION_IDENTITY_MIN_FACE_SIDE_PX=56
```

For live SFace matching, frames below the face-size floor are reported as
`low_quality_face` instead of `no_match`, so the HUD can ask the wearer to move
closer or zoom rather than implying the contact DB failed.

Enrollment can be done through the API or CLI after a useful crop exists:

```bash
curl -X POST http://JETSON_LAN_IP:8765/api/identity/enroll \
  -H 'content-type: application/json' \
  -d '{"display_name":"Trâm","aliases":["tram"],"image_ref":"/api/crops/SESSION_ID/p1_latest.jpg"}'

python scripts/enroll_identity_sample.py \
  --name "Trâm" \
  --alias tram \
  --image /api/crops/SESSION_ID/p1_latest.jpg

python scripts/enroll_identity_sample.py \
  --name "Trâm" \
  --alias tram \
  --embedding-backend opencv_sface \
  --image /api/crops/SESSION_ID/face_f1_latest.jpg
```

Operational endpoints:

```text
GET  /api/identity/status
GET  /api/identity/contacts
POST /api/identity/enroll
POST /api/identity/match
```

## People Registry And Immich Sync

The People Registry is the metadata layer for known-person skills. It stores
names, aliases, phone/address, links, notes, and Immich person IDs in Jetson
runtime storage while keeping photos and thumbnails in Immich.

Configure Jetson-local env:

```bash
OPENVISION_PEOPLE_REGISTRY_DB_PATH=/home/jay/openvision-rokid-v2/runtime/people/people_registry.json
OPENVISION_IMMICH_BASE_URL=http://192.168.8.105:2283
OPENVISION_IMMICH_API_KEY_FILE=/home/jay/openvision-rokid-v2/ops/secrets/immich_api_key
OPENVISION_IMMICH_SYNC_TIMEOUT_S=8
```

Create an Immich API key with people read/update permissions, write only the
key value into the Jetson secrets file, then restart `openvision-jetson`.

Operational endpoints:

```text
GET  /api/people/status
GET  /api/people
POST /api/people/sync
POST /api/people/{person_id}
POST /api/people/{person_id}/sync-name
POST /api/people/{person_id}/enroll-identity
```

If Immich is not running or is not exposed on the LAN port, `/api/people/status`
still works and `/api/people/sync` reports a skipped/error state without storing
photos in OpenVision.

Snapshot `source` must identify a separate Rokid/OpenVision runtime, for example:

```text
rokid_yolo26_external
openvision_yolo26_lab
```

Sources containing Ring/security markers are rejected by the adapter.

## RV101 Media Ingest

v2 now exposes the product-shaped RV101 control/media contract:

- control websocket: `ws://JETSON_LAN_IP:8765/ws`
- video TCP: `JETSON_LAN_IP:8770`
- audio TCP: `JETSON_LAN_IP:8771`
- status: `GET /api/rv101/ingest`

The websocket `client_hello` response is `session_accept` with the active TCP ports. Video and audio use the existing `RVS1` frame envelope from the glasses app: H.264 samples on video TCP and PCM S16LE chunks on audio TCP.

## v1 Retirement Rule

Do not stop or delete v1 from Jetson until v2 has passed:

- local v2 tests;
- Jetson dependency install;
- `openvision-jetson` service starts;
- Web UI reachable at `http://JETSON_LAN_IP:8765`;
- at least one RV101 or iPhone session can be created;
- RV101 `/ws` handshake and TCP media ports are reachable;
- OpenAI key is present only in Jetson environment;
- YOLO26 adapter is either disabled or explicitly pointed at a separate Rokid-specific runtime/snapshot source;
- no Ring / YOLO26 security runtime is affected.

After those gates pass, stop/delete only the known v1 Rokid service/files. Do not stop Ring / YOLO26 security services. Use `docs/openvision/16_ACCEPTANCE_TESTS.md`, `ROKID_CURRENT_STATE.md`, and a fresh Jetson log as the retirement gate.
