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
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from . import media, render as renderer, script_ai, tts  # noqa: E402
from .styles import STYLES  # noqa: E402

DATA = Path(os.getenv("DATA_DIR") or ROOT / "data") / "jobs"
DATA.mkdir(parents=True, exist_ok=True)
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


# ------------------------------------------------------------------ API

@app.get("/api/config")
def config():
    return {
        "gemini": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "elevenlabs": bool(tts.eleven_key()),
        "styles": {k: v["label"] for k, v in STYLES.items()},
        "max_upload_mb": MAX_UPLOAD_MB,
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


class RenderReq(BaseModel):
    segments: list[dict]
    provider: str = "edge"
    voice_id: str = ""
    style: str = "hai_huoc"
    aspect: str = "9:16"
    game_volume: float = 0.35
    voice_volume: float = 1.0
    duck: bool = True
    subtitles: bool = True
    title: str = ""


@app.post("/api/jobs/{job_id}/render")
def make_video(job_id: str, req: RenderReq):
    d = job_dir(job_id)
    job = JOBS[job_id]
    segs = script_ai.normalize({"segments": req.segments}, job["info_obj"].duration)["segments"]

    def task(progress):
        script = dict(job.get("script") or {})
        script["segments"] = segs
        update(job_id, script=script, result=None)
        if not RENDER_SLOTS.acquire(blocking=False):
            progress("Đang có video khác được xuất, đang chờ tới lượt...")
            RENDER_SLOTS.acquire()
        try:
            result = renderer.render(d, d / job["source"], job["info_obj"], segs,
                                     req.model_dump(), progress)
        finally:
            RENDER_SLOTS.release()
        result["aspect"] = req.aspect
        result["version"] = uuid.uuid4().hex[:6]
        update(job_id, result=result)

    background(job_id, "render", task)
    return public(job_id)


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
