"""Offline tests: no API keys, no Internet.

Run:  pip install pytest  &&  python -m pytest -q
Gemini is replaced by fakes; speech uses the "_test" provider (a sine tone).
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("media") / "src.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=6",
        "-f", "lavfi", "-i", "sine=duration=6",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
    ], check=True)
    return path


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    from fastapi.testclient import TestClient
    import app.server as server
    server = importlib.reload(server)  # pick up DATA_DIR
    return TestClient(server.app), server


def wait_done(c, job_id, timeout=60):
    for _ in range(int(timeout / 0.2)):
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


FAKE_POSTS = {
    "tiktok": {"title": "", "caption": "Pha flash vào trụ huyền thoại 😂", "hashtags": ["lienquan", "#highlight", "#lienquan"]},
    "facebook": {"title": "", "caption": "Ai từng như này chưa?", "hashtags": ["#lienquanmobile"]},
    "youtube": {"title": "Flash vào trụ", "caption": "Mô tả", "hashtags": ["#lienquan"]},
}


# --------------------------------------------------------------- script_ai

def test_normalize_clamps_and_removes_overlap():
    from app import script_ai
    data = {"summary": " Trận hay ", "segments": [
        {"start": 3, "end": 9, "event": "b", "text": "câu hai"},
        {"start": -1, "end": 4, "event": "a", "text": "câu một"},
        {"start": 5, "end": 6, "event": "c", "text": "   "},
    ], "posts": FAKE_POSTS}
    out = script_ai.normalize(data, duration=8)
    segs = out["segments"]
    assert [s["text"] for s in segs] == ["câu một", "câu hai"]
    assert segs[0]["start"] == 0 and segs[1]["start"] >= segs[0]["end"]
    assert segs[1]["end"] <= 8
    assert out["summary"] == "Trận hay"


def test_normalize_posts_cleans_hashtags():
    from app import script_ai
    posts = script_ai.normalize_posts(FAKE_POSTS)
    assert posts["tiktok"]["hashtags"] == ["#lienquan", "#highlight"]      # added '#', removed duplicate
    assert "#Shorts" in posts["youtube"]["hashtags"]                         # always on YouTube
    assert script_ai.normalize_posts(None) is None


def test_gemini_error_messages_are_vietnamese():
    from app import script_ai
    assert "hết lượt" in script_ai.gemini_error_message(Exception("429 RESOURCE_EXHAUSTED"))
    assert "GEMINI_API_KEY" in script_ai.gemini_error_message(Exception("API key not valid"))


# --------------------------------------------------------------- tts cache

def test_tts_cache_reuses_audio(tmp_path, monkeypatch):
    from app import tts
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "cache")
    calls = []
    real = tts._synthesize
    monkeypatch.setattr(tts, "_synthesize", lambda *a, **k: (calls.append(a), real(*a, **k)))
    a = tts.synthesize_cached("_test", "xin chào các bạn", "v1", "+0%")
    b = tts.synthesize_cached("_test", "xin chào các bạn ", "v1", "+0%")   # same after strip
    tts.synthesize("_test", "xin chào các bạn", "v1", tmp_path / "copy.mp3", "+0%")
    assert a == b and len(calls) == 1 and (tmp_path / "copy.mp3").stat().st_size > 0
    tts.synthesize_cached("_test", "xin chào các bạn", "v2", "+0%")          # other voice → new audio
    assert len(calls) == 2


# --------------------------------------------------------------- API flow

def test_full_flow_with_fake_gemini(client, sample_video, monkeypatch):
    c, server = client
    r = c.post("/api/upload", files={"file": ("tran.mp4", sample_video.read_bytes(), "video/mp4")})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["info"]["orientation"] == "ngang"

    def fake_script(video, duration, style, notes, progress):
        return server.script_ai.normalize({"summary": "Một pha hài", "posts": FAKE_POSTS, "segments": [
            {"start": 0.3, "end": 2.5, "event": "farm", "text": "Bắt đầu trận đấu nào"},
            {"start": 3, "end": 5.5, "event": "chết", "text": "Ôi không flash vào trụ"},
        ]}, duration)
    monkeypatch.setattr(server.script_ai, "generate_script", fake_script)

    assert c.post(f"/api/jobs/{job['id']}/script", json={"style": "hai_huoc"}).status_code == 200
    job = wait_done(c, job["id"])
    assert job["status"] == "done", job["error"]
    assert job["script"]["posts"]["youtube"]["hashtags"][-1] == "#Shorts"

    # Captions regenerated from an edited script (text only).
    seen = {}

    def fake_posts(segments, summary, style, notes):
        seen["lines"] = [s["text"] for s in segments]
        return server.script_ai.normalize_posts(FAKE_POSTS)
    monkeypatch.setattr(server.script_ai, "generate_posts", fake_posts)
    edited = [dict(s) for s in job["script"]["segments"]]
    edited[0]["text"] = "Câu đã sửa"
    assert c.post(f"/api/jobs/{job['id']}/captions", json={"segments": edited, "style": "ca_khia"}).status_code == 200
    job = wait_done(c, job["id"])
    assert job["status"] == "done", job["error"]
    assert seen["lines"][0] == "Câu đã sửa"
    assert job["script"]["segments"][0]["text"] == "Câu đã sửa"

    # Preview one line, then render: the preview audio must be reused.
    r = c.post("/api/tts-preview", json={"text": "Câu đã sửa", "provider": "_test", "voice_id": "v"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and len(r.content) > 0
    cached_before = set(server.TTS_CACHE.iterdir())

    r = c.post(f"/api/jobs/{job['id']}/render", json={
        "segments": job["script"]["segments"], "provider": "_test", "voice_id": "v", "aspect": "9:16"})
    assert r.status_code == 200
    job = wait_done(c, job["id"], timeout=120)
    assert job["status"] == "done", job["error"]
    assert (job["result"]["width"], job["result"]["height"]) == (1080, 1920)
    assert job["script"]["posts"] is not None                                 # render keeps captions
    assert len(set(server.TTS_CACHE.iterdir()) - cached_before) == 1          # only the 2nd line was new
    assert c.get(f"/api/jobs/{job['id']}/output").status_code == 200


def test_preview_validation(client):
    c, _ = client
    assert c.post("/api/tts-preview", json={"text": "  ", "provider": "_test"}).status_code == 400
    assert c.post("/api/tts-preview", json={"text": "a" * 601, "provider": "_test"}).status_code == 400
    r = c.post("/api/tts-preview", json={"text": "xin chào", "provider": "khong-co"})
    assert r.status_code == 400 and "nhà cung cấp" in r.json()["detail"]


def test_password_gate(client, monkeypatch):
    c, server = client
    monkeypatch.setattr(server, "APP_PASSWORD", "bimat")
    assert c.get("/api/config").status_code == 401
    assert c.get("/api/config", auth=("ai-cung-duoc", "bimat")).status_code == 200
    assert c.get("/healthz").status_code == 200
