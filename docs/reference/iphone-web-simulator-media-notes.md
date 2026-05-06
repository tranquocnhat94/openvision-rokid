# iPhone Web Simulator Media Notes

Updated: 2026-04-23

This note captures the authoritative browser constraints for using an iPhone as a thin Rokid simulator client against Jetson.

## Why this matters

The browser simulator is only useful if iPhone Safari can act like a thin `camera + mic + HUD` terminal:

- request camera and microphone permissions reliably
- keep the preview inline instead of forcing awkward fullscreen behavior
- stream media into the same Jetson session model as the real glasses

Safari is stricter than desktop browsers, so the simulator must follow Safari/WebKit rules exactly.

## Authoritative constraints

### 1. `getUserMedia()` requires a secure context

`navigator.mediaDevices.getUserMedia()` is only available in secure contexts.

Practical consequence:

- do not expect `http://JETSON_LAN_IP:9080/simulator` to work for iPhone camera/mic
- always use the HTTPS simulator URL exposed through Tailscale Serve

Current correct URL shape:

- `https://<jetson-tailnet-name>.ts.net/simulator`

References:

- MDN `getUserMedia()` secure-context requirement
- WebKit `A Closer Look Into WebRTC` HTTPS origin requirement
- Tailscale Serve HTTPS requirement

## 2. Safari prompts when `getUserMedia()` is called

Safari presents the permission prompt when `getUserMedia()` is invoked. The website should trigger capture in a user-driven flow and should not bury capture startup behind avoidable async work.

Practical consequence for this project:

- the simulator should request media from the `Start simulator` tap immediately
- do not wait for websocket/session round-trips first

The intended flow is:

1. user taps `Start simulator`
2. browser immediately calls `getUserMedia(...)`
3. browser attaches the stream to an inline local preview with `playsinline`
4. browser opens the Jetson control websocket
5. browser negotiates a `RTCPeerConnection` offer/answer with Jetson and sends the real camera/mic tracks over WebRTC

References:

- WebKit `A Closer Look Into WebRTC`
- Apple Web Audio docs on explicit user action

## 3. iPhone video preview should stay inline

Safari on iPhone expects inline playback to be explicitly allowed.

Practical consequence:

- the local preview element should include `playsinline`
- the script should also set `video.playsInline = true`
- the preview should be `muted` and `autoplay` because it is just the local camera monitor for upload, not a user-facing media player

Without inline playback, iPhone behavior can drift toward full-screen video or frozen preview behavior.

References:

- Apple `Delivering Video Content for Safari`
- WebKit bug report documenting that `playsinline` can be required even for hidden `getUserMedia()` previews on iOS

## 4. Prefer WebRTC for live upstream media

For an iPhone-backed live simulator, the browser-native path is:

- `navigator.mediaDevices.getUserMedia(...)`
- `RTCPeerConnection`
- `addTrack(...)`
- `createOffer()` / `setLocalDescription()` / `setRemoteDescription()`

This matches the official WebKit WebRTC guidance and the wider WebRTC sample ecosystem more closely than a custom path such as:

- draw camera frames into a canvas
- JPEG-encode them in JavaScript
- resample PCM in Web Audio
- upload both over a generic websocket

That custom path can exist as a debug fallback, but it should not be the main transport for iPhone Safari.

References:

- WebKit `A Closer Look Into WebRTC`
- WebRTC samples

## 5. One tab at a time can own capture

WebKit notes that only one Safari tab can capture video or audio at a time. When another tab gains access, existing tracks can be silenced and send mute events.

Practical consequence:

- if capture suddenly goes black/silent on iPhone, check whether another Safari tab or app has taken camera/mic access
- simulator UI should treat `mute`/`unmute` or silence transitions as recoverable device-state events, not always backend failure

Reference:

- WebKit `A Closer Look Into WebRTC`

## Current implementation choices

The browser simulator should now follow this order:

1. `tap`
2. `getUserMedia`
3. attach inline local preview
4. connect websocket/session for HUD/control
5. `RTCPeerConnection` offer/answer with Jetson
6. stream real camera + mic tracks upstream over WebRTC
7. keep HUD, skill trace, and mode/result traffic on the websocket plane

This is intentionally closer to the real glasses architecture:

- browser/iPhone remains thin
- Jetson remains session owner, voice/skill owner, HUD authority

## Non-goals

- do not move AI, routing, or perception into the browser simulator
- do not rely on browser-side heavy CV or on-device skill logic
- do not optimize for generic desktop browser demo behavior at the expense of Safari correctness

## References

- [MDN: MediaDevices.getUserMedia()](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)
- [WebKit: A Closer Look Into WebRTC](https://webkit.org/blog/7763/a-closer-look-into-webrtc/)
- [Apple: Delivering Video Content for Safari](https://developer.apple.com/documentation/webkit/delivering-video-content-for-safari)
- [WebKit: MediaRecorder API](https://webkit.org/blog/11353/mediarecorder-api/)
- [WebRTC samples](https://webrtc.github.io/samples/)
- [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve)
