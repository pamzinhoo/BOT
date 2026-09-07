@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado no PATH.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  if exist "venv\Scripts\python.exe" (
    echo Usando venv existente.
  ) else (
    echo Criando .venv...
    python -m venv .venv
  )
)

if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
  call "venv\Scripts\activate.bat"
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

where npm >nul 2>nul
if errorlevel 1 (
  echo npm nao encontrado. Instale Node.js para buildar o painel.
  exit /b 1
)

cd frontend
if not exist "node_modules" npm install
npm run build
cd ..

echo Setup concluido. Use start_dashboard.bat.
endlocal
