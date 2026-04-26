param(
    [string]$RootDir = "$env:USERPROFILE\rokid_stt_probe",
    [int]$Port = 9460
)

$ErrorActionPreference = "Stop"

$pidFile = Join-Path $RootDir "run\phowhisper_worker.pid"
$targetIds = New-Object System.Collections.Generic.HashSet[int]

if (Test-Path $pidFile) {
    $pidValue = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    $pidNumber = 0
    if ([int]::TryParse($pidValue, [ref]$pidNumber) -and $pidNumber -gt 0) {
        [void]$targetIds.Add($pidNumber)
    }
}

Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.OwningProcess -gt 0) {
        [void]$targetIds.Add([int]$_.OwningProcess)
    }
}

Get-CimInstance Win32_Process | Where-Object {
    ($_.CommandLine -like "*phowhisper_http_server.py*") -and ($_.CommandLine -like "*--port $Port*")
} | ForEach-Object {
    [void]$targetIds.Add([int]$_.ProcessId)
}

if ($targetIds.Count -gt 0) {
    $changed = $true
    while ($changed) {
        $changed = $false
        $current = @($targetIds)
        Get-CimInstance Win32_Process | Where-Object { $current -contains [int]$_.ParentProcessId } | ForEach-Object {
            if ($targetIds.Add([int]$_.ProcessId)) {
                $changed = $true
            }
        }
    }
}

foreach ($processId in @($targetIds) | Sort-Object -Descending) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        Write-Output "Stopped PhoWhisper process PID $processId"
    }
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue

$remaining = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($remaining) {
    throw "PhoWhisper port $Port is still listening after stop"
}
