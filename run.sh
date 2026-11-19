#!/usr/bin/env bash
# Chạy ứng dụng trên macOS / Linux
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Mở trình duyệt tại: http://localhost:8000"
python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
