# iPhone Web Harness

The iPhone/browser harness accelerates backend, cloud, skill, and HUD iteration.

It should:

- use HTTPS or another secure origin;
- require a direct tap before camera/mic capture;
- use `playsinline`;
- send media through WebRTC;
- render the same HUD scene model as RV101;
- show only minimal phone-side status;
- expose detailed debugging through Jetson Ops Console.

It must not:

- become a separate product;
- add simulator-only modes;
- bypass Jetson skill/runtime ownership;
- render custom product HUD outside the shared HUD scene protocol.

Every simulator decision should remain portable to the RV101 thin-client contract.
