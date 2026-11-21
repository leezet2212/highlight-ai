"""API for the ✍️ Content AI tool. Stateless: results are kept in the browser."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from . import content
from .script_ai import ScriptError

router = APIRouter(prefix="/api/content")


def _ai(fn, *args):
    try:
        return fn(*args)
    except ScriptError as exc:
        raise HTTPException(400, str(exc))


@router.get("/formats")
def formats():
    return content.FORMATS


class IdeasReq(BaseModel):
    format: str = "anh_hung"
    topic: str = ""
    seconds: int = 60
    tone: str = ""
    count: int = 3


@router.post("/ideas")
def ideas(req: IdeasReq):
    return _ai(content.generate_ideas, req.format, req.topic, req.seconds, req.tone, req.count)


class CheckReq(BaseModel):
    text: str
    kind: str = "caption"
    ai_made: bool = False


@router.post("/quick-check")
def quick_check(req: CheckReq):
    return {"quick": content.quick_check(req.text)}


@router.post("/check")
def check(req: CheckReq):
    return _ai(content.check_content, req.text, req.kind, req.ai_made)


class PlanReq(BaseModel):
    topic: str = ""
    formats: list[str] = []
    days: int = 7
    per_day: int = 1
    start: str = ""


@router.post("/plan")
def plan(req: PlanReq):
    return _ai(content.generate_plan, req.topic, req.formats, req.days, req.per_day, req.start)


class IcsReq(BaseModel):
    items: list[dict]


@router.post("/plan.ics")
def plan_file(req: IcsReq):
    if not req.items:
        raise HTTPException(400, "Lịch đang trống.")
    return Response(content.plan_ics(req.items), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="lich-dang-tiktok.ics"'})
