# Codex Prompt — Review Guardrail

Use this after any Codex-generated patch.

```text
Review the current diff against AGENTS.md and docs/openvision.

Flag any issue where the patch:
1. turns Rokid into a heavy app
2. makes Jetson less central as realtime brain
3. sends too much data to cloud
4. creates skill-specific HUD rendering
5. creates direct cloud calls outside cloud_gateway
6. bypasses perception_graph
7. adds feature endpoints without skill manifest
8. lacks metrics/logs
9. touches unrelated V1/Ring/Yolo/security runtime
10. claims hardware success without real logs

Return:
- must-fix before merge
- safe-to-merge but improve later
- recommended next PR
```
