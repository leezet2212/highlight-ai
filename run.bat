@echo off
REM Chay ung dung tren Windows
cd /d "%~dp0"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .env copy .env.example .env
echo Mo trinh duyet tai: http://localhost:8000
start "" http://localhost:8000
python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
pause
