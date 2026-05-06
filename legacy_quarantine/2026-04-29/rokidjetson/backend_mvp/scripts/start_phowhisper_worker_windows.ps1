param(
    [string]$RootDir = "$env:USERPROFILE\rokid_stt_probe",
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 9460,
    [int]$CpuThreads = 4,
    [int]$IdleUnloadMs = 120000
)

$ErrorActionPreference = "Stop"

$python = Join-Path $RootDir "venv\Scripts\python.exe"
$pythonw = Join-Path $RootDir "venv\Scripts\pythonw.exe"
$serverScript = Join-Path $RootDir "phowhisper_http_server.py"
$modelDir = Join-Path $RootDir "models\PhoWhisper-small-ct2-fasterWhisper"
$runDir = Join-Path $RootDir "run"
$pidFile = Join-Path $runDir "phowhisper_worker.pid"
$stdoutFile = Join-Path $runDir "phowhisper_worker.stdout.log"
$stderrFile = Join-Path $runDir "phowhisper_worker.stderr.log"

New-Item -ItemType Directory -Force -Path $runDir | Out-Null

if (!(Test-Path $python)) {
    throw "Missing Python runtime: $python"
}
if (!(Test-Path $serverScript)) {
    throw "Missing server script: $serverScript"
}
if (!(Test-Path $modelDir)) {
    throw "Missing model dir: $modelDir"
}

if (Test-Path $pidFile) {
    $pidValue = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($pidValue) {
        $existing = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Output "PhoWhisper worker already running with PID $pidValue"
            exit 0
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

try {
    New-NetFirewallRule -Name "rokid-phowhisper-9460" -DisplayName "Rokid PhoWhisper Worker 9460" -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort $Port -Profile Any -ErrorAction SilentlyContinue | Out-Null
} catch {
}

$arguments = @(
    $serverScript,
    "--host", $BindHost,
    "--port", "$Port",
    "--model-dir", $modelDir,
    "--language", "vi",
    "--cpu-threads", "$CpuThreads",
    "--compute-type", "int8",
    "--beam-size", "5",
    "--idle-unload-ms", "$IdleUnloadMs"
)

$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $RootDir -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile -PassThru
$process.Id | Set-Content -Path $pidFile -Encoding ascii

Start-Sleep -Milliseconds 1500
$alive = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
if (!$alive) {
    $stderr = ""
    if (Test-Path $stderrFile) {
        $stderr = (Get-Content $stderrFile -Raw -ErrorAction SilentlyContinue).Trim()
    }
    throw "PhoWhisper worker failed to stay alive. $stderr"
}

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5 | Out-Null
} catch {
    $stderr = ""
    if (Test-Path $stderrFile) {
        $stderr = (Get-Content $stderrFile -Raw -ErrorAction SilentlyContinue).Trim()
    }
    throw "PhoWhisper worker started but health check failed. $stderr"
}

Write-Output "Started PhoWhisper worker PID $($process.Id) on port $Port"
