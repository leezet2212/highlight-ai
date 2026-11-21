"""👗 Video Thời Trang: clothes photos + model photo + dance video → AI try-on
images, a text-free 9:16 product video in the chosen lengths, and TikTok
captions / hashtags / trend and posting-time suggestions.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .media import MediaError, VideoInfo, image_size, probe, run, video_encoders
from .render import even, layout
from .script_ai import ScriptError, _client, gemini_error_message

FPS = 30
W, H = 1080, 1920
MAX_CLOTHES = 5
TRYON_HOLD = 1.0          # seconds a try-on photo is shown at the start/end of the video

# Good posting windows for a Vietnamese TikTok audience (local time). These are
# general habits, not live TikTok data – the AI adds context on top.
POSTING_WINDOWS = [
    {"label": "Trưa", "start": "11:00", "end": "13:00", "why": "Giờ nghỉ trưa, nhiều người lướt TikTok"},
    {"label": "Chiều tan làm", "start": "17:00", "end": "18:30", "why": "Trên đường về, giờ tan học/tan làm"},
    {"label": "Tối", "start": "19:30", "end": "22:30", "why": "Khung giờ đông người xem và mua sắm nhất"},
]


class FashionError(RuntimeError):
    pass


# ---------------------------------------------------------------- AI try-on

TRYON_PROMPT = """Ảnh đầu tiên là NGƯỜI MẪU. Các ảnh sau là SẢN PHẨM QUẦN ÁO cần mặc thử.
Hãy tạo một ảnh chụp thời trang CHÂN THỰC của chính người mẫu đó đang mặc đúng (các) sản phẩm trong ảnh:
- Giữ nguyên khuôn mặt, kiểu tóc, vóc dáng, màu da của người mẫu.
- Giữ đúng màu sắc, hoạ tiết, chất liệu, kiểu dáng của quần áo; sản phẩm phải là điểm nhấn.
- Ảnh dọc toàn thân, ánh sáng studio đẹp, phông nền đơn giản sạch sẽ, phong cách ảnh bán hàng TikTok Shop.
- Trang phục kín đáo, phù hợp mọi lứa tuổi. KHÔNG thêm chữ, logo hay watermark.
{extra}"""


def generate_tryon(model_photo: Path, clothes: list[Path], out_dir: Path, count: int = 1,
                   notes: str = "", on_progress=lambda m: None) -> list[str]:
    """Ask Gemini's image model for photos of the model wearing the clothes."""
    from google.genai import types

    if not clothes:
        raise FashionError("Hãy tải lên ít nhất một ảnh quần áo.")
    client = _client()
    model = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    parts = [types.Part.from_bytes(data=model_photo.read_bytes(), mime_type="image/png")]
    parts += [types.Part.from_bytes(data=c.read_bytes(), mime_type="image/png") for c in clothes]
    prompt = TRYON_PROMPT.format(extra=f"Yêu cầu thêm: {notes.strip()}" if notes.strip() else "")
    made = []
    for i in range(max(1, min(count, 3))):
        on_progress(f"AI đang mặc thử quần áo cho người mẫu ({i + 1}/{count})...")
        try:
            resp = client.models.generate_content(
                model=model, contents=[*parts, prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                    image_config=types.ImageConfig(aspect_ratio="9:16")),
            )
        except Exception as exc:
            raise FashionError(gemini_error_message(exc)) from exc
        image = None
        for cand in resp.candidates or []:
            for part in (cand.content.parts if cand.content else []) or []:
                if part.inline_data and part.inline_data.data:
                    image = part.inline_data.data
                    break
            if image:
                break
        if not image:
            raise FashionError("AI không tạo được ảnh mặc thử (có thể ảnh bị bộ lọc an toàn từ chối). "
                               "Hãy thử ảnh người mẫu rõ mặt, mặc đồ kín đáo, và ảnh quần áo chụp rõ.")
        raw = out_dir / f"tryon_raw_{i}.bin"
        raw.write_bytes(image)
        name = next_name(out_dir, "tryon", ".png")
        try:
            run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-frames:v", "1", str(out_dir / name)])
        finally:
            raw.unlink(missing_ok=True)
        made.append(name)
    return made


def next_name(folder: Path, prefix: str, ext: str) -> str:
    n = 1
    while (folder / f"{prefix}_{n}{ext}").exists():
        n += 1
    return f"{prefix}_{n}{ext}"


# ---------------------------------------------------------------- product video

def _fit_filter(src_w: int, src_h: int, label_in: str, label_out: str) -> str:
    """Fit any picture into 1080x1920 without cropping: blurred copy as background."""
    lay = layout("9:16", VideoInfo(src_w, src_h, 1.0, False))
    fw, fh, fx, fy = lay["fw"], lay["fh"], lay["fx"], lay["fy"]
    if not lay["blur"]:
        return f"[{label_in}]scale={W}:{H}:flags=lanczos,setsar=1[{label_out}]"
    bw, bh = even(W / 4), even(H / 4)
    return (f"[{label_in}]split=2[{label_out}b][{label_out}f];"
            f"[{label_out}b]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
            f"boxblur=10:2,eq=brightness=-0.1,scale={W}:{H}[{label_out}bg];"
            f"[{label_out}f]scale={fw}:{fh}:flags=lanczos[{label_out}fg];"
            f"[{label_out}bg][{label_out}fg]overlay={fx}:{fy},setsar=1[{label_out}]")


def plan_timeline(duration: float, tryon_at: str, has_tryon: bool) -> dict:
    """Seconds for each part. Very short videos give the photo less time."""
    hold = min(TRYON_HOLD, duration * 0.25) if has_tryon and tryon_at in ("start", "end", "both") else 0.0
    head = hold if tryon_at in ("start", "both") else 0.0
    tail = hold if tryon_at in ("end", "both") else 0.0
    return {"head": round(head, 3), "tail": round(tail, 3), "dance": round(duration - head - tail, 3)}


def render_product_video(work: Path, dance: Path, out_name: str, *, duration: float, start: float = 0.0,
                         tryon: Path | None = None, tryon_at: str = "start", pip: Path | None = None,
                         keep_audio: bool = True, enhance: bool = False) -> dict:
    """Text-free 9:16 video: [try-on photo] → dance clip (+ small product photo) → [try-on photo]."""
    info = probe(dance)
    duration = float(min(max(duration, 1.0), 60.0))
    plan = plan_timeline(duration, tryon_at, tryon is not None)
    start = max(0.0, min(float(start), max(0.0, info.duration - 0.5)))
    loop = start + plan["dance"] > info.duration + 0.01      # short clip → loop it

    inputs: list[str] = []
    if loop:
        inputs += ["-stream_loop", "-1"]
    inputs += ["-ss", f"{start:.3f}", "-i", str(dance)]
    idx = {"dance": 0}
    if tryon is not None and (plan["head"] or plan["tail"]):
        idx["tryon"] = _count_inputs(inputs)
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(tryon)]
    if pip is not None:
        idx["pip"] = _count_inputs(inputs)
        inputs += ["-i", str(pip)]

    f = []
    pre = "hqdn3d=1.5:1.5:6:6," if enhance else ""
    post = ",unsharp=5:5:0.8:5:5:0.0" if enhance else ""
    f.append(f"[0:v]{pre}fps={FPS},trim=duration={plan['dance']:.3f},setpts=PTS-STARTPTS{post}[dsrc]")
    f.append(_fit_filter(info.width, info.height, "dsrc", "dfit"))
    cur = "dfit"
    if pip is not None:
        pw, ph = image_size(pip)
        cw = even(W * 0.28)
        ch = even(cw * ph / max(1, pw))
        if ch > H * 0.3:
            ch = even(H * 0.3)
            cw = even(ch * pw / max(1, ph))
        b = 8
        f.append(f"[{idx['pip']}:v]scale={cw}:{ch}:flags=lanczos,pad={cw + 2 * b}:{ch + 2 * b}:{b}:{b}:white,"
                 f"format=rgba[pipimg]")
        f.append(f"[{cur}][pipimg]overlay={W - cw - 2 * b - 40}:{H - ch - 2 * b - 260}:format=auto[dpip]")
        cur = "dpip"
    parts = []
    if "tryon" in idx:
        tw, th = image_size(tryon)
        f.append(f"[{idx['tryon']}:v]trim=duration={max(plan['head'], plan['tail']) + 0.1:.3f},setpts=PTS-STARTPTS[tsrc]")
        f.append(_fit_filter(tw, th, "tsrc", "tfit"))
        # Slow zoom so the photo doesn't feel frozen.
        f.append(f"[tfit]scale={even(W * 1.06)}:{even(H * 1.06)},crop={W}:{H}:"
                 f"(iw-ow)/2*(1-t/{max(plan['head'], plan['tail']) + 0.1:.3f}):(ih-oh)/2,setsar=1[tzoom]")
        splits = [n for n in ("head", "tail") if plan[n]]
        if len(splits) == 2:
            f.append("[tzoom]split=2[thead0][ttail0]")
            names = {"head": "thead0", "tail": "ttail0"}
        else:
            names = {splits[0]: "tzoom"}
        for n in splits:
            f.append(f"[{names[n]}]trim=duration={plan[n]:.3f},setpts=PTS-STARTPTS,fps={FPS}[t{n}]")
        if plan["head"]:
            parts.append("thead")
        parts.append(cur)
        if plan["tail"]:
            parts.append("ttail")
    else:
        parts.append(cur)

    # Audio: the dance clip's own sound (or silence) under the dance part only.
    has_audio = keep_audio and info.has_audio
    silence = "anullsrc=r=44100:cl=stereo"
    a_parts = []
    for p in parts:
        seg = plan["dance"] if p == cur else plan["head" if p == "thead" else "tail"]
        lbl = f"a_{p}"
        if p == cur and has_audio:
            f.append(f"[0:a]atrim=duration={seg:.3f},asetpts=PTS-STARTPTS,aresample=44100,"
                     f"aformat=channel_layouts=stereo[{lbl}]")
        else:
            f.append(f"{silence},atrim=duration={seg:.3f}[{lbl}]")
        a_parts.append(lbl)
    # concat needs identical size/format/fps on every part.
    norm = []
    for p in parts:
        f.append(f"[{p}]format=yuv420p,fps={FPS},setsar=1[n_{p}]")
        norm.append(f"n_{p}")
    concat_in = "".join(f"[{v}][{a}]" for v, a in zip(norm, a_parts))
    f.append(f"{concat_in}concat=n={len(parts)}:v=1:a=1[vc][ac]")
    f.append("[vc]format=yuv420p[vout]")

    out = work / out_name
    encoders = video_encoders()
    for i, (enc, enc_args) in enumerate(encoders):
        try:
            run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(f),
                 "-map", "[vout]", "-map", "[ac]", "-t", f"{duration:.3f}",
                 "-c:v", enc, *enc_args, "-r", str(FPS),
                 "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)])
            break
        except MediaError:
            if i == len(encoders) - 1:
                raise
    return {"file": out_name, "duration": duration, "plan": plan, "looped": loop}


def _count_inputs(args: list[str]) -> int:
    return sum(1 for a in args if a == "-i")


# ---------------------------------------------------------------- captions & trends

POSTS_PROMPT = """Bạn là chuyên gia bán hàng thời trang trên TikTok / TikTok Shop ở Việt Nam.
Các ảnh đính kèm là sản phẩm quần áo (và có thể có ảnh người mẫu mặc thử).
Thông tin người bán: {notes}
Hôm nay là {today}.

Hãy dùng Google Search để tham khảo xu hướng thời trang và TikTok gần đây ở Việt Nam, rồi trả về DUY NHẤT một khối JSON (không giải thích thêm) theo mẫu:
{{
  "product": "mô tả ngắn sản phẩm bạn nhìn thấy",
  "captions": ["3 caption TikTok khác nhau, ngắn (dưới 150 ký tự), gây tò mò, có câu kêu gọi mua/xem giỏ hàng, được dùng emoji"],
  "hashtags": ["8-12 hashtag: vài cái phổ biến (#fyp #xuhuong) + thời trang + đúng loại sản phẩm, viết liền không dấu"],
  "music": ["3-5 gợi ý KIỂU nhạc hoặc trend âm thanh đang hợp với video nhảy thời trang – người dùng sẽ tự chọn trong thư viện nhạc TikTok"],
  "trends": ["3-5 ý tưởng trend/format video đang hot có thể làm theo với sản phẩm này"],
  "best_times": ["2-3 khung giờ đăng nên chọn (giờ Việt Nam) kèm lý do ngắn"]
}}
Chỉ gợi ý điều bạn thấy hợp lý; nếu không chắc một trend còn hot hay không, hãy ghi rõ "nên kiểm tra lại"."""


def generate_posts(images: list[Path], notes: str) -> dict:
    from google.genai import types

    if not images:
        raise FashionError("Hãy tải lên ảnh quần áo trước khi tạo caption.")
    parts = [types.Part.from_bytes(data=p.read_bytes(), mime_type="image/png") for p in images[:6]]
    prompt = POSTS_PROMPT.format(notes=notes.strip() or "(không có)",
                                 today=datetime.now().strftime("%d/%m/%Y"))
    try:
        resp = _client().models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=[*parts, prompt],
            # Search grounding lets the model look at recent trends; it can't be
            # combined with a JSON schema, so the JSON is parsed from the text.
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())],
                                               temperature=0.9),
        )
    except Exception as exc:
        raise FashionError(gemini_error_message(exc)) from exc
    return normalize_posts(parse_json_block(resp.text or ""))


def parse_json_block(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise FashionError("AI không trả về gợi ý đúng định dạng, hãy thử lại.")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise FashionError("AI trả về gợi ý bị lỗi định dạng, hãy thử lại.") from exc


def _clean_tags(tags) -> list[str]:
    out, seen = [], set()
    for t in tags or []:
        t = "".join(ch for ch in str(t) if ch.isalnum() or ch == "_")
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append("#" + t)
    return out[:15]


def normalize_posts(data: dict) -> dict:
    lst = lambda k, n: [str(x).strip() for x in (data.get(k) or []) if str(x).strip()][:n]  # noqa: E731
    return {
        "product": str(data.get("product", "")).strip(),
        "captions": lst("captions", 5),
        "hashtags": _clean_tags(data.get("hashtags")),
        "music": lst("music", 6),
        "trends": lst("trends", 6),
        "best_times": lst("best_times", 4),
    }


# ---------------------------------------------------------------- posting reminder

def next_slots(now: datetime | None = None, days: int = 3) -> list[dict]:
    """Upcoming posting windows (local time), for the reminder picker."""
    now = now or datetime.now()
    slots = []
    for d in range(days):
        day = (now + timedelta(days=d)).date()
        for w in POSTING_WINDOWS:
            h, m = map(int, w["start"].split(":"))
            at = datetime(day.year, day.month, day.day, h, m)
            if at > now:
                slots.append({"at": at.strftime("%Y-%m-%dT%H:%M"), "label": w["label"], "why": w["why"],
                              "range": f"{w['start']}–{w['end']}"})
    return slots[:6]


def reminder_ics(at: datetime, title: str, description: str) -> str:
    """Calendar file that pops up a reminder at the chosen time (phone/PC calendar)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    start = at.strftime("%Y%m%dT%H%M%S")
    end = (at + timedelta(minutes=15)).strftime("%Y%m%dT%H%M%S")
    esc = lambda s: s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")  # noqa: E731
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TikTok Studio AI//VN", "BEGIN:VEVENT",
        f"UID:{stamp}-{start}@tiktok-studio-ai", f"DTSTAMP:{stamp}", f"DTSTART:{start}", f"DTEND:{end}",
        f"SUMMARY:{esc(title)}", f"DESCRIPTION:{esc(description)}",
        "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Đến giờ đăng TikTok!", "TRIGGER:-PT5M", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR", ""])
