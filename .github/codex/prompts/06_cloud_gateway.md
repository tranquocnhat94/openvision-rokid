# Codex Prompt — Phase 5 Cloud Escalation Gateway

```text
Read AGENTS.md and docs/openvision/09_CLOUD_ESCALATION_GATEWAY.md.

Goal: centralize all cloud AI calls through a cloud escalation gateway.

Tasks:
1. Find current cloud/API call sites.
2. Design cloud_gateway interface.
3. Define EvidenceBundle and CloudResult models.
4. Add privacy and budget checks.
5. Add timeout/fallback behavior.
6. Add structured response validation.
7. Refactor one simple skill or placeholder to request cloud via gateway instead of direct call.

Rules:
- Do not scatter cloud calls.
- Do not send full video stream.
- Do not commit keys.
- Do not enable cloud for sensitive content without privacy gate.

Tests:
- evidence bundle serialization
- privacy blocked path
- cloud timeout fallback with mock

Output:
- changed files
- call sites found
- gateway API
- tests run
- next PR
```
