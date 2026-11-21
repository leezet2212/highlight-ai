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


# --------------------------------------------------------------- audio options

def _render_capture(tmp_path, sample_video, monkeypatch, segments, **opts):
    """Render with the _test voice and record ffmpeg filters + which voice each line used."""
    from app import media, render
    calls, voices = [], []
    real_run = render.run
    monkeypatch.setattr(render, "run", lambda cmd, cwd=None: (calls.append(cmd), real_run(cmd, cwd))[1])
    real_synth = render.synthesize
    monkeypatch.setattr(render, "synthesize",
                        lambda p, t, v, out, rate: (voices.append((p, v)), real_synth("_test", t, v, out, rate)))
    job = tmp_path / "job"
    job.mkdir(parents=True)
    info = media.probe(sample_video)
    render.render(job, sample_video, info, segments, {"provider": "_test", "voice_id": "chung", **opts})
    final = next(c for c in reversed(calls) if "output.mp4" in c)
    return final[final.index("-filter_complex") + 1], voices, job


SEGS = [{"start": 0.3, "end": 2.5, "text": "câu một"},
        {"start": 3, "end": 5, "text": "câu hai", "provider": "_test", "voice_id": "nu"}]


def test_mute_original_drops_video_audio(tmp_path, sample_video, monkeypatch):
    kept, _, _ = _render_capture(tmp_path / "a", sample_video, monkeypatch, SEGS, aspect="16:9")
    muted, _, job = _render_capture(tmp_path / "b", sample_video, monkeypatch, SEGS, aspect="16:9",
                                    mute_original=True)
    assert "[0:a]" in kept and "sidechaincompress" in kept
    assert "[0:a]" not in muted and "sidechaincompress" not in muted
    assert (job / "output.mp4").stat().st_size > 0


def test_per_line_voice(tmp_path, sample_video, monkeypatch):
    _, voices, _ = _render_capture(tmp_path, sample_video, monkeypatch, SEGS, aspect="16:9")
    assert voices == [("_test", "chung"), ("_test", "nu")]


def test_normalize_keeps_line_voice():
    from app import script_ai
    out = script_ai.normalize({"segments": SEGS}, duration=6)["segments"]
    assert "voice_id" not in out[0]
    assert (out[1]["provider"], out[1]["voice_id"]) == ("_test", "nu")


# --------------------------------------------------------------- picture tools

def _frame(video: Path, out: Path, t=2.0):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(video),
                    "-frames:v", "1", str(out)], check=True)
    from PIL import Image
    return Image.open(out).convert("L")


def _sharpest_edge(img, box):
    """Largest jump between horizontally neighbouring pixels: sharp edges ~200, blurred < 60."""
    region = img.crop(box)
    w, h = region.size
    px = region.load()
    return max(abs(px[x + 1, y] - px[x, y]) for y in range(0, h, 2) for x in range(w - 1))


def test_blur_box_px_clamps_and_rejects_tiny():
    from app import render
    assert render.blur_box_px({"x": 0.5, "y": 0.5, "w": 0.9, "h": 0.9}, 640, 360) == (320, 180, 320, 180)
    assert render.blur_box_px({"x": 0, "y": 0, "w": 0.001, "h": 0.5}, 640, 360) is None
    assert render.blur_box_px({"x": "a"}, 640, 360) is None


def test_filter_graph_has_all_picture_steps():
    from app import media, render
    info = media.VideoInfo(1280, 720, 6.0, True)
    lay = render.layout("9:16", info)
    g = render.build_video_filter(lay, info, enhance=True, use_ass=True, tail=0,
                                  blur_boxes=[{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}],
                                  logo={"w": 160, "h": 80, "x": 10, "y": 10, "opacity": 0.8})
    assert g.index("crop=") < g.index("hqdn3d") < g.index("unsharp") < g.index("[2:v]") < g.index("ass=subs.ass")
    assert g.endswith("[vout]")


def test_render_with_blur_logo_signature_and_enhance(tmp_path, sample_video, monkeypatch):
    logo = tmp_path / "logo.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=200x100",
                    "-frames:v", "1", str(logo)], check=True)
    box = {"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5}
    common = dict(aspect="original", subtitles=False)
    _, _, plain = _render_capture(tmp_path / "plain", sample_video, monkeypatch, SEGS, **common)
    _, _, edited = _render_capture(tmp_path / "edit", sample_video, monkeypatch, SEGS, **common,
                                   blur_boxes=[box], enhance=True, logo_path=str(logo),
                                   watermark_text="@BLV_Test", watermark_pos="tl", watermark_opacity=1)
    a = _frame(plain / "output.mp4", tmp_path / "a.png")
    b = _frame(edited / "output.mp4", tmp_path / "b.png")
    w, h = a.size
    inner = (int(w * 0.32), int(h * 0.32), int(w * 0.68), int(h * 0.68))
    assert _sharpest_edge(a, inner) > 150                         # colour-bar edges in the original
    assert _sharpest_edge(b, inner) < 60                          # ...gone inside the blurred box
    from PIL import Image
    rgb = Image.open(tmp_path / "b.png").convert("RGB")
    m = round(min(w, h) * 0.035)                                  # corner margin used by render
    r, g, bl = rgb.getpixel((m + 20, m + 10))
    assert r > 180 and g < 90 and bl < 90                          # red logo in the top-left corner


def test_logo_upload_and_delete(client, tmp_path):
    c, server = client
    png = tmp_path / "l.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=1200x300",
                    "-frames:v", "1", str(png)], check=True)
    assert c.get("/api/config").json()["logo"] is False
    r = c.post("/api/logo", files={"file": ("logo.png", png.read_bytes(), "image/png")})
    assert r.status_code == 200 and r.json()["width"] == 800      # downscaled to 800px
    assert c.get("/api/config").json()["logo"] is True
    assert c.get("/api/logo").headers["content-type"] == "image/png"
    bad = c.post("/api/logo", files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code == 400
    assert c.delete("/api/logo").status_code == 200 and c.get("/api/logo").status_code == 404


# --------------------------------------------------------------- learn style from a sample video

FAKE_PROFILE = {"has_commentary": True, "name": "BLV miền Tây", "summary": "Hài, giọng miền Tây.",
                "prompt": "- Xưng 'tui', gọi người xem là 'bà con'\n- Câu ngắn, dồn dập", "pace": "nhanh",
                "examples": ["Trời đất ơi bà con ơi!", "Pha này tui chịu luôn á"]}


def test_normalize_profile_rejects_videos_without_commentary():
    from app import script_ai
    with pytest.raises(script_ai.ScriptError, match="Không nghe thấy giọng bình luận"):
        script_ai.normalize_profile({**FAKE_PROFILE, "has_commentary": False})
    assert script_ai.normalize_profile({**FAKE_PROFILE, "pace": "??"})["pace"] == "vua"


def test_learn_style_from_sample_video(client, sample_video, monkeypatch, tmp_path):
    c, server = client
    seen = {}
    monkeypatch.setattr(server.script_ai, "analyze_style",
                        lambda video, progress: (seen.setdefault("video", video),
                                                 server.script_ai.normalize_profile(FAKE_PROFILE))[1])
    r = c.post("/api/style-samples", data={"name": ""},
               files={"file": ("mau.mp4", sample_video.read_bytes(), "video/mp4")})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    for _ in range(100):
        task = c.get(f"/api/style-samples/{sid}").json()
        if task["status"] != "running":
            break
        time.sleep(0.1)
    assert task["status"] == "done", task["error"]
    key = task["style_key"]
    assert seen["video"].name == "sample.mp4"                         # the small copy was analysed
    assert not (server.STYLES_DIR / "samples" / sid).exists()        # sample video deleted afterwards
    assert c.get("/api/config").json()["styles"][key] == "🎧 BLV miền Tây"

    # The learned style is what the AI is told when writing commentary.
    prompt = server.styles.style_prompt(key)
    assert "bà con" in prompt and "Trời đất ơi bà con ơi!" in prompt and "KHÔNG lặp lại" in prompt
    assert server.styles.edge_rate(key) == "+15%"

    # Edit, then survive a server restart, then delete.
    r = c.put(f"/api/styles/{key}", json={"name": "Miền Tây vui", "prompt": "- Nói chậm rãi"})
    assert r.status_code == 200 and r.json()["label"] == "🎧 Miền Tây vui"
    assert c.put(f"/api/styles/{key}", json={"prompt": "  "}).status_code == 400
    server.load_custom_styles()
    assert server.styles.CUSTOM[key]["prompt"] == "- Nói chậm rãi"
    assert c.delete(f"/api/styles/{key}").status_code == 200
    assert key not in c.get("/api/config").json()["styles"]
    assert c.put("/api/styles/hai_huoc", json={"name": "x"}).status_code == 404   # built-ins are read-only


def test_sample_video_needs_sound(client, tmp_path):
    c, _ = client
    silent = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:duration=2",
                    "-c:v", "libx264", str(silent)], check=True)
    r = c.post("/api/style-samples", files={"file": ("s.mp4", silent.read_bytes(), "video/mp4")})
    assert r.status_code == 400 and "không có tiếng" in r.json()["detail"]


# --------------------------------------------------------------- 👗 fashion tool

def _png(path: Path, color="red", size="300x400") -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s={size}",
                    "-frames:v", "1", str(path)], check=True)
    return path


def test_fashion_timeline_and_json_helpers():
    from app import fashion
    assert fashion.plan_timeline(3, "start", True) == {"head": 0.75, "tail": 0.0, "dance": 2.25}
    assert fashion.plan_timeline(10, "both", True) == {"head": 1.0, "tail": 1.0, "dance": 8.0}
    assert fashion.plan_timeline(10, "both", False)["dance"] == 10
    data = fashion.parse_json_block('Đây là gợi ý:\n```json\n{"captions": ["a"], "hashtags": ["fyp", "#fyp", "xu huong"]}\n```')
    assert fashion.normalize_posts(data)["hashtags"] == ["#fyp", "#xuhuong"]
    with pytest.raises(fashion.FashionError):
        fashion.parse_json_block("không có json")
    ics = fashion.reminder_ics(__import__("datetime").datetime(2026, 12, 1, 19, 30), "Đăng", "a, b; c")
    assert "DTSTART:20261201T193000" in ics and "a\\, b\; c" in ics and "BEGIN:VALARM" in ics


def test_fashion_full_flow(client, tmp_path, monkeypatch):
    c, server = client
    from app import fashion, fashion_api
    dance = tmp_path / "dance.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=25:duration=4",
                    "-f", "lavfi", "-i", "sine=duration=4", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(dance)],
                   check=True)
    pid = c.post("/api/fashion").json()["id"]
    up = lambda kind, path, mime: c.post(f"/api/fashion/{pid}/upload", data={"kind": kind},  # noqa: E731
                                         files={"file": (path.name, path.read_bytes(), mime)})
    assert up("clothes", _png(tmp_path / "ao.jpg", "pink"), "image/jpeg").status_code == 200
    assert up("model", _png(tmp_path / "mau.png", "blue"), "image/png").status_code == 200
    r = up("dance", dance, "video/mp4")
    assert r.status_code == 200 and r.json()["dance_info"]["orientation"] == "dọc"
    assert up("clothes", tmp_path / "ao.jpg", "image/jpeg").json()["clothes"] == ["clothes_1.png", "clothes_2.png"]

    # Try-on needs consent; the fake AI writes a PNG like the real one would.
    assert c.post(f"/api/fashion/{pid}/tryon", json={"consent": False}).status_code == 400

    def fake_tryon(model_photo, clothes, out_dir, count=1, notes="", on_progress=None):
        name = fashion.next_name(out_dir, "tryon", ".png")
        _png(out_dir / name, "green", "540x960")
        return [name]
    monkeypatch.setattr(fashion_api.fashion, "generate_tryon", fake_tryon)
    assert c.post(f"/api/fashion/{pid}/tryon", json={"consent": True}).status_code == 200
    p = wait_fashion(c, pid)
    assert p["status"] == "done", p["error"]
    assert p["tryon"] == ["tryon_1.png"]

    # Text-free product videos in two lengths, try-on photo at the start, product photo in the corner.
    r = c.post(f"/api/fashion/{pid}/render", json={"durations": [3, 10], "tryon": "tryon_1.png",
                                                     "tryon_at": "start", "pip": "clothes_1.png"})
    assert r.status_code == 200
    p = wait_fashion(c, pid, 120)
    assert p["status"] == "done", p["error"]
    outs = {o["duration"]: o for o in p["outputs"]}
    assert set(outs) == {3, 10} and outs[10]["looped"]                    # 4s dance looped to fill 10s
    from app import media
    for sec, o in outs.items():
        info = media.probe(server.DATA.parent / "fashion" / pid / o["file"])
        assert (info.width, info.height) == (1080, 1920) and abs(info.duration - sec) < 0.15
    first = _frame(server.DATA.parent / "fashion" / pid / outs[3]["file"], tmp_path / "f.png", 0.2)
    from PIL import Image
    r_, g_, b_ = Image.open(tmp_path / "f.png").convert("RGB").getpixel((540, 960))
    assert g_ > 100 and r_ < 80                                            # opens on the (green) try-on photo

    # Captions & trends (fake AI), posting slots and calendar reminder.
    monkeypatch.setattr(fashion_api.fashion, "generate_posts",
                        lambda images, notes: fashion.normalize_posts({"captions": ["Xinh quá 😍"], "hashtags": ["fyp"]}))
    assert c.post(f"/api/fashion/{pid}/posts", json={"notes": "249k"}).status_code == 200
    p = wait_fashion(c, pid)
    assert p["posts"]["hashtags"] == ["#fyp"]
    slot = c.get(f"/api/fashion/{pid}/slots").json()["slots"][0]["at"]
    r = c.get(f"/api/fashion/{pid}/reminder.ics", params={"at": slot, "caption": "Xinh quá"})
    assert r.status_code == 200 and "text/calendar" in r.headers["content-type"]

    # Files can't be read outside the project folder.
    assert c.get(f"/api/fashion/{pid}/file/project.json").status_code == 404
    assert c.get(f"/api/fashion/{pid}/file/..%2F..%2Fstyles").status_code == 404
    # Delete an output and an asset.
    assert len(c.delete(f"/api/fashion/{pid}/output/{outs[3]['file']}").json()["outputs"]) == 1
    assert c.delete(f"/api/fashion/{pid}/asset/clothes_2.png").json()["clothes"] == ["clothes_1.png"]


def wait_fashion(c, pid, timeout=60):
    for _ in range(int(timeout / 0.2)):
        p = c.get(f"/api/fashion/{pid}").json()
        if p["status"] != "running":
            return p
        time.sleep(0.2)
    raise AssertionError("fashion task did not finish")


# --------------------------------------------------------------- ✍️ content AI

def test_quick_check_flags_risky_words():
    from app import content
    words = [f["word"] for f in content.quick_check("Váy rẻ nhất, cam kết 100%! Inbox zalo 0912 345 678, xem www.abc.vn")]
    assert {"rẻ nhất", "cam kết", "100%", "inbox", "zalo", "số điện thoại", "đường link"} <= set(words)
    assert content.quick_check("Bạn chọn màu nào? Xem tới cuối nha 😍") == []
    assert content.quick_check("ibuprofen") == []                    # "ib" only as a whole word


def test_content_api_with_fake_ai(client, monkeypatch):
    c, _ = client
    from app import content
    calls = []

    def fake_call(contents, search=False, temperature=1.0):
        calls.append((contents, search))
        if "biên kịch" in contents:
            return {"trend_note": "Đang hot", "ideas": [
                {"title": "Shipper cứu cô gái", "hook": "Tiếng hét giữa đêm", "twist": "Cô gái là sếp mới",
                 "characters": ["Anh shipper"], "hashtags": ["phimngan", "#phimngan", "fyp"], "notes": ["Bật nhãn AI"],
                 "scenes": [{"time": "0-3s", "visual": "Ngõ tối", "ai_prompt": "night alley, vertical 9:16"}]},
                {"title": "Không có cảnh", "scenes": []}]}
        if "chuyên gia tối ưu" in contents:
            return {"scores": {"hook": 12, "originality": "4", "emotion": None}, "summary": "Ổn",
                    "issues": [{"type": "tu_cam", "text": "rẻ nhất", "why": "tuyệt đối", "fix": "giá tốt"}],
                    "rewrites": ["Bản mới"], "hook_ideas": ["Mở đầu mới"], "hashtags": ["xuhuong"]}
        return {"items": [{"day": 2, "time": "19:30", "format": "Anh hùng", "title": "Tập 2", "hook": "h"},
                          {"day": 1, "time": "sai giờ", "title": "Tập 1"}, {"day": "x"}]}
    monkeypatch.setattr(content, "_call", fake_call)

    assert "anh_hung" in c.get("/api/content/formats").json()
    r = c.post("/api/content/ideas", json={"format": "gap_nguoi_noi_tieng", "topic": "ca sĩ", "count": 2})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["ideas"]) == 1 and d["ideas"][0]["hashtags"] == ["#phimngan", "#fyp"]   # empty idea dropped
    prompt, used_search = calls[-1]
    assert used_search and "nhân vật HƯ CẤU" in prompt and "nhãn" in prompt         # guardrails always sent
    assert c.post("/api/content/ideas", json={"format": "custom", "topic": " "}).status_code == 400

    d = c.post("/api/content/check", json={"text": "Váy rẻ nhất", "ai_made": True}).json()
    assert d["scores"]["hook"] == 10 and d["scores"]["originality"] == 4 and d["scores"]["emotion"] == 0
    assert d["needs_ai_label"] is True and d["quick"][0]["word"] == "rẻ nhất"
    assert c.post("/api/content/check", json={"text": "  "}).status_code == 400

    d = c.post("/api/content/plan", json={"days": 7, "per_day": 1, "start": "2026-12-01", "formats": ["anh_hung"]}).json()
    assert [i["at"] for i in d["items"]] == ["2026-12-01T19:30", "2026-12-02T19:30"]   # sorted, bad time → 19:30
    r = c.post("/api/content/plan.ics", json={"items": d["items"]})
    assert r.status_code == 200 and r.text.count("BEGIN:VEVENT") == 2 and "DTSTART:20261202T193000" in r.text
