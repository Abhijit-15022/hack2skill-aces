"""Manager feed, Ask, and on-call incidents."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from .. import models as m
from .. import serialize as ser
from ..auth import Ctx, ctx
from ..services import ask as ask_svc
from ..services import feed as feed_svc
from ..services import oncall
from ..services.core import add_log, audit, user_teams

router = APIRouter(tags=["ai"])


@router.get("/feed")
def get_feed(filter: str | None = None, c: Ctx = Depends(ctx)):
    return feed_svc.for_viewer(c.db, c.user, filter)


@router.post("/feed/rebuild")
def rebuild_feed(c: Ctx = Depends(ctx)):
    return {"created_or_updated": feed_svc.rebuild(c.db, c.org_id)}


class ReactIn(BaseModel):
    kind: str  # kudos | nudge | seen


@router.post("/feed/{item_id}/react")
def react(item_id: int, body: ReactIn, c: Ctx = Depends(ctx)):
    if body.kind not in ("kudos", "nudge", "seen"):
        raise HTTPException(422, "kind must be kudos, nudge or seen.")
    item = c.db.get(m.FeedItem, item_id)
    if not item:
        raise HTTPException(404, "No such card.")
    existing = c.db.scalar(select(m.Reaction).where(m.Reaction.feed_item_id == item_id, m.Reaction.user_id == c.user.id,
                                                    m.Reaction.kind == body.kind))
    if existing and body.kind == "kudos":
        c.db.delete(existing)
        return {"ok": True, "active": False}
    if not existing:
        c.db.add(m.Reaction(org_id=c.org_id, feed_item_id=item_id, user_id=c.user.id, kind=body.kind))
    if body.kind == "nudge" and item.task_id:
        task = c.db.get(m.Task, item.task_id)
        target = c.db.get(m.User, task.assignee_id) if task.assignee_id else None
        add_log(c.db, c.org_id, source="manual", task=task, author=c.user,
                summary=f"nudged {target.name if target else 'the assignee'}")
        audit(c.db, c.org_id, actor=c.user, action=f"Nudged {target.name if target else 'assignee'} on {task.key}",
              target_type="task", target_id=task.id)
    if body.kind == "kudos" and item.subject_user_id:
        audit(c.db, c.org_id, actor=c.user, action="Sent kudos", target_type="user", target_id=item.subject_user_id)
    return {"ok": True, "active": True}


class AskIn(BaseModel):
    question: str


@router.post("/ask")
def ask(body: AskIn, c: Ctx = Depends(ctx)):
    if not body.question.strip():
        raise HTTPException(422, "Ask a question.")
    return ask_svc.answer(c.db, c.user, body.question.strip()) | {
        "scope": {"teams": len(user_teams(c.db, c.user.id)), "all": c.user.is_org_admin}}


@router.get("/incidents")
def incidents(c: Ctx = Depends(ctx)):
    rows = c.db.scalars(select(m.Incident).order_by(m.Incident.detected_at.desc()).limit(50)).all()
    return {"incidents": [ser.incident(c.db, i) for i in rows]}


@router.get("/incidents/{incident_id}")
def incident(incident_id: int, c: Ctx = Depends(ctx)):
    i = c.db.get(m.Incident, incident_id)
    if not i:
        raise HTTPException(404, "No such incident.")
    out = ser.incident(c.db, i)
    resource = c.db.get(m.Resource, i.resource_id) if i.resource_id else None
    if resource:
        teams = {t.id: t for t in c.db.scalars(select(m.Team))}
        out["owners"] = {"tech": ser.team(teams.get(resource.owner_team_id)),
                         "business": ser.team(teams.get(resource.business_team_id))}
        team = teams.get(resource.owner_team_id)
        out["autonomy"] = team.autonomy if team else "draft"
    if i.review_task_id:
        out["review_task"] = ser.task(c.db, c.db.get(m.Task, i.review_task_id))
    return out


@router.post("/incidents/{incident_id}/approve")
def approve(incident_id: int, c: Ctx = Depends(ctx)):
    i = c.db.get(m.Incident, incident_id)
    if not i:
        raise HTTPException(404, "No such incident.")
    try:
        oncall.approve(c.db, i, c.user)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return ser.incident(c.db, i)


class RejectIn(BaseModel):
    reason: str = ""


@router.post("/incidents/{incident_id}/reject")
def reject(incident_id: int, body: RejectIn, c: Ctx = Depends(ctx)):
    i = c.db.get(m.Incident, incident_id)
    if not i:
        raise HTTPException(404, "No such incident.")
    i.status = "needs_human"
    if i.review_task_id:
        review = c.db.get(m.Task, i.review_task_id)
        add_log(c.db, c.org_id, source="manual", task=review, author=c.user,
                summary=f"requested changes: {body.reason or 'no reason given'}")
    c.db.execute(delete(m.FeedItem).where(m.FeedItem.dedupe_key == f"review-{i.id}"))
    audit(c.db, c.org_id, actor=c.user, action=f"Rejected the fix for {i.key}", target_type="incident",
          target_id=i.id, reason=body.reason)
    return ser.incident(c.db, i)
