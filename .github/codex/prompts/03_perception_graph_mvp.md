# Codex Prompt — Phase 2 Perception Graph MVP

```text
Read AGENTS.md and docs/openvision/07_PERCEPTION_GRAPH.md.

Goal: implement the smallest perception graph MVP.

Tasks:
1. Define a PerceptionGraph data model.
2. Define object/text/risk/metrics structures.
3. Add serialization to JSON.
4. Connect existing detector output if available; otherwise add a placeholder adapter that can be wired later.
5. Compute coarse zones from bounding boxes.
6. Add a log or debug endpoint that emits current graph snapshot.

Rules:
- Skills must consume the graph, not detector internals.
- Do not modify old security/Ring/Yolo runtime if present.
- Do not add cloud calls.
- Keep PR scoped to graph model + adapter.

Tests:
- unit test zone computation
- unit test graph serialization
- run available build/import checks

Output:
- changed files
- graph JSON example
- tests run
- next PR
```
