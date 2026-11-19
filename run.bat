@echo off
REM ============================================================
REM  Highlight AI - chay tren may Windows. Bam dup file nay.
REM  (Muon mo tu dien thoai o bat cu dau: bam dup run-public.bat)
REM ============================================================
cd /d "%~dp0"
title Highlight AI

where python >nul 2>nul
if errorlevel 1 (
  echo [LOI] Chua cai Python.
  echo Tai tai https://www.python.org/downloads/ - khi cai nho tick "Add Python to PATH".
  pause & exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [LOI] Chua cai FFmpeg.
  echo Mo PowerShell va chay lenh:  winget install Gyan.FFmpeg
  echo Sau do DONG va mo lai file nay.
  pause & exit /b 1
)

if not exist .venv (
  echo Lan dau chay: dang cai dat, vui long doi 1-2 phut...
  python -m venv .venv
  if errorlevel 1 ( pause & exit /b 1 )
)
call .venv\Scripts\activate.bat
pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo [LOI] Cai thu vien that bai - kiem tra ket noi Internet.
  pause & exit /b 1
)
if not exist .env copy .env.example .env >nul

if defined HIGHLIGHT_PUBLIC (
  findstr /r /c:"^APP_PASSWORD=..*" .env >nul 2>nul
  if errorlevel 1 (
    echo [LOI] Hay dat mat khau trong file .env truoc, vi du:  APP_PASSWORD=matkhaucuaban
    echo Neu khong co mat khau, ai co link cung dung duoc va tieu het luot mien phi cua ban.
    pause & exit /b 1
  )
  if not exist cloudflared.exe (
    echo Dang tai Cloudflare Tunnel...
    curl -L -s -o cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
    if errorlevel 1 ( echo [LOI] Khong tai duoc cloudflared. & pause & exit /b 1 )
  )
  REM Cloudflare's free tunnel rejects uploads over 100 MB.
  set MAX_UPLOAD_MB=95
  start "Link cong khai - tim dong https://...trycloudflare.com" cloudflared.exe tunnel --url http://localhost:8000
  echo.
  echo  Link cong khai hien trong cua so "Link cong khai" vua mo
  echo  Link co dang https://....trycloudflare.com - doi moi lan chay.
) else (
  start "" cmd /c "timeout /t 4 >nul & start http://localhost:8000"
)

echo.
echo  Highlight AI dang chay tai: http://localhost:8000
echo  Dong cua so nay de tat ung dung.
echo.
python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
pause
