"""✍️ Content AI: short-drama ideas & scene-by-scene scripts, content check &
rewrite, and a posting calendar for TikTok.

Guardrails live in SAFETY_RULES and are sent with every request: fictional
characters only (no real people / celebrities), non-graphic action, staged or
AI-made videos must carry TikTok's AI-generated label.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

from .fashion import parse_json_block
from .script_ai import ScriptError, _client, gemini_error_message

FORMATS = {
    "anh_hung": "🦸 Anh hùng cứu mỹ nhân",
    "giup_nguoi_gia": "👵 Ra tay giúp người già bị bắt nạt",
    "gap_nguoi_noi_tieng": "🌟 Bất ngờ gặp người nổi tiếng trong ngành (nhân vật hư cấu)",
    "doi_doi": "🔄 Bị coi thường → lật kèo đổi đời",
    "tinh_cam": "💞 Chuyện tình cảm có plot twist",
    "review": "🛍️ Review / bán hàng kể chuyện",
    "custom": "✍️ Tự nhập chủ đề",
}

SAFETY_RULES = """QUY TẮC BẮT BUỘC (để video không bị TikTok gỡ hay bóp tương tác):
- CHỈ dùng nhân vật HƯ CẤU. Không dùng tên, khuôn mặt, giọng nói hay hình ảnh của người thật/người nổi tiếng có thật. Nếu người dùng nhắc tên người thật, hãy đổi thành nhân vật hư cấu tương đương (ví dụ "nữ ca sĩ hàng đầu", "CEO công ty công nghệ lớn") và ghi điều đó vào "notes".
- Cảnh hành động/xô xát: ngắn, KHÔNG máu me, không vũ khí nguy hiểm, không hướng dẫn bạo lực; kết thúc bằng điều tích cực (công an/người xung quanh can thiệp, kẻ xấu xin lỗi...).
- Không có trẻ em trong tình huống tình cảm hay nguy hiểm; không xúc phạm vùng miền, giới tính, nghề nghiệp; không bịa đặt về tổ chức/thương hiệu có thật.
- Video dàn dựng hoặc do AI tạo phải bật nhãn "Nội dung do AI tạo" của TikTok và có thể ghi "Phim ngắn dàn dựng" – nhắc điều này trong "notes".
- Mỗi kịch bản phải có một chi tiết/twist RIÊNG, tránh khuôn mẫu nhàm chán mà ai cũng làm."""


def _call(contents, *, search: bool = False, temperature: float = 1.0) -> dict:
    from google.genai import types

    cfg = {"temperature": temperature}
    if search:
        cfg["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    try:
        resp = _client().models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), contents=contents,
            config=types.GenerateContentConfig(**cfg))
    except ScriptError:
        raise
    except Exception as exc:
        raise ScriptError(gemini_error_message(exc)) from exc
    return parse_json_block(resp.text or "")


def _strs(v, n: int, limit: int = 400) -> list[str]:
    return [str(x).strip()[:limit] for x in (v or []) if str(x).strip()][:n]


def _tags(v) -> list[str]:
    out, seen = [], set()
    for t in v or []:
        t = "".join(ch for ch in str(t) if ch.isalnum() or ch == "_")
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append("#" + t)
    return out[:12]


# ---------------------------------------------------------------- ideas & scripts

IDEAS_PROMPT = """Bạn là biên kịch phim ngắn dọc (TikTok/Reels/Shorts) cho thị trường Việt Nam, chuyên làm video triệu view.
Thể loại: {fmt}
Chủ đề/lĩnh vực của kênh: {topic}
Thời lượng mỗi video: khoảng {seconds} giây. Giọng điệu: {tone}.
Hôm nay là {today}. Hãy dùng Google Search để xem các format phim ngắn đang thịnh hành gần đây trên mạng xã hội Việt Nam, rồi viết {count} kịch bản KHÁC NHAU.

{safety}

Trả về DUY NHẤT một khối JSON:
{{
  "trend_note": "1-2 câu: format này đang hot thế nào, nên làm khác đi ra sao để nổi bật",
  "ideas": [
    {{
      "title": "tên video ngắn gọn",
      "hook": "câu/cảnh trong 3 giây đầu khiến người xem dừng lướt",
      "twist": "chi tiết bất ngờ làm video này khác các video cùng thể loại",
      "characters": ["nhân vật hư cấu: mô tả ngắn"],
      "scenes": [
        {{"time": "0-3s", "visual": "mô tả cảnh bằng tiếng Việt", "dialogue": "lời thoại/lời dẫn tiếng Việt (có thể để trống)",
          "on_screen_text": "chữ hiện trên màn hình (ngắn, có thể để trống)",
          "ai_prompt": "prompt TIẾNG ANH chi tiết cho công cụ tạo video AI (nhân vật, bối cảnh, góc máy, ánh sáng, chuyển động, phong cách điện ảnh dọc 9:16)"}}
      ],
      "caption": "caption TikTok dưới 150 ký tự, có câu hỏi kéo bình luận",
      "hashtags": ["6-10 hashtag viết liền không dấu"],
      "notes": ["lưu ý khi làm/đăng (nhãn AI, chỗ đã đổi người thật thành nhân vật hư cấu...)"]
    }}
  ]
}}"""


def generate_ideas(fmt: str, topic: str, seconds: int, tone: str, count: int) -> dict:
    fmt_text = FORMATS.get(fmt, "") if fmt != "custom" else ""
    if fmt == "custom" and not topic.strip():
        raise ScriptError("Hãy nhập chủ đề bạn muốn làm.")
    prompt = IDEAS_PROMPT.format(
        fmt=fmt_text or topic.strip() or FORMATS["anh_hung"],
        topic=topic.strip() or "(chưa có – chọn chủ đề phổ biến hợp thể loại)",
        seconds=max(10, min(int(seconds), 180)), tone=tone.strip() or "kịch tính, cảm xúc, có hậu",
        count=max(1, min(int(count), 5)), today=datetime.now().strftime("%d/%m/%Y"), safety=SAFETY_RULES)
    data = _call(prompt, search=True)
    ideas = []
    for it in (data.get("ideas") or [])[:5]:
        scenes = [{
            "time": str(s.get("time", "")).strip()[:20],
            "visual": str(s.get("visual", "")).strip()[:600],
            "dialogue": str(s.get("dialogue", "")).strip()[:400],
            "on_screen_text": str(s.get("on_screen_text", "")).strip()[:120],
            "ai_prompt": str(s.get("ai_prompt", "")).strip()[:1200],
        } for s in (it.get("scenes") or [])[:12] if isinstance(s, dict)]
        if not scenes:
            continue
        ideas.append({
            "title": str(it.get("title", "")).strip()[:120] or "Kịch bản",
            "hook": str(it.get("hook", "")).strip()[:300],
            "twist": str(it.get("twist", "")).strip()[:300],
            "characters": _strs(it.get("characters"), 6, 200),
            "scenes": scenes,
            "caption": str(it.get("caption", "")).strip()[:300],
            "hashtags": _tags(it.get("hashtags")),
            "notes": _strs(it.get("notes"), 6, 300),
        })
    if not ideas:
        raise ScriptError("AI chưa viết được kịch bản, hãy thử lại hoặc đổi chủ đề.")
    return {"trend_note": str(data.get("trend_note", "")).strip()[:500], "ideas": ideas}


# ---------------------------------------------------------------- content check

# Words that often get TikTok / TikTok Shop posts limited in Vietnam: absolute
# claims, health/finance promises, sending viewers off the platform. This is a
# quick heuristic, not TikTok's official list.
RISKY_WORDS = [
    ("rẻ nhất", "Khẳng định tuyệt đối – nên nói “giá tốt”, “giá ưu đãi”."),
    ("tốt nhất", "Khẳng định tuyệt đối – nên nói “được nhiều người chọn”."),
    ("số 1", "Khẳng định tuyệt đối khi không có chứng nhận."),
    ("100%", "Cam kết tuyệt đối dễ bị coi là gây hiểu lầm."),
    ("cam kết", "Hứa hẹn kết quả dễ bị coi là gây hiểu lầm."),
    ("bảo hành trọn đời", "Hứa hẹn khó chứng minh."),
    ("chữa khỏi", "Tuyên bố chữa bệnh – bị hạn chế mạnh."),
    ("trị dứt điểm", "Tuyên bố chữa bệnh – bị hạn chế mạnh."),
    ("giảm cân cấp tốc", "Nội dung sức khoẻ/giảm cân bị hạn chế."),
    ("thuốc", "Nội dung thuốc/dược phẩm bị kiểm duyệt chặt."),
    ("làm giàu nhanh", "Hứa hẹn tài chính – dễ bị coi là lừa đảo."),
    ("kiếm tiền dễ", "Hứa hẹn tài chính – dễ bị coi là lừa đảo."),
    ("lãi suất", "Nội dung tài chính bị kiểm duyệt chặt."),
    ("inbox", "Kéo người xem ra khỏi TikTok – dễ bị bóp tương tác."),
    ("ib", "Kéo người xem ra khỏi TikTok – dễ bị bóp tương tác."),
    ("zalo", "Kéo người xem sang nền tảng khác – dễ bị bóp tương tác."),
    ("facebook", "Kéo người xem sang nền tảng khác – dễ bị bóp tương tác."),
    ("shopee", "Nhắc sàn khác – TikTok Shop thường hạn chế."),
    ("lazada", "Nhắc sàn khác – TikTok Shop thường hạn chế."),
    ("số điện thoại", "Thông tin liên hệ ngoài nền tảng – dễ bị hạn chế."),
    ("sđt", "Thông tin liên hệ ngoài nền tảng – dễ bị hạn chế."),
    ("follow để", "Câu xin follow/like lộ liễu (engagement bait) có thể bị giảm đề xuất."),
    ("like và share", "Câu xin like/share lộ liễu (engagement bait) có thể bị giảm đề xuất."),
    ("máu", "Từ ngữ bạo lực – nội dung có thể bị giới hạn độ tuổi."),
    ("giết", "Từ ngữ bạo lực – nội dung có thể bị giới hạn độ tuổi."),
    ("đâm chém", "Từ ngữ bạo lực – nội dung có thể bị giới hạn độ tuổi."),
]
PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.-]?\d){8,10}(?!\d)")
URL_RE = re.compile(r"(https?://|www\.)\S+", re.I)


def quick_check(text: str) -> list[dict]:
    """Instant, offline heuristic flags shown before (or without) the AI review."""
    low = text.lower()
    found = []
    for word, why in RISKY_WORDS:
        if re.search(rf"(?<![\wÀ-ỹ]){re.escape(word)}(?![\wÀ-ỹ])", low):
            found.append({"word": word, "why": why})
    if PHONE_RE.search(text):
        found.append({"word": "số điện thoại", "why": "Có số điện thoại – TikTok thường hạn chế bài kéo người xem ra ngoài."})
    if URL_RE.search(text):
        found.append({"word": "đường link", "why": "Có link ngoài trong caption – thường bị giảm đề xuất."})
    return found


CHECK_PROMPT = """Bạn là chuyên gia tối ưu nội dung TikTok ở Việt Nam. Hãy đánh giá nội dung sau (caption hoặc kịch bản video):
---
{text}
---
Loại nội dung: {kind}. {extra}

{safety}

Trả về DUY NHẤT một khối JSON:
{{
  "scores": {{"hook": 0-10, "originality": 0-10, "emotion": 0-10, "clarity": 0-10, "cta": 0-10, "safety": 0-10}},
  "summary": "nhận xét chung 1-2 câu",
  "issues": [{{"type": "tu_cam|gay_hieu_lam|nguoi_that|bao_luc|ban_quyen|nhan_ai|nham_chan|khac", "text": "đoạn có vấn đề", "why": "vì sao", "fix": "nên sửa thế nào"}}],
  "needs_ai_label": true/false,
  "rewrites": ["2-3 phiên bản viết lại hay hơn, an toàn hơn, giữ ý chính"],
  "hook_ideas": ["3 câu mở đầu 3 giây mạnh hơn"],
  "hashtags": ["6-10 hashtag phù hợp, viết liền không dấu"]
}}
"safety": 10 là an toàn, thấp là dễ bị hạn chế. "originality" thấp nếu nội dung giống khuôn mẫu đại trà."""

SCORE_KEYS = ("hook", "originality", "emotion", "clarity", "cta", "safety")


def check_content(text: str, kind: str = "caption", ai_made: bool = False) -> dict:
    text = text.strip()
    if not text:
        raise ScriptError("Hãy dán caption hoặc kịch bản cần kiểm tra.")
    extra = "Video này có dùng AI tạo hình/giọng hoặc là cảnh dàn dựng." if ai_made else ""
    data = _call(CHECK_PROMPT.format(text=text[:6000], kind="kịch bản video" if kind == "script" else "caption",
                                     extra=extra, safety=SAFETY_RULES), temperature=0.7)
    scores = {}
    for k in SCORE_KEYS:
        try:
            scores[k] = max(0, min(10, round(float((data.get("scores") or {}).get(k, 0)))))
        except (TypeError, ValueError):
            scores[k] = 0
    issues = [{
        "type": str(i.get("type", "khac")).strip()[:30],
        "text": str(i.get("text", "")).strip()[:300],
        "why": str(i.get("why", "")).strip()[:300],
        "fix": str(i.get("fix", "")).strip()[:300],
    } for i in (data.get("issues") or [])[:10] if isinstance(i, dict)]
    return {
        "scores": scores,
        "overall": round(sum(scores.values()) / len(scores), 1),
        "summary": str(data.get("summary", "")).strip()[:400],
        "issues": issues,
        "needs_ai_label": bool(data.get("needs_ai_label", ai_made)) or ai_made,
        "rewrites": _strs(data.get("rewrites"), 3, 2000),
        "hook_ideas": _strs(data.get("hook_ideas"), 3, 200),
        "hashtags": _tags(data.get("hashtags")),
        "quick": quick_check(text),
    }


# ---------------------------------------------------------------- content calendar

PLAN_PROMPT = """Bạn là người lập kế hoạch nội dung TikTok cho kênh ở Việt Nam.
Chủ đề/lĩnh vực kênh: {topic}
Các thể loại muốn làm: {formats}
Lập kế hoạch {days} ngày, mỗi ngày {per_day} video, bắt đầu từ {start} (hôm nay là {today}).
Xen kẽ thể loại để không nhàm; ngày cuối tuần nên có video mạnh nhất; giờ đăng theo thói quen xem TikTok ở Việt Nam (trưa 11h-13h, chiều 17h-18h30, tối 19h30-22h30).

{safety}

Trả về DUY NHẤT một khối JSON:
{{"items": [{{"day": 1, "time": "HH:MM", "format": "thể loại", "title": "tên video", "hook": "câu mở đầu 3 giây", "goal": "mục tiêu: view / tương tác / bán hàng / follow"}}]}}"""


def generate_plan(topic: str, formats: list[str], days: int, per_day: int, start: str) -> dict:
    days = 7 if int(days) not in (7, 14, 30) else int(days)
    per_day = max(1, min(int(per_day), 3))
    try:
        start_day = datetime.strptime(start, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        start_day = (datetime.now() + timedelta(days=1)).date()
    names = [FORMATS[f] for f in formats if f in FORMATS and f != "custom"] or list(FORMATS.values())[:5]
    data = _call(PLAN_PROMPT.format(topic=topic.strip() or "giải trí, phim ngắn", formats=", ".join(names),
                                    days=days, per_day=per_day, start=start_day.strftime("%d/%m/%Y"),
                                    today=datetime.now().strftime("%d/%m/%Y"), safety=SAFETY_RULES))
    items = []
    for it in (data.get("items") or [])[: days * per_day]:
        try:
            d = max(1, min(int(it.get("day", 1)), days))
        except (TypeError, ValueError):
            continue
        t = str(it.get("time", "19:30")).strip()
        if not re.fullmatch(r"\d{1,2}:\d{2}", t):
            t = "19:30"
        hh, mm = map(int, t.split(":"))
        when = datetime.combine(start_day + timedelta(days=d - 1), datetime.min.time()).replace(
            hour=min(hh, 23), minute=min(mm, 59))
        items.append({"day": d, "at": when.strftime("%Y-%m-%dT%H:%M"),
                      "format": str(it.get("format", "")).strip()[:80],
                      "title": str(it.get("title", "")).strip()[:150],
                      "hook": str(it.get("hook", "")).strip()[:250],
                      "goal": str(it.get("goal", "")).strip()[:80]})
    if not items:
        raise ScriptError("AI chưa lập được lịch, hãy thử lại.")
    items.sort(key=lambda x: x["at"])
    return {"days": days, "per_day": per_day, "start": start_day.isoformat(), "items": items}


def plan_ics(items: list[dict]) -> str:
    """One calendar file with a reminder for every planned video."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    esc = lambda s: str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")  # noqa: E731
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TikTok Studio AI//Content//VN"]
    for i, it in enumerate(items[:200]):
        try:
            at = datetime.strptime(it["at"], "%Y-%m-%dT%H:%M")
        except (KeyError, ValueError):
            continue
        desc = f"Thể loại: {it.get('format', '')}\nMở đầu: {it.get('hook', '')}\nMục tiêu: {it.get('goal', '')}"
        lines += ["BEGIN:VEVENT", f"UID:{stamp}-{i}@tiktok-studio-ai", f"DTSTAMP:{stamp}",
                  f"DTSTART:{at:%Y%m%dT%H%M%S}", f"DTEND:{at + timedelta(minutes=15):%Y%m%dT%H%M%S}",
                  f"SUMMARY:{esc('🎬 ' + it.get('title', 'Đăng video TikTok'))}", f"DESCRIPTION:{esc(desc)}",
                  "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Sắp đến giờ đăng TikTok!", "TRIGGER:-PT30M",
                  "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
