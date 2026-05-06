# Backend MVP Legacy Reference

This folder is the old backend MVP. It is not the active V2 product path.

The active system now lives in:

- `OpenVision rokid/jetson/`
- `docs/openvision/`

Use this folder only as reference for:

- lessons learned from media ingest;
- older OpenAI Realtime experiments;
- previous skill/tool call attempts;
- dashboard/UI patterns worth rebuilding cleanly;
- historical tests and bugs.

Do not add new product behavior here unless the user explicitly asks.

When porting an idea into V2:

1. identify the V2 owner (`media_gateway`, `perception`, `skills`, `hud_authority`, `realtime_agent`, `simulator_bridge`, or `lab_fallbacks`);
2. express behavior through schemas and typed skills;
3. avoid direct cloud calls outside the gateway;
4. avoid custom HUD outside HUD scene protocol;
5. keep Debug STT sidecar-only;
6. do not touch Ring / YOLO26 security runtime.
