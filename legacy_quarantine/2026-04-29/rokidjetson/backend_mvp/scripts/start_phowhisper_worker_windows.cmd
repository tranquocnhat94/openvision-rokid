@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0start_phowhisper_worker_windows.ps1" -RootDir "C:\Users\Tranq\rokid_stt_probe" -Port 9460 -CpuThreads 2 -IdleUnloadMs 120000
