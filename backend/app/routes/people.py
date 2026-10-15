"""My Day, Focus Guard, Team Health, async standups and meeting capture."""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from .. import models as m
from ..auth import Ctx, admin_ctx, ctx
from ..services import focus, health, meetings, myday
from ..services.core import enqueue, user_teams

router = APIRouter(tags=["people"])
SAMPLE_MEETING = Path(__file__).resolve().parents[1] / "assets" / "sample-meeting.wav"


# ---------------------------------------------------------------- My Day

@router.get("/me/day")
def my_day(c: Ctx = Depends(ctx)):
    return myday.serialize(c.db, myday.get_or_plan(c.db, c.user), c.user)


@router.post("/me/day/plan")
def replan(c: Ctx = Depends(ctx)):
    return myday.serialize(c.db, myday.plan(c.db, c.user), c.user)


@router.get("/users/{user_id}/day")
def user_day(user_id: int, c: Ctx = Depends(ctx)):
    user = c.db.get(m.User, user_id)
    if user is None:
        raise HTTPException(404, "No such person.")
    leads = {t.id for t in health.teams_for(c.db, c.user)}
    if not (c.user.is_org_admin or user.id == c.user.id or leads & set(user_teams(c.db, user.id))):
        raise HTTPException(403, "You can see the plans of people in teams you lead.")
    return myday.serialize(c.db, myday.get_or_plan(c.db, user), user)


# ---------------------------------------------------------------- connected tools (relay-agent)

@router.get("/me/devices")
def my_devices(c: Ctx = Depends(ctx)):
    from ..services import devices
    return devices.for_user(c.db, c.user)


@router.get("/admin/devices")
def org_devices(c: Ctx = Depends(admin_ctx)):
    from ..services import devices
    return devices.for_org(c.db)


# ---------------------------------------------------------------- Focus Guard

class FocusIn(BaseModel):
    minutes: int = 50
    task_id: int | None = None


@router.get("/me/notifications")
def notifications(c: Ctx = Depends(ctx)):
    focus.release(c.db, c.user.id)
    return focus.inbox(c.db, c.user)


@router.post("/me/focus")
def start_focus(body: FocusIn, c: Ctx = Depends(ctx)):
    if not 5 <= body.minutes <= 240:
        raise HTTPException(422, "Focus time must be between 5 and 240 minutes.")
    task = c.db.get(m.Task, body.task_id) if body.task_id else None
    focus.start_focus(c.db, c.user, body.minutes, task)
    if task and task.status == "todo":
        task.status = "doing"
    return focus.inbox(c.db, c.user)


@router.post("/me/focus/end")
def end_focus(c: Ctx = Depends(ctx)):
    released = focus.end_focus(c.db, c.user)
    return focus.inbox(c.db, c.user) | {"released": released}


@router.post("/notifications/{notification_id}/read")
def read(notification_id: int, c: Ctx = Depends(ctx)):
    n = c.db.get(m.Notification, notification_id)
    if n and n.user_id == c.user.id:
        n.status = "read"
    return {"ok": True}


# ---------------------------------------------------------------- Team Health and standups

@router.get("/health/teams")
def team_health(c: Ctx = Depends(ctx)):
    return health.report(c.db, c.user)


class ActionIn(BaseModel):
    type: str
    task_id: int
    to_user_id: int | None = None


@router.post("/health/actions")
def health_action(body: ActionIn, c: Ctx = Depends(ctx)):
    try:
        return health.apply_action(c.db, c.user, body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/teams/{team_id}/standup")
def team_standup(team_id: int, refresh: bool = False, c: Ctx = Depends(ctx)):
    team = c.db.get(m.Team, team_id)
    if team is None:
        raise HTTPException(404, "No such team.")
    s = meetings.standup(c.db, team, refresh)
    return {"team": {"id": team.id, "name": team.name, "color": team.color}, "day": s.day, "by_ai": s.by_ai,
            "people": s.people, "generated_at": s.created_at}


# ---------------------------------------------------------------- meetings

@router.get("/meetings")
def list_meetings(c: Ctx = Depends(ctx)):
    rows = c.db.scalars(select(m.Meeting).order_by(m.Meeting.created_at.desc()).limit(30)).all()
    return {"meetings": [meetings.serialize(r) for r in rows]}


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int, c: Ctx = Depends(ctx)):
    mt = c.db.get(m.Meeting, meeting_id)
    if mt is None:
        raise HTTPException(404, "No such meeting.")
    return meetings.serialize(mt)


def _queue_meeting(c: Ctx, title: str, src: Path, original_name: str) -> dict:
    dest = meetings.meetings_dir() / f"{uuid.uuid4().hex}{Path(original_name).suffix.lower() or '.wav'}"
    shutil.copy(src, dest)
    team_ids = user_teams(c.db, c.user.id)
    mt = m.Meeting(org_id=c.org_id, created_by_id=c.user.id, team_id=team_ids[0] if team_ids else None,
                   title=title or Path(original_name).stem, file_name=original_name)
    c.db.add(mt)
    c.db.flush()
    enqueue(c.db, c.org_id, "meeting_process", {"meeting_id": mt.id, "path": str(dest), "user_id": c.user.id})
    return meetings.serialize(mt)


@router.post("/meetings")
async def upload_meeting(title: str = Form(""), file: UploadFile = File(...), c: Ctx = Depends(ctx)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".webm", ".aiff"):
        raise HTTPException(422, "Upload an audio recording (wav, mp3, m4a, aac, ogg, flac or webm).")
    tmp = meetings.meetings_dir() / f"upload-{uuid.uuid4().hex}{suffix}"
    with tmp.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    try:
        return _queue_meeting(c, title, tmp, file.filename or f"meeting{suffix}")
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/demo/meeting/sample")
def sample_meeting(c: Ctx = Depends(ctx)):
    if not SAMPLE_MEETING.exists():
        raise HTTPException(404, "The sample recording is missing from the build.")
    return _queue_meeting(c, "Data and Finance sync", SAMPLE_MEETING, "sample-meeting.wav")


@router.get("/demo/meeting/sample.wav")
def sample_audio():
    return FileResponse(SAMPLE_MEETING, media_type="audio/wav")


# ---------------------------------------------------------------- demo helpers

@router.post("/demo/plan-everyone")
def plan_everyone(c: Ctx = Depends(admin_ctx)):
    users = c.db.scalars(select(m.User).where(m.User.kind == "human")).all()
    for u in users:
        enqueue(c.db, c.org_id, "plan_day", {"user_id": u.id})
    return {"queued": len(users)}


@router.post("/demo/focus/{email}")
def demo_focus(email: str, c: Ctx = Depends(admin_ctx)):
    """Start a 50-minute focus block for someone and send them five pings, one of them urgent."""
    user = c.db.scalar(select(m.User).where(m.User.email == email.lower()))
    if user is None:
        raise HTTPException(404, "No such person.")
    plan = myday.get_or_plan(c.db, user)
    task = c.db.get(m.Task, plan.items[0]["task_id"]) if plan.items else None
    focus.start_focus(c.db, user, 50, task)
    pings = [
        ("kudos", "Kavya sent you kudos", "For closing 3 requests yesterday."),
        ("fyi", "Weekly finance newsletter is out", "Read when you have time."),
        ("request", "Ananya replied on the Q3 payouts thread", "Thanks! Friday is fine."),
        ("nudge", "Arjun asked about the Lumen Logistics KYC", "Any update on the approval?"),
        ("incident", "orders_daily failed: Revenue dashboard will be late", "The on-call agent is on it; Finance numbers are stale."),
    ]
    out = [focus.notify(c.db, user.id, k, t, b) for k, t, b in pings]
    return {"held": sum(1 for n in out if n and n.status == "held"),
            "delivered": sum(1 for n in out if n and n.status == "delivered"), "user": user.name}
