@echo off
setlocal
title AryaInfer - Inkling 2 Mini (one server)

rem Inkling is a normal model in the 8080 roster now. This just asks the
rem running server to switch to it; Qwen is restored by asking for iq3_s.
set "BASE=http://127.0.0.1:8080"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { Invoke-RestMethod '%BASE%/v1/models' -TimeoutSec 3 | Out-Null } catch { Write-Host 'AryaInfer is not running on 8080. Start it first.'; exit 1 }"
if errorlevel 1 (
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $body = @{ model = 'inkling-2-mini-sq-15' } | ConvertTo-Json; $r = Invoke-RestMethod -Method Post -Uri '%BASE%/api/models/load' -ContentType 'application/json' -Body $body -TimeoutSec 600; Write-Host 'Inkling is loaded on 8080.'; Start-Process '%BASE%/'"
if errorlevel 1 (
  echo Could not switch to Inkling.
  pause
  exit /b 1
)
