param(
    [string]$RootDir = "$env:USERPROFILE\rokid_stt_probe"
)

$ErrorActionPreference = "Stop"

$startScript = Join-Path $RootDir "run\start_phowhisper_detached.ps1"
if (!(Test-Path $startScript)) {
    throw "Missing start script: $startScript"
}

$legacyTask = Get-ScheduledTask -TaskName "RokidPhoWhisperWorker" -ErrorAction SilentlyContinue
if ($legacyTask) {
    Unregister-ScheduledTask -TaskName "RokidPhoWhisperWorker" -Confirm:$false
    Write-Output "Removed legacy task RokidPhoWhisperWorker"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask `
    -TaskName "OpenVisionPhoWhisper" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "OpenVision Rokid Debug STT PhoWhisper sidecar. Sidecar only; no command routing." `
    -Force | Out-Null

Write-Output "Installed canonical task OpenVisionPhoWhisper"
