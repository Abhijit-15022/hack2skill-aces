"""Turn raw work signals (Claude sessions, commits, emails, calendar events) into task updates."""
import json
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from . import llm, sop
from .core import add_log, audit, create_task, feed, now, refresh_task_embedding, set_status, user_teams
from .matching import match_task
from .redact import redact


class IngestError(ValueError):
    pass


def _user(db: Session, email: str | None) -> m.User:
    user = db.scalar(select(m.User).where(m.User.email == (email or "").lower()))
    if not user:
        raise IngestError(f"No user with email {email!r} in this organisation.")
    return user


def _home_team(db: Session, user: m.User) -> m.Team | None:
    ids = user_teams(db, user.id)
    return db.get(m.Team, ids[0]) if ids else None


# ---------------------------------------------------------------- Claude Code sessions

def transcript_text(transcript) -> tuple[str, list[str]]:
    """Accept a Claude Code JSONL transcript (string or parsed list) and return readable text + touched files."""
    entries = transcript
    if isinstance(transcript, str):
        entries = []
        for line in transcript.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"type": "text", "message": {"role": "user", "content": line}})
    parts, files = [], []
    for e in entries or []:
        msg = e.get("message") if isinstance(e, dict) else None
        if not isinstance(msg, dict):
            continue
        role = msg.get("role") or e.get("type")
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(f"{role}: {content}")
            continue
        for block in content or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                parts.append(f"{role}: {block['text']}")
            elif block.get("type") == "tool_use":
                inp = block.get("input") or {}
                path = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
                if path and path not in files:
                    files.append(path)
                parts.append(f"{role} used {block.get('name')}{' on ' + path if path else ''}")
    text = "\n".join(parts)
    return text[-16000:], files


def _summarise_session(text: str, files: list[str], branch: str | None) -> dict:
    out = llm.generate_json(f"""Summarise this coding session for the developer's task tracker.
Branch: {branch or "unknown"}. Files touched: {", ".join(files[:30]) or "none"}.
Return JSON {{"title": str (task title, max 10 words), "summary": str (2-3 sentences, past tense, what was done and
why), "progress": "doing"|"done", "decisions": [str] (design decisions with their reason, may be empty),
"next_steps": [str]}}.
Session:
---
{text}
---""")
    if out and out.get("summary"):
        return out
    user_lines = [ln[6:] for ln in text.splitlines() if ln.startswith("user: ")]
    first = (user_lines[0] if user_lines else "Coding session").strip()
    return {"title": first[:80], "summary": f"Worked on: {first[:200]}. Touched {len(files)} file(s)"
            + (f": {', '.join(f.split('/')[-1] for f in files[:5])}." if files else "."),
            "progress": "doing", "decisions": [], "next_steps": []}


def _merge_description(task: m.Task, update: str, next_steps: list[str]) -> str:
    out = llm.generate_text(f"""Rewrite this task description so it stays short and current (max 120 words,
plain text, no headings). Keep what still matters, add the new progress, end with what's left if known.
Task: {task.title}
Current description: {task.description or "(empty)"}
New progress: {update}
Next steps: {"; ".join(next_steps) or "unknown"}""")
    if out:
        return out
    stamp = now().strftime("%d %b")
    base = (task.description or "").strip()
    return f"{base}\n• {stamp}: {update}".strip()


def ingest_claude(db: Session, org_id: int, p: dict) -> dict:
    user = _user(db, p.get("user_email"))
    text, files = transcript_text(p.get("transcript") or "")
    files = list(dict.fromkeys(files + list(p.get("files") or [])))
    if not text.strip():
        return {"skipped": "empty transcript"}
    text, redactions = redact(text)
    s = _summarise_session(text, files, p.get("git_branch"))
    task, score, why = match_task(db, user, f"{s['title']}\n{s['summary']}", hints=[p.get("git_branch") or "", text[:2000]])
    created = False
    if task is None:
        task = create_task(db, org_id, title=s["title"], team=_home_team(db, user), created_by=user,
                           assignee_id=user.id, status="doing", description=s["summary"], description_by_ai=True)
        created, why = True, "new work"
    else:
        task.description = _merge_description(task, s["summary"], s.get("next_steps") or [])
        task.description_by_ai = True
        if task.status == "todo":
            task.status = "doing"
        if s.get("progress") == "done" and task.status == "doing":
            task.status = "review"
        refresh_task_embedding(task)
    log = add_log(db, org_id, source="claude", summary=s["summary"], task=task, author=user,
                  raw_ref=p.get("session_id"),
                  meta={"files": files[:50], "decisions": s.get("decisions") or [], "branch": p.get("git_branch"),
                        "redactions": redactions, "matched": why})
    for d in (s.get("decisions") or [])[:2]:
        feed(db, org_id, kind="decision", team_id=task.team_id, task_id=task.id, subject_user_id=user.id,
             title=d[:140], body=f"Captured from {user.name.split()[0]}'s Claude session on {task.key}.",
             sources=["Claude session", task.key], score=0.4)
    audit(db, org_id, actor=None, action=f"{'Created' if created else 'Updated'} {task.key} from a Claude session",
          target_type="task", target_id=task.id, reason=why, approved_by="Automatic (task update)")
    return {"task": task.key, "created": created, "matched": why, "redactions": redactions, "log_id": log.id}


# ---------------------------------------------------------------- git commits

def ingest_git(db: Session, org_id: int, p: dict) -> dict:
    user = _user(db, p.get("author_email"))
    message, _ = redact(p.get("message") or "")
    diff, redactions = redact((p.get("diff") or "")[:6000])
    files = p.get("files") or []
    sha = (p.get("sha") or "")[:12]
    summary = llm.generate_text(
        f"In one sentence, past tense, say what this commit changed and why.\nMessage: {message}\n"
        f"Files: {', '.join(files[:20])}\nDiff:\n{diff}") or message.splitlines()[0] if message else f"Commit {sha}"
    task, score, why = match_task(db, user, f"{message}\n{summary}", hints=[p.get("branch") or "", message])
    if task:
        task.links = (task.links or []) + [{"kind": "commit", "label": f"Commit {sha[:7]}", "ref": sha,
                                            "url": p.get("url")}]
        if task.status == "todo":
            task.status = "doing"
    log = add_log(db, org_id, source="git", summary=summary, task=task, author=user, raw_ref=sha,
                  meta={"files": files[:50], "branch": p.get("branch"), "repo": p.get("repo"), "matched": why,
                        "redactions": redactions})
    return {"task": task.key if task else None, "matched": why, "log_id": log.id}


# ---------------------------------------------------------------- email

REQUEST_HINT = re.compile(r"\b(can you|could you|please|pls|need|send|share|by (mon|tue|wed|thu|fri|eod|tomorrow))\b", re.I)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _due_from_text(text: str) -> datetime | None:
    t = text.lower()
    today = now()
    if "tomorrow" in t:
        return today + timedelta(days=1)
    if "eod" in t or "today" in t:
        return today
    for i, d in enumerate(WEEKDAYS):
        if d in t or re.search(rf"\b{d[:3]}\b", t):
            ahead = (i - today.weekday()) % 7 or 7
            return today + timedelta(days=ahead)
    return None


def _classify_email(subject: str, body: str) -> dict:
    out = llm.generate_json(f"""Is this email asking the recipient to do something? Return JSON
{{"is_request": bool, "title": str (task title, max 10 words, imperative), "summary": str (one sentence),
"due": "YYYY-MM-DD" or null}}. Today is {now().date()}.
Subject: {subject}
Body:
{body[:4000]}""")
    if out and "is_request" in out:
        return out
    text = f"{subject}\n{body}"
    due = _due_from_text(text)
    return {"is_request": bool(REQUEST_HINT.search(text)), "title": subject[:80] or "Email request",
            "summary": body.strip().splitlines()[0][:200] if body.strip() else subject,
            "due": due.date().isoformat() if due else None}


def _past_similar(db: Session, user: m.User, text: str) -> m.EmailRequest | None:
    past = db.scalars(select(m.EmailRequest).where(m.EmailRequest.to_user_id == user.id,
                                                   m.EmailRequest.replied_at.isnot(None))).all()
    if not past:
        return None
    vec = llm.embed_one(text, "RETRIEVAL_QUERY")
    best = max(past, key=lambda r: llm.cosine(vec, llm.embed_one(f"{r.subject}\n{r.body}")))
    sim = llm.cosine(vec, llm.embed_one(f"{best.subject}\n{best.body}"))
    return best if sim >= (0.7 if llm.enabled() else 0.35) else None


def ingest_email(db: Session, org_id: int, p: dict) -> dict:
    sender = (p.get("from") or "").lower()
    recipients = [r.lower() for r in (p.get("to") if isinstance(p.get("to"), list) else [p.get("to") or ""])]
    subject, _ = redact(p.get("subject") or "")
    body, redactions = redact(p.get("body") or "")
    thread = p.get("thread_id") or p.get("in_reply_to") or subject
    attachments = p.get("attachments") or []
    sender_user = db.scalar(select(m.User).where(m.User.email == sender))
    result: dict = {}

    open_req = db.scalar(select(m.EmailRequest).where(m.EmailRequest.thread_id == thread,
                                                      m.EmailRequest.replied_at.is_(None)))
    if sender_user and open_req and open_req.to_user_id == sender_user.id:
        open_req.replied_at = now()
        open_req.attachments = attachments
        task = db.get(m.Task, open_req.task_id) if open_req.task_id else None
        names = ", ".join(a.get("name", "") for a in attachments)
        log = add_log(db, org_id, source="email", task=task, author=sender_user,
                      summary=f"Replied to {open_req.from_addr}" + (f" with {names}" if names else ""),
                      raw_ref=thread, meta={"attachments": attachments, "reply": True})
        if task and task.status != "done":
            set_status(db, task, "done", None, "reply sent", source="email")
        result = {"closed_task": task.key if task else None, "log_id": log.id}
        sop.match_evidence(db, log, "email", f"{subject}\n{body}\n{names}")
        return result

    for rcpt in recipients:
        user = db.scalar(select(m.User).where(m.User.email == rcpt, m.User.kind == "human"))
        if not user or not user.email_capture:
            continue
        cls = _classify_email(subject, body)
        log = add_log(db, org_id, source="email", author=None, on_behalf_of=user,
                      summary=f"Email from {sender}: {cls.get('summary') or subject}", raw_ref=thread,
                      meta={"from": sender, "subject": subject, "attachments": attachments, "redactions": redactions})
        sop.match_evidence(db, log, "email", f"{subject}\n{body}\n" + " ".join(a.get("name", "") for a in attachments))
        if not cls.get("is_request") or sender_user is not None and sender_user.id == user.id:
            result[rcpt] = {"request": False}
            continue
        previous = _past_similar(db, user, f"{subject}\n{body}")
        desc = f"{sender} asked: {cls.get('summary') or subject}"
        links = [{"kind": "email", "label": f"Email from {sender.split('@')[0].title()}", "ref": thread}]
        if previous:
            files = ", ".join(a.get("name", "") for a in previous.attachments) or "no attachment"
            desc += (f"\n\nLast time ({previous.created_at:%d %b}), you replied to “{previous.subject}” "
                     f"with {files}. Relay can start from that.")
            links += [{"kind": "file", "label": a.get("name"), "ref": a.get("name")} for a in previous.attachments]
        due = None
        if cls.get("due"):
            try:
                due = datetime.fromisoformat(cls["due"]).replace(hour=18)
            except ValueError:
                due = None
        task = create_task(db, org_id, title=cls.get("title") or subject, team=_home_team(db, user), created_by=None,
                           assignee_id=user.id, type="request", description=desc, description_by_ai=True,
                           due_at=due, links=links)
        log.task_id = task.id
        db.add(m.EmailRequest(org_id=org_id, task_id=task.id, thread_id=thread, from_addr=sender,
                              to_user_id=user.id, subject=subject, body=body[:20000], attachments=attachments))
        audit(db, org_id, actor=None, action=f"Created {task.key} from an email to {user.name}",
              target_type="task", target_id=task.id, reason=f"Request from {sender}",
              approved_by="Automatic (task update)")
        result[rcpt] = {"request": True, "task": task.key, "found_previous": bool(previous)}
    return result


# ---------------------------------------------------------------- calendar

def ingest_calendar(db: Session, org_id: int, p: dict) -> dict:
    organizer = db.scalar(select(m.User).where(m.User.email == (p.get("organizer") or "").lower()))
    title, _ = redact(p.get("title") or "")
    attendees = p.get("attendees") or []
    summary = f"Calendar invite “{title}” for {p.get('start', 'unscheduled')}" + (
        f" with {', '.join(attendees[:4])}" if attendees else "")
    log = add_log(db, org_id, source="calendar", summary=summary, author=organizer, raw_ref=p.get("event_id"),
                  meta={"title": title, "start": p.get("start"), "attendees": attendees})
    touched = sop.match_evidence(db, log, "calendar", f"{title}\n{' '.join(attendees)}")
    return {"log_id": log.id, "sop_steps": [{"id": t.id, "status": t.status} for t in touched]}
