"""Watch the highlight video with Gemini and write a timed commentary script."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from pydantic import BaseModel

from .styles import style_prompt


class Segment(BaseModel):
    start: float
    end: float
    event: str
    text: str


class Script(BaseModel):
    summary: str
    segments: list[Segment]


PROMPT = """Bạn là bình luận viên game Liên Quân Mobile (Arena of Valor) cho kênh TikTok/YouTube Việt Nam.
Hãy XEM KỸ video highlight đính kèm (dài {duration:.1f} giây) và viết lời bình luận lồng tiếng tiếng Việt.

PHONG CÁCH: {style}
YÊU CẦU THÊM CỦA NGƯỜI DÙNG: {notes}

Quy tắc:
- Chia lời bình thành các đoạn bám sát diễn biến thật trên màn hình (giao tranh, hạ gục, bị hạ, dùng chiêu cuối, phá trụ, lấy rồng, lật kèo...). Đọc thông báo/killfeed trên màn hình nếu có.
- "start"/"end" tính bằng giây, nằm trong khoảng 0 đến {duration:.1f}, tăng dần, KHÔNG chồng lên nhau.
- Độ dài lời mỗi đoạn phải đọc kịp trong (end - start) giây: khoảng 3 từ tiếng Việt mỗi giây. Đừng nhồi chữ.
- Đoạn đầu tiên bắt đầu trong 1 giây đầu và phải có "câu mồi" gây tò mò để người xem không lướt qua.
- Để lại khoảng lặng ngắn giữa các đoạn cho tiếng game. Tổng thời lượng nói khoảng 60-80% video.
- Đoạn cuối là câu chốt ấn tượng (có thể kêu gọi follow/bình luận một cách tự nhiên).
- "event": mô tả ngắn điều đang xảy ra trên màn hình (để người dùng kiểm tra). "text": lời sẽ được đọc.
- Chỉ viết lời thoại thuần, không emoji, không ký hiệu, không chú thích trong ngoặc.
- "summary": tóm tắt 1-2 câu diễn biến trận.
"""


class ScriptError(RuntimeError):
    pass


def _state_name(f) -> str:
    st = getattr(f, "state", None)
    return str(getattr(st, "name", st) or "").upper()


def generate_script(video: Path, duration: float, style: str, notes: str,
                    on_progress=lambda msg: None) -> dict:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ScriptError("Chưa có GEMINI_API_KEY trong file .env (lấy miễn phí tại aistudio.google.com).")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    on_progress("Đang tải video lên Gemini...")
    uploaded = client.files.upload(file=str(video))
    waited = 0
    while _state_name(uploaded).endswith("PROCESSING"):
        if waited > 300:
            raise ScriptError("Gemini xử lý video quá lâu, hãy thử video ngắn hơn.")
        on_progress("Gemini đang xử lý video...")
        time.sleep(3)
        waited += 3
        uploaded = client.files.get(name=uploaded.name)
    if _state_name(uploaded).endswith("FAILED"):
        raise ScriptError("Gemini không đọc được video này.")

    on_progress("AI đang xem trận đấu và viết lời bình...")
    prompt = PROMPT.format(
        duration=duration,
        style=style_prompt(style),
        notes=notes.strip() or "(không có)",
    )
    try:
        resp = client.models.generate_content(
            model=model,
            contents=[uploaded, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=Script,
                temperature=1.0,
            ),
        )
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass

    try:
        data = json.loads(resp.text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ScriptError(f"Gemini trả về dữ liệu không hợp lệ: {resp.text!r:.300}") from exc
    return normalize(data, duration)


def normalize(data: dict, duration: float) -> dict:
    """Clamp times into the video and remove overlaps."""
    segs = []
    for s in sorted(data.get("segments", []), key=lambda s: float(s.get("start", 0))):
        text = str(s.get("text", "")).strip()
        if not text:
            continue
        start = max(0.0, min(float(s.get("start", 0)), duration))
        end = max(start + 0.5, min(float(s.get("end", start + 2)), duration))
        if segs and start < segs[-1]["end"]:
            start = segs[-1]["end"]
            if start >= duration:
                break
            end = max(end, start + 0.5)
        segs.append({
            "start": round(start, 2),
            "end": round(min(end, duration), 2),
            "event": str(s.get("event", "")).strip(),
            "text": text,
        })
    return {"summary": str(data.get("summary", "")).strip(), "segments": segs}
