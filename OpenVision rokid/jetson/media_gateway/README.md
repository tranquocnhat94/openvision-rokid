# Media Gateway

Media gateway accepts client media and control channels.

Source package:

- `openvision_jetson/media_gateway.py`
- `openvision_jetson/media_command_gateway.py`
- `openvision_jetson/rv101_tcp_ingest.py`
- `openvision_jetson/preview_store.py`

Inputs:

- RV101 H.264 TCP video;
- RV101 PCM TCP audio;
- RV101 websocket/control;
- iPhone WebRTC audio/video;
- iPhone websocket/control.

Outputs:

- typed MediaCommand / MediaEvent status;
- frame bus events;
- audio chunk events;
- client transport metrics;
- session lifecycle events.

This module does not decide user intent and does not execute skills.
Camera activation must enter through `MediaCommandGateway` so snapshot,
burst, and live-video requests carry a session, skill, reason, timeout,
resolution/FPS budget, auto-stop policy, and scorecard event.
