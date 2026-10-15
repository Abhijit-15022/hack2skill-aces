"""Manager feed: finite, ranked cards built from what already happened."""
from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from .core import feed, now, user_teams

KIND_ORDER = {"needs": 0, "incident": 1, "stuck": 2, "win": 3, "decision": 4, "trend": 5, "invisible": 6}


def rebuild(db: Session, org_id: int) -> int:
    """Daily cards (stuck work, wins, invisible work, trends). Real-time cards are written by the features."""
    t = now()
    made = 0
    last_log = dict(db.execute(select(m.WorkLog.task_id, func.max(m.WorkLog.created_at))
                               .where(m.WorkLog.task_id.isnot(None)).group_by(m.WorkLog.task_id)).all())
    for task in db.scalars(select(m.Task).where(m.Task.status != "done", m.Task.type.in_(["request", "review", "sop_step"]))):
        quiet_since = last_log.get(task.id, task.created_at)
        if t - quiet_since < timedelta(days=2) and not (task.due_at and task.due_at < t):
            continue
        who = db.get(m.User, task.assignee_id) if task.assignee_id else None
        days = max((t - quiet_since).days, 1)
        reason = "overdue" if task.due_at and task.due_at < t else f"no update in {days} days"
        feed(db, org_id, kind="stuck", team_id=task.team_id, task_id=task.id, subject_user_id=task.assignee_id,
             title=f"{task.title} — {reason}", body=(task.description or "")[:220],
             sources=[task.key] + [lk.get("label") for lk in (task.links or [])[:2] if lk.get("label")],
             actions=[{"type": "nudge", "user_id": task.assignee_id}, {"type": "reassign", "task_id": task.id}],
             score=0.7 + min(days, 7) / 30, data={"assignee": who.name if who else None},
             dedupe_key=f"stuck-{task.id}")
        made += 1

    closed = db.execute(select(m.Task.assignee_id, m.Task.team_id, func.count())
                        .where(m.Task.closed_at >= t - timedelta(days=1), m.Task.assignee_id.isnot(None))
                        .group_by(m.Task.assignee_id, m.Task.team_id)).all()
    for user_id, team_id, n in closed:
        user = db.get(m.User, user_id)
        if n < 3 or user.kind != "human":
            continue
        feed(db, org_id, kind="win", team_id=team_id, subject_user_id=user_id,
             title=f"{user.name.split()[0]} closed {n} tasks", body="Closed in the last 24 hours.",
             actions=[{"type": "kudos", "user_id": user_id}], score=0.45,
             dedupe_key=f"win-{user_id}-{t:%Y%m%d}")
        made += 1

    reqs = db.execute(select(m.Task.assignee_id, m.Task.team_id, func.count()).where(
        m.Task.type == "request", m.Task.created_at >= t - timedelta(days=7)).group_by(m.Task.assignee_id, m.Task.team_id)).all()
    for user_id, team_id, n in reqs:
        if not user_id or n < 3:
            continue
        user = db.get(m.User, user_id)
        done = db.scalar(select(func.count()).where(m.Task.type == "request", m.Task.assignee_id == user_id,
                                                    m.Task.status == "done", m.Task.created_at >= t - timedelta(days=7)))
        feed(db, org_id, kind="invisible", team_id=team_id, subject_user_id=user_id,
             title=f"{user.name.split()[0]} handled {n} ad-hoc requests this week",
             body=f"Picked up from email and tracked automatically. {done} closed.",
             sources=[f"{n} email requests", f"{done} closed"], actions=[{"type": "kudos", "user_id": user_id}],
             score=0.35, dedupe_key=f"invisible-{user_id}-{t:%G%V}")
        made += 1

    for team in db.scalars(select(m.Team)):
        this_week = db.scalar(select(func.count()).select_from(m.Incident).join(m.Task, m.Task.id == m.Incident.task_id)
                              .where(m.Task.team_id == team.id, m.Incident.detected_at >= t - timedelta(days=7)))
        last_week = db.scalar(select(func.count()).select_from(m.Incident).join(m.Task, m.Task.id == m.Incident.task_id)
                              .where(m.Task.team_id == team.id, m.Incident.detected_at >= t - timedelta(days=14),
                                     m.Incident.detected_at < t - timedelta(days=7)))
        if last_week >= 2 and this_week < last_week:
            pct = round((last_week - this_week) / last_week * 100)
            days = []
            for d in range(7):
                start = t - timedelta(days=7 - d)
                days.append(db.scalar(select(func.count()).select_from(m.Incident).join(m.Task, m.Task.id == m.Incident.task_id)
                                      .where(m.Task.team_id == team.id, m.Incident.detected_at >= start,
                                             m.Incident.detected_at < start + timedelta(days=1))))
            feed(db, org_id, kind="trend", team_id=team.id, title=f"{team.name} failures down {pct}% this week",
                 body=f"{this_week} this week vs {last_week} last week.", data={"per_day": days}, score=0.3,
                 dedupe_key=f"trend-{team.id}-{t:%G%V}")
            made += 1
    return made


def for_viewer(db: Session, viewer: m.User, kind_filter: str | None = None) -> dict:
    t = now()
    teams = user_teams(db, viewer.id)
    q = select(m.FeedItem).where(m.FeedItem.created_at >= t - timedelta(days=3))
    if not viewer.is_org_admin:
        q = q.where((m.FeedItem.team_id.in_(teams or [-1])) | (m.FeedItem.team_id.is_(None)))
    items = db.scalars(q).all()
    groups = {"needs": {"needs", "stuck"}, "failures": {"incident", "trend"}, "wins": {"win", "invisible", "decision"}}
    if kind_filter in groups:
        items = [i for i in items if i.kind in groups[kind_filter]]
    items.sort(key=lambda i: (KIND_ORDER.get(i.kind, 9), -i.score, -i.created_at.timestamp()))
    reactions = db.execute(select(m.Reaction.feed_item_id, m.Reaction.kind, m.Reaction.user_id)
                           .where(m.Reaction.feed_item_id.in_([i.id for i in items] or [-1]))).all()
    kudos = Counter(r[0] for r in reactions if r[1] == "kudos")
    mine = {(r[0], r[1]) for r in reactions if r[2] == viewer.id}
    team_names = {tm.id: tm for tm in db.scalars(select(m.Team))}
    cards = [{
        "id": i.id, "kind": i.kind, "title": i.title, "body": i.body, "team": team_names[i.team_id].name if i.team_id in team_names else None,
        "created_at": i.created_at, "sources": i.sources, "actions": i.actions, "data": i.data,
        "task_id": i.task_id, "incident_id": i.incident_id, "project_id": i.project_id,
        "kudos": kudos.get(i.id, 0), "kudos_by_me": (i.id, "kudos") in mine, "nudged_by_me": (i.id, "nudge") in mine,
    } for i in items]
    stories = []
    for tid, team in team_names.items():
        if not viewer.is_org_admin and tid not in teams:
            continue
        team_items = [i for i in items if i.team_id == tid]
        health = "red" if any(i.kind == "incident" and "green again" not in i.title for i in team_items) else (
            "amber" if any(i.kind == "stuck" for i in team_items) else "green")
        stories.append({"team_id": tid, "name": team.name, "short": team.short, "color": team.color,
                        "health": health, "items": [c for c in cards if c["team"] == team.name][:5]})
    stories.sort(key=lambda s: {"red": 0, "amber": 1, "green": 2}[s["health"]])
    return {
        "cards": cards, "stories": stories,
        "summary": {"total": len(cards), "needs_you": sum(1 for c in cards if c["kind"] in ("needs", "stuck")),
                    "handled": sum(1 for c in cards if (c["id"], "nudge") in mine or c["kudos_by_me"])},
    }
