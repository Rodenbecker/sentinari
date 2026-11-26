@echo off
setlocal
set "ROOT=%~dp0"
set "SERVER=%ROOT%llama_server\llama-server.exe"
set "CHAT_MODEL=%ROOT%Gemma\gemma-4-26B-A4B-it-qat-q4_0-gguf\gemma-4-26B_q4_0-it.gguf"
set "EMBED_MODEL=%ROOT%Gemma\Qwen3-Embedding-0.6B-Q8_0.gguf"

if not exist "%SERVER%" (
    echo llama-server.exe not found: %SERVER%
    exit /b 1
)
if not exist "%CHAT_MODEL%" (
    echo Gemma GGUF not found: %CHAT_MODEL%
    exit /b 1
)
if not exist "%EMBED_MODEL%" (
    echo Qwen embedding GGUF not found: %EMBED_MODEL%
    exit /b 1
)

call :ensure_chat
if errorlevel 1 exit /b 1
call :ensure_embeddings
if errorlevel 1 exit /b 1

echo Gemma chat and Qwen embedding endpoints are ready.
exit /b 0

:ensure_chat
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:8101/health' -TimeoutSec 3; if ($r.status -eq 'ok') { exit 0 } } catch {}; exit 1"
if not errorlevel 1 (
    echo Reusing Gemma chat server on port 8101.
    exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort 8101 -State Listen -ErrorAction SilentlyContinue) { exit 0 }; exit 1"
if errorlevel 1 (
    echo Starting Gemma 4 chat server on port 8101...
    start "Sentinari Gemma 4 Chat" /min "%SERVER%" -m "%CHAT_MODEL%" --host 127.0.0.1 --port 8101 -ngl 99 -c 4096 -fa on -ctk q8_0 -ctv q8_0 --reasoning off
) else (
    echo Gemma chat port 8101 is occupied; waiting for its health check.
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(180); do { try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:8101/health' -TimeoutSec 3; if ($r.status -eq 'ok') { exit 0 } } catch {}; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
    echo Gemma chat server did not become healthy on port 8101.
    exit /b 1
)
exit /b 0

:ensure_embeddings
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:8102/health' -TimeoutSec 3; if ($r.status -eq 'ok') { exit 0 } } catch {}; exit 1"
if not errorlevel 1 (
    echo Reusing Qwen embedding server on port 8102.
    exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort 8102 -State Listen -ErrorAction SilentlyContinue) { exit 0 }; exit 1"
if errorlevel 1 (
    echo Starting Qwen3 embedding server on port 8102...
    start "Sentinari Qwen3 Embeddings" /min "%SERVER%" -m "%EMBED_MODEL%" --host 127.0.0.1 --port 8102 -ngl 99 --embeddings --pooling last
) else (
    echo Embedding port 8102 is occupied; waiting for its health check.
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(180); do { try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:8102/health' -TimeoutSec 3; if ($r.status -eq 'ok') { exit 0 } } catch {}; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
    echo Qwen embedding server did not become healthy on port 8102.
    exit /b 1
)
exit /b 0
