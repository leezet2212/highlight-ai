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


class Post(BaseModel):
    title: str
    caption: str
    hashtags: list[str]


class Posts(BaseModel):
    tiktok: Post
    facebook: Post
    youtube: Post


class Script(BaseModel):
    summary: str
    segments: list[Segment]
    posts: Posts


class PostsOnly(BaseModel):
    posts: Posts


POSTS_RULES = """Viết thêm "posts": nội dung đăng bài cho từng mạng xã hội, cùng giọng văn với phong cách bình luận, bám đúng diễn biến trận:
- "tiktok": "title" để trống; "caption" 1-2 câu ngắn (dưới 150 ký tự) gây tò mò, được dùng emoji; "hashtags" 4-6 cái.
- "facebook": "title" để trống; "caption" 2-4 câu kể lại pha hay/hài, kết bằng câu hỏi kéo bình luận, được dùng emoji; "hashtags" 3-5 cái.
- "youtube": "title" tiêu đề Shorts hấp dẫn dưới 70 ký tự; "caption" là mô tả 2-3 câu; "hashtags" 3-5 cái, luôn có #Shorts.
- Hashtag viết liền không dấu, bắt đầu bằng #, ví dụ #lienquan #lienquanmobile #highlight. Không bịa tên tướng nếu không chắc chắn."""


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

{posts_rules}
"""

CAPTION_PROMPT = """Bạn là người quản lý kênh TikTok/Facebook/YouTube về game Liên Quân Mobile ở Việt Nam.
Dựa trên kịch bản bình luận của một video highlight dưới đây, hãy viết nội dung đăng bài.

PHONG CÁCH: {style}
YÊU CẦU THÊM CỦA NGƯỜI DÙNG: {notes}
TÓM TẮT TRẬN: {summary}
KỊCH BẢN BÌNH LUẬN (theo thời gian):
{lines}

{posts_rules}
"""


class ScriptError(RuntimeError):
    pass


def _state_name(f) -> str:
    st = getattr(f, "state", None)
    return str(getattr(st, "name", st) or "").upper()


def generate_script(video: Path, duration: float, style: str, notes: str,
                    on_progress=lambda msg: None) -> dict:
    from google.genai import types

    client = _client()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    on_progress("Đang tải video lên Gemini...")
    try:
        uploaded = client.files.upload(file=str(video))
    except Exception as exc:
        raise ScriptError(gemini_error_message(exc)) from exc
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
        posts_rules=POSTS_RULES,
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
    except Exception as exc:
        raise ScriptError(gemini_error_message(exc)) from exc
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


def _client():
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ScriptError("Chưa có GEMINI_API_KEY trong file .env (lấy miễn phí tại aistudio.google.com).")
    from google import genai
    return genai.Client(api_key=api_key)


def generate_posts(segments: list[dict], summary: str, style: str, notes: str) -> dict:
    """Write captions/hashtags from the (possibly edited) script – text only, no video upload."""
    from google.genai import types

    lines = "\n".join(f"[{float(s['start']):.1f}s] {str(s.get('text', '')).strip()}"
                      for s in segments if str(s.get("text", "")).strip())
    if not lines:
        raise ScriptError("Kịch bản đang trống – hãy viết lời bình trước rồi mới tạo caption.")
    prompt = CAPTION_PROMPT.format(style=style_prompt(style), notes=notes.strip() or "(không có)",
                                   summary=summary.strip() or "(không có)", lines=lines,
                                   posts_rules=POSTS_RULES)
    try:
        resp = _client().models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=PostsOnly, temperature=1.0),
        )
        data = json.loads(resp.text)
    except ScriptError:
        raise
    except (TypeError, json.JSONDecodeError) as exc:
        raise ScriptError("Gemini trả về caption không hợp lệ, hãy thử lại.") from exc
    except Exception as exc:
        raise ScriptError(gemini_error_message(exc)) from exc
    return normalize_posts(data.get("posts"))


def gemini_error_message(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "429" in msg or "quota" in low or "resource_exhausted" in low:
        return "Đã hết lượt Gemini miễn phí (theo phút hoặc theo ngày). Đợi một lúc rồi thử lại."
    if "api key" in low or "401" in msg or "403" in msg or "permission" in low:
        return "Gemini từ chối GEMINI_API_KEY – kiểm tra lại key trong file .env."
    return f"Lỗi khi gọi Gemini: {msg[:300]}"


def clean_tag(tag: str) -> str:
    tag = "".join(ch for ch in str(tag).strip() if ch.isalnum() or ch == "_")
    return f"#{tag}" if tag else ""


def normalize_posts(posts) -> dict | None:
    if not isinstance(posts, dict):
        return None
    out = {}
    for net in ("tiktok", "facebook", "youtube"):
        p = posts.get(net) or {}
        tags, seen = [], set()
        for t in p.get("hashtags") or []:
            t = clean_tag(t)
            if t and t.lower() not in seen:
                seen.add(t.lower())
                tags.append(t)
        if net == "youtube" and "#shorts" not in seen:
            tags.append("#Shorts")
        out[net] = {"title": str(p.get("title", "")).strip(),
                    "caption": str(p.get("caption", "")).strip(),
                    "hashtags": tags}
    return out


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
        seg = {
            "start": round(start, 2),
            "end": round(min(end, duration), 2),
            "event": str(s.get("event", "")).strip(),
            "text": text,
        }
        # Optional per-line voice chosen in the editor.
        if s.get("provider") and s.get("voice_id"):
            seg["provider"] = str(s["provider"]).strip()
            seg["voice_id"] = str(s["voice_id"]).strip()
        segs.append(seg)
    return {"summary": str(data.get("summary", "")).strip(), "segments": segs,
            "posts": normalize_posts(data.get("posts"))}
