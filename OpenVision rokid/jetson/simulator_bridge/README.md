# Simulator Bridge

The simulator bridge connects the iPhone web client to the same Jetson session model used by RV101.

Source package:

- `openvision_jetson/simulator_bridge.py`

Responsibilities:

- WebRTC offer/answer;
- audio/video ingest;
- websocket/control;
- HUD scene delivery;
- simulator metrics;
- session trace integration.

No simulator-only product path is allowed.
