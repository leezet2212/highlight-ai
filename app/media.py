"""Video/audio helpers built on ffmpeg/ffprobe."""
from __future__ import annotations

import json
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


def audio_duration(path: Path) -> float:
    out = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ])
    return float(out.strip())


def make_preview(src: Path, dst: Path) -> None:
    """Browser-friendly H.264 copy used in the editor (small and fast)."""
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-vf", "scale='min(960,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "28", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dst),
    ])
