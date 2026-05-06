param(
    [string]$RootDir = "$env:USERPROFILE\rokid_stt_probe",
    [int]$Port = 9460,
    [int]$CpuThreads = 2
)

$ErrorActionPreference = "Stop"

$root = $RootDir
$run = Join-Path $root "run"
$python = Join-Path $root "venv\Scripts\python.exe"
$server = Join-Path $root "phowhisper_http_server.py"
$modelDir = Join-Path $root "models\PhoWhisper-small-ct2-fasterWhisper"
$tokenFile = Join-Path $run "debug_stt_token.txt"
$pidFile = Join-Path $run "phowhisper_worker.pid"
$stdout = Join-Path $run "phowhisper_worker.stdout.log"
$stderr = Join-Path $run "phowhisper_worker.stderr.log"
$stopScript = Join-Path $root "stop_phowhisper_worker_windows.ps1"

New-Item -ItemType Directory -Force -Path $run | Out-Null

if (!(Test-Path $python)) { throw "Missing Python venv: $python" }
if (!(Test-Path $server)) { throw "Missing PhoWhisper server: $server" }
if (!(Test-Path $modelDir)) { throw "Missing PhoWhisper model dir: $modelDir" }
if (!(Test-Path $tokenFile)) { throw "Missing debug STT auth token file: $tokenFile" }

if (Test-Path $stopScript) {
    & $stopScript -RootDir $root -Port $Port
} else {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.OwningProcess -gt 0) { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    }
}

$arguments = @(
    $server,
    "--host", "0.0.0.0",
    "--port", [string]$Port,
    "--model-dir", $modelDir,
    "--language", "vi",
    "--cpu-threads", [string]$CpuThreads,
    "--compute-type", "int8",
    "--beam-size", "5",
    "--idle-unload-ms", "120000",
    "--auth-token-file", $tokenFile
)

function Quote-Arg([string]$Value) {
    if ($Value -match '[\s"]') {
        return '"' + ($Value -replace '"', '\"') + '"'
    }
    return $Value
}

$commandLine = (Quote-Arg $python) + " " + (($arguments | ForEach-Object { Quote-Arg ([string]$_) }) -join " ")
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $commandLine
    CurrentDirectory = $root
}
if ($result.ReturnValue -ne 0) {
    throw "Win32_Process.Create failed: $($result.ReturnValue)"
}

$result.ProcessId | Set-Content -Path $pidFile -Encoding ascii

$listener = $null
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) { break }
}

if (!$listener) {
    $err = if (Test-Path $stderr) { Get-Content $stderr -Raw } else { "" }
    throw "PhoWhisper worker did not open port $Port. $err"
}

if ($listener.OwningProcess -gt 0) {
    $listener.OwningProcess | Set-Content -Path $pidFile -Encoding ascii
}

$token = (Get-Content $tokenFile -Raw).Trim()
$headers = @{ "X-OpenVision-Debug-STT-Token" = $token }
$health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -Headers $headers -TimeoutSec 8

Write-Output "listener_pid=$($listener.OwningProcess)"
$health | ConvertTo-Json -Compress
