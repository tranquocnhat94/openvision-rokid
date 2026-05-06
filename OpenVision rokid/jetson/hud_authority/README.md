# HUD Authority

HUD authority converts runtime state into compact HUD scene JSON.

Source package:

- `openvision_jetson/hud.py`
- `openvision_jetson/hud_authority.py`
- `openvision_jetson/display_command_gateway.py`

Responsibilities:

- answer strip;
- edge chips;
- thumbnail strip;
- target reticle;
- alert priority;
- TTL and scene expiration;
- client acknowledgement tracking;
- RV101 safe-zone constraints.
- typed DisplayCommand validation and HUD-scene adaptation.

The glasses render HUD scenes. They do not invent product state.
