@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado no PATH.
  exit /b 1
)

if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
  call "venv\Scripts\activate.bat"
) else (
  echo Nenhum venv encontrado. Rode setup_dashboard.bat primeiro.
  exit /b 1
)

if not exist "frontend\dist\index.html" (
  echo Build do painel nao encontrado. Rode setup_dashboard.bat primeiro.
  exit /b 1
)

python -c "import fastapi, jwt, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo Dependencias Python incompletas. Rode setup_dashboard.bat primeiro.
  exit /b 1
)

set API_HOST=127.0.0.1
if "%API_PORT%"=="" set API_PORT=8000
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -Command "$health='http://127.0.0.1:%API_PORT%/admin/api/health'; $ready='http://127.0.0.1:%API_PORT%/admin/api/ready'; $admin='http://127.0.0.1:%API_PORT%/admin'; $apiUp=$false; for($i=0;$i -lt 120;$i++){try{$h=Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 2; if($h.StatusCode -eq 200){$apiUp=$true; break}}catch{}; Start-Sleep -Seconds 1}; if(-not $apiUp){Write-Host 'API nao respondeu /health dentro do timeout. O bot pode ainda estar iniciando.'; exit 0}; for($i=0;$i -lt 120;$i++){try{$r=Invoke-RestMethod -Uri $ready -TimeoutSec 2; if($r.ready){Write-Host ('Dashboard pronto. Guilds carregadas: ' + $r.guild_count); Start-Process $admin; exit 0}; Write-Host ('Aguardando Discord ready... ready=' + $r.discord_ready + ' guilds=' + $r.guild_count)}catch{Write-Host 'API viva, readiness ainda indisponivel.'}; Start-Sleep -Seconds 1}; Write-Host 'Timeout aguardando Discord ready. Abrindo dashboard mesmo assim; estado pode aparecer como inicializando.'; Start-Process $admin"
python main.py
endlocal
