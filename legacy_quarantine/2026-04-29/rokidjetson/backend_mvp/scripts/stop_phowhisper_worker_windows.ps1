param(
    [string]$RootDir = "$env:USERPROFILE\rokid_stt_probe"
)

$ErrorActionPreference = "Stop"

$pidFile = Join-Path $RootDir "run\phowhisper_worker.pid"

if (Test-Path $pidFile) {
    $pidValue = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($pidValue) {
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $pidValue -Force
            Write-Output "Stopped PhoWhisper worker PID $pidValue"
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
