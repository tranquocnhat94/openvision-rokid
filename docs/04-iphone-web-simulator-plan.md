# iPhone Web Simulator Plan

The iPhone simulator exists to accelerate Jetson/cloud/HUD development before every loop is tested on RV101.

It is a thin debug client, not a new product.

## Requirements

- Run from a secure origin: HTTPS, local trusted cert, Tailscale HTTPS, or another secure tunnel.
- Start camera/mic capture from a direct user tap.
- Use inline preview with `playsinline`.
- Send audio/video to Jetson through WebRTC.
- Use the same control/result/HUD contract as the glasses.
- Expose metrics to the Ops Console.
- Keep product behavior portable to RV101.

## Session Flow

```text
Open simulator URL on iPhone
  -> tap Start
  -> browser requests camera/mic
  -> preview starts inline
  -> WebRTC offer/answer with Jetson
  -> websocket joins same Jetson session model
  -> Jetson opens Realtime session
  -> OpenAI routes tools
  -> Jetson executes skill
  -> Jetson emits HUD scene JSON
  -> iPhone renders the same HUD scene model
```

## UI Shape

The simulator screen should stay close to the glasses experience:

- live camera preview;
- transparent lower answer strip;
- small edge chips;
- small thumbnails for selected/search results;
- minimal connection state;
- no full debug console on the phone screen.

Debug details belong in the desktop Ops Console.

## What It Can Prove

- Jetson service and session model.
- iPhone camera/mic permissions and media flow.
- WebRTC upstream into Jetson.
- OpenAI Realtime connection and tool calls.
- Skill execution and HUD scene output.
- Debug STT completed sentence for the same turn.
- Sensor preview and HUD mirror.

## What It Cannot Prove

- RV101 microphone source stability.
- RV101 hardware H.264 behavior.
- Glasses thermal/CPU/battery load.
- Real optical HUD comfort.
- Final RV101 product readiness.

## Anti-Drift Rules

- No simulator-only mode picker.
- No simulator-only skill routing.
- No hidden local interpretation before Jetson/OpenAI.
- No phone-style feature screens.
- No behavior that cannot map to HUD scene JSON.
- All simulator behavior must be replayable as a Jetson session trace.
