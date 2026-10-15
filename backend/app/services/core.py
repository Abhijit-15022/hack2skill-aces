"""Small building blocks every feature uses: tasks, work logs, audit entries, feed items, queue events."""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import models as m
from . import llm


def now() -> datetime:
    return datetime.now(timezone.utc)


def agent_user(db: Session, org_id: int) -> m.User:
    return db.scalar(select(m.User).where(m.User.org_id == org_id, m.User.kind == "agent"))


def team_by_name(db: Session, name: str) -> m.Team | None:
    return db.scalar(select(m.Team).where(m.Team.name == name))


def user_teams(db: Session, user_id: int) -> list[int]:
    return list(db.scalars(select(m.TeamMember.team_id).where(m.TeamMember.user_id == user_id)))


def next_task_key(db: Session, team: m.Team | None) -> str:
    if team is None:
        n = db.scalar(select(m.Task.id).order_by(m.Task.id.desc()).limit(1)) or 0
        return f"T-{n + 1}"
    seq = db.execute(
        update(m.Team).where(m.Team.id == team.id).values(task_seq=m.Team.task_seq + 1).returning(m.Team.task_seq)
    ).scalar_one()
    return f"{team.short}-{seq}"


def task_text(task: m.Task) -> str:
    return f"{task.title}\n{task.description or ''}"


def create_task(db: Session, org_id: int, *, title: str, team: m.Team | None, created_by: m.User | None,
                assignee_id: int | None = None, type: str = "feature", status: str = "todo",
                description: str = "", description_by_ai: bool = False, project_id: int | None = None,
                parent_id: int | None = None, due_at: datetime | None = None, priority: str = "normal",
                links: list | None = None) -> m.Task:
    if assignee_id is None and team is not None:
        assignee_id = team.lead_id
    task = m.Task(
        org_id=org_id, key=next_task_key(db, team), team_id=team.id if team else None, title=title[:300],
        description=description, description_by_ai=description_by_ai, type=type, status=status,
        assignee_id=assignee_id, created_by_id=created_by.id if created_by else None, project_id=project_id,
        parent_id=parent_id, due_at=due_at, priority=priority, links=links or [],
    )
    task.embedding = llm.embed_one(f"{title}\n{description}")
    db.add(task)
    db.flush()
    return task


def refresh_task_embedding(task: m.Task) -> None:
    task.embedding = llm.embed_one(task_text(task))


def add_log(db: Session, org_id: int, *, source: str, summary: str, task: m.Task | None = None,
            author: m.User | None = None, on_behalf_of: m.User | None = None, raw_ref: str | None = None,
            meta: dict | None = None) -> m.WorkLog:
    entry = m.WorkLog(
        org_id=org_id, task_id=task.id if task else None, author_id=author.id if author else None,
        on_behalf_of_id=on_behalf_of.id if on_behalf_of else None, source=source, summary=summary,
        raw_ref=raw_ref, meta=meta or {},
    )
    entry.embedding = llm.embed_one(summary)
    db.add(entry)
    db.flush()
    return entry


def audit(db: Session, org_id: int, *, actor: m.User | None, action: str, target_type: str | None = None,
          target_id: int | None = None, reason: str = "", approved_by: str = "") -> None:
    db.add(m.AuditLog(org_id=org_id, actor_id=actor.id if actor else None, action=action, target_type=target_type,
                      target_id=target_id, reason=reason, approved_by=approved_by))


def feed(db: Session, org_id: int, *, kind: str, title: str, body: str, team_id: int | None = None,
         score: float = 0.5, task_id: int | None = None, incident_id: int | None = None,
         project_id: int | None = None, subject_user_id: int | None = None, sources: list | None = None,
         actions: list | None = None, data: dict | None = None, dedupe_key: str | None = None) -> m.FeedItem:
    if dedupe_key:
        existing = db.scalar(select(m.FeedItem).where(m.FeedItem.dedupe_key == dedupe_key))
        if existing:
            existing.kind, existing.title, existing.body, existing.score = kind, title, body, score
            existing.sources, existing.actions = sources or [], actions or []
            existing.data = data or {}
            existing.created_at = now()
            return existing
    item = m.FeedItem(org_id=org_id, kind=kind, title=title, body=body, team_id=team_id, score=score,
                      task_id=task_id, incident_id=incident_id, project_id=project_id,
                      subject_user_id=subject_user_id, sources=sources or [], actions=actions or [],
                      data=data or {}, dedupe_key=dedupe_key)
    db.add(item)
    db.flush()
    return item


def enqueue(db: Session, org_id: int, kind: str, payload: dict) -> m.Event:
    event = m.Event(org_id=org_id, kind=kind, payload=payload)
    db.add(event)
    db.flush()
    return event


def set_status(db: Session, task: m.Task, status: str, actor: m.User | None, reason: str,
               source: str = "manual") -> None:
    if task.status == status:
        return
    old = task.status
    task.status = status
    task.closed_at = now() if status == "done" else None
    label = {"todo": "to do", "doing": "in progress", "review": "in review", "done": "done"}[status]
    add_log(db, task.org_id, source=source, summary=f"marked this {label} \u2014 {reason} (was {old})", task=task,
            author=actor)
