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

from .media import MediaError, VideoInfo, audio_duration, run, video_encoders
from .styles import edge_rate
from .tts import synthesize

MAX_SPEEDUP = 1.35        # never speed speech up more than this to fit a slot
MAX_TAIL = 4.0            # seconds the last frame may be held for a long final line
GAP = 0.12                # minimum silence between two lines


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


def write_ass(path: Path, cues, lay: dict, title: str, total: float, font: str) -> None:
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

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    if title.strip():
        cy = lay["fy"] // 2 if lay["fy"] >= size * 3 else round(H * 0.08)
        events.append(f"Dialogue: 1,{ass_time(0)},{ass_time(total)},Title,,0,0,0,,"
                      f"{{\\pos({W // 2},{cy})}}{ass_escape(title.strip())}")
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


# ---------------------------------------------------------------- pipeline

def render(job_dir: Path, src: Path, info: VideoInfo, segments: list[dict], opts: dict,
           on_progress=lambda msg: None) -> dict:
    provider = opts.get("provider", "edge")
    voice_id = opts.get("voice_id") or "vi-VN-NamMinhNeural"
    rate = opts.get("rate") or edge_rate(opts.get("style", ""))
    aspect = opts.get("aspect", "9:16")
    game_volume = float(opts.get("game_volume", 0.35))
    voice_volume = float(opts.get("voice_volume", 1.0))
    duck = bool(opts.get("duck", True))
    subtitles = bool(opts.get("subtitles", True))
    title = str(opts.get("title", ""))
    font = os.getenv("SUBTITLE_FONT", "Arial")

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
        synthesize(provider, s["text"].strip(), voice_id, out, rate)
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

    # 4. Subtitles.
    lay = layout(aspect, info)
    if subtitles or title.strip():
        cues = subtitle_cues(lines, 6 if lay["H"] > lay["W"] else 9) if subtitles else []
        write_ass(job_dir / "subs.ass", cues, lay, title, total, font)
    write_srt(job_dir / "output.srt", lines)

    # 5. Final video.
    on_progress("Đang xuất video (bước này hơi lâu)...")
    W, H, fw, fh, fx, fy = (lay[k] for k in ("W", "H", "fw", "fh", "fx", "fy"))
    if lay["blur"]:
        bw, bh = even(W / 4), even(H / 4)
        v = (f"[0:v]split=2[bgs][fgs];"
             f"[bgs]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
             f"boxblur=10:2,eq=brightness=-0.12:saturation=1.3,scale={W}:{H}[bg];"
             f"[fgs]scale={fw}:{fh}[fg];[bg][fg]overlay={fx}:{fy},setsar=1")
    else:
        v = f"[0:v]scale={W}:{H},setsar=1"
    tail = total - info.duration
    if tail > 0.05:
        v += f",tpad=stop_mode=clone:stop_duration={tail:.3f}"
    if subtitles or title.strip():
        v += ",ass=subs.ass"
    v += ",format=yuv420p[vout]"

    if info.has_audio:
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
