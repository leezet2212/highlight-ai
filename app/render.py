"""Turn (video + commentary script) into the final social-media video.

Layout: the whole game screen is always kept visible. When the source does not
match the output frame (e.g. a landscape Liên Quân recording exported as 9:16
for TikTok), the video is fitted inside the frame and the empty area is filled
with a blurred, zoomed copy of the same video. Subtitles go into that empty
area so they never cover the game HUD.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

from .media import MediaError, VideoInfo, audio_duration, image_size, run, video_encoders
from .styles import edge_rate
from .tts import synthesize

MAX_SPEEDUP = 1.35        # never speed speech up more than this to fit a slot
MAX_TAIL = 4.0            # seconds the last frame may be held for a long final line
GAP = 0.12                # minimum silence between two lines
DEFAULT_VOICE = "vi-VN-NamMinhNeural"


def even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def frame_size(aspect: str, info: VideoInfo) -> tuple[int, int]:
    if aspect == "9:16":
        return 1080, 1920
    if aspect == "16:9":
        return 1920, 1080
    if aspect == "1:1":
        return 1080, 1080
    scale = min(1.0, 1920 / max(info.width, info.height))
    return even(info.width * scale), even(info.height * scale)


def layout(aspect: str, info: VideoInfo) -> dict:
    W, H = frame_size(aspect, info)
    s = min(W / info.width, H / info.height)
    fw, fh = min(W, even(info.width * s)), min(H, even(info.height * s))
    fx, fy = (W - fw) // 2, (H - fh) // 2
    return {"W": W, "H": H, "fw": fw, "fh": fh, "fx": fx, "fy": fy,
            "blur": fw < W - 2 or fh < H - 2}


# ---------------------------------------------------------------- subtitles

def ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def chunk_words(text: str, max_words: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    n = math.ceil(len(words) / max_words)
    size = math.ceil(len(words) / n)
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


def subtitle_cues(lines: list[dict], max_words: int) -> list[tuple[float, float, str]]:
    """Split each spoken line into short on-screen chunks timed by length."""
    cues = []
    for ln in lines:
        chunks = chunk_words(ln["text"], max_words)
        total = sum(len(c) for c in chunks) or 1
        t = ln["start"]
        for c in chunks:
            d = (ln["end"] - ln["start"]) * len(c) / total
            cues.append((t, t + d, c))
            t += d
    return cues


def write_ass(path: Path, cues, lay: dict, title: str, total: float, font: str,
              mark: dict | None = None) -> None:
    W, H = lay["W"], lay["H"]
    portrait = H > W
    size = round((0.034 if portrait else 0.05) * H)
    bottom_space = H - (lay["fy"] + lay["fh"])
    if bottom_space >= size * 3:
        # Subtitles sit in the blurred band under the game screen.
        align, margin_v = 8, lay["fy"] + lay["fh"] + round(bottom_space * 0.18)
    else:
        align, margin_v = 2, round(H * 0.07)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},{size},&H00FFFFFF,&H0000FFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{max(3, size // 12)},2,{align},{round(W * 0.06)},{round(W * 0.06)},{margin_v},1
Style: Title,{font},{round(size * 1.15)},&H0000E5FF,&H0000FFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{max(3, size // 10)},2,5,{round(W * 0.05)},{round(W * 0.05)},0,1
Style: Mark,{font},{round(size * 0.72)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{max(2, size // 18)},1,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    if title.strip():
        cy = lay["fy"] // 2 if lay["fy"] >= size * 3 else round(H * 0.08)
        events.append(f"Dialogue: 1,{ass_time(0)},{ass_time(total)},Title,,0,0,0,,"
                      f"{{\\pos({W // 2},{cy})}}{ass_escape(title.strip())}")
    if mark and mark.get("text"):
        # Channel signature in a corner; alpha byte: 00 = opaque, FF = invisible.
        alpha = f"{round(255 * (1 - mark['opacity'])):02X}"
        events.append(f"Dialogue: 2,{ass_time(0)},{ass_time(total)},Mark,,0,0,0,,"
                      f"{{\\an{mark['an']}\\pos({mark['x']},{mark['y']})\\alpha&H{alpha}&}}"
                      f"{ass_escape(mark['text'])}")
    for start, end, text in cues:
        # Small pop-in animation for each chunk.
        anim = "{\\fscx85\\fscy85\\t(0,120,\\fscx100\\fscy100)}"
        events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{anim}{ass_escape(text)}")
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def write_srt(path: Path, lines: list[dict]) -> None:
    out = []
    for i, ln in enumerate(lines, 1):
        out.append(f"{i}\n{srt_time(ln['start'])} --> {srt_time(ln['end'])}\n{ln['text']}\n")
    path.write_text("\n".join(out), encoding="utf-8")


# ---------------------------------------------------------------- picture options

CORNERS = {"tl", "tr", "bl", "br"}
ENHANCE_PRE = "hqdn3d=1.5:1.5:6:6"            # light denoise before upscaling
ENHANCE_POST = "unsharp=5:5:0.9:5:5:0.0"      # then sharpen edges


def floor_even(x: float) -> int:
    return max(0, int(x) // 2 * 2)


def blur_box_px(box: dict, w: int, h: int) -> tuple[int, int, int, int] | None:
    """Box given as fractions of the source frame → even pixel rect, or None if too small."""
    try:
        fx, fy = (min(max(float(box[k]), 0.0), 1.0) for k in ("x", "y"))
        fw, fh = (min(max(float(box[k]), 0.0), 1.0) for k in ("w", "h"))
    except (KeyError, TypeError, ValueError):
        return None
    x, y = floor_even(fx * w), floor_even(fy * h)
    bw, bh = floor_even(min(fw, 1 - fx) * w), floor_even(min(fh, 1 - fy) * h)
    bw, bh = min(bw, w - x), min(bh, h - y)
    if bw < 8 or bh < 8:
        return None
    return x, y, bw, bh


def mark_position(lay: dict, corner: str, logo_h: int, logo_w: int) -> dict:
    """Where the logo (top-left px) and the text signature (ASS \\an + \\pos) go."""
    W, H = lay["W"], lay["H"]
    m = round(min(W, H) * 0.035)
    gap = round(m * 0.4)
    left, top = corner in ("tl", "bl"), corner in ("tl", "tr")
    logo_x = m if left else W - m - logo_w
    logo_y = m if top else H - m - logo_h
    tx = m if left else W - m
    if top:
        ty, an = m + (logo_h + gap if logo_h else 0), 7 if left else 9
    else:
        ty, an = H - m - (logo_h + gap if logo_h else 0), 1 if left else 3
    return {"logo_x": logo_x, "logo_y": logo_y, "x": tx, "y": ty, "an": an}


def build_video_filter(lay: dict, info: VideoInfo, *, enhance: bool, blur_boxes: list,
                       logo: dict | None, tail: float, use_ass: bool) -> str:
    """ffmpeg filtergraph producing [vout]. Input 0 = video, input 2 = logo (if any)."""
    W, H, fw, fh, fx, fy = (lay[k] for k in ("W", "H", "fw", "fh", "fx", "fy"))
    parts, cur = [], "0:v"

    # 1. Blur the user's boxes on the source frame, so they follow the video into any layout.
    for i, box in enumerate(blur_boxes[:10]):
        px = blur_box_px(box, info.width, info.height)
        if not px:
            continue
        x, y, bw, bh = px
        r = max(1, min(24, bw // 4, bh // 4))     # chroma plane is half size: radius <= w/4
        parts.append(f"[{cur}]split=2[bm{i}][bc{i}];[bc{i}]crop={bw}:{bh}:{x}:{y},"
                     f"boxblur={r}:3[bb{i}];[bm{i}][bb{i}]overlay={x}:{y}[bs{i}]")
        cur = f"bs{i}"

    # 2. Fit into the output frame (sharpened if asked), blurred copy as background.
    pre = f"{ENHANCE_PRE}," if enhance else ""
    post = f",{ENHANCE_POST}" if enhance else ""
    if lay["blur"]:
        bw, bh = even(W / 4), even(H / 4)
        parts.append(f"[{cur}]split=2[bgs][fgs];"
                     f"[bgs]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
                     f"boxblur=10:2,eq=brightness=-0.12:saturation=1.3,scale={W}:{H}[bg];"
                     f"[fgs]{pre}scale={fw}:{fh}:flags=lanczos{post}[fg];"
                     f"[bg][fg]overlay={fx}:{fy},setsar=1[base]")
    else:
        parts.append(f"[{cur}]{pre}scale={W}:{H}:flags=lanczos{post},setsar=1[base]")
    cur = "base"

    # 3. Logo.
    if logo:
        parts.append(f"[2:v]scale={logo['w']}:{logo['h']}:flags=lanczos,format=rgba,"
                     f"colorchannelmixer=aa={logo['opacity']:.2f}[logo];"
                     f"[{cur}][logo]overlay={logo['x']}:{logo['y']}:format=auto[lg]")
        cur = "lg"

    # 4. Hold the last frame for a long final line, then text (subs, title, signature).
    chain = []
    if tail > 0.05:
        chain.append(f"tpad=stop_mode=clone:stop_duration={tail:.3f}")
    if use_ass:
        chain.append("ass=subs.ass")
    chain.append("format=yuv420p")
    parts.append(f"[{cur}]" + ",".join(chain) + "[vout]")
    return ";".join(parts)


# ---------------------------------------------------------------- pipeline

VOICE_PROVIDERS = {"edge", "elevenlabs", "_test"}


def line_voice_of(seg: dict, provider: str, voice_id: str) -> tuple[str, str]:
    """Per-line voice override if the line has a valid one, else the default voice."""
    p, v = str(seg.get("provider") or "").strip(), str(seg.get("voice_id") or "").strip()
    if p in VOICE_PROVIDERS and v:
        return p, v
    return provider, voice_id


def render(job_dir: Path, src: Path, info: VideoInfo, segments: list[dict], opts: dict,
           on_progress=lambda msg: None) -> dict:
    provider = opts.get("provider", "edge")
    voice_id = opts.get("voice_id") or DEFAULT_VOICE
    rate = opts.get("rate") or edge_rate(opts.get("style", ""))
    aspect = opts.get("aspect", "9:16")
    game_volume = float(opts.get("game_volume", 0.35))
    voice_volume = float(opts.get("voice_volume", 1.0))
    duck = bool(opts.get("duck", True))
    # "Tắt hẳn tiếng gốc": drop the video's own audio track entirely.
    keep_original = info.has_audio and not bool(opts.get("mute_original", False))
    subtitles = bool(opts.get("subtitles", True))
    title = str(opts.get("title", ""))
    font = os.getenv("SUBTITLE_FONT", "Arial")
    enhance = bool(opts.get("enhance", False))
    blur_boxes = [b for b in (opts.get("blur_boxes") or []) if isinstance(b, dict)]
    mark_text = str(opts.get("watermark_text", "")).strip()[:60]
    corner = opts.get("watermark_pos") if opts.get("watermark_pos") in CORNERS else "tr"
    mark_opacity = min(max(float(opts.get("watermark_opacity", 0.85)), 0.15), 1.0)
    logo_path = opts.get("logo_path")             # set by the server when "use logo" is on
    logo_size = min(max(float(opts.get("logo_size", 0.16)), 0.05), 0.4)

    segs = sorted([s for s in segments if str(s.get("text", "")).strip()],
                  key=lambda s: float(s["start"]))
    if not segs:
        raise ValueError("Kịch bản trống – hãy thêm ít nhất một câu bình luận.")

    voice_dir = job_dir / "voice"
    voice_dir.mkdir(exist_ok=True)
    for f in voice_dir.glob("*"):
        f.unlink()

    # 1. Speech for each line.
    clips = []
    for i, s in enumerate(segs):
        on_progress(f"Đang tạo giọng đọc {i + 1}/{len(segs)}...")
        out = voice_dir / f"{i:03d}.mp3"
        # A line may use its own voice (e.g. two commentators); otherwise the global one.
        line_provider, line_voice = line_voice_of(s, provider, voice_id)
        synthesize(line_provider, s["text"].strip(), line_voice, out, rate)
        clips.append(out)

    # 2. Fit each line to its slot: speed up a little if needed, otherwise
    #    push the next line later so voices never overlap.
    lines, cursor = [], 0.0
    for i, (s, clip) in enumerate(zip(segs, clips)):
        dur = audio_duration(clip)
        start = max(float(s["start"]), cursor)
        slot_end = float(segs[i + 1]["start"]) if i + 1 < len(segs) else info.duration
        avail = max(0.3, slot_end - start - GAP)
        tempo = min(MAX_SPEEDUP, dur / avail) if dur > avail else 1.0
        spoken = dur / tempo
        lines.append({"start": start, "end": start + spoken, "tempo": tempo,
                      "clip": clip, "text": s["text"].strip()})
        cursor = start + spoken + GAP

    total = max(info.duration, min(lines[-1]["end"] + 0.3, info.duration + MAX_TAIL))

    # 3. One voice track.
    on_progress("Đang ghép các câu bình luận...")
    voice_wav = job_dir / "voice.wav"
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for ln in lines:
        cmd += ["-i", str(ln["clip"])]
    parts = []
    for i, ln in enumerate(lines):
        ms = int(ln["start"] * 1000)
        parts.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo,"
                     f"atempo={ln['tempo']:.4f},adelay={ms}:all=1[a{i}]")
    mix_in = "".join(f"[a{i}]" for i in range(len(lines)))
    parts.append(f"{mix_in}amix=inputs={len(lines)}:normalize=0:duration=longest,"
                 f"apad,atrim=0:{total:.3f}[v]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", str(voice_wav)]
    run(cmd)

    # 4. Subtitles, title, signature.
    lay = layout(aspect, info)
    logo = None
    if logo_path and Path(logo_path).exists():
        lw_src, lh_src = image_size(Path(logo_path))
        lw = even(min(lay["W"], lay["H"]) * logo_size * (1.0 if lay["H"] >= lay["W"] else 1.2))
        lh = even(lw * lh_src / max(1, lw_src))
        logo = {"w": lw, "h": lh, "opacity": mark_opacity}
    pos = mark_position(lay, corner, logo["h"] if logo else 0, logo["w"] if logo else 0)
    if logo:
        logo.update(x=pos["logo_x"], y=pos["logo_y"])
    mark = {"text": mark_text, "opacity": mark_opacity, **pos} if mark_text else None
    use_ass = subtitles or bool(title.strip()) or bool(mark)
    if use_ass:
        cues = subtitle_cues(lines, 6 if lay["H"] > lay["W"] else 9) if subtitles else []
        write_ass(job_dir / "subs.ass", cues, lay, title, total, font, mark)
    write_srt(job_dir / "output.srt", lines)

    # 5. Final video.
    on_progress("Đang xuất video (bước này hơi lâu)...")
    W, H = lay["W"], lay["H"]
    v = build_video_filter(lay, info, enhance=enhance, blur_boxes=blur_boxes, logo=logo,
                           tail=total - info.duration, use_ass=use_ass)

    if keep_original:
        a = (f"[0:a]aresample=44100,aformat=channel_layouts=stereo,volume={game_volume:.3f},apad[game];"
             f"[1:a]volume={voice_volume:.3f},asplit=2[vo1][vo2];")
        if duck:
            a += "[game][vo1]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=400[gd];"
        else:
            a += "[game]anull[gd];[vo1]anullsink;"
        a += "[gd][vo2]amix=inputs=2:normalize=0:duration=longest,alimiter=limit=0.95[aout]"
    else:
        a = f"[1:a]volume={voice_volume:.3f},alimiter=limit=0.95[aout]"

    output = job_dir / "output.mp4"
    encoders = video_encoders()
    for idx, (encoder, enc_args) in enumerate(encoders):
        try:
            run([
                "ffmpeg", "-y", "-v", "error", "-i", str(src), "-i", voice_wav.name,
                *(["-i", str(logo_path)] if logo else []),
                "-filter_complex", v + ";" + a,
                "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}",
                "-c:v", encoder, *enc_args,
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", output.name,
            ], cwd=job_dir)
            break
        except MediaError:
            if idx == len(encoders) - 1:
                raise
            # GPU encoder failed on this video (driver/size limits): use the CPU.
            on_progress("Card đồ hoạ lỗi, đang xuất lại bằng CPU...")

    return {"width": W, "height": H, "duration": round(total, 2), "encoder": encoder,
            "lines": [{k: (round(v, 2) if isinstance(v, float) else v)
                       for k, v in ln.items() if k != "clip"} for ln in lines]}
