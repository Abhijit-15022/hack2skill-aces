"""AI coding sessions (Claude Code, Cursor, Codex, Antigravity) -> task updates, blockers and expected outcomes."""
import re
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from . import focus, llm
from .core import add_log, audit, create_task, feed, refresh_task_embedding, user_teams
from .matching import find_keys, match_task
from .redact import redact
from .timeutil import now

TOOL_LABEL = {"claude": "Claude Code", "cursor": "Cursor", "codex": "Codex", "antigravity": "Antigravity"}


class SessionError(ValueError):
    pass


def _summarise(tool: str, title: str, text: str, branch: str | None, repo: str | None, files: list[str]) -> dict:
    out = llm.generate_json(f"""You keep a developer's task tracker current from their AI coding session in
{TOOL_LABEL.get(tool, tool)}. Repo: {repo or "unknown"}. Branch: {branch or "unknown"}. Session title: {title}.
Files touched: {", ".join(files[:25]) or "unknown"}.
Read the session and return JSON:
{{"title": str (task title, imperative, max 10 words),
"summary": str (2-3 sentences, past tense: what was done and why, concrete),
"progress": "doing" | "done" | "blocked",
"done": [str] (finished pieces, max 4, short),
"blockers": [{{"text": str (what is stopping progress), "waiting_on": str or null (person, team or thing)}}]
  (only real blockers: missing access, waiting on someone, failing dependency, unanswered question; [] if none),
"next_steps": [str] (max 3),
"expected_outcome": str or null (ONLY if the user explicitly said what done looks like),
"suggested_outcome": str (your best one-sentence guess of what 'done' means for this work),
"decisions": [str] (design decisions with the reason, may be empty)}}
Session:
---
{text}
---""", tier="fast")
    if out and out.get("summary"):
        out.setdefault("blockers", [])
        out["blockers"] = [b for b in out["blockers"] if isinstance(b, dict) and b.get("text")]
        return out
    user_lines = [ln.split(":", 1)[1].strip() for ln in text.splitlines() if ln.startswith("user:")]
    first = (user_lines[0] if user_lines else title or "Coding session")[:120]
    blockers = [{"text": ln.strip()[:200], "waiting_on": None} for ln in text.splitlines()
                if re.search(r"\b(blocked|waiting (on|for)|can't proceed|no access|permission denied)\b", ln, re.I)][:2]
    return {"title": (title or first)[:80], "summary": f"Worked on: {first}.", "progress": "blocked" if blockers else "doing",
            "done": [], "blockers": blockers, "next_steps": [], "expected_outcome": None,
            "suggested_outcome": f"{title or first} is finished and reviewed.", "decisions": []}


def _previous_task(db: Session, user: m.User, repo: str | None, branch: str | None) -> m.Task | None:
    """Sessions on the same repo and branch usually continue the same task."""
    if not (repo and branch) or branch in ("main", "master", "HEAD"):
        return None
    recent = db.scalars(select(m.WorkLog).where(m.WorkLog.author_id == user.id, m.WorkLog.task_id.isnot(None),
                                                m.WorkLog.created_at >= now() - timedelta(days=14))
                        .order_by(m.WorkLog.created_at.desc()).limit(50)).all()
    for lg in recent:
        if (lg.meta or {}).get("repo") == repo and (lg.meta or {}).get("branch") == branch:
            t = db.get(m.Task, lg.task_id)
            if t and t.status != "done":
                return t
    return None


def _merge_description(task: m.Task, s: dict) -> str:
    out = llm.generate_text(f"""Rewrite this task description so it stays short and current (max 110 words, plain
text, no headings). Keep what still matters, add the new progress, end with what's left.
Task: {task.title}
Expected outcome: {task.expected_outcome or "not set"}
Current description: {task.description or "(empty)"}
New progress: {s["summary"]}
Done: {"; ".join(s.get("done") or []) or "-"}
Next: {"; ".join(s.get("next_steps") or []) or "-"}""")
    if out:
        return out
    return f"{(task.description or '').strip()}\n• {now():%d %b}: {s['summary']}".strip()


def _update_blockers(db: Session, task: m.Task, found: list[dict], tool: str, user: m.User) -> list[dict]:
    """Open blockers come from the latest session: new ones are added, ones no longer mentioned are resolved."""
    current = [dict(b) for b in (task.blockers or [])]
    open_ = [b for b in current if not b.get("resolved_at")]
    new = []
    for f in found[:3]:
        if any(_similar(f["text"], b["text"]) for b in open_):
            continue
        b = {"id": uuid.uuid4().hex[:8], "text": f["text"][:240], "waiting_on": f.get("waiting_on"),
             "source": tool, "at": now().isoformat(), "resolved_at": None}
        current.append(b)
        new.append(b)
    for b in open_:
        if not any(_similar(f["text"], b["text"]) for f in found):
            b_ref = next(x for x in current if x["id"] == b["id"])
            b_ref["resolved_at"] = now().isoformat()
    task.blockers = current
    if new:
        lead = db.get(m.Team, task.team_id).lead_id if task.team_id else None
        for b in new:
            add_log(db, task.org_id, source=tool, task=task, author=user,
                    summary=f"blocked: {b['text']}" + (f" (waiting on {b['waiting_on']})" if b.get("waiting_on") else ""))
        if lead and lead != user.id:
            focus.notify(db, lead, "blocker", f"{user.name.split()[0]} is blocked on {task.key}", new[0]["text"], task.id)
        feed(db, task.org_id, kind="stuck", team_id=task.team_id, task_id=task.id, subject_user_id=user.id,
             title=f"{user.name.split()[0]} is blocked on {task.title}",
             body=new[0]["text"] + (f" Waiting on {new[0]['waiting_on']}." if new[0].get("waiting_on") else ""),
             sources=[task.key, TOOL_LABEL.get(tool, tool)],
             actions=[{"type": "nudge", "user_id": user.id}, {"type": "open_task", "task_id": task.id}],
             score=0.85, dedupe_key=f"blocked-{task.id}")
    return new


def _similar(a: str, b: str) -> bool:
    wa, wb = set(re.findall(r"[a-z0-9]{4,}", a.lower())), set(re.findall(r"[a-z0-9]{4,}", b.lower()))
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.5


def ask_outcome(db: Session, task: m.Task, user: m.User, suggestion: str | None) -> bool:
    """One question per task: what does done look like? Returns True if a new question was asked."""
    if task.expected_outcome:
        return False
    open_q = db.scalar(select(m.Notification).where(m.Notification.task_id == task.id, m.Notification.kind == "question",
                                                    m.Notification.status != "read"))
    if open_q:
        return False
    n = focus.notify(db, user.id, "question", f"What should “{task.title}” achieve when it's done?",
                     suggestion or "", task.id)
    return n is not None


def ingest_session(db: Session, org_id: int, p: dict) -> dict:
    tool = p.get("tool") or "claude"
    user = db.scalar(select(m.User).where(m.User.email == (p.get("user_email") or "").lower()))
    if not user:
        raise SessionError(f"No user with email {p.get('user_email')!r} in this organisation.")
    text, redactions = redact(p.get("transcript") or "")
    if len(text.strip()) < 40:
        return {"skipped": "too little to summarise"}
    sid = p.get("session_id") or f"{tool}:{uuid.uuid4().hex}"
    files = list(p.get("files") or [])
    s = _summarise(tool, p.get("title") or "", text[-16000:], p.get("git_branch"), p.get("repo"), files)

    previous_log = db.scalar(select(m.WorkLog).where(m.WorkLog.raw_ref == sid, m.WorkLog.source == tool))
    task = db.get(m.Task, previous_log.task_id) if previous_log and previous_log.task_id else None
    why = "same session as before" if task else ""
    if task is None:
        task = _previous_task(db, user, p.get("repo"), p.get("git_branch"))
        why = "same repo and branch as an earlier session" if task else ""
    if task is None:
        task, _, why = match_task(db, user, f"{s['title']}\n{s['summary']}",
                                  hints=[p.get("git_branch") or "", p.get("title") or "", text[:2000]])
    created = False
    if task is None:
        teams = user_teams(db, user.id)
        task = create_task(db, org_id, title=s["title"], team=db.get(m.Team, teams[0]) if teams else None,
                           created_by=user, assignee_id=user.id, status="doing", description=s["summary"],
                           description_by_ai=True)
        task.started_at = now()
        created, why = True, "new work"
    else:
        task.description = _merge_description(task, s)
        task.description_by_ai = True
        if task.status == "todo":
            task.status, task.started_at = "doing", task.started_at or now()
        if s.get("progress") == "done" and task.status == "doing":
            task.status = "review"
    if s.get("expected_outcome") and not task.expected_outcome:
        task.expected_outcome, task.outcome_by_ai = s["expected_outcome"][:500], True
    new_blockers = _update_blockers(db, task, s.get("blockers") or [], tool, user)
    refresh_task_embedding(task)

    meta = {"tool": tool, "title": p.get("title"), "files": files[:50], "branch": p.get("git_branch"),
            "repo": p.get("repo"), "done": s.get("done") or [], "next_steps": s.get("next_steps") or [],
            "blockers": s.get("blockers") or [], "decisions": s.get("decisions") or [], "redactions": redactions,
            "matched": why}
    if previous_log:
        previous_log.summary, previous_log.meta, previous_log.task_id = s["summary"], meta, task.id
        previous_log.embedding = llm.embed_one(s["summary"])
        log = previous_log
    else:
        log = add_log(db, org_id, source=tool, summary=s["summary"], task=task, author=user, raw_ref=sid, meta=meta)
    asked = ask_outcome(db, task, user, s.get("suggested_outcome"))
    from .health import invalidate
    invalidate()
    for d in (s.get("decisions") or [])[:2]:
        feed(db, org_id, kind="decision", team_id=task.team_id, task_id=task.id, subject_user_id=user.id, title=d[:140],
             body=f"Captured from {user.name.split()[0]}'s {TOOL_LABEL.get(tool, tool)} session on {task.key}.",
             sources=[TOOL_LABEL.get(tool, tool), task.key], score=0.4, dedupe_key=f"decision-{sid}-{d[:40]}")
    audit(db, org_id, actor=None, action=f"{'Created' if created else 'Updated'} {task.key} from a {TOOL_LABEL.get(tool, tool)} session",
          target_type="task", target_id=task.id, reason=why, approved_by="Automatic (task update)")
    return {"task": task.key, "task_id": task.id, "created": created, "matched": why, "redactions": redactions,
            "blockers": [b["text"] for b in new_blockers], "asked_outcome": asked, "log_id": log.id,
            "summary": s["summary"]}


def set_outcome(db: Session, task: m.Task, user: m.User, text: str) -> None:
    task.expected_outcome, task.outcome_by_ai = text.strip()[:500], False
    for n in db.scalars(select(m.Notification).where(m.Notification.task_id == task.id, m.Notification.kind == "question",
                                                     m.Notification.status != "read")):
        n.status = "read"
    add_log(db, task.org_id, source="manual", task=task, author=user, summary=f"set the expected outcome: {task.expected_outcome}")
    refresh_task_embedding(task)


def resolve_blocker(db: Session, task: m.Task, user: m.User, blocker_id: str) -> None:
    blockers = [dict(b) for b in (task.blockers or [])]
    for b in blockers:
        if b["id"] == blocker_id and not b.get("resolved_at"):
            b["resolved_at"] = now().isoformat()
            add_log(db, task.org_id, source="manual", task=task, author=user, summary=f"resolved blocker: {b['text']}")
    task.blockers = blockers


def questions(db: Session, user: m.User) -> list[dict]:
    rows = db.scalars(select(m.Notification).where(m.Notification.user_id == user.id, m.Notification.kind == "question",
                                                   m.Notification.status != "read").order_by(m.Notification.created_at.desc())).all()
    out = []
    for n in rows:
        t = db.get(m.Task, n.task_id) if n.task_id else None
        if t and not t.expected_outcome:
            out.append({"id": n.id, "task_id": t.id, "key": t.key, "title": t.title, "question": n.title,
                        "suggestion": n.body, "asked_at": n.created_at})
    return out
