"""Video/audio helpers built on ffmpeg/ffprobe."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(RuntimeError):
    pass


def run(cmd: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise MediaError(f"Lệnh {cmd[0]} thất bại:\n{tail}")
    return proc.stdout


@dataclass
class VideoInfo:
    width: int
    height: int
    duration: float
    has_audio: bool

    @property
    def is_landscape(self) -> bool:
        return self.width >= self.height

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "duration": round(self.duration, 2),
            "has_audio": self.has_audio,
            "orientation": "ngang" if self.is_landscape else "dọc",
        }


def probe(path: Path) -> VideoInfo:
    out = run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ])
    data = json.loads(out)
    vstreams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if not vstreams:
        raise MediaError("File không có hình ảnh video.")
    v = vstreams[0]
    w, h = int(v["width"]), int(v["height"])

    # Phone recordings often store a rotation flag instead of rotated pixels.
    # ffmpeg auto-rotates when decoding, so report the size as displayed.
    rotation = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(float(sd["rotation"]))
    if not rotation and "rotate" in v.get("tags", {}):
        rotation = int(v["tags"]["rotate"])
    if abs(rotation) % 180 == 90:
        w, h = h, w

    duration = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    return VideoInfo(w, h, duration, has_audio)


def image_size(path: Path) -> tuple[int, int]:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=width,height", "-of", "csv=p=0:s=x", str(path)])
    w, h = out.strip().split("x")[:2]
    return int(w), int(h)


def save_logo(src: Path, dst: Path) -> None:
    """Normalise an uploaded logo (png/jpg/webp...) to a PNG of at most 800px."""
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-frames:v", "1",
         "-vf", "scale='min(800,iw)':-2:flags=lanczos,format=rgba", str(dst)])


def audio_duration(path: Path) -> float:
    out = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ])
    return float(out.strip())


# Hardware H.264 encoders, fastest first. Each entry: (encoder, quality args).
# ffmpeg often lists encoders the machine has no hardware for, so every
# candidate is verified with a tiny test encode before it is used.
HW_ENCODERS = [
    ("h264_nvenc", ["-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"]),           # NVIDIA
    ("h264_qsv", ["-preset", "faster", "-global_quality", "21"]),                        # Intel
    ("h264_amf", ["-quality", "balanced", "-rc", "cqp", "-qp_i", "21", "-qp_p", "23"]),  # AMD
    ("h264_videotoolbox", ["-q:v", "65"]),                                               # macOS
]
_encoder_cache: list[tuple[str, list[str]]] | None = None


def software_encoder() -> tuple[str, list[str]]:
    preset = os.getenv("VIDEO_PRESET", "veryfast")
    return "libx264", ["-preset", preset, "-crf", "20"]


def _encoder_works(name: str, args: list[str]) -> bool:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.2",
         "-c:v", name, *args, "-pix_fmt", "yuv420p", "-f", "null", "-"],
        capture_output=True, timeout=30,
    )
    return proc.returncode == 0


def video_encoders() -> list[tuple[str, list[str]]]:
    """Encoders to try for the final video, best first; libx264 is always last.

    VIDEO_ENCODER=auto (default) picks a working GPU encoder if there is one;
    set it to e.g. libx264 or h264_nvenc to force a choice.
    """
    global _encoder_cache
    if _encoder_cache is not None:
        return _encoder_cache
    choice = os.getenv("VIDEO_ENCODER", "auto").strip() or "auto"
    found: list[tuple[str, list[str]]] = []
    if choice != "libx264":
        for name, args in HW_ENCODERS:
            if choice not in ("auto", name):
                continue
            try:
                if _encoder_works(name, args):
                    found.append((name, args))
                    break
            except Exception:
                pass
    found.append(software_encoder())
    _encoder_cache = found
    print(f"[highlight-ai] Bộ mã hoá video: {found[0][0]}")
    return found


def make_preview(src: Path, dst: Path) -> None:
    """Browser-friendly H.264 copy used in the editor (small and fast)."""
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-vf", "scale='min(960,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "28", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dst),
    ])
