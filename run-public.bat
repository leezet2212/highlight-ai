@echo off
REM Chay Highlight AI va tao link cong khai mien phi (Cloudflare Tunnel)
REM de mo tu dien thoai o bat cu dau. Can dat APP_PASSWORD trong .env.
cd /d "%~dp0"
set HIGHLIGHT_PUBLIC=1
call run.bat
