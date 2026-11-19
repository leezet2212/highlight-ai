#!/usr/bin/env bash
# Highlight AI – chạy trên macOS / Linux.   ./run.sh          (chỉ máy này)
#                                          ./run.sh public   (thêm link công khai)
set -e
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "[LỖI] Chưa cài Python 3 (https://www.python.org/downloads/)"; exit 1; }
command -v ffmpeg  >/dev/null || { echo "[LỖI] Chưa cài FFmpeg – macOS: brew install ffmpeg | Ubuntu: sudo apt install ffmpeg"; exit 1; }

if [ ! -d .venv ]; then
  echo "Lần đầu chạy: đang cài đặt, vui lòng đợi 1-2 phút..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q --disable-pip-version-check -r requirements.txt
[ -f .env ] || cp .env.example .env

open_url() { (command -v open >/dev/null && open "$1") || (command -v xdg-open >/dev/null && xdg-open "$1") || true; }

if [ "${1:-}" = "public" ]; then
  grep -qE '^APP_PASSWORD=.+' .env || {
    echo "[LỖI] Hãy đặt mật khẩu trong file .env trước, ví dụ: APP_PASSWORD=matkhaucuaban"; exit 1; }
  CF=$(command -v cloudflared || true)
  if [ -z "$CF" ]; then
    if [ "$(uname)" = "Darwin" ] && command -v brew >/dev/null; then
      brew install cloudflared; CF=$(command -v cloudflared)
    else
      ARCH=$(uname -m); case "$ARCH" in x86_64) ARCH=amd64;; aarch64|arm64) ARCH=arm64;; esac
      curl -L -s -o cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$ARCH"
      chmod +x cloudflared; CF=./cloudflared
    fi
  fi
  export MAX_UPLOAD_MB=95   # Cloudflare's free tunnel rejects uploads over 100 MB
  "$CF" tunnel --url http://localhost:8000 > .tunnel.log 2>&1 &
  TUNNEL_PID=$!
  trap 'kill $TUNNEL_PID 2>/dev/null' EXIT
  ( for _ in $(seq 30); do
      URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' .tunnel.log | head -1)
      if [ -n "$URL" ]; then echo; echo "  🌐 Link công khai: $URL  (đổi mỗi lần chạy)"; echo; break; fi
      sleep 1
    done ) &
else
  ( sleep 3; open_url http://localhost:8000 ) &
fi

echo
echo "  Highlight AI đang chạy tại: http://localhost:8000   (Ctrl+C để tắt)"
echo
python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
