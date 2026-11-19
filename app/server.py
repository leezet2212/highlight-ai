"""FastAPI web app: upload → AI script → edit → render → download."""
from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from . import media, render as renderer, script_ai, tts  # noqa: E402
from . import styles  # noqa: E402
from .styles import edge_rate  # noqa: E402

DATA = Path(os.getenv("DATA_DIR") or ROOT / "data") / "jobs"
DATA.mkdir(parents=True, exist_ok=True)
TTS_CACHE = DATA.parent / "tts_cache"
LOGO = DATA.parent / "assets" / "logo.png"     # one channel logo, reused for every video
STYLES_DIR = DATA.parent / "styles"            # styles learned from sample videos (kept forever)
STYLES_FILE = STYLES_DIR / "styles.json"
MAX_SAMPLE_SECONDS = 300
SAMPLE_TASKS: dict[str, dict] = {}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))
JOB_TTL_HOURS = float(os.getenv("JOB_TTL_HOURS", "24"))
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
# ffmpeg is CPU/RAM heavy: on a small server render one video at a time.
RENDER_SLOTS = threading.Semaphore(max(1, int(os.getenv("MAX_CONCURRENT_RENDERS", "1"))))

app = FastAPI(title="Highlight AI – Bình luận Liên Quân")
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


@app.middleware("http")
async def password_gate(request: Request, call_next):
    """Optional HTTP Basic auth so a public deployment doesn't burn your API quota.

    Any username works; the password must equal APP_PASSWORD.
    """
    if not APP_PASSWORD or request.url.path == "/healthz":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            _, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
            if secrets.compare_digest(pw.encode(), APP_PASSWORD.encode()):
                return await call_next(request)
        except Exception:
            pass
    return Response("Cần mật khẩu để dùng Highlight AI.", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Highlight AI", charset="UTF-8"'},
                    media_type="text/plain; charset=utf-8")


@app.get("/healthz")
def healthz():
    return {"ok": True}


def cleanup_old_jobs() -> None:
    """Delete uploads/results older than JOB_TTL_HOURS so the disk doesn't fill up."""
    if JOB_TTL_HOURS <= 0:
        return
    cutoff = time.time() - JOB_TTL_HOURS * 3600
    for d in DATA.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff and JOBS.get(d.name, {}).get("status") != "running":
                shutil.rmtree(d, ignore_errors=True)
                JOBS.pop(d.name, None)
        except FileNotFoundError:
            pass
    if TTS_CACHE.exists():
        for f in TTS_CACHE.iterdir():
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except FileNotFoundError:
                pass


def job_dir(job_id: str) -> Path:
    if job_id not in JOBS:
        raise HTTPException(404, "Không tìm thấy video, hãy tải lên lại.")
    return DATA / job_id


def update(job_id: str, **kw) -> None:
    with LOCK:
        JOBS[job_id].update(kw)
        meta = {k: v for k, v in JOBS[job_id].items() if k != "info_obj"}
    (DATA / job_id / "job.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")


def background(job_id: str, kind: str, fn) -> None:
    if JOBS[job_id].get("status") == "running":
        raise HTTPException(409, "Đang xử lý, vui lòng đợi.")
    update(job_id, status="running", task=kind, progress="Bắt đầu...", error=None)

    def work():
        try:
            fn(lambda msg: update(job_id, progress=msg))
            update(job_id, status="done", progress="Xong!")
        except Exception as exc:
            traceback.print_exc()
            update(job_id, status="error", error=str(exc))

    threading.Thread(target=work, daemon=True).start()


def restore_jobs() -> None:
    """Keep jobs from earlier runs available after a server restart."""
    for d in DATA.iterdir():
        meta_file = d / "job.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text("utf-8"))
                if meta.get("status") == "running":
                    meta.update(status="error", error="Máy chủ đã khởi động lại giữa chừng.")
                meta["info_obj"] = media.VideoInfo(**{k: meta["info"][k] for k in
                                                     ("width", "height", "duration", "has_audio")})
                JOBS[d.name] = meta
            except Exception:
                pass


cleanup_old_jobs()
restore_jobs()
tts.CACHE_DIR = TTS_CACHE


def load_custom_styles() -> None:
    styles.CUSTOM.clear()
    if STYLES_FILE.exists():
        try:
            styles.CUSTOM.update(json.loads(STYLES_FILE.read_text("utf-8")))
        except (OSError, json.JSONDecodeError):
            traceback.print_exc()


def save_custom_styles() -> None:
    STYLES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STYLES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(styles.CUSTOM, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(STYLES_FILE)


def style_entry(name: str, profile: dict) -> dict:
    return {
        "label": f"🎧 {name}",
        "name": name,
        "summary": profile.get("summary", ""),
        "prompt": profile["prompt"],
        "examples": profile.get("examples", []),
        "pace": profile.get("pace", "vua"),
        "edge_rate": styles.PACE_RATE.get(profile.get("pace", "vua"), "+5%"),
        "created": int(time.time()),
    }


load_custom_styles()


# ------------------------------------------------------------------ API

@app.get("/api/config")
def config():
    return {
        "gemini": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "elevenlabs": bool(tts.eleven_key()),
        "styles": styles.all_labels(),
        "max_upload_mb": MAX_UPLOAD_MB,
        "logo": LOGO.exists(),
    }


@app.get("/api/voices")
def voices():
    return tts.list_voices()


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    cleanup_old_jobs()
    job_id = uuid.uuid4().hex[:12]
    d = DATA / job_id
    d.mkdir(parents=True)
    ext = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    src = d / f"source{ext}"
    size = 0
    with src.open("wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB << 20:
                fh.close()
                shutil.rmtree(d, ignore_errors=True)
                raise HTTPException(413, f"Video quá lớn (tối đa {MAX_UPLOAD_MB} MB).")
            fh.write(chunk)
    try:
        info = media.probe(src)
        media.make_preview(src, d / "preview.mp4")
    except media.MediaError as exc:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, f"Không đọc được video: {exc}")
    if info.duration > 600:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "Video dài quá 10 phút – hãy cắt đoạn highlight ngắn hơn.")

    JOBS[job_id] = {"id": job_id, "name": file.filename, "source": src.name,
                    "info": info.to_dict(), "info_obj": info, "status": "idle",
                    "script": None, "result": None}
    update(job_id)
    return public(job_id)


def public(job_id: str) -> dict:
    return {k: v for k, v in JOBS[job_id].items() if k != "info_obj"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job_dir(job_id)
    return public(job_id)


class ScriptReq(BaseModel):
    style: str = "hai_huoc"
    notes: str = ""


@app.post("/api/jobs/{job_id}/script")
def make_script(job_id: str, req: ScriptReq):
    d = job_dir(job_id)
    job = JOBS[job_id]

    def task(progress):
        script = script_ai.generate_script(d / "preview.mp4", job["info_obj"].duration,
                                           req.style, req.notes, progress)
        script["style"] = req.style
        update(job_id, script=script)

    background(job_id, "script", task)
    return public(job_id)


class CaptionReq(BaseModel):
    segments: list[dict]
    style: str = "hai_huoc"
    notes: str = ""


@app.post("/api/jobs/{job_id}/captions")
def make_captions(job_id: str, req: CaptionReq):
    job_dir(job_id)
    job = JOBS[job_id]
    segs = script_ai.normalize({"segments": req.segments}, job["info_obj"].duration)["segments"]

    def task(progress):
        progress("AI đang viết caption và hashtag...")
        script = dict(job.get("script") or {"summary": ""})
        posts = script_ai.generate_posts(segs, script.get("summary", ""), req.style, req.notes)
        script.update(segments=segs, posts=posts, style=req.style)
        update(job_id, script=script)

    background(job_id, "captions", task)
    return public(job_id)


class PreviewReq(BaseModel):
    text: str
    provider: str = "edge"
    voice_id: str = ""
    style: str = "hai_huoc"


@app.post("/api/tts-preview")
def tts_preview(req: PreviewReq):
    """Speak one line so the user can hear it before rendering the whole video."""
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Câu này đang trống.")
    if len(text) > 600:
        raise HTTPException(400, "Câu quá dài để nghe thử (tối đa 600 ký tự).")
    voice = req.voice_id or renderer.DEFAULT_VOICE
    try:
        path = tts.synthesize_cached(req.provider, text, voice, edge_rate(req.style))
    except tts.TTSError as exc:
        raise HTTPException(400, str(exc))
    return FileResponse(path, media_type="audio/mpeg")


class RenderReq(BaseModel):
    segments: list[dict]
    provider: str = "edge"
    voice_id: str = ""
    style: str = "hai_huoc"
    aspect: str = "9:16"
    game_volume: float = 0.35
    voice_volume: float = 1.0
    duck: bool = True
    mute_original: bool = False
    subtitles: bool = True
    title: str = ""
    enhance: bool = False
    watermark_text: str = ""
    watermark_pos: str = "tr"
    watermark_opacity: float = 0.85
    use_logo: bool = False
    logo_size: float = 0.16
    blur_boxes: list[dict] = []


@app.post("/api/jobs/{job_id}/render")
def make_video(job_id: str, req: RenderReq):
    d = job_dir(job_id)
    job = JOBS[job_id]
    segs = script_ai.normalize({"segments": req.segments}, job["info_obj"].duration)["segments"]

    def task(progress):
        script = dict(job.get("script") or {})
        script["segments"] = segs
        # Remember the boxes drawn on this video so they come back after a reload.
        update(job_id, script=script, result=None, blur_boxes=req.blur_boxes[:10])
        if not RENDER_SLOTS.acquire(blocking=False):
            progress("Đang có video khác được xuất, đang chờ tới lượt...")
            RENDER_SLOTS.acquire()
        try:
            opts = req.model_dump()
            opts["logo_path"] = str(LOGO) if req.use_logo and LOGO.exists() else None
            result = renderer.render(d, d / job["source"], job["info_obj"], segs, opts, progress)
        finally:
            RENDER_SLOTS.release()
        result["aspect"] = req.aspect
        result["version"] = uuid.uuid4().hex[:6]
        update(job_id, result=result)

    background(job_id, "render", task)
    return public(job_id)


# ------------------------------------------------------------------ sample styles

@app.post("/api/style-samples")
async def upload_style_sample(file: UploadFile = File(...), name: str = Form("")):
    """A video that already has commentary the user likes → learn its style."""
    sid = uuid.uuid4().hex[:10]
    d = STYLES_DIR / "samples" / sid
    d.mkdir(parents=True)
    src = d / f"source{Path(file.filename or 'mau.mp4').suffix.lower() or '.mp4'}"
    size = 0
    with src.open("wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB << 20:
                fh.close()
                shutil.rmtree(d, ignore_errors=True)
                raise HTTPException(413, f"Video mẫu quá lớn (tối đa {MAX_UPLOAD_MB} MB).")
            fh.write(chunk)
    try:
        info = media.probe(src)
    except media.MediaError:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "Không đọc được video mẫu.")
    if not info.has_audio:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "Video mẫu không có tiếng – cần video có giọng bình luận để học phong cách.")
    if info.duration > MAX_SAMPLE_SECONDS:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "Video mẫu dài quá 5 phút – hãy cắt một đoạn bình luận tiêu biểu ngắn hơn.")

    SAMPLE_TASKS[sid] = {"id": sid, "status": "running", "progress": "Đang chuẩn bị video mẫu...",
                         "error": None, "style_key": None}

    def work():
        task = SAMPLE_TASKS[sid]
        try:
            small = d / "sample.mp4"
            media.make_preview(src, small)          # smaller upload, keeps the audio
            profile = script_ai.analyze_style(small, lambda m: task.update(progress=m))
            key = f"mau_{sid}"
            styles.CUSTOM[key] = style_entry(name.strip()[:40] or profile["name"], profile)
            save_custom_styles()
            task.update(status="done", progress="Xong!", style_key=key)
        except Exception as exc:
            traceback.print_exc()
            task.update(status="error", error=str(exc))
        finally:
            shutil.rmtree(d, ignore_errors=True)    # only the learned style is kept

    threading.Thread(target=work, daemon=True).start()
    return SAMPLE_TASKS[sid]


@app.get("/api/style-samples/{sid}")
def style_sample_status(sid: str):
    if sid not in SAMPLE_TASKS:
        raise HTTPException(404, "Không tìm thấy lượt học phong cách này.")
    return SAMPLE_TASKS[sid]


@app.get("/api/styles")
def list_custom_styles():
    return styles.CUSTOM


class StyleEdit(BaseModel):
    name: str | None = None
    prompt: str | None = None


@app.put("/api/styles/{key}")
def edit_style(key: str, req: StyleEdit):
    st = styles.CUSTOM.get(key)
    if not st:
        raise HTTPException(404, "Chỉ sửa được phong cách học từ video mẫu.")
    if req.name is not None and req.name.strip():
        st["name"] = req.name.strip()[:40]
        st["label"] = f"🎧 {st['name']}"
    if req.prompt is not None:
        if not req.prompt.strip():
            raise HTTPException(400, "Hướng dẫn phong cách không được để trống.")
        st["prompt"] = req.prompt.strip()[:4000]
    save_custom_styles()
    return st


@app.delete("/api/styles/{key}")
def delete_style(key: str):
    if styles.CUSTOM.pop(key, None) is None:
        raise HTTPException(404, "Không tìm thấy phong cách này.")
    save_custom_styles()
    return {"ok": True}


@app.get("/api/logo")
def get_logo():
    if not LOGO.exists():
        raise HTTPException(404, "Chưa có logo.")
    return FileResponse(LOGO, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/logo")
async def upload_logo(file: UploadFile = File(...)):
    data = await file.read((5 << 20) + 1)
    if len(data) > 5 << 20:
        raise HTTPException(413, "Logo quá lớn (tối đa 5 MB).")
    LOGO.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOGO.parent / f"upload-{uuid.uuid4().hex}{Path(file.filename or 'logo.png').suffix.lower()}"
    tmp.write_bytes(data)
    try:
        media.save_logo(tmp, LOGO)
    except media.MediaError:
        raise HTTPException(400, "Không đọc được ảnh logo – hãy dùng file PNG hoặc JPG.")
    finally:
        tmp.unlink(missing_ok=True)
    w, h = media.image_size(LOGO)
    return {"ok": True, "width": w, "height": h}


@app.delete("/api/logo")
def delete_logo():
    LOGO.unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/preview")
def preview(job_id: str):
    return FileResponse(job_dir(job_id) / "preview.mp4", media_type="video/mp4")


@app.get("/api/jobs/{job_id}/output")
def output(job_id: str, download: bool = False):
    f = job_dir(job_id) / "output.mp4"
    if not f.exists():
        raise HTTPException(404, "Chưa có video kết quả.")
    name = f"highlight-binh-luan-{job_id}.mp4" if download else None
    return FileResponse(f, media_type="video/mp4", filename=name)


@app.get("/api/jobs/{job_id}/srt")
def srt(job_id: str):
    f = job_dir(job_id) / "output.srt"
    if not f.exists():
        raise HTTPException(404, "Chưa có phụ đề.")
    return FileResponse(f, media_type="application/x-subrip", filename=f"phu-de-{job_id}.srt")


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
