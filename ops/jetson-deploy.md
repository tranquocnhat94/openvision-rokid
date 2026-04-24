# Jetson Deploy Notes

These notes describe the intended Jetson deployment shape. Replace the example host, user, and path with values from your own device.

## Target

- host: `<your-jetson-host-or-ip>`
- user: `jetson`
- deploy path: `/opt/openvision-rokid`

Never write Jetson passwords, OpenAI keys, SSH keys, or private service tokens into this repository.

## Deploy

```bash
JETSON_HOST=<your-jetson-host-or-ip> \
JETSON_USER=jetson \
JETSON_PATH=/opt/openvision-rokid \
bash scripts/deploy_to_jetson.sh
```

The deploy script preserves Jetson-local runtime state:

- `.venv/`
- `runtime/`
- `ops/secrets/`

## Example URLs

- LAN HTTP: `http://<your-jetson-host-or-ip>:8765`
- Optional HTTPS/tunnel endpoint: `https://<your-secure-hostname>:8443`
- iPhone simulator: `https://<your-secure-hostname>:8443/simulator/`
- API docs: `https://<your-secure-hostname>:8443/ops/api`

## Install systemd Service On Jetson

```bash
sudo cp /opt/openvision-rokid/ops/systemd/openvision-jetson.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now openvision-jetson
sudo systemctl status openvision-jetson --no-pager
```

## Secret Setup

v2 supports `OPENAI_API_KEY_FILE` so the key can stay in a Jetson-only file with restricted permissions.

```bash
cd /opt/openvision-rokid
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

## YOLO26 Adapter Setup

v2 exposes a separate adapter surface for Rokid perception snapshots:

- status: `GET /api/adapters/yolo26`
- snapshot ingress: `POST /api/adapters/yolo26/{session_id}/detections`

Default mode is `disabled`. For a separate Rokid-specific detector process, set:

```bash
OPENVISION_YOLO26_MODE=external_snapshot
```

The external runtime posts normalized detections into v2, and v2 updates the perception graph plus HUD-facing skill layer.

## RV101 Media Ingest

v2 exposes the RV101 control/media contract:

- control websocket: `ws://<your-jetson-host-or-ip>:8765/ws`
- video TCP: `<your-jetson-host-or-ip>:8770`
- audio TCP: `<your-jetson-host-or-ip>:8771`
- status: `GET /api/rv101/ingest`

The websocket `client_hello` response is `session_accept` with the active TCP ports. Video and audio use the `RVS1` frame envelope: H.264 samples on video TCP and PCM S16LE chunks on audio TCP.
