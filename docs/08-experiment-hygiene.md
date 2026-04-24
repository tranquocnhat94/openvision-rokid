# Experiment Hygiene

This document exists because v1 became heavy when failed routes, fallback panels, old modes, and unused compatibility branches stayed in the active path.

v2 should stay clean by forcing every experiment to finish.

## The Three End States

Every experiment must become exactly one of:

- `promote`: active product/skill runtime;
- `quarantine`: lab/archive path, off by default;
- `remove`: deleted from active path.

## Promote

Promote only when the experiment has:

- a clear owner module;
- typed contract or schema;
- tests or replay fixture;
- telemetry;
- settings with safe defaults;
- documentation in active docs;
- clear HUD/product behavior if user-facing;
- no hidden dependency on old modes or local heuristics.

Examples:

- `count_people` becomes a typed skill with detector adapter, result schema, trace, tests, and HUD answer strip.
- `search_targets` becomes a typed skill with crop evidence, cloud resolver, candidate IDs, thumbnails, and selected-target state.

## Quarantine

Quarantine when the idea may be useful later but should not influence the product path today.

Rules:

- place under lab/archive/fallback paths;
- keep off by default;
- label clearly in UI/docs;
- exclude from default tool schemas and prompts;
- exclude from normal settings pages;
- document what evidence would be required to promote it.

Examples:

- replay-only analysis;
- offline local services;
- fake camera/audio fixtures;
- old experiments kept only for comparison.

## Remove

Remove when the experiment:

- duplicates the product route;
- confuses future implementation;
- is not likely to be promoted;
- keeps tests alive for obsolete behavior;
- appears in UI as if it is supported;
- adds config/rules that nobody should use.

Removal means all active traces are cleaned:

- source code;
- tests;
- settings;
- env examples;
- Web UI panels;
- docs;
- prompts/tool schemas;
- deployment scripts.

## Debug Is Not Exempt

Debug features still need discipline.

Allowed debug:

- sensor preview in Ops Console;
- Debug STT sidecar labelled as Ops-only;
- skill dry-run with simulated labels;
- replay sessions;
- redacted bundles.

Not allowed debug:

- hidden command routing;
- old modes in product controls;
- fake skill output without labels;
- OpenAI transcription branch kept "just in case";
- UI panels that imply a fallback is a first-class product path.

## Feature Flag Rules

A feature flag is temporary unless it guards a real product option.

Each flag should have:

- owner;
- default value;
- reason;
- removal or promotion condition;
- test coverage for the default behavior.

Delete flags that no longer protect a real decision.

## Documentation Rules

Active docs should describe the active product.

History belongs in archive docs. If active docs mention a removed route, they must frame it as:

- removed;
- forbidden;
- archived;
- or lab-only.

Do not write "future maybe" in active architecture unless there is a typed owner and a plausible integration path.

## Review Checklist

Before finishing a change, ask:

- Did I add a new route, flag, fallback, or panel?
- Is it product, lab, or temporary?
- Is it visible in the right place?
- Is it off by default if lab?
- Did I remove docs/tests/config for anything I deleted?
- Could a future AI mistake this for the active path?
- Does this keep the glasses thin?
- Does this preserve Jetson as the skill/HUD authority?
