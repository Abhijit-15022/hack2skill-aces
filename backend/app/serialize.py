"""Turn ORM rows into JSON the UI can render directly."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m


def user(u: m.User | None) -> dict | None:
    if u is None:
        return None
    return {"id": u.id, "name": u.name, "email": u.email, "kind": u.kind, "title": u.title,
            "initials": u.initials, "color": u.color, "is_org_admin": u.is_org_admin}


def team(t: m.Team | None) -> dict | None:
    if t is None:
        return None
    return {"id": t.id, "name": t.name, "short": t.short, "color": t.color, "handles": t.handles,
            "lead_id": t.lead_id, "autonomy": t.autonomy}


def task(db: Session, t: m.Task, detail: bool = False) -> dict:
    out = {
        "id": t.id, "key": t.key, "title": t.title, "type": t.type, "status": t.status, "priority": t.priority,
        "description": t.description, "description_by_ai": t.description_by_ai,
        "team": team(db.get(m.Team, t.team_id)) if t.team_id else None,
        "assignee": user(db.get(m.User, t.assignee_id)) if t.assignee_id else None,
        "created_by": user(db.get(m.User, t.created_by_id)) if t.created_by_id else None,
        "project_id": t.project_id, "parent_id": t.parent_id, "due_at": t.due_at, "created_at": t.created_at,
        "updated_at": t.updated_at, "closed_at": t.closed_at, "links": t.links or [],
    }
    last = db.scalar(select(m.WorkLog).where(m.WorkLog.task_id == t.id).order_by(m.WorkLog.created_at.desc()).limit(1))
    out["last_update"] = {"source": last.source, "at": last.created_at} if last else None
    if detail:
        logs = db.scalars(select(m.WorkLog).where(m.WorkLog.task_id == t.id).order_by(m.WorkLog.created_at)).all()
        out["timeline"] = [{
            "id": lg.id, "source": lg.source, "summary": lg.summary, "at": lg.created_at, "meta": lg.meta,
            "author": user(db.get(m.User, lg.author_id)) if lg.author_id else None,
        } for lg in logs]
        out["sources_count"] = len({(lg.source, lg.raw_ref) for lg in logs})
        out["children"] = [{"id": c.id, "key": c.key, "title": c.title, "status": c.status}
                           for c in db.scalars(select(m.Task).where(m.Task.parent_id == t.id))]
    return out


def incident(db: Session, i: m.Incident) -> dict:
    return {
        "id": i.id, "key": i.key, "namespace": i.namespace, "flow_id": i.flow_id, "execution_id": i.execution_id,
        "status": i.status, "severity": i.severity, "category": i.category, "cause_kind": i.cause_kind,
        "root_cause_title": i.root_cause_title, "root_cause": i.root_cause, "confidence": i.confidence,
        "steps": i.steps or [], "fix": {k: v for k, v in (i.fix or {}).items() if k not in ("old_sql",)},
        "impact": i.impact or [], "task_id": i.task_id, "review_task_id": i.review_task_id,
        "detected_at": i.detected_at, "resolved_at": i.resolved_at,
    }
