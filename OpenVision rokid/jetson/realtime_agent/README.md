# Realtime Agent

The Realtime agent is the current live cloud AI bridge for conversation/tool interaction.

Source package:

- `openvision_jetson/realtime_events.py`
- `openvision_jetson/realtime_manager.py`

Responsibilities:

- create/update live cloud AI sessions;
- send audio according to active turn policy;
- expose typed Jetson skills as tools;
- handle function calls and function outputs;
- enforce session, privacy, cloud budget, and timeout policy before tool execution;
- reconnect safely;
- record latency and errors;
- keep secrets out of traces.

Architecture discipline:

- Jetson remains the skill runtime and HUD authority;
- cloud/live AI can choose or reason, but must act through typed tools/results;
- direct cloud calls should move behind the cloud gateway/evidence-bundle path as that layer hardens;
- this module must not grow a parallel OpenAI transcription route.

If the operator needs to see what was spoken, use the Debug STT sidecar and keep it outside command routing.
