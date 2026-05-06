# Jetson OpenAI Realtime Skill Foundation

Updated: 2026-04-23

This document defines the new voice architecture direction for the Rokid `RV101` + Jetson stack.

It replaces the old mental model of:

- `speech -> STT -> heuristic router -> HUD`

with:

- `speech -> OpenAI Realtime conversation -> typed Jetson skills -> HUD`

## Why this direction exists

The old stack proved that:

- raw STT alone is not the same thing as natural command understanding
- Vietnamese command quality can be acceptable for narrow commands, but the system becomes brittle when natural phrasing expands
- every new feature adds more router heuristics, prompt patches, and fallback branches

The new direction aims to:

- improve natural Vietnamese command understanding
- make Jetson capabilities look like typed tools
- keep the glasses thin
- preserve Jetson as the owner of grounded skills, local runtime state, selected-target state, and HUD authority
- create a foundation for an OpenClaw-style wearable agent stack that is centered on vision/world skills rather than office automation

## Core architecture

Glasses:

- capture mic + camera
- stream audio/video to Jetson
- render thin HUD only

Jetson:

- owns session state
- owns perception state and target search state
- owns skill registry
- owns HUD scene authority
- owns OpenAI Realtime/API session lifecycle and the tool bridge

OpenAI Realtime:

- interprets natural Vietnamese speech
- acts as the primary agent brain and planner
- chooses Jetson skills/tools when the user is issuing a command or when more grounded evidence is needed
- returns structured function calls, not free-form guesses

## Important rule

Do not let the glasses talk directly to OpenAI as the system owner.

The correct pattern for this project is:

- `glasses -> Jetson -> OpenAI Realtime -> Jetson skills`

not:

- `glasses -> OpenAI -> Jetson`

Why:

- Jetson has the live perception context
- Jetson owns the active target search state
- Jetson owns the HUD contract
- secrets and guardrails belong on Jetson, not on the glasses
- OpenAI can still be the reasoning/planning brain while Jetson remains the trusted boundary for device state and real-world actions

## Skill model

Jetson skills are typed function tools.

They are not giant feature screens and they are not free-form mode strings inside the glasses app.

Current first-party skills in the foundation:

- `set_jetson_mode`
- `query_scene`
- `search_target`
- `clear_target_search`

These skills are intentionally small and map directly onto the existing backend behavior.

## What stays as fallback

`PhoWhisper` remains useful, but no longer as the main product direction.

It stays as:

- offline fallback
- regression benchmark path
- backup path if OpenAI Realtime is unavailable

It should not be the main place where product intelligence is invested from this point onward.

## Product implications

This direction prioritizes:

- command understanding over pretty live captioning
- typed tool execution over heuristic routing
- a reusable Jetson skill layer that can later power other systems such as OpenClaw-like backends
- a wearable-agent future where local machines behind the glasses can help:
  - Jetson for live media, skill execution, local perception runtimes, and HUD authority
  - mini PC for auxiliary local services
  - Pi5 for lightweight edge/home support services
  - OpenAI/cloud AI for planning, conversation, tool choice, and difficult reasoning/disambiguation

This direction does not guarantee perfect word-for-word transcript quality.

Instead, it is optimized for:

- understanding the user's intent
- calling the right Jetson skill
- returning compact HUD state

The intended differentiation from a generic OpenClaw-style agent is:

- much heavier investment in `vision skills`
- stronger local perception state
- selected-target continuity across follow-up questions
- real-world, glasses-native interaction rather than office-centric workflows

## Migration rules

When this mode is active:

- do not depend on local partial caption probing
- do not depend on chat-completions router fallback
- do not let unfinished HUD transcript behavior override skill-driven HUD state
- keep local segmented STT only as backup

## Active implementation pieces

Backend foundation files:

- [skills_runtime.py](rokidjetson/backend_mvp/app/skills_runtime.py)
- [openai_realtime_skills.py](rokidjetson/backend_mvp/app/openai_realtime_skills.py)
- [voice_runtime.py](rokidjetson/backend_mvp/app/voice_runtime.py)

Config entry point:

- [voice_settings.json](rokidjetson/backend_mvp/config/voice_settings.json)

## Current limitation

This foundation can be wired and verified locally without changing the glasses app, but it still requires:

- a valid OpenAI API key on Jetson
- real-device speech logs
- latency and intent validation against actual Jetson skills

Do not claim end-to-end product success until those logs exist.
