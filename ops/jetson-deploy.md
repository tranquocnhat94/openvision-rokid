# Jetson Deploy Notes

Target Jetson:

- host: `JETSON_LAN_IP`
- user: `JETSON_USER`
- deploy path: `/opt/openvision-rokid`

Do not write the Jetson password or OpenAI key into this repo.

## Deploy

```bash
cd /path/to/openvision-rokid
JETSON_HOST=JETSON_LAN_IP JETSON_USER=JETSON_USER bash scripts/deploy_to_jetson.sh
```

The deploy script preserves Jetson-local runtime state:

- `.venv/`
- `runtime/`
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

Default mode is `disabled` so v2 does not accidentally touch the existing Ring / security YOLO26 runtime. For a separate Rokid-specific detector process, set:

```bash
OPENVISION_YOLO26_MODE=external_snapshot
```

The external runtime posts normalized detections into v2, and v2 updates the perception graph plus HUD-facing skill layer. Do not point v2 at the Ring runtime process.

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

After those gates pass, stop/delete only the known v1 Rokid service/files. Do not stop Ring / YOLO26 security services. Use `docs/openvision/16_ACCEPTANCE_TESTS.md`, `the current project status docs`, and a fresh Jetson log as the retirement gate.
