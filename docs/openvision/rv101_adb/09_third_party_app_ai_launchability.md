# RV101 Third-Party App AI Launchability

Updated: 2026-04-29
Device target: Rokid Glasses RV101

## Bottom Line

A normal OpenVision APK can probably be made visible and launchable in the RV101
Launcher with standard Android manifest declarations. But this does not prove
that Rokid's native AI will open it when the user says "open OpenVision Rokid".

Static RV101 evidence says:

```text
Manifest with MAIN/LAUNCHER or MAIN/LEANBACK_LAUNCHER
  -> likely visible in Launcher app list
  -> launchable when selected in Launcher UI
```

But native AI app opening says:

```text
Rokid AI/NLU
  -> control_app JSON
  -> hardcoded first-party name whitelist
  -> Rokid scene/page
```

No generic native-AI path was found that maps arbitrary app labels or package
names to `AppDataManager.launchAppByPkgName(...)`.

## What To Declare Anyway

Recommended minimum for the OpenVision app:

```xml
<application
    android:label="OpenVision Rokid"
    android:icon="@mipmap/ic_launcher">

    <activity
        android:name=".MainActivity"
        android:exported="true">
        <intent-filter>
            <action android:name="android.intent.action.MAIN" />
            <category android:name="android.intent.category.LAUNCHER" />
            <category android:name="android.intent.category.LEANBACK_LAUNCHER" />
        </intent-filter>
    </activity>
</application>
```

Useful optional deep link:

```xml
<intent-filter>
    <action android:name="android.intent.action.VIEW" />
    <category android:name="android.intent.category.DEFAULT" />
    <category android:name="android.intent.category.BROWSABLE" />
    <data android:scheme="openvisionrokid" android:host="open" />
</intent-filter>
```

This makes our app easy to launch from our own tooling and future approved
bridges, but it does not automatically teach Rokid AI the phrase.

## Evidence Summary

Launcher visibility evidence:

```text
AppSearchManager queries MAIN/LAUNCHER and MAIN/LEANBACK_LAUNCHER.
AppSearchManager loads package label/icon into AppInfo.
AppListAdapter calls AppDataManager.launchAppByPkgName(packageName).
```

Native AI limitation evidence:

```text
OnLineManager dispatches JSON command plus params.
ControlAppOrSceneAction handles control_app.
control_app switches over fixed names like Navigation, AI Chat, Translator, Settings.
No arbitrary package/app-label branch was found.
```

External open-app caveat:

```text
ExternalCmdReceiver parses com.rokid.os.sprite.launcher.cmd with cmd=open_app.
NormalStatusManager$1.onOpenApp(uri, pkg) is empty in this build.
```

## Safe Test Later

When an OpenVision APK exists, verify without modifying system apps:

```bash
adb shell pm list packages | grep openvision
adb shell dumpsys package com.openvision.rokid | grep -i -E "MAIN|LAUNCHER|LEANBACK|label|Activity"
adb shell monkey -p com.openvision.rokid -c android.intent.category.LAUNCHER 1
adb logcat -v time -s OnLineManager ExternalCmdReceiver AppDataManager AppSearchManager ActivityTaskManager
```

Then say:

```text
open OpenVision Rokid
mo OpenVision Rokid
mo ung dung OpenVision Rokid
```

Only claim native AI launch works if logs show `AppDataManager` or
`ActivityTaskManager` opening `com.openvision.rokid` as a result of the voice
command.

## OpenVision Decision

Do not rely on Rokid native AI to open OpenVision by app name. Build our own
cloud-realtime typed command path, keep the app launcher/deep-link friendly, and
treat native AI launch as an optional convenience if real-device logs later prove
it.

## Deep-Dive Evidence

Full static-analysis notes are in:

```text
device_research/rv101_system_apks_2026-04-29/rokid_jsai_wake_research/06_third_party_app_ai_launchability.md
```
