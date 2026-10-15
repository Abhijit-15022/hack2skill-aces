"""My Day: each person's top three tasks, estimated from history, booked into free time, with context attached."""
import statistics
from datetime import date, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from . import focus, llm
from .timeutil import fmt_minutes, local, now, today

QUADRANTS = {"do": "Urgent and important", "schedule": "Important, not urgent", "delegate": "Urgent, less important",
             "later": "Neither: keep for later"}
DEFAULT_MIN = {"review": 30, "request": 45, "incident": 60, "sop_step": 30, "chore": 60, "feature": 120, "bug": 90}
BUFFER = 10


def _candidates(db: Session, user: m.User) -> list[m.Task]:
    return db.scalars(select(m.Task).where(m.Task.assignee_id == user.id, m.Task.status != "done")).all()


def estimate(db: Session, task: m.Task) -> tuple[int, str]:
    """Median focused time of the most similar finished tasks; falls back to a per-type default."""
    done = db.scalars(select(m.Task).where(m.Task.actual_min.isnot(None), m.Task.type == task.type)).all()
    if task.embedding is not None and done:
        done.sort(key=lambda t: llm.cosine(task.embedding, t.embedding), reverse=True)
    sample = [t.actual_min for t in done[:5]]
    if len(sample) >= 3:
        med = int(statistics.median(sample))
        return max(15, round(med / 5) * 5), f"median of {len(sample)} similar tasks"
    return DEFAULT_MIN.get(task.type, 60), "typical for this kind of task"


def _features(db: Session, user: m.User, t: m.Task) -> dict:
    t_now = now()
    last = db.scalar(select(m.WorkLog.created_at).where(m.WorkLog.task_id == t.id).order_by(m.WorkLog.created_at.desc()).limit(1))
    due_days = (local(t.due_at).date() - today()).days if t.due_at else None
    waiting = None
    if t.type == "review":
        waiting = "someone is blocked until you review"
    elif t.type == "request":
        er = db.scalar(select(m.EmailRequest).where(m.EmailRequest.task_id == t.id))
        waiting = f"{er.from_addr} is waiting for a reply" if er else "a colleague asked for this"
    est, basis = estimate(db, t)
    return {"key": t.key, "title": t.title, "type": t.type, "status": t.status, "priority": t.priority,
            "due_in_days": due_days, "waiting_on_you": waiting,
            "days_since_update": (t_now - (last or t.created_at)).days, "estimate_min": est, "estimate_basis": basis}


def _score(f: dict) -> tuple[float, str]:
    urgent = f["due_in_days"] is not None and f["due_in_days"] <= 1 or f["type"] in ("incident", "review")
    important = f["priority"] == "high" or f["waiting_on_you"] is not None or f["type"] in ("incident", "sop_step")
    s = (4 if f["due_in_days"] is not None and f["due_in_days"] < 0 else 0)
    s += 3 if urgent else 0
    s += 2 if important else 0
    s += min(f["days_since_update"], 5) * 0.3
    s += 0.5 if f["status"] == "doing" else 0
    quad = "do" if urgent and important else "schedule" if important else "delegate" if urgent else "later"
    return s, quad


def _rank(user: m.User, feats: list[dict], free_min: int) -> tuple[list[dict], str, bool]:
    out = llm.generate_json(f"""You plan {user.name}'s workday ({user.title}). They have about {free_min} minutes
free outside meetings today. Pick at most 3 tasks to do today, most important first, using the Eisenhower
matrix (urgent = due within a day, someone blocked, or a production problem; important = high priority or someone
waiting). Prefer finishing work over starting new work. Keep the given estimates unless clearly wrong.
Tasks: {feats}
Return JSON {{"summary": str (one short sentence for them, second person, no greeting),
"picks": [{{"key": str, "quadrant": "do"|"schedule"|"delegate"|"later", "why": str (max 18 words),
"estimate_min": int}}]}}""", tier="fast")
    if out and out.get("picks"):
        by_key = {f["key"]: f for f in feats}
        picks = [p | {"estimate_min": int(p.get("estimate_min") or by_key[p["key"]]["estimate_min"])}
                 for p in out["picks"] if p.get("key") in by_key][:3]
        if picks:
            return picks, out.get("summary") or "", True
    ranked = sorted(feats, key=lambda f: _score(f)[0], reverse=True)[:3]
    picks = []
    for f in ranked:
        why = f["waiting_on_you"] or (f"due in {f['due_in_days']} day(s)" if f["due_in_days"] is not None else
                                      f"no update for {f['days_since_update']} days" if f["days_since_update"] else "in progress")
        picks.append({"key": f["key"], "quadrant": _score(f)[1], "why": why[0].upper() + why[1:] + ".",
                      "estimate_min": f["estimate_min"]})
    return picks, "", False


def _context(db: Session, user: m.User, t: m.Task) -> list[dict]:
    items: list[dict] = []
    er = db.scalar(select(m.EmailRequest).where(m.EmailRequest.task_id == t.id))
    if er:
        items.append({"kind": "email", "title": er.subject, "detail": f"From {er.from_addr}: {er.body[:240]}"})
    for link in (t.links or [])[:4]:
        if link.get("kind") in ("file", "commit", "pr", "incident"):
            items.append({"kind": link["kind"], "title": link.get("label"), "detail": link.get("url") or ""})
    for lg in db.scalars(select(m.WorkLog).where(m.WorkLog.task_id == t.id, m.WorkLog.source != "manual")
                         .order_by(m.WorkLog.created_at.desc()).limit(2)):
        items.append({"kind": lg.source, "title": "Last progress", "detail": lg.summary[:240]})
    if t.embedding is not None:
        related = db.scalars(select(m.WorkLog).where(m.WorkLog.task_id != t.id, m.WorkLog.embedding.isnot(None),
                                                     or_(m.WorkLog.author_id == user.id, m.WorkLog.on_behalf_of_id == user.id))
                             .order_by(m.WorkLog.embedding.cosine_distance(t.embedding)).limit(1)).all()
        for lg in related:
            if llm.cosine(lg.embedding, t.embedding) > (0.55 if llm.enabled() else 0.3):
                other = db.get(m.Task, lg.task_id) if lg.task_id else None
                items.append({"kind": "related", "title": f"Similar work{' on ' + other.key if other else ''}",
                              "detail": f"{lg.created_at:%d %b}: {lg.summary[:200]}"})
    return items[:5]


def plan(db: Session, user: m.User, day: date | None = None) -> m.DayPlan:
    day = day or today()
    key = day.isoformat()
    tasks = {t.key: t for t in _candidates(db, user)}
    feats = [_features(db, user, t) for t in tasks.values()]
    slots = focus.free_slots(db, user.id, day, from_time=now() if day == today() else None)
    free_min = int(sum((b - a).total_seconds() / 60 for a, b in slots))
    picks, summary, by_ai = _rank(user, feats, free_min) if feats else ([], "", False)

    focus.clear_relay_focus(db, user.id, day)
    items, booked = [], 0
    slot_iter = [list(s) for s in slots]
    for rank, p in enumerate(picks, start=1):
        t = tasks[p["key"]]
        need = timedelta(minutes=p["estimate_min"])
        block = None
        for s in slot_iter:
            if s[1] - s[0] >= need:
                block = (s[0], s[0] + need)
                s[0] = s[0] + need + timedelta(minutes=BUFFER)
                break
        if block:
            db.add(m.CalendarEvent(org_id=user.org_id, user_id=user.id, kind="focus", source="relay", start=block[0],
                                   end=block[1], task_id=t.id, title=f"Focus: {t.title}"))
            booked += p["estimate_min"]
        t.estimate_min = p["estimate_min"]
        feat = next(f for f in feats if f["key"] == t.key)
        items.append({"rank": rank, "task_id": t.id, "key": t.key, "title": t.title, "type": t.type,
                      "quadrant": p.get("quadrant", "do"), "quadrant_label": QUADRANTS.get(p.get("quadrant"), ""),
                      "why": p.get("why", ""), "estimate_min": p["estimate_min"], "estimate_basis": feat["estimate_basis"],
                      "focus_start": block[0].isoformat() if block else None,
                      "focus_end": block[1].isoformat() if block else None,
                      "context": _context(db, user, t)})
    if not summary:
        summary = (f"{len(items)} thing{'s' if len(items) != 1 else ''} today, {fmt_minutes(booked)} of focus booked."
                   if items else "Nothing assigned to you. A good day to help a teammate.")
    db.execute(delete(m.DayPlan).where(m.DayPlan.user_id == user.id, m.DayPlan.day == key))
    dp = m.DayPlan(org_id=user.org_id, user_id=user.id, day=key, summary=summary, items=items, focus_minutes=booked,
                   by_ai=by_ai)
    db.add(dp)
    db.flush()
    return dp


def get_or_plan(db: Session, user: m.User) -> m.DayPlan:
    dp = db.scalar(select(m.DayPlan).where(m.DayPlan.user_id == user.id, m.DayPlan.day == today().isoformat()))
    return dp or plan(db, user)


def serialize(db: Session, dp: m.DayPlan, user: m.User) -> dict:
    day = date.fromisoformat(dp.day)
    evs = focus.events(db, user.id, day)
    done_ids = {t.id for t in db.scalars(select(m.Task).where(m.Task.id.in_([i["task_id"] for i in dp.items] or [-1]),
                                                           m.Task.status == "done"))}
    return {
        "day": dp.day, "summary": dp.summary, "focus_minutes": dp.focus_minutes, "by_ai": dp.by_ai,
        "generated_at": dp.created_at,
        "items": [i | {"done": i["task_id"] in done_ids} for i in dp.items],
        "calendar": [{"id": e.id, "title": e.title, "start": e.start, "end": e.end, "kind": e.kind, "source": e.source,
                      "task_id": e.task_id} for e in evs],
        "meeting_minutes": focus.meeting_minutes(db, user.id, day),
    }
