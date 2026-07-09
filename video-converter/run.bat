@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

title Video Converter

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python не найден. Установите Python 3.11+ и добавьте в PATH.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Не удалось создать .venv
    pause
    exit /b 1
  )
)

call .venv\Scripts\activate.bat

pip show fastapi >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies...
  pip install -r requirements.txt -q
)

where ffmpeg >nul 2>&1
if errorlevel 1 (
  if not exist "bin\ffmpeg.exe" (
    echo.
    echo [WARN] FFmpeg не найден в PATH и bin\ffmpeg.exe отсутствует.
    echo        Скачайте: https://www.gyan.dev/ffmpeg/builds/
    echo        Положите ffmpeg.exe и ffprobe.exe в папку bin\
    echo.
  )
)

set PORT=8765
set HOST=127.0.0.1

echo.
echo  Video Converter
echo  ===============
echo  URL: http://%HOST%:%PORT%
echo  Закройте это окно для остановки сервера.
echo.

start "" "http://%HOST%:%PORT%"

python -m uvicorn backend.main:app --host %HOST% --port %PORT% --app-dir .

if errorlevel 1 (
  echo.
  echo [ERROR] Сервер завершился с ошибкой.
  pause
)
