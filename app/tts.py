"""Text-to-speech: ElevenLabs (paid / free tier) and Edge TTS (free)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

import httpx

EDGE_VOICES = [
    {"id": "vi-VN-NamMinhNeural", "name": "Nam Minh (nam) – Edge, miễn phí"},
    {"id": "vi-VN-HoaiMyNeural", "name": "Hoài My (nữ) – Edge, miễn phí"},
]

ELEVEN_URL = "https://api.elevenlabs.io/v1"

# Set by the server. Speech for the same (voice, text, speed) is made once and
# reused by both the per-line preview and the final render, so previewing a
# line never costs ElevenLabs characters twice.
CACHE_DIR: Path | None = None


class TTSError(RuntimeError):
    pass


def eleven_key() -> str:
    return os.getenv("ELEVENLABS_API_KEY", "").strip()


def list_voices() -> dict:
    voices = {"edge": EDGE_VOICES, "elevenlabs": [], "elevenlabs_error": None}
    key = eleven_key()
    if not key:
        voices["elevenlabs_error"] = "Chưa có ELEVENLABS_API_KEY trong .env"
        return voices
    try:
        r = httpx.get(f"{ELEVEN_URL}/voices", headers={"xi-api-key": key}, timeout=20)
        r.raise_for_status()
        voices["elevenlabs"] = [
            {"id": v["voice_id"], "name": f'{v["name"]} – ElevenLabs'}
            for v in r.json().get("voices", [])
        ]
    except Exception as exc:  # network / auth problems shouldn't break the page
        voices["elevenlabs_error"] = f"Không lấy được giọng ElevenLabs: {exc}"
    return voices


def synth_elevenlabs(text: str, voice_id: str, out: Path) -> None:
    key = eleven_key()
    if not key:
        raise TTSError("Chưa có ELEVENLABS_API_KEY trong file .env")
    model = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")
    body = {
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.35, "similarity_boost": 0.8, "style": 0.5},
    }
    # Multilingual v2.5 models accept an explicit language for better Vietnamese.
    if "v2_5" in model or "v3" in model:
        body["language_code"] = "vi"
    r = httpx.post(
        f"{ELEVEN_URL}/text-to-speech/{voice_id}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": key, "accept": "audio/mpeg"},
        json=body,
        timeout=120,
    )
    if r.status_code != 200:
        detail = r.text[:300]
        if r.status_code in (401, 403):
            raise TTSError(f"ElevenLabs từ chối key ({r.status_code}): {detail}")
        if "quota" in detail.lower():
            raise TTSError("Hết lượt ký tự ElevenLabs tháng này – hãy chọn giọng Edge miễn phí.")
        raise TTSError(f"ElevenLabs lỗi {r.status_code}: {detail}")
    out.write_bytes(r.content)


def synth_edge(text: str, voice_id: str, out: Path, rate: str = "+0%") -> None:
    import edge_tts

    async def go():
        await edge_tts.Communicate(text, voice_id, rate=rate).save(str(out))

    try:
        asyncio.run(go())
    except Exception as exc:
        raise TTSError(f"Edge TTS lỗi (cần Internet): {exc}") from exc


def cache_key(provider: str, text: str, voice_id: str, rate: str) -> str:
    model = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5") if provider == "elevenlabs" else ""
    speed = rate if provider == "edge" else ""
    raw = json.dumps([provider, voice_id, model, speed, text.strip()], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def synthesize_cached(provider: str, text: str, voice_id: str, rate: str = "+0%") -> Path:
    """Return an mp3 for this line, generating it only if it isn't cached yet."""
    if CACHE_DIR is None:
        raise RuntimeError("tts.CACHE_DIR is not configured")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{cache_key(provider, text, voice_id, rate)}.mp3"
    if cached.exists() and cached.stat().st_size > 0:
        cached.touch()  # keep recently used speech from being cleaned up
        return cached
    tmp = CACHE_DIR / f".{uuid.uuid4().hex}.mp3"
    try:
        _synthesize(provider, text.strip(), voice_id, tmp, rate)
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise TTSError("Dịch vụ giọng đọc trả về file rỗng, hãy thử lại.")
        os.replace(tmp, cached)
    finally:
        tmp.unlink(missing_ok=True)
    return cached


def synthesize(provider: str, text: str, voice_id: str, out: Path, rate: str = "+0%") -> None:
    if CACHE_DIR is None:
        _synthesize(provider, text, voice_id, out, rate)
    else:
        shutil.copyfile(synthesize_cached(provider, text, voice_id, rate), out)


def _synthesize(provider: str, text: str, voice_id: str, out: Path, rate: str = "+0%") -> None:
    if provider == "elevenlabs":
        synth_elevenlabs(text, voice_id, out)
    elif provider == "edge":
        synth_edge(text, voice_id, out, rate)
    elif provider == "_test":  # offline tone, used only by the self-test
        from .media import run
        dur = max(1.0, len(text.split()) / 3)
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             f"sine=frequency=440:duration={dur}", "-f", "mp3", str(out)])
    else:
        raise TTSError(f"Không biết nhà cung cấp giọng: {provider}")
