# Android Client

The RV101/Rokid Android app has been split out of the backend repo.

Standalone app repo:

```text
/Users/tranquocnhat/Documents/codex/openvision-rokid-glasses-app
```

Use that repository for app source, app docs, Gradle builds, APK install, and
app-only progress updates. Keep this backend workspace focused on Jetson,
shared contracts, simulator, skill/runtime, replay, and Ops Console work.

The app repo contains its own:

```text
AGENTS.md
README.md
PROGRESS.md
MEASURED_DECISIONS.md
RELEASE_SIGNOFF.md
docs/openvision/
Gradle Android project
```

Backend signoff scripts remain in this repo. From the app repo, set:

```bash
export OPENVISION_BACKEND_REPO=/Users/tranquocnhat/Documents/codex/rokid
```
