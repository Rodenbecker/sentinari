@echo off
REM ============================================================
REM  launch-all.bat - Start local GGUF model services, then Sentinari core.
REM ============================================================

set "ROOT=%~dp0..\"
set "SRV=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
set "LOGDIR=%ROOT%Logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "SRVLOG=%SRV%inference_server.log"
set "CORELOG=%LOGDIR%\launch-sentinari-core.log"

echo.
echo SENTINARI STACK LAUNCHER
echo ------------------------
echo 1/2  Gemma chat and Qwen embedding servers (ports 8101/8102)
echo 2/2  Sentinari core (port 8099)
echo.

if not exist "%PYTHON%" (
    echo Could not find Python runtime at %PYTHON%
    pause
    exit /b 1
)

REM ---- 1/2: local GGUF model services; never start the incompatible ONNX server ----
if not exist "%ROOT%START_GEMMA4.bat" (
    echo Model launcher not found: %ROOT%START_GEMMA4.bat
    exit /b 1
)
call "%ROOT%START_GEMMA4.bat"
if errorlevel 1 (
    echo Local model services failed to become healthy.
    exit /b 1
)

REM ---- 2/2: Sentinari core (same never-duplicate logic as launch-sentinari.bat) ----
REM NOTE: the bottom "Stack is up" open covers the already-running path too -
REM keep exactly ONE browser-open in this file (§50: start "" silently no-ops).
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [System.Net.WebRequest]::DefaultWebProxy = $null; $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8099/health' -TimeoutSec 2; if ($h.ok) { exit 0 } } catch {}; if (Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction SilentlyContinue) { exit 0 }; exit 1"
if not errorlevel 1 (
    echo Sentinari core already running. Reusing the existing server...
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction SilentlyContinue) { exit 0 }; exit 1"
    if not errorlevel 1 (
        echo Port 8099 is occupied but the Sentinari health endpoint is failing.
        echo Stop the stale core process and run this launcher again; refusing to start a duplicate.
        exit /b 1
    )
    echo Starting Sentinari Core Server...
    set "SENTINARI_SHARED_SKILLS_ROOT=%ROOT%data\skills"
    set "OLLAMA_GPU_OVERRIDE=0"
    start "Sentinari Core" /min cmd /c "cd /d "%ROOT%" && set SENTINARI_SHARED_SKILLS_ROOT=%ROOT%data\skills && set OLLAMA_GPU_OVERRIDE=0 && "%PYTHON%" run_smi.py serve >> "%CORELOG%" 2>&1"

    echo Waiting for Sentinari core health...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(60); do { try { [System.Net.WebRequest]::DefaultWebProxy = $null; $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8099/health' -TimeoutSec 3; if ($h.ok) { exit 0 } } catch {}; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $deadline); exit 1"
    if errorlevel 1 (
        echo Sentinari core did not answer in time. Last log lines:
        powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path '%CORELOG%') { Get-Content '%CORELOG%' -Tail 8 } else { Write-Host '(log not found)' }"
        echo.
        echo The server MAY still be coming up. Check: http://127.0.0.1:8099/ui/playground
        pause
        exit /b 1
    )
)

echo.
echo Stack is up:
echo   Gemma chat  : http://127.0.0.1:8101/health
echo   Embeddings  : http://127.0.0.1:8102/health
echo   Sentinari   : http://127.0.0.1:8099/
call "%ROOT%open_url.bat" "http://127.0.0.1:8099/" "%LOGDIR%\open-url.log"
pause
