@echo off
setlocal
"C:\Users\Tranq\rokid_stt_probe\venv\Scripts\python.exe" "C:\Users\Tranq\rokid_stt_probe\phowhisper_http_server.py" --host 0.0.0.0 --port 9460 --model-dir "C:\Users\Tranq\rokid_stt_probe\models\PhoWhisper-small-ct2-fasterWhisper" --language vi --cpu-threads 4 --compute-type int8 --beam-size 5 --idle-unload-ms 120000
