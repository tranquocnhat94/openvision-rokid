# rokidjetson Legacy Reference

This folder is legacy/reference material for the old Jetson backend direction.

The active product foundation is:

- `OpenVision rokid/`
- `docs/openvision/`

Do not expand this folder as the V2 product path unless the user explicitly asks. Use it only to recover lessons, logs, protocol details, or implementation ideas that can be rebuilt cleanly inside OpenVision V2.

Important interpretation rules:

- old mode logic becomes typed internal capabilities only if it is rebuilt through V2 skill manifests;
- direct cloud calls must move behind a cloud gateway/evidence-bundle path;
- HUD output must move through shared HUD scene protocol;
- Ring / YOLO26 security runtime must not be touched or reused directly;
- failed or obsolete experiments should be removed or quarantined, not carried into V2.
