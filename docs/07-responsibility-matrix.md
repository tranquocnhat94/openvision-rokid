# Responsibility Matrix

This matrix keeps v2 from drifting back into a mixed prototype.

## Runtime Ownership

| Area | RV101 glasses | iPhone simulator | Jetson | OpenAI / cloud AI | Mini PC / helpers | Ops Console |
| --- | --- | --- | --- | --- | --- | --- |
| Camera capture | Owner | Debug substitute | Receives | No | No | Observes |
| Mic capture | Owner | Debug substitute | Receives | No | No | Observes |
| Hardware H.264 | Owner | No | Ingests | No | No | Observes |
| WebRTC | No | Owner | Receives | No | No | Observes |
| Session state | Thin ID only | Thin ID only | Owner | Uses context | No | Observes |
| Voice understanding | No | No | Streams audio/tools | Owner | No | Observes |
| Debug transcript | No | No | Sends completed turn | No | PhoWhisper sidecar | Displays only |
| Intent planning | No | No | Exposes tools | Owner | No | Observes |
| Skill execution | No | No | Owner | Chooses tools | Optional delegate | Observes |
| Internal runtime modes | No | No | Owner | Requests via tools | Optional delegate | Observes |
| YOLO26 adapter | No | No | Separate Rokid owner | No | No | Observes |
| Ring/security runtime | No | No | Protected external system | No | No | Do not mutate |
| Perception graph | No | No | Owner | Reads summaries/evidence | No | Observes |
| Cloud visual reasoning | No | No | Packages evidence | Owner | Optional | Observes |
| Selected target | Renders only | Renders only | Owner | Reasons over evidence | No | Observes |
| HUD scene | Renders only | Renders only | Owner | Suggests content via tools | No | Mirrors/debugs |
| Settings | Minimal connection only | Minimal connection only | Owner | No | Service endpoints only | Owner UI |
| Secrets | No | No | Secure runtime only | Uses API | Secure runtime only | Redacted status only |

## Product Boundaries

### RV101 Glasses

Must stay thin:

- capture;
- encode;
- transport;
- HUD rendering;
- local diagnostics.

Must not own:

- old mode selection;
- skill planning;
- target tracking;
- cloud decisions;
- rich settings pages.

### iPhone Simulator

Must mirror the glasses contract:

- tap-to-start media;
- WebRTC transport;
- same HUD scene model;
- same Jetson session trace.

Must not become:

- a separate mobile app product;
- an alternate skill router;
- a place for hidden debug-only intent logic.

### Jetson

Must be the trusted executor:

- media gateway;
- Realtime bridge;
- skill registry;
- perception graph;
- selected target;
- local adapters;
- HUD authority;
- debug/export.

### OpenAI / Cloud AI

Must be the high-level brain:

- Vietnamese voice understanding;
- conversation;
- tool selection;
- visual reasoning when Jetson evidence is insufficient;
- response shaping.

It should not directly mutate Jetson state except through typed tool calls.

### Mini PC / Pi5 / Helpers

Must be helper services behind Jetson:

- Debug STT sidecar;
- future auxiliary local services;
- future lightweight home/edge support.

They should not bypass Jetson ownership or become separate product brains.

### Ops Console

Must be an operator/debug surface:

- settings;
- traces;
- session inspection;
- skill dry-run;
- perception inspection;
- sensor preview;
- Debug STT visibility;
- HUD mirror;
- iPhone simulator launch.

It must not define product behavior that RV101 cannot use.

### OpenClaw Bridge

Future OpenClaw-style actions should be separated behind explicit tools:

- document tasks;
- mail tasks;
- posting/workflow tasks;
- external machine cooperation.

This bridge should require permissions and audit logs. It should not be mixed silently into the core vision/perception skill layer.
