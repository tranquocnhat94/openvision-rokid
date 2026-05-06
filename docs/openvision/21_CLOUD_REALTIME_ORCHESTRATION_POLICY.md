# 21 — Cloud Realtime Orchestration Policy

## Purpose

This document updates the V2 direction so Codex does not accidentally pull OpenVision Rokid back into the V1 local-STT-first architecture.

V2 is not:

```text
Rokid -> local STT -> Jetson router -> cloud AI
```

V2 is:

```text
Rokid voice stream -> cloud realtime AI -> Jetson tools/skills -> Rokid display/HUD
```

The cloud realtime model is the primary intent interpreter and skill choreographer. Jetson is the execution and perception engine. Rokid is a low-power media terminal.

## Why cloud realtime first

The V1 path worked as an experiment, but it imposed a rigid routing model:

1. capture audio,
2. transcribe locally or through a batch STT endpoint,
3. route locally,
4. maybe call cloud later.

That design made the system feel like a command parser with AI bolted on.

V2 should feel like a realtime multimodal operator that can decide:

- which skill to call,
- whether the skill needs a snapshot,
- whether the skill needs a short clip,
- whether live video should be enabled,
- whether Jetson local perception is enough,
- whether cloud visual reasoning is needed,
- how to combine several skills,
- and how to present the final result on Rokid.

## Correct authority split

### Cloud realtime AI owns

- natural language understanding,
- conversation state,
- user intent,
- multi-step planning,
- tool selection,
- skill choreography,
- final natural-language response,
- and cloud-level multimodal reasoning.

### Jetson owns

- tool server,
- skill execution,
- local perception graph,
- detector/tracker/OCR adapters,
- media ingestion from glasses,
- media budgets,
- privacy gates,
- scorecard logging,
- and display/HUD validation.

### Rokid owns

- microphone capture,
- foreground app-open conversation audio stream,
- optional push-to-talk debug/fallback trigger,
- camera capture only when requested,
- short media upload/stream to Jetson,
- and rendering display commands from Jetson.

## Cloud is orchestrator, not unrestricted executor

The cloud model may decide that a skill should be used, but it must not bypass Jetson's typed executor.

Cloud tool call:

```json
{
  "tool": "target_finder.find",
  "arguments": {
    "query": "người áo vàng đeo balo",
    "visual_mode": "live_video",
    "duration_ms": 15000
  }
}
```

Jetson validates:

- Does this tool exist?
- Is this tool enabled?
- Is live video allowed for this user/session?
- Is the requested duration within budget?
- Does the skill need a privacy gate?
- Does the display output match schema?

Only then does Jetson execute.

## V2 non-goals

Do not prioritize:

- local STT as default,
- local LLM as default router,
- always-on video stream,
- complex Android UI on Rokid,
- cloud sending raw commands directly to glasses without Jetson validation,
- untyped display payloads,
- or skill-specific media hacks.

## Allowed local STT role

Local STT may exist only as:

- debug sidecar,
- emergency offline fallback,
- comparison benchmark,
- or future optional mode.

It must not be required for the main V2 path.

## Preferred routing modes

### Mode A — Recommended MVP: glasses audio to Jetson relay, Jetson to cloud realtime

```text
Rokid mic -> Jetson realtime bridge -> cloud realtime -> Jetson tools -> Rokid display
```

Use this first if Android/WebRTC direct-to-cloud is difficult or if you want centralized logging and security.

### Mode B — Advanced: glasses direct to cloud realtime, Jetson as tool server

```text
Rokid mic -> cloud realtime
cloud tool calls -> Rokid data channel or app server -> Jetson tool server
Jetson result -> cloud and/or Rokid display
```

Use this when direct WebRTC from Rokid is stable and token/session management is solved.

### Recommendation

Build Mode A first because it requires fewer moving parts on the glasses, centralizes credentials on Jetson/server, and still preserves the V2 philosophy: no local STT, cloud realtime is the orchestrator.

Then add Mode B as an optimization path.

## Golden rule

The final product may use direct glass-to-cloud audio, but the first stable V2 should use the simplest reliable path that keeps the glasses light and the skill system typed.
