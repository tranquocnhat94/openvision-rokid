# Agent Service

Service composition and lifecycle live here.

Responsibilities:

- start/stop module services;
- create session IDs;
- route events by session;
- expose health checks;
- attach tracing and redaction;
- enforce feature flags and permissions.

The agent service keeps only app-shell responsibilities:

- `openvision_jetson/control_plane.py`
- `openvision_jetson/fastapi_app.py`
- `openvision_jetson/settings.py`
- `openvision_jetson/session_store.py`
- `openvision_jetson/event_store.py`
- `openvision_jetson/contracts.py`

Runtime implementations live in the sibling Jetson module folders, not here.

The agent service should depend on module interfaces, not old product modes.

It should keep product routes, lab fallbacks, and debug visibility separate so v2 does not grow hidden branches.
