"""Tasks, projects and SOPs."""
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from .. import models as m
from .. import serialize as ser
from ..auth import Ctx, ctx
from ..services import sop as sop_svc
from ..services.core import add_log, audit, create_task, refresh_task_embedding, set_status, user_teams

router = APIRouter(tags=["work"])
STATUSES = ("todo", "doing", "review", "done")


# ---------------------------------------------------------------- tasks

@router.get("/tasks")
def list_tasks(team_id: int | None = None, assignee_id: int | None = None, status: str | None = None,
               project_id: int | None = None, mine: bool = False, c: Ctx = Depends(ctx)):
    q = select(m.Task).order_by(m.Task.updated_at.desc())
    if not c.user.is_org_admin:
        teams = user_teams(c.db, c.user.id)
        q = q.where((m.Task.team_id.in_(teams or [-1])) | (m.Task.assignee_id == c.user.id))
    if team_id:
        q = q.where(m.Task.team_id == team_id)
    if assignee_id or mine:
        q = q.where(m.Task.assignee_id == (assignee_id or c.user.id))
    if status:
        q = q.where(m.Task.status == status)
    if project_id:
        q = q.where(m.Task.project_id == project_id)
    tasks = c.db.scalars(q.limit(300)).all()
    by_ai = sum(1 for t in tasks if t.description_by_ai)
    return {"tasks": [ser.task(c.db, t) for t in tasks],
            "columns": {s: [t.id for t in tasks if t.status == s] for s in STATUSES},
            "auto_written_pct": round(by_ai / len(tasks) * 100) if tasks else 0}


@router.get("/tasks/{task_id}")
def get_task(task_id: int, c: Ctx = Depends(ctx)):
    task = c.db.get(m.Task, task_id)
    if not task:
        task = c.db.scalar(select(m.Task).where(m.Task.key == str(task_id)))
    if not task:
        raise HTTPException(404, "No such task.")
    return ser.task(c.db, task, detail=True)


@router.get("/tasks/by-key/{key}")
def get_task_by_key(key: str, c: Ctx = Depends(ctx)):
    task = c.db.scalar(select(m.Task).where(m.Task.key == key.upper()))
    if not task:
        raise HTTPException(404, "No such task.")
    return ser.task(c.db, task, detail=True)


class TaskIn(BaseModel):
    title: str
    description: str = ""
    team_id: int | None = None
    assignee_id: int | None = None
    project_id: int | None = None
    type: str = "feature"
    priority: str = "normal"
    due_at: datetime | None = None


@router.post("/tasks")
def new_task(body: TaskIn, c: Ctx = Depends(ctx)):
    team = c.db.get(m.Team, body.team_id) if body.team_id else None
    if team is None:
        ids = user_teams(c.db, c.user.id)
        team = c.db.get(m.Team, ids[0]) if ids else None
    task = create_task(c.db, c.org_id, title=body.title, team=team, created_by=c.user,
                       assignee_id=body.assignee_id, type=body.type, description=body.description,
                       project_id=body.project_id, due_at=body.due_at, priority=body.priority)
    add_log(c.db, c.org_id, source="manual", summary="created this task", task=task, author=c.user)
    return ser.task(c.db, task, detail=True)


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    assignee_id: int | None = None
    team_id: int | None = None
    priority: str | None = None
    due_at: datetime | None = None


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskPatch, c: Ctx = Depends(ctx)):
    task = c.db.get(m.Task, task_id)
    if not task:
        raise HTTPException(404, "No such task.")
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes:
        if changes["status"] not in STATUSES:
            raise HTTPException(422, f"status must be one of {', '.join(STATUSES)}.")
        set_status(c.db, task, changes.pop("status"), c.user, "updated by hand")
        if task.status == "done":
            sp = c.db.scalar(select(m.StepProgress).where(m.StepProgress.task_id == task.id,
                                                          m.StepProgress.status.in_(["pending", "needs_confirmation"])))
            if sp:
                sop_svc.mark_done(c.db, sp, log=None, confidence=1.0, by=c.user)
    if "assignee_id" in changes and changes["assignee_id"] != task.assignee_id:
        new = c.db.get(m.User, changes["assignee_id"]) if changes["assignee_id"] else None
        add_log(c.db, c.org_id, source="manual", task=task, author=c.user,
                summary=f"reassigned to {new.name if new else 'nobody'}")
    if "description" in changes:
        task.description_by_ai = False
    for k, v in changes.items():
        setattr(task, k, v)
    if {"title", "description"} & changes.keys():
        refresh_task_embedding(task)
    return ser.task(c.db, task, detail=True)


class CommentIn(BaseModel):
    text: str


@router.post("/tasks/{task_id}/comments")
def comment(task_id: int, body: CommentIn, c: Ctx = Depends(ctx)):
    task = c.db.get(m.Task, task_id)
    if not task:
        raise HTTPException(404, "No such task.")
    add_log(c.db, c.org_id, source="manual", summary=body.text, task=task, author=c.user)
    return ser.task(c.db, task, detail=True)


# ---------------------------------------------------------------- projects

@router.get("/projects")
def list_projects(c: Ctx = Depends(ctx)):
    out = []
    for p in c.db.scalars(select(m.Project).order_by(m.Project.started_at.desc())):
        steps = sop_svc.progress(c.db, p) if p.sop_id else []
        done = sum(1 for s in steps if s["status"] in ("done", "done_out_of_order"))
        out.append({"id": p.id, "name": p.name, "subject": p.subject, "status": p.status, "team_id": p.team_id,
                    "sop_id": p.sop_id, "done": done, "total": len(steps), "started_at": p.started_at})
    return {"projects": out}


@router.get("/projects/{project_id}")
def get_project(project_id: int, c: Ctx = Depends(ctx)):
    p = c.db.get(m.Project, project_id)
    if not p:
        raise HTTPException(404, "No such project.")
    sop = c.db.get(m.Sop, p.sop_id) if p.sop_id else None
    steps = sop_svc.progress(c.db, p)
    activity = c.db.scalars(select(m.WorkLog).join(m.Task, m.Task.id == m.WorkLog.task_id)
                            .where(m.Task.project_id == p.id).order_by(m.WorkLog.created_at.desc()).limit(10)).all()
    return {
        "id": p.id, "name": p.name, "subject": p.subject, "status": p.status, "started_at": p.started_at,
        "team": ser.team(c.db.get(m.Team, p.team_id)) if p.team_id else None,
        "owner": ser.user(c.db.get(m.User, p.owner_id)) if p.owner_id else None,
        "sop": {"id": sop.id, "title": sop.title, "version": p.sop_version} if sop else None,
        "steps": steps, "done": sum(1 for s in steps if s["status"] in ("done", "done_out_of_order")),
        "drift": sop_svc.drift(c.db, sop) if sop else [],
        "activity": [{"summary": a.summary, "source": a.source, "at": a.created_at} for a in activity],
    }


class ProjectIn(BaseModel):
    sop_id: int
    name: str
    subject: str | None = None


@router.post("/projects")
def start_project(body: ProjectIn, c: Ctx = Depends(ctx)):
    sop = c.db.get(m.Sop, body.sop_id)
    if not sop or sop.status != "published":
        raise HTTPException(422, "Start projects from a published SOP.")
    project = sop_svc.start_project(c.db, sop, name=body.name, subject=body.subject, owner=c.user)
    return get_project(project.id, c)


class ConfirmIn(BaseModel):
    yes: bool


@router.post("/step-progress/{sp_id}/confirm")
def confirm_step(sp_id: int, body: ConfirmIn, c: Ctx = Depends(ctx)):
    sp = c.db.get(m.StepProgress, sp_id)
    if not sp:
        raise HTTPException(404, "No such step.")
    if body.yes:
        sop_svc.mark_done(c.db, sp, log=c.db.get(m.WorkLog, sp.matched_log_id) if sp.matched_log_id else None,
                          confidence=1.0, by=c.user)
    else:
        sp.status, sp.matched_log_id, sp.confidence = "pending", None, None
    c.db.execute(delete(m.FeedItem).where(m.FeedItem.dedupe_key == f"confirm-{sp.id}"))
    audit(c.db, c.org_id, actor=c.user, action=f"{'Confirmed' if body.yes else 'Rejected'} an evidence match",
          target_type="step_progress", target_id=sp.id)
    return get_project(sp.project_id, c)


# ---------------------------------------------------------------- SOPs

def _sop_out(c: Ctx, s: m.Sop) -> dict:
    steps = c.db.scalars(select(m.SopStep).where(m.SopStep.sop_id == s.id).order_by(m.SopStep.seq)).all()
    teams = {t.id: t.name for t in c.db.scalars(select(m.Team))}
    projects = c.db.scalar(select(func.count()).select_from(m.Project).where(m.Project.sop_id == s.id))
    return {
        "id": s.id, "title": s.title, "description": s.description, "status": s.status, "version": s.version,
        "team_id": s.team_id, "team": teams.get(s.team_id), "source_file": s.source_file, "projects": projects,
        "steps": [{"id": st.id, "seq": st.seq, "title": st.title, "owner_team_id": st.owner_team_id,
                   "owner_team": teams.get(st.owner_team_id), "owner_role": st.owner_role,
                   "evidence_type": st.evidence_type, "evidence_hint": st.evidence_hint,
                   "due_offset_days": st.due_offset_days, "depends_on": st.depends_on or [],
                   "needs_approval": st.needs_approval, "notes": st.notes} for st in steps],
    }


@router.get("/sops")
def list_sops(c: Ctx = Depends(ctx)):
    return {"sops": [_sop_out(c, s) for s in c.db.scalars(select(m.Sop).order_by(m.Sop.title))]}


@router.get("/sops/{sop_id}")
def get_sop(sop_id: int, c: Ctx = Depends(ctx)):
    s = c.db.get(m.Sop, sop_id)
    if not s:
        raise HTTPException(404, "No such SOP.")
    return _sop_out(c, s) | {"suggestions": sop_svc.review_suggestions(c.db, s)}


def _team_admin(c: Ctx, team_id: int) -> None:
    if c.user.is_org_admin:
        return
    role = c.db.scalar(select(m.TeamMember.role).where(m.TeamMember.team_id == team_id,
                                                      m.TeamMember.user_id == c.user.id))
    if role not in ("admin", "lead"):
        raise HTTPException(403, "Only this team's admins can edit its SOPs.")


def _save_steps(c: Ctx, sop: m.Sop, steps: list[dict]) -> None:
    teams = {t.name.lower(): t.id for t in c.db.scalars(select(m.Team))}
    c.db.execute(delete(m.SopStep).where(m.SopStep.sop_id == sop.id))
    for i, st in enumerate(steps, start=1):
        owner = st.get("owner_team_id") or teams.get((st.get("owner_team") or "").lower())
        if owner is None and not st.get("owner_role"):
            owner = sop.team_id
        c.db.add(m.SopStep(org_id=c.org_id, sop_id=sop.id, seq=i, title=st.get("title", f"Step {i}")[:300],
                           owner_team_id=owner, owner_role=st.get("owner_role"),
                           evidence_type=st.get("evidence_type") or "manual",
                           evidence_hint=st.get("evidence_hint") or "",
                           due_offset_days=int(st.get("due_offset_days") or 0),
                           depends_on=[int(d) for d in (st.get("depends_on") or [])],
                           needs_approval=bool(st.get("needs_approval")), notes=st.get("notes") or ""))
    c.db.flush()


@router.post("/sops/draft")
async def draft_sop(team_id: int = Form(...), text: str = Form(""), file: UploadFile | None = File(None),
                    c: Ctx = Depends(ctx)):
    """Create a draft SOP from an uploaded PDF/DOCX/TXT or a plain-English description."""
    _team_admin(c, team_id)
    source_name = None
    if file is not None:
        raw = await file.read()
        source_name = file.filename
        if (file.filename or "").lower().endswith(".pdf"):
            import io

            from pypdf import PdfReader
            text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)
        else:
            text = raw.decode("utf-8", errors="ignore")
    if not text.strip():
        raise HTTPException(422, "Upload a file or describe the process.")
    team_names = [t.name for t in c.db.scalars(select(m.Team))]
    draft = sop_svc.draft_steps(text, team_names)
    sop = m.Sop(org_id=c.org_id, team_id=team_id, title=draft.get("title") or "New SOP",
                description=draft.get("description") or "", status="draft", version=1, source_file=source_name,
                owner_id=c.user.id)
    c.db.add(sop)
    c.db.flush()
    _save_steps(c, sop, draft.get("steps") or [])
    audit(c.db, c.org_id, actor=c.user, action=f"Drafted SOP “{sop.title}” with AI", target_type="sop",
          target_id=sop.id, reason=f"from {source_name or 'a description'}")
    return get_sop(sop.id, c)


class SopIn(BaseModel):
    title: str | None = None
    description: str | None = None
    steps: list[dict] | None = None


@router.put("/sops/{sop_id}")
def save_sop(sop_id: int, body: SopIn, c: Ctx = Depends(ctx)):
    s = c.db.get(m.Sop, sop_id)
    if not s:
        raise HTTPException(404, "No such SOP.")
    _team_admin(c, s.team_id)
    in_use = c.db.scalar(select(func.count()).select_from(m.Project).where(m.Project.sop_id == s.id))
    if s.status == "published" and in_use:
        # Running projects keep their version; edits go into a new draft version.
        s = m.Sop(org_id=c.org_id, team_id=s.team_id, title=s.title, description=s.description, status="draft",
                  version=s.version + 1, source_file=s.source_file, owner_id=c.user.id)
        c.db.add(s)
        c.db.flush()
        if body.steps is None:
            old = _sop_out(c, c.db.get(m.Sop, sop_id))["steps"]
            _save_steps(c, s, old)
    if body.title is not None:
        s.title = body.title
    if body.description is not None:
        s.description = body.description
    if body.steps is not None:
        _save_steps(c, s, body.steps)
    if s.status == "published":
        s.status = "draft"
    return get_sop(s.id, c)


@router.post("/sops/{sop_id}/publish")
def publish_sop(sop_id: int, c: Ctx = Depends(ctx)):
    s = c.db.get(m.Sop, sop_id)
    if not s:
        raise HTTPException(404, "No such SOP.")
    _team_admin(c, s.team_id)
    for older in c.db.scalars(select(m.Sop).where(m.Sop.team_id == s.team_id, m.Sop.title == s.title,
                                                  m.Sop.id != s.id, m.Sop.status == "published")):
        older.status = "superseded"
    s.status = "published"
    audit(c.db, c.org_id, actor=c.user, action=f"Published {s.title} v{s.version}", target_type="sop", target_id=s.id)
    return get_sop(s.id, c)
