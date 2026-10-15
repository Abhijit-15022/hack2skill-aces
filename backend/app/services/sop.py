"""SOPs: draft them with AI, run them as projects, tick steps off from evidence, spot outdated SOPs."""
import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from . import llm
from .core import add_log, audit, create_task, feed, now, set_status

EVIDENCE_TYPES = ("email", "calendar", "file", "task", "manual")
STOP = set("a an the and or of to for in on with by is be at from as it this that new step".split())
AUTO_DONE = 0.75
# The kind of evidence itself says something: a calendar invite means something was booked/scheduled.
KIND_WORDS = {"calendar": "book schedule calendar invite meeting", "email": "email send sent share",
              "file": "upload file document", "task": "task ticket closed"}
ASK = 0.45


def _guess_evidence(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(book|schedule|meeting|induction|call|check-in|interview|session)\b", t):
        return "calendar"
    if re.search(r"\b(upload|file|document|pdf|scan|attach)\b", t):
        return "file"
    if re.search(r"\b(email|send|share|collect|receive|request|notify|tell|inform)\b", t):
        return "email"
    if re.search(r"\b(create|ship|set up|setup|provision|install|account)\b", t):
        return "task"
    return "manual"


def draft_steps(text: str, team_names: list[str]) -> dict:
    """Turn an SOP document or a plain-English description into structured steps."""
    prompt = f"""You turn a company's standard operating procedure into a checklist that software can track.
Teams in this company: {", ".join(team_names)}.
Return JSON: {{"title": str, "description": str, "steps": [{{"title": str (imperative, max 8 words),
"owner_team": one of the teams or null, "owner_role": str or null (e.g. "hiring manager"),
"evidence_type": one of {list(EVIDENCE_TYPES)}, "evidence_hint": str (what proves it is done, e.g.
"email with signed offer attached"), "due_offset_days": int (days after the project starts),
"depends_on": [int step numbers, 1-based], "needs_approval": bool}}]}}.
Keep 3-12 steps, in order. Document:
---
{text[:20000]}
---"""
    out = llm.generate_json(prompt, tier="smart")
    if out and out.get("steps"):
        for s in out["steps"]:
            if s.get("evidence_type") not in EVIDENCE_TYPES:
                s["evidence_type"] = _guess_evidence(s.get("title", ""))
        return out
    lines = [re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if 3 < len(ln) < 200]
    title = lines[0] if lines else "New SOP"
    steps = lines[1:13] if len(lines) > 1 else lines
    return {
        "title": title[:120],
        "description": "",
        "steps": [{"title": s[:120], "owner_team": None, "owner_role": None, "evidence_type": _guess_evidence(s),
                   "evidence_hint": "", "due_offset_days": i * 2, "depends_on": [i] if i else [],
                   "needs_approval": False} for i, s in enumerate(steps)],
    }


def review_suggestions(db: Session, sop: m.Sop) -> list[dict]:
    """Rule-based checks plus drift found in past projects. Each suggestion can be applied by the UI."""
    steps = db.scalars(select(m.SopStep).where(m.SopStep.sop_id == sop.id).order_by(m.SopStep.seq)).all()
    out = []
    for s in steps:
        if s.evidence_type == "manual" and not s.needs_approval:
            guess = _guess_evidence(f"{s.title} {s.evidence_hint}")
            guess = "task" if guess == "manual" else guess
            what = {"email": "an email", "calendar": "a calendar invite", "file": "an uploaded file", "task": "a closed task"}[guess]
            out.append({"id": f"evidence-{s.id}", "kind": "MISSING DETAIL", "step_id": s.id,
                        "text": f"Step {s.seq} (\u201c{s.title}\u201d) is ticked off by hand. Match it to {what} so "
                                "it's tracked automatically.",
                        "apply": {"step_id": s.id, "evidence_type": guess}})
        if s.owner_team_id is None and not s.owner_role:
            out.append({"id": f"owner-{s.id}", "kind": "MISSING OWNER", "step_id": s.id,
                        "text": f"Step {s.seq} has no owner team, so Relay can't assign it.", "apply": None})
    out.extend(drift(db, sop))
    return out


def drift(db: Session, sop: m.Sop) -> list[dict]:
    """Steps that teams regularly complete before their dependencies: the SOP order is probably out of date."""
    steps = {s.id: s for s in db.scalars(select(m.SopStep).where(m.SopStep.sop_id == sop.id))}
    projects = db.scalars(select(m.Project).where(m.Project.sop_id == sop.id)).all()
    if len(projects) < 5:
        return []
    out = []
    for step in steps.values():
        if not step.depends_on:
            continue
        rows = db.scalars(select(m.StepProgress).where(m.StepProgress.sop_step_id == step.id,
                                                       m.StepProgress.status.in_(["done", "done_out_of_order"]))).all()
        if len(rows) < 5:
            continue
        early = sum(1 for r in rows if r.status == "done_out_of_order")
        if early / len(rows) >= 0.6:
            dep = ", ".join(str(d) for d in step.depends_on)
            out.append({"id": f"drift-{step.id}", "kind": "SOP MAY BE OUT OF DATE", "step_id": step.id,
                        "text": f"In {early} of the last {len(rows)} projects, step {step.seq} "
                                f"(“{step.title}”) was done before step {dep}. Move it earlier?",
                        "apply": {"step_id": step.id, "move_before": min(step.depends_on)}})
    return out


def start_project(db: Session, sop: m.Sop, *, name: str, subject: str | None, owner: m.User,
                  team_id: int | None = None) -> m.Project:
    project = m.Project(org_id=sop.org_id, team_id=team_id or sop.team_id, name=name, subject=subject,
                        sop_id=sop.id, sop_version=sop.version, owner_id=owner.id)
    db.add(project)
    db.flush()
    steps = db.scalars(select(m.SopStep).where(m.SopStep.sop_id == sop.id).order_by(m.SopStep.seq)).all()
    for step in steps:
        team = db.get(m.Team, step.owner_team_id) if step.owner_team_id else None
        assignee = owner.id if (step.owner_role and not team) else None
        due = project.started_at + timedelta(days=step.due_offset_days) if project.started_at else None
        desc = (f"Step {step.seq} of {sop.title} (v{sop.version}). Done when: "
                f"{step.evidence_hint or step.evidence_type}.")
        task = create_task(db, sop.org_id, title=f"{step.title} — {subject}" if subject else step.title,
                           team=team, created_by=owner, assignee_id=assignee, type="sop_step",
                           description=desc, description_by_ai=True, project_id=project.id, due_at=due)
        db.add(m.StepProgress(org_id=sop.org_id, project_id=project.id, sop_step_id=step.id, task_id=task.id,
                              due_at=due))
    audit(db, sop.org_id, actor=owner, action=f"Started project “{name}” from {sop.title} v{sop.version}",
          target_type="project", target_id=project.id)
    return project


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in STOP}


def _score(step: m.SopStep, project: m.Project, evidence: str) -> float:
    ev = f"{evidence.lower()} {KIND_WORDS.get(step.evidence_type, '')}"
    title_kw = _keywords(step.title)
    all_kw = title_kw | _keywords(step.evidence_hint)
    lexical = max(len([w for w in title_kw if w in ev]) / max(len(title_kw), 1),
                  len([w for w in all_kw if w in ev]) / max(len(all_kw), 1))
    semantic = llm.cosine(llm.embed_one(evidence, "RETRIEVAL_QUERY"),
                          llm.embed_one(f"{step.title}. {step.evidence_hint}"))
    score = max(lexical, semantic if llm.enabled() else lexical)
    if project.subject and project.subject.lower() in ev:
        score += 0.3
    elif project.subject and project.subject.split()[0].lower() in ev:
        score += 0.1
    return score


def _judge(step: m.SopStep, project: m.Project, evidence: str) -> float | None:
    out = llm.generate_json(
        f"""Project: {project.name} (about {project.subject or "n/a"}).
SOP step {step.seq}: "{step.title}". It counts as done when: {step.evidence_hint or step.evidence_type}.
New evidence:
---
{evidence[:3000]}
---
Does this evidence show the step is done? Return JSON {{"match": bool, "confidence": number 0-1, "why": str}}.""")
    if not out:
        return None
    return float(out.get("confidence", 0)) if out.get("match") else 0.0


def match_evidence(db: Session, log: m.WorkLog, kind: str, evidence: str) -> list[m.StepProgress]:
    """Try to tick off open SOP steps that expect this kind of evidence."""
    rows = db.execute(
        select(m.StepProgress, m.SopStep, m.Project)
        .join(m.SopStep, m.SopStep.id == m.StepProgress.sop_step_id)
        .join(m.Project, m.Project.id == m.StepProgress.project_id)
        .where(m.Project.status == "active", m.StepProgress.status.in_(["pending", "needs_confirmation"]),
               m.SopStep.evidence_type == kind)
    ).all()
    scored = sorted(((_score(st, pr, evidence), sp, st, pr) for sp, st, pr in rows), key=lambda x: x[0], reverse=True)
    touched = []
    for score, sp, step, project in scored[:3]:
        if score < ASK:
            continue
        judged = _judge(step, project, evidence)
        confidence = judged if judged is not None else score
        if confidence >= AUTO_DONE:
            mark_done(db, sp, log=log, confidence=confidence, by=None)
        elif confidence >= ASK and sp.status == "pending":
            sp.status, sp.matched_log_id, sp.confidence = "needs_confirmation", log.id, confidence
            feed(db, sp.org_id, kind="needs", team_id=project.team_id, project_id=project.id, task_id=sp.task_id,
                 title=f"Does this complete “{step.title}”?",
                 body=f"{log.summary} — {round(confidence * 100)}% match for {project.name}.",
                 sources=[project.name], actions=[{"type": "confirm_step", "step_progress_id": sp.id}],
                 score=0.8, dedupe_key=f"confirm-{sp.id}")
        touched.append(sp)
    return touched


def mark_done(db: Session, sp: m.StepProgress, *, log: m.WorkLog | None, confidence: float | None,
              by: m.User | None) -> None:
    step = db.get(m.SopStep, sp.sop_step_id)
    project = db.get(m.Project, sp.project_id)
    deps_done = True
    if step.depends_on:
        dep_steps = db.scalars(select(m.SopStep.id).where(m.SopStep.sop_id == step.sop_id,
                                                         m.SopStep.seq.in_(step.depends_on))).all()
        dep_rows = db.scalars(select(m.StepProgress).where(m.StepProgress.project_id == project.id,
                                                          m.StepProgress.sop_step_id.in_(dep_steps))).all()
        deps_done = all(r.status in ("done", "done_out_of_order") for r in dep_rows)
    sp.status = "done" if deps_done else "done_out_of_order"
    sp.done_at, sp.confidence = now(), confidence
    sp.matched_log_id = log.id if log else sp.matched_log_id
    sp.confirmed_by_id = by.id if by else None
    if sp.task_id:
        task = db.get(m.Task, sp.task_id)
        if task and task.status != "done":
            reason = f"matched {log.source} evidence" if log else "confirmed"
            set_status(db, task, "done", by, reason, source="sop")
    remaining = db.scalars(select(m.StepProgress).where(m.StepProgress.project_id == project.id,
                                                       m.StepProgress.status.notin_(["done", "done_out_of_order", "skipped"]))).all()
    if not remaining:
        project.status = "done"
        feed(db, project.org_id, kind="win", team_id=project.team_id, project_id=project.id,
             title=f"{project.name} is complete", body="Every SOP step is done.", score=0.6,
             dedupe_key=f"project-done-{project.id}")


def progress(db: Session, project: m.Project) -> list[dict]:
    rows = db.execute(
        select(m.StepProgress, m.SopStep)
        .join(m.SopStep, m.SopStep.id == m.StepProgress.sop_step_id)
        .where(m.StepProgress.project_id == project.id).order_by(m.SopStep.seq)
    ).all()
    out = []
    for sp, step in rows:
        evidence = db.get(m.WorkLog, sp.matched_log_id) if sp.matched_log_id else None
        team = db.get(m.Team, step.owner_team_id) if step.owner_team_id else None
        out.append({
            "step_progress_id": sp.id, "seq": step.seq, "title": step.title, "status": sp.status,
            "owner": team.name if team else (step.owner_role or ""), "evidence_type": step.evidence_type,
            "evidence": evidence.summary if evidence else None, "confidence": sp.confidence,
            "task_id": sp.task_id, "due_at": sp.due_at, "done_at": sp.done_at,
        })
    return out
