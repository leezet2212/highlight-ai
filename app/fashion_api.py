"""API for the 👗 Video Thời Trang tool. Projects live in data/fashion/<id>/."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import fashion, media

router = APIRouter(prefix="/api/fashion")
ROOT: Path = Path("data/fashion")         # set by the server (init())
PROJECTS: dict[str, dict] = {}
LOCK = threading.Lock()
TTL_HOURS = float(os.getenv("FASHION_TTL_HOURS", "168"))   # keep projects a week
MAX_DANCE_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".bmp"}
render_slots: threading.Semaphore | None = None


def init(data_root: Path, slots: threading.Semaphore) -> None:
    global ROOT, render_slots
    ROOT = data_root / "fashion"
    ROOT.mkdir(parents=True, exist_ok=True)
    render_slots = slots
    PROJECTS.clear()
    cutoff = time.time() - TTL_HOURS * 3600
    for d in ROOT.iterdir():
        meta = d / "project.json"
        if not meta.exists():
            continue
        if TTL_HOURS > 0 and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            continue
        try:
            p = json.loads(meta.read_text("utf-8"))
            if p.get("status") == "running":
                p.update(status="error", error="Máy chủ đã khởi động lại giữa chừng.")
            PROJECTS[p["id"]] = p
        except (OSError, json.JSONDecodeError, KeyError):
            pass


def folder(pid: str) -> Path:
    if pid not in PROJECTS:
        raise HTTPException(404, "Không tìm thấy dự án, hãy tạo dự án mới.")
    return ROOT / pid


def save(pid: str, **kw) -> dict:
    with LOCK:
        PROJECTS[pid].update(kw)
        data = dict(PROJECTS[pid])
    (ROOT / pid / "project.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    return data


def run_task(pid: str, task: str, fn) -> dict:
    if PROJECTS[pid].get("status") == "running":
        raise HTTPException(409, "Đang xử lý, vui lòng đợi.")
    save(pid, status="running", task=task, progress="Bắt đầu...", error=None)

    def work():
        try:
            fn(lambda m: save(pid, progress=m))
            save(pid, status="done", progress="Xong!")
        except Exception as exc:
            traceback.print_exc()
            save(pid, status="error", error=str(exc))

    threading.Thread(target=work, daemon=True).start()
    return PROJECTS[pid]


async def store_upload(file: UploadFile, dst: Path, limit_mb: int) -> None:
    size = 0
    with dst.open("wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit_mb << 20:
                fh.close()
                dst.unlink(missing_ok=True)
                raise HTTPException(413, f"File quá lớn (tối đa {limit_mb} MB).")
            fh.write(chunk)


def to_png(src: Path, dst: Path) -> None:
    """Normalise any photo to PNG (max 1600px) so every later step reads one format."""
    try:
        media.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-frames:v", "1",
                   "-vf", "scale='min(1600,iw)':-2:flags=lanczos", str(dst)])
    except media.MediaError:
        raise HTTPException(400, "Không đọc được ảnh – hãy dùng ảnh JPG hoặc PNG.")
    finally:
        src.unlink(missing_ok=True)


# ------------------------------------------------------------------ projects

@router.post("")
def create_project():
    pid = uuid.uuid4().hex[:10]
    (ROOT / pid).mkdir(parents=True)
    PROJECTS[pid] = {"id": pid, "created": int(time.time()), "clothes": [], "model": None,
                     "dance": None, "dance_info": None, "tryon": [], "outputs": [], "posts": None,
                     "status": "idle", "task": None, "progress": None, "error": None}
    return save(pid)


@router.get("/{pid}")
def get_project(pid: str):
    folder(pid)
    return PROJECTS[pid]


@router.post("/{pid}/upload")
async def upload_asset(pid: str, kind: str = Form(...), file: UploadFile = File(...)):
    d = folder(pid)
    p = PROJECTS[pid]
    ext = Path(file.filename or "").suffix.lower()
    if kind in ("clothes", "model"):
        if kind == "clothes" and len(p["clothes"]) >= fashion.MAX_CLOTHES:
            raise HTTPException(400, f"Tối đa {fashion.MAX_CLOTHES} ảnh quần áo.")
        if ext and ext not in IMAGE_EXT:
            raise HTTPException(400, "Hãy chọn file ảnh (JPG, PNG, WEBP).")
        tmp = d / f"upload-{uuid.uuid4().hex}{ext or '.img'}"
        await store_upload(file, tmp, 20)
        name = fashion.next_name(d, kind, ".png") if kind == "clothes" else "model.png"
        to_png(tmp, d / name)
        if kind == "clothes":
            return save(pid, clothes=p["clothes"] + [name])
        return save(pid, model=name, tryon=p["tryon"])
    if kind == "dance":
        tmp = d / f"dance-upload{ext or '.mp4'}"
        await store_upload(file, tmp, MAX_DANCE_MB)
        try:
            info = media.probe(tmp)
        except media.MediaError:
            tmp.unlink(missing_ok=True)
            raise HTTPException(400, "Không đọc được video nhảy.")
        if info.duration > 600:
            tmp.unlink(missing_ok=True)
            raise HTTPException(400, "Video nhảy dài quá 10 phút – hãy cắt ngắn hơn.")
        final = d / f"dance{ext or '.mp4'}"
        for old in d.glob("dance.*"):
            old.unlink()
        tmp.rename(final)
        media.make_preview(final, d / "dance_preview.mp4")
        return save(pid, dance=final.name, dance_info=info.to_dict())
    raise HTTPException(400, "Loại file không hợp lệ.")


@router.delete("/{pid}/asset/{name}")
def delete_asset(pid: str, name: str):
    d = folder(pid)
    p = PROJECTS[pid]
    if name in p["clothes"]:
        p["clothes"].remove(name)
    elif name in p["tryon"]:
        p["tryon"].remove(name)
    elif name == p.get("model"):
        p["model"] = None
    else:
        raise HTTPException(404, "Không tìm thấy file.")
    (d / name).unlink(missing_ok=True)
    return save(pid)


@router.get("/{pid}/file/{name}")
def get_file(pid: str, name: str, download: bool = False):
    d = folder(pid)
    f = (d / name).resolve()
    if f.parent != d.resolve() or not f.exists() or f.name == "project.json":
        raise HTTPException(404, "Không tìm thấy file.")
    media_type = "video/mp4" if f.suffix == ".mp4" else "image/png"
    return FileResponse(f, media_type=media_type, filename=f.name if download else None,
                        headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ AI try-on

class TryonReq(BaseModel):
    count: int = 1
    notes: str = ""
    consent: bool = False


@router.post("/{pid}/tryon")
def make_tryon(pid: str, req: TryonReq):
    d = folder(pid)
    p = PROJECTS[pid]
    if not req.consent:
        raise HTTPException(400, "Hãy xác nhận bạn có quyền dùng ảnh của người mẫu này.")
    if not p.get("model"):
        raise HTTPException(400, "Hãy tải ảnh người mẫu lên trước.")
    if not p["clothes"]:
        raise HTTPException(400, "Hãy tải ít nhất một ảnh quần áo lên trước.")

    def task(progress):
        made = fashion.generate_tryon(d / p["model"], [d / c for c in p["clothes"]], d,
                                      count=req.count, notes=req.notes, on_progress=progress)
        save(pid, tryon=PROJECTS[pid]["tryon"] + made)

    return run_task(pid, "tryon", task)


# ------------------------------------------------------------------ product video

class RenderReq(BaseModel):
    durations: list[float] = [10]
    start: float = 0
    tryon: str | None = None          # file name of the try-on photo to show, or None
    tryon_at: str = "start"           # start | end | both
    pip: str | None = None            # clothes photo shown small during the dance
    keep_audio: bool = True
    enhance: bool = False


@router.post("/{pid}/render")
def make_video(pid: str, req: RenderReq):
    d = folder(pid)
    p = PROJECTS[pid]
    if not p.get("dance"):
        raise HTTPException(400, "Hãy tải video nhảy của người mẫu lên trước.")
    durations = sorted({round(min(max(float(x), 1), 60), 1) for x in req.durations})[:5]
    if not durations:
        raise HTTPException(400, "Hãy chọn ít nhất một thời lượng video.")
    tryon = req.tryon if req.tryon in p["tryon"] else None
    pip = req.pip if req.pip in p["clothes"] + p["tryon"] else None

    def task(progress):
        if not render_slots.acquire(blocking=False):
            progress("Đang có video khác được xuất, đang chờ tới lượt...")
            render_slots.acquire()
        try:
            outputs = list(PROJECTS[pid]["outputs"])
            for i, sec in enumerate(durations):
                progress(f"Đang xuất video {sec:g} giây ({i + 1}/{len(durations)})...")
                name = fashion.next_name(d, f"video_{sec:g}s", ".mp4")
                r = fashion.render_product_video(
                    d, d / p["dance"], name, duration=sec, start=req.start,
                    tryon=d / tryon if tryon else None, tryon_at=req.tryon_at,
                    pip=d / pip if pip else None, keep_audio=req.keep_audio, enhance=req.enhance)
                outputs.insert(0, {"file": name, "duration": sec, "created": int(time.time()),
                                   "looped": r["looped"]})
                save(pid, outputs=outputs[:20])
        finally:
            render_slots.release()

    return run_task(pid, "render", task)


@router.delete("/{pid}/output/{name}")
def delete_output(pid: str, name: str):
    d = folder(pid)
    outs = [o for o in PROJECTS[pid]["outputs"] if o["file"] != name]
    (d / Path(name).name).unlink(missing_ok=True)
    return save(pid, outputs=outs)


# ------------------------------------------------------------------ captions, trends, times

class PostsReq(BaseModel):
    notes: str = ""


@router.post("/{pid}/posts")
def make_posts(pid: str, req: PostsReq):
    d = folder(pid)
    p = PROJECTS[pid]
    images = [d / c for c in p["clothes"]] + [d / t for t in p["tryon"][:2]]
    if not p["clothes"]:
        raise HTTPException(400, "Hãy tải ảnh quần áo lên trước khi tạo caption.")

    def task(progress):
        progress("AI đang xem sản phẩm và tìm trend TikTok...")
        save(pid, posts=fashion.generate_posts(images, req.notes))

    return run_task(pid, "posts", task)


@router.get("/{pid}/slots")
def posting_slots(pid: str):
    folder(pid)
    return {"windows": fashion.POSTING_WINDOWS, "slots": fashion.next_slots()}


@router.get("/{pid}/reminder.ics")
def reminder(pid: str, at: str, caption: str = ""):
    folder(pid)
    try:
        when = datetime.strptime(at, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise HTTPException(400, "Thời gian nhắc không hợp lệ.")
    ics = fashion.reminder_ics(when, "Đăng video TikTok 👗", caption[:1500] or "Đến giờ đăng video thời trang!")
    return Response(ics, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="nhac-dang-tiktok-{when:%Y%m%d-%H%M}.ics"'})
