# RokidVideoStream Legacy Reference

This folder contains the legacy RV101 Android app.

The active V2 glasses contract is documented in:

- `OpenVision rokid/glasses/`
- `docs/openvision/`

Use this folder only as reference until the clean V2 Android module is built. Do not add product features here unless the user explicitly asks.

Lessons still worth preserving:

- glasses should stay thin;
- use hardware H.264 encode for video;
- keep microphone capture and transport lightweight;
- keep HUD compact and see-through first;
- avoid old mode screens and phone-like UI;
- push perception, tracking, skill routing, cloud decisions, and HUD authority to Jetson.

If code is ported from here into V2, rebuild it under the V2 ownership model and verify it with real logs before claiming device success.
