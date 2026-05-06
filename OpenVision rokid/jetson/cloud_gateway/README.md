# Cloud Gateway

Cloud Gateway owns typed cloud escalation for OpenVision Rokid V2.

Source package:

- `openvision_jetson/cloud_gateway.py`

Responsibilities:

- build `cloud_evidence_bundle.v1`;
- enforce privacy and budget gates;
- call the configured cloud verifier provider;
- validate `cloud_result.v1`;
- validate `needs_cloud` skill/tool payloads before they leave Jetson;
- log latency and failure reasons.

Skills may request escalation through this module, but they must not call cloud APIs directly.
JetsonToolServer rejects any `needs_cloud` result that does not carry a valid
`cloud_evidence_bundle`, gateway response, and `cloud_result`.

OpenAI Responses visual verification is available as an opt-in provider:

```bash
OPENVISION_CLOUD_VERIFY_ENABLED=1
OPENVISION_CLOUD_VERIFY_MODEL=gpt-4.1-mini
OPENVISION_CLOUD_VERIFY_IMAGE_DETAIL=low
```

When enabled, Jetson resolves local preview refs into data URLs before calling
OpenAI, so the private `/api/preview/...` endpoint does not need to be exposed
publicly.
