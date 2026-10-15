"""Team Health: spot overload, after-hours work, blockers, stuck reviews and missing early feedback; suggest one action."""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from . import focus, llm
from .core import add_log, audit
from .myday import estimate
from .timeutil import fmt_minutes, is_after_hours, local, now, today, workday

REQUESTS_HIGH, LOAD_HIGH, NIGHTS_HIGH = 8, 1.3, 3


def _capacity_min(db: Session, user_id: int) -> int:
    """Free working minutes over the next 5 working days, from the calendar."""
    total, day, counted = 0, today(), 0
    while counted < 5:
        if workday(day):
            total += sum((b - a).total_seconds() / 60 for a, b in focus.free_slots(db, user_id, day))
            counted += 1
        day += timedelta(days=1)
    return int(total)


def person(db: Session, user: m.User, teammates: list[m.User]) -> dict:
    t_now = now()
    open_tasks = db.scalars(select(m.Task).where(m.Task.assignee_id == user.id, m.Task.status != "done")).all()
    committed = sum(t.estimate_min or estimate(db, t)[0] for t in open_tasks)
    capacity = max(_capacity_min(db, user.id), 60)
    load = committed / capacity
    requests = [t for t in open_tasks if t.type == "request"]
    overdue = [t for t in open_tasks if t.due_at and t.due_at < t_now]
    reviews = [t for t in open_tasks if t.type == "review" and t_now - t.created_at > timedelta(hours=4)]
    quiet = []
    for t in open_tasks:
        if t.status != "doing" or t_now - t.created_at < timedelta(days=2) or (t.estimate_min or 0) < 240:
            continue
        others = db.scalar(select(m.WorkLog.id).where(m.WorkLog.task_id == t.id, m.WorkLog.author_id.isnot(None),
                                                      m.WorkLog.author_id != user.id).limit(1))
        if not others:
            quiet.append(t)
    nights = None
    if user.share_wellbeing:
        logs = db.scalars(select(m.WorkLog.created_at).where(m.WorkLog.author_id == user.id,
                                                             m.WorkLog.created_at >= t_now - timedelta(days=7))).all()
        nights = len({local(ts).date() for ts in logs if is_after_hours(ts)})

    signals = []
    if len(requests) >= REQUESTS_HIGH or load >= LOAD_HIGH:
        signals.append({"kind": "overload", "level": "high",
                        "text": f"{len(open_tasks)} open tasks ({len(requests)} requests): about {fmt_minutes(committed)} "
                                f"of work for {fmt_minutes(capacity)} of free time this week"})
    elif load >= 0.9:
        signals.append({"kind": "overload", "level": "watch", "text": f"Booked at {round(load * 100)}% of free time this week"})
    if nights is not None and nights >= NIGHTS_HIGH:
        signals.append({"kind": "after_hours", "level": "high", "text": f"Worked after 9 pm on {nights} of the last 7 nights"})
    for t in reviews:
        hrs = int((t_now - t.created_at).total_seconds() // 3600)
        signals.append({"kind": "review_stuck", "level": "watch" if hrs < 24 else "high", "task_id": t.id,
                        "text": f"{t.key} “{t.title}” has waited {hrs} h for their review"})
    for t in quiet:
        signals.append({"kind": "no_feedback", "level": "watch", "task_id": t.id,
                        "text": f"{t.key} “{t.title}”: {int((t_now - t.created_at).days)} days in, no feedback from anyone yet"})
    for t in overdue[:2]:
        signals.append({"kind": "overdue", "level": "watch", "task_id": t.id, "text": f"{t.key} is overdue"})
    blocked = [(t, b) for t in open_tasks for b in (t.blockers or []) if not b.get("resolved_at")]
    for t, b in blocked[:3]:
        age_h = (t_now - datetime.fromisoformat(b["at"])).total_seconds() / 3600 if b.get("at") else 0
        signals.append({"kind": "blocked", "level": "high" if age_h >= 24 else "watch", "task_id": t.id, "blocker_id": b["id"],
                        "waiting_on": b.get("waiting_on"),
                        "text": f"Blocked on {t.key}: {b['text']}" + (f" (waiting on {b['waiting_on']})" if b.get("waiting_on") else "")})
    level = "high" if any(s["level"] == "high" for s in signals) else "watch" if signals else "ok"

    action = _suggest(db, user, signals, open_tasks, requests, reviews, quiet, teammates) if level != "ok" else None
    working = [{"key": t.key, "title": t.title, "status": t.status, "outcome": t.expected_outcome,
                "last": (db.scalar(select(m.WorkLog.summary).where(m.WorkLog.task_id == t.id, m.WorkLog.author_id == user.id)
                                   .order_by(m.WorkLog.created_at.desc()).limit(1)) or "")[:200]}
               for t in sorted(open_tasks, key=lambda t: (t.status != "doing", t.status != "review"))[:4]]
    return {"user": {"id": user.id, "name": user.name, "initials": user.initials, "color": user.color, "title": user.title,
                     "shares_wellbeing": user.share_wellbeing},
            "level": level, "open_tasks": len(open_tasks), "requests": len(requests), "overdue": len(overdue),
            "committed_min": committed, "capacity_min": capacity, "load": round(load, 2),
            "after_hours_nights": nights, "signals": signals, "action": action, "working_on": working, "summary": None}


def _least_loaded(db: Session, teammates: list[m.User], exclude: int) -> m.User | None:
    pool = [u for u in teammates if u.id != exclude and u.kind == "human"]
    if not pool:
        return None
    return min(pool, key=lambda u: len(db.scalars(select(m.Task.id).where(m.Task.assignee_id == u.id,
                                                                         m.Task.status != "done")).all()))


def _person_named(db: Session, text: str | None) -> m.User | None:
    if not text:
        return None
    for u in db.scalars(select(m.User).where(m.User.kind == "human")):
        if u.name.lower() in text.lower() or re.search(rf"\b{re.escape(u.name.split()[0])}\b", text, re.I):
            return u
    return None


def _suggest(db, user, signals, open_tasks, requests, reviews, quiet, teammates) -> dict | None:
    kinds = {s["kind"] for s in signals}
    for s in signals:
        if s["kind"] == "blocked" and s["level"] == "high" or s["kind"] == "blocked" and "overload" not in kinds:
            who = _person_named(db, s.get("waiting_on"))
            if who and who.id != user.id:
                return {"type": "unblock", "task_id": s["task_id"], "to_user_id": who.id,
                        "label": f"Ask {who.name.split()[0]} to unblock",
                        "text": f"{user.name.split()[0]} is waiting on {who.name.split()[0]}: {s['text'].split(': ', 1)[-1]}"}
    if "overload" in kinds or "after_hours" in kinds:
        movable = sorted(requests or open_tasks, key=lambda t: (t.priority == "high", t.due_at is not None))
        to = _least_loaded(db, teammates, user.id)
        if movable and to:
            t = movable[0]
            return {"type": "reassign", "task_id": t.id, "to_user_id": to.id,
                    "label": f"Move {t.key} to {to.name.split()[0]}",
                    "text": f"Move “{t.title}” to {to.name.split()[0]}, who has the most free time."}
    if "review_stuck" in kinds and reviews:
        t = reviews[0]
        to = _least_loaded(db, teammates, user.id)
        return {"type": "reassign", "task_id": t.id, "to_user_id": to.id if to else None,
                "label": f"Give the review to {to.name.split()[0]}" if to else "Nudge",
                "text": f"{t.key} is blocking a fix. Hand the review to {to.name.split()[0] if to else 'someone else'}."}
    if "no_feedback" in kinds and quiet:
        t = quiet[0]
        return {"type": "ask_review", "task_id": t.id, "to_user_id": t.created_by_id if t.created_by_id != user.id else None,
                "label": "Ask for early feedback", "text": f"Ask for a big-picture review of {t.key} now, before it's finished."}
    return None


def explain(team: m.Team, people: list[dict]) -> dict:
    """A headline for the team and one AI summary per person: working towards, progress, blocked by."""
    risky = [p for p in people if p["level"] != "ok"]
    out = llm.generate_json(f"""You help a manager look after the {team.name} team. Use only the data below.
1. "headline": calm, specific, max 16 words: who needs help this week and why (or that the team is fine). No blame.
2. "people": for each person, "summary": max 2 short sentences in plain English for their manager: what they're
working towards (use the expected outcome when known), how far along they are, and what's blocking them if anything.
Data: {[{"name": p["user"]["name"], "working_on": p["working_on"], "signals": [s["text"] for s in p["signals"]]} for p in people]}
Return JSON {{"headline": str, "people": [{{"name": str, "summary": str}}]}}.""", tier="fast")
    by_name = {x.get("name"): x.get("summary") for x in (out or {}).get("people", []) if isinstance(x, dict)}
    for p in people:
        p["summary"] = by_name.get(p["user"]["name"]) or _fallback_summary(p)
    if out and out.get("headline"):
        return {"headline": out["headline"], "by_ai": True}
    if not risky:
        return {"headline": f"{team.name} looks healthy this week.", "by_ai": False}
    names = " and ".join(p["user"]["name"].split()[0] for p in risky[:2])
    return {"headline": f"{names} need{'s' if len(risky) == 1 else ''} attention this week.", "by_ai": False}


def _fallback_summary(p: dict) -> str:
    if not p["working_on"]:
        return "No open work assigned."
    w = p["working_on"][0]
    text = f"Working on {w['key']} \u201c{w['title']}\u201d" + (f", aiming for: {w['outcome']}" if w["outcome"] else "") + "."
    blocked = next((s["text"] for s in p["signals"] if s["kind"] == "blocked"), None)
    return text + (f" {blocked}." if blocked else "")


def teams_for(db: Session, viewer: m.User) -> list[m.Team]:
    q = select(m.Team).order_by(m.Team.name)
    if not viewer.is_org_admin:
        q = q.where(m.Team.lead_id == viewer.id)
    return db.scalars(q).all()


_CACHE: dict[tuple, tuple[float, dict]] = {}
CACHE_SECONDS = 120


def invalidate() -> None:
    _CACHE.clear()


def report(db: Session, viewer: m.User) -> dict:
    team_list = teams_for(db, viewer)
    key = (viewer.org_id, tuple(t.id for t in team_list))
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    gathered = []
    for team in team_list:
        members = db.scalars(select(m.User).join(m.TeamMember, m.TeamMember.user_id == m.User.id)
                             .where(m.TeamMember.team_id == team.id, m.User.kind == "human")).all()
        people = [person(db, u, members) for u in members]
        people.sort(key=lambda p: {"high": 0, "watch": 1, "ok": 2}[p["level"]])
        gathered.append((team, people))
    # One Gemini call per team, in parallel (network-bound; explain() doesn't touch the database).
    with ThreadPoolExecutor(max_workers=6) as pool:
        explained = list(pool.map(lambda tp: explain(*tp), gathered))
    out = [{"team": {"id": t.id, "name": t.name, "color": t.color, "short": t.short}, "people": people, **ex}
           for (t, people), ex in zip(gathered, explained)]
    out.sort(key=lambda t: min([{"high": 0, "watch": 1, "ok": 2}[p["level"]] for p in t["people"]] or [2]))
    result = {"teams": out}
    _CACHE[key] = (time.time(), result)
    return result


def apply_action(db: Session, viewer: m.User, action: dict) -> dict:
    invalidate()
    task = db.get(m.Task, action.get("task_id"))
    if task is None:
        raise ValueError("That task no longer exists.")
    kind = action.get("type")
    if kind == "reassign":
        to = db.get(m.User, action.get("to_user_id"))
        if to is None:
            raise ValueError("Choose who should take it.")
        old = db.get(m.User, task.assignee_id) if task.assignee_id else None
        task.assignee_id = to.id
        add_log(db, task.org_id, source="manual", task=task, author=viewer,
                summary=f"reassigned from {old.name if old else 'nobody'} to {to.name} (Team Health)")
        focus.notify(db, to.id, "request", f"{viewer.name.split()[0]} moved {task.key} to you", task.title, task.id)
        audit(db, task.org_id, actor=viewer, action=f"Reassigned {task.key} to {to.name}", target_type="task",
              target_id=task.id, reason="Team Health suggestion", approved_by=viewer.name)
        return {"done": f"{task.key} is now with {to.name.split()[0]}."}
    if kind == "ask_review":
        who = db.get(m.User, action.get("to_user_id")) if action.get("to_user_id") else None
        if who is None and task.team_id:
            lead = db.get(m.Team, task.team_id).lead_id
            who = db.get(m.User, lead) if lead and lead != task.assignee_id else None
        add_log(db, task.org_id, source="manual", task=task, author=viewer,
                summary=f"asked {who.name if who else 'the team'} for early feedback")
        if who:
            focus.notify(db, who.id, "review", f"Early feedback wanted on {task.key}", task.title, task.id)
        audit(db, task.org_id, actor=viewer, action=f"Asked for early feedback on {task.key}", target_type="task",
              target_id=task.id, reason="Team Health suggestion", approved_by=viewer.name)
        return {"done": f"Asked {who.name.split()[0] if who else 'the team'} to look at {task.key} now."}
    if kind == "unblock":
        who = db.get(m.User, action.get("to_user_id"))
        if who is None:
            raise ValueError("Choose who can unblock it.")
        blocker = next((b for b in (task.blockers or []) if not b.get("resolved_at")), None)
        detail = blocker["text"] if blocker else task.title
        focus.notify(db, who.id, "blocker", f"{db.get(m.User, task.assignee_id).name.split()[0] if task.assignee_id else 'Someone'} "
                                            f"is waiting on you for {task.key}", detail, task.id)
        add_log(db, task.org_id, source="manual", task=task, author=viewer, summary=f"asked {who.name} to unblock: {detail}")
        audit(db, task.org_id, actor=viewer, action=f"Asked {who.name} to unblock {task.key}", target_type="task",
              target_id=task.id, reason="Team Health suggestion", approved_by=viewer.name)
        return {"done": f"Asked {who.name.split()[0]} to unblock {task.key}."}
    if kind == "nudge":
        focus.notify(db, task.assignee_id, "nudge", f"{viewer.name.split()[0]} nudged you on {task.key}", task.title, task.id)
        return {"done": "Nudged."}
    raise ValueError("Unknown action.")
