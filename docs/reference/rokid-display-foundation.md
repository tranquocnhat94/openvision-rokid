# Rokid Display Foundation

Updated: 2026-04-22

## Why this doc exists

This file is the project's display foundation for future Rokid + Jetson work.

It exists to answer one recurring question clearly:

- what the Rokid display actually is
- what it can technically show
- what it should show for a good HUD experience
- how that should shape this repo's architecture and UI decisions

This is not a generic AR design note.

This is the display policy for the current project direction:

- glasses = thin sensor + transport + HUD terminal
- Jetson = perception + voice + routing + HUD authority

## Scope

This document is about the display behavior and HUD design constraints of the Rokid glasses family that matters to this repo.

It is especially relevant to:

- `RokidVideoStream/app/src/main/java/com/example/cxrservicedemo/videostream/VideoStreamActivity.kt`
- `rokidjetson/backend_mvp/app/main.py`
- `rokidjetson/backend_mvp/app/static/dashboard.js`
- `docs/reference/hud-scene-protocol.md`

## Target device for this repo

For the current project, the working assumption should be:

- target device family = `Rokid Glasses`
- confirmed user device model = `RV101`
- display class = on-glasses Android runtime with green monochrome HUD display
- not `Rokid Max / Max 2 / Air / Joy / Spatial`
- not `Rokid AI Glasses Style` display-free variant

Why this is the safest current assumption:

- the user described a vertical Android-like display that still renders as green HUD
- the project runs a native app directly on the glasses, including camera, mic, and touchpad-style input handling
- the app manifest uses Rokid glass adaptation metadata:
  - `design_width_in_dp = 640`
  - `design_height_in_dp = 360`
- the current glass app handles Rokid-style `KeyEvent` input:
  - `DPAD_LEFT`
  - `DPAD_RIGHT`
  - `DPAD_CENTER`
  - `ENTER`
  - `TV`
  - `BACK`

Relevant local files:

- [AndroidManifest.xml](RokidVideoStream/app/src/main/AndroidManifest.xml)
- [VideoStreamActivity.kt](RokidVideoStream/app/src/main/java/com/example/cxrservicedemo/videostream/VideoStreamActivity.kt)

Important nuance:

- the most detailed public developer docs we have are from the older `Rokid Glass / Glass 2` documentation branch
- the active product direction in this repo is `Rokid Glasses`
- therefore those older docs should be used as `display/input principle references`, not assumed to be a perfect one-to-one runtime spec for every newer device detail

Future rule:

- when a source is clearly about `Rokid Max` or another non-HUD product line, do not apply it to this project
- when a source is clearly about older `Glass 2`, use it only if it still matches the behavior of the current `Rokid Glasses` family and real device observations

## Source confidence ladder

Use this order when making future display decisions.

### 1. Highest confidence: official Rokid hardware and developer docs

- Rokid official developer docs entry:
  - [Rokid System Solution](https://rokidglass.github.io/glass2-docs/en/)
- Official older UI guideline PDF:
  - [Glass_OS_Guideline.pdf](https://rokidglass.github.io/glass2-docs/zh/5-design/files/Glass_OS_Guideline.pdf)
- Official product page:
  - [Rokid Glasses product page](https://global.rokid.com/products/rokid-glasses)
- Official product blog post:
  - [Rokid Glasses are lightweight AR smart glasses with Micro-LED displays](https://global.rokid.com/blogs/news/rokid-glasses-are-lightweight-ar-smart-glasses-with-micro-led-displays-and-a-499-price-tag)

### 2. Medium confidence: current repo behavior and real device logs

- local HUD protocol:
  - [hud-scene-protocol.md](docs/reference/hud-scene-protocol.md)
- current glass UI notes:
  - [official-glass-ui-notes.md](docs/reference/official-glass-ui-notes.md)
- current display heuristics:
  - [display-experience-playbook.md](docs/reference/display-experience-playbook.md)

### 3. Lower confidence but still useful: community implementation notes

- Tencent Cloud community article:
  - [From zero to one: drawing a remote collaboration system on Rokid Glasses](https://cloud.tencent.com/developer/article/2601113)

Use community sources for practical hints, not as the final authority.

## What the display most likely is

The right mental model is:

- the glasses are Android-capable
- the display is still a monochrome green optical HUD
- therefore "can render a normal Android app" is not the same as "should behave like a phone"

### What is confirmed by official sources

From the official Rokid 2025 product materials:

- the glasses use dual monochrome green Micro LED displays
- the optics use a diffractive optical waveguide
- text size and brightness are adjustable
- the hardware can show teleprompter, translation, notes, navigation, and other glanceable overlays

From the official older Rokid developer guideline:

- the UI system is meant for glass-style HUD interaction, not phone-style screens
- the design reference canvas is `1280 x 720 px`
- the developer logical size is `640 x 360 dp`
- `1 dp = 2 px`
- interaction is built around head control and simple directional focus rather than dense screen touch behavior

### Important official mismatch

There is an official mismatch in current hardware spec pages:

- the official blog page says `480 x 398` per eye and `23 deg FOV`
- the current product page says `30 deg FOV`

This means future HUD layout should be designed conservatively.

Policy for this repo:

- assume the readable and comfortable HUD field is smaller than the theoretical maximum
- do not pack critical UI into edge-most coordinates
- optimize for glanceability under a narrower effective FOV

## What the display can do vs what we should do

### What it can do

Technically, the glasses can:

- run Android software
- show full-screen or near-full-screen screens
- show media and video-like content
- render ordinary app layouts

### What we should do

For this project, we should treat the glasses as:

- a transparent HUD
- a low-clutter guidance surface
- a short-text and cue-first display
- a receiver for Jetson-owned scene decisions

That means:

- no phone-style full-screen screens in the normal runtime flow
- no dense dashboards on-glass
- no permanent camera preview on-glass for the AI stream use case
- no "feature mode pages" as the primary product UX

The app can still host Android views, but the UX should behave like HUD cards, chips, strips, and markers.

## Core design rules from official guidance

These are the stable rules future topics should keep.

### 1. Rokid is not a phone

Do not treat the display like a portrait Android phone screen.

The correct base model is:

- transparent optics
- constrained readable area
- glance-first interaction
- minimal occlusion of the real world

### 2. Keep the center mostly clear

The center is the most expensive visual territory.

Use it for:

- temporary target markers
- short-lived alignment cues
- critical alerts only when necessary

Do not use it for:

- long answers
- persistent cards
- debug panels
- image-heavy galleries

### 3. Lower-safe-zone is the main answer area

The answer strip belongs in the lower safe zone.

This aligns with:

- official Rokid guidance patterns
- real-world comfort for see-through reading
- the current project direction

Use the lower area for:

- short assistant answers
- short status text
- live caption when it is the current task

### 4. Edge chips beat large cards

Use top or upper-edge chips for:

- task label
- mic state
- concise system state

Do not spend a whole card on state that can fit inside a chip.

### 5. Gallery must stay tiny

Gallery is useful for candidate comparison, but it is not a browsing surface.

On-glass guidance:

- maximum 2 candidate tiles in normal runtime
- each tile is a cue, not a content container
- label + tiny evidence thumbnail is enough

If more than 2 candidates exist:

- show the top 2 on-glass
- keep the longer list in Jetson dashboard or voice explanation

### 6. Marker is semantic, not decorative

A target marker should answer:

- what object the user should look at
- roughly where it is
- whether it is the selected or primary candidate

It should not become a busy reticle system.

### 7. Monochrome-first is the safest policy

The current official and community evidence strongly suggests that green-first design is the safest assumption.

For this repo:

- do not rely on rich full-color semantics on-glass
- design icons, markers, and thumbnails so they still work after green-only conversion
- prefer contrast hierarchy over color hierarchy

### 8. Motion must support reading, not decoration

Animation on HUD should:

- clarify state transition
- reduce surprise
- help eye tracking

Animation should not:

- float continuously for decoration
- bounce large panels into view
- shift reading targets unnecessarily

### 9. Respect logical viewport design

The official developer guidance gives a logical design frame:

- `640 x 360 dp`

That should be treated as the design coordinate space for HUD logic, even if the Android activity container itself is different.

### 10. Head control matters

The old official guideline treats head-controlled focus and directional interaction as first-class.

Implication for our project:

- HUD zones should behave like stable anchors
- layout should not assume precision tapping in many locations
- directional cues should be easy to parse with a brief glance

## Practical conclusions for this repo

### Current architecture direction is correct

The current direction remains the best one:

- glasses capture camera and mic
- glasses transport data to Jetson
- Jetson decides the scene
- glasses render only a thin HUD

This matches the display reality better than any phone-style architecture.

### Current project UI pattern is directionally right

The current combination is good:

- lower answer strip
- upper-right mini gallery
- center marker when needed

That fits the official Rokid display logic much better than:

- full-screen result pages
- normal Android settings-style screens
- dense inspector overlays

### The current glass renderer is still only partially mature

Today the project is not fully declarative end to end.

Current state:

- Jetson already behaves like scene authority
- the glasses renderer still maps known component kinds to fixed view slots
- the dashboard now mirrors the scene visually for debugging

This is acceptable for the current phase, but it is not the final form.

## Current repo mapping

### Jetson scene authority

Jetson constructs HUD scenes in:

- [main.py](rokidjetson/backend_mvp/app/main.py)

Relevant functions:

- `make_hud_scene(...)`
- `make_target_search_hud_scene(...)`
- `queue_target_search_hud_scene(...)`

Jetson is the correct place to decide:

- task chips
- answer strip text
- candidate gallery items
- direction hint
- target marker

### Glasses-side HUD renderer

The current renderer lives in:

- [VideoStreamActivity.kt](RokidVideoStream/app/src/main/java/com/example/cxrservicedemo/videostream/VideoStreamActivity.kt)

Relevant behavior:

- `renderHud(...)`
- `renderTargetGallery()`
- `renderTargetMarker()`
- sticky HUD fallback
- speech-state fallback when no meaningful scene is active

Important limitation:

- the renderer is still component-aware and slot-based
- it is not yet a generic zone-driven layout engine

### Dashboard preview and diagnostics

Jetson dashboard now includes a HUD mirror in:

- [dashboard.js](rokidjetson/backend_mvp/app/static/dashboard.js)

This is useful because it gives a near-real-time scene preview without wearing the glasses.

Use it to debug:

- scene component composition
- gallery size overflow
- marker coordinates
- scene vs speech-state fallback

## Concrete policy for future UI work

Future topics should follow these project policies.

### RokidViewportPolicy

We should add and keep a single logical viewport policy for the glasses app:

- design against a HUD coordinate system close to `640 x 360 dp`
- keep a center exclusion region
- define stable safe zones for top chips, lower strip, mini gallery, and marker clamp bounds

Do not let each view compute its own ad hoc geometry independently.

### RokidScenePolicy

Jetson should remain the owner of scene semantics.

The glasses should only decide:

- tolerant rendering
- visibility fallback
- safe clamping
- local caching for resilience

The glasses should not decide product-level mode logic.

### RokidChromaPolicy

All on-glass display assets should be designed to survive green-only output.

That includes:

- icons
- markers
- direction arrows
- candidate thumbnails

Recommended rule:

- preview thumbnails should be mono or high-contrast before they reach the glasses

### RokidThumbnailPolicy

Candidate thumbnails are useful, but only if they remain legible on the display.

Recommended rules:

- crop for head or upper torso, not full scene
- increase contrast
- prefer green-first or monochrome preprocessing
- keep dimensions small and consistent
- treat thumbnails as evidence cues, not photo content

### RokidLayerPolicy

The layer order should stay simple and predictable:

1. base transparent world view
2. center marker if active
3. upper utility chips and mini gallery
4. lower answer strip
5. developer overlay only when explicitly enabled

If two layers compete, the lower answer strip and target marker should win over debug content.

## Recommended next implementation steps

These are the highest-value display upgrades still ahead.

### 1. Introduce a true viewport policy object on the glasses

Add one shared layout policy for:

- safe zones
- marker clamp bounds
- center exclusion region
- gallery maximum count
- responsive text sizing

### 2. Move toward a more zone-driven renderer

Keep known components, but reduce hard-coded per-widget assumptions.

Goal:

- Jetson says what scene exists
- glasses decide how to place it inside a stable zone policy

### 3. Convert candidate thumbnails to display-native preprocessing

This is one of the most important unfinished display optimizations.

Recommended direction:

- preprocess on Jetson
- emit small, high-contrast, display-friendly thumbnails
- avoid raw colorful JPEG assumptions

### 4. Add display validation profiles

Maintain profile values for:

- indoor
- outdoor bright light
- small-text stress case
- target-search stress case

Because emulator quality is not enough.

### 5. Keep dashboard mirror as the desktop truth source

The dashboard mirror should remain the fastest way to validate:

- scene composition
- layer conflicts
- gallery truncation
- marker placement

But device testing still decides final UX quality.

## Validation checklist for future display changes

A display change is not done until all of these are true.

### Layout and readability

- the center stays mostly clear during normal operation
- answer text remains readable in the lower safe zone
- no important text is forced into the extreme edges
- gallery does not crowd the answer strip

### Semantics

- target marker clearly identifies the selected candidate
- scene text is short and task-specific
- speech-state fallback does not override a meaningful scene

### Layering

- no unintended overlap between gallery, answer strip, and marker
- developer overlay never breaks the user flow when disabled
- sticky HUD does not persist stale live-caption content

### Device suitability

- content remains legible in realistic brightness conditions
- thumbnail cues remain useful after display conversion
- no phone-style page is required for the main runtime loop

### Performance

- no obvious extra render churn on the glasses
- HUD changes are event-driven rather than constantly redrawn
- no regression to video or audio hot paths

## Open questions and cautions

These are still real and should be remembered.

### Official spec mismatch is unresolved

Official Rokid material currently disagrees on FOV.

Treat any final safe-zone tuning as device-validated, not spec-validated.

### Newer Rokid glasses software stack may differ from older glass2 docs

The most detailed official UI guideline we have is from the older Rokid developer stack.

That does not make it useless, but it does mean:

- use it for display principles
- confirm runtime details on actual hardware
- treat exact platform implementation details as potentially evolved

### Community JSON-card approaches are informative, not binding

Some community examples show JSON-driven UI pipelines.

That is useful as inspiration for declarative rendering, but this repo should not copy that architecture blindly unless it clearly improves the current Jetson-owned scene model.

## Bottom line

For this project, the correct display mindset is:

- not "small Android phone in front of the eye"
- not "full AR spatial UI"
- but "green monochrome glanceable HUD driven by Jetson scene authority"

If a future change makes the glass UI feel more like a compact pilot HUD and less like a phone app, it is probably moving in the right direction.

## References

Official:

- [Rokid System Solution](https://rokidglass.github.io/glass2-docs/en/)
- [Glass_OS_Guideline.pdf](https://rokidglass.github.io/glass2-docs/zh/5-design/files/Glass_OS_Guideline.pdf)
- [Rokid Glasses product page](https://global.rokid.com/products/rokid-glasses)
- [Rokid Glasses product blog](https://global.rokid.com/blogs/news/rokid-glasses-are-lightweight-ar-smart-glasses-with-micro-led-displays-and-a-499-price-tag)

Project-local:

- [official-glass-ui-notes.md](docs/reference/official-glass-ui-notes.md)
- [display-experience-playbook.md](docs/reference/display-experience-playbook.md)
- [hud-scene-protocol.md](docs/reference/hud-scene-protocol.md)

Community:

- [Tencent Cloud community article](https://cloud.tencent.com/developer/article/2601113)
