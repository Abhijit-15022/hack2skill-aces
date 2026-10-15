"""Calendar helpers and Focus Guard: hold non-urgent notifications while someone is in a focus block."""
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import models as m
from . import llm
from .timeutil import at, day_bounds, local, now, today

WORK_START = (9, 30)
WORK_END = (18, 30)
ALWAYS_URGENT = {"incident"}
NEVER_URGENT = {"kudos", "fyi"}


# ---------------------------------------------------------------- calendar

def events(db: Session, user_id: int, day: date) -> list[m.CalendarEvent]:
    start, end = day_bounds(day)
    return db.scalars(select(m.CalendarEvent).where(m.CalendarEvent.user_id == user_id, m.CalendarEvent.start < end,
                                                    m.CalendarEvent.end > start).order_by(m.CalendarEvent.start)).all()


def free_slots(db: Session, user_id: int, day: date, from_time: datetime | None = None,
               ignore_relay_focus: bool = True) -> list[tuple[datetime, datetime]]:
    """Gaps of 25+ minutes in working hours, after `from_time` if given."""
    start, end = at(day, *WORK_START), at(day, *WORK_END)
    if from_time and from_time > start:
        start = from_time.replace(second=0, microsecond=0)
        start += timedelta(minutes=(5 - start.minute % 5) % 5)
    # Planned focus blocks that haven't started are about to be re-planned; anything already under way stays busy.
    busy = [(e.start, e.end) for e in events(db, user_id, day)
            if not (ignore_relay_focus and e.kind == "focus" and e.source == "relay" and e.start >= now())]
    slots, cursor = [], start
    for b_start, b_end in sorted(busy):
        if b_start > cursor and (b_start - cursor) >= timedelta(minutes=25):
            slots.append((cursor, min(b_start, end)))
        cursor = max(cursor, b_end)
    if end - cursor >= timedelta(minutes=25):
        slots.append((cursor, end))
    return [(a, b) for a, b in slots if b > a]


def meeting_minutes(db: Session, user_id: int, day: date) -> int:
    return int(sum((e.end - e.start).total_seconds() / 60 for e in events(db, user_id, day) if e.kind == "meeting"))


def active_focus(db: Session, user_id: int, when: datetime | None = None) -> m.CalendarEvent | None:
    when = when or now()
    return db.scalar(select(m.CalendarEvent).where(m.CalendarEvent.user_id == user_id, m.CalendarEvent.kind == "focus",
                                                   m.CalendarEvent.start <= when, m.CalendarEvent.end > when)
                     .order_by(m.CalendarEvent.start).limit(1))


def start_focus(db: Session, user: m.User, minutes: int, task: m.Task | None = None) -> m.CalendarEvent:
    current = active_focus(db, user.id)
    if current:
        current.end = now()
    ev = m.CalendarEvent(org_id=user.org_id, user_id=user.id, kind="focus", source="session", start=now(),
                         end=now() + timedelta(minutes=minutes), task_id=task.id if task else None,
                         title=f"Focus: {task.title}" if task else "Focus time")
    db.add(ev)
    db.flush()
    return ev


def end_focus(db: Session, user: m.User) -> int:
    current = active_focus(db, user.id)
    if current:
        current.end = now()
    return release(db, user.id)


# ---------------------------------------------------------------- notifications

def _is_urgent(kind: str, title: str, body: str, focus_task: str | None) -> tuple[bool, str]:
    if kind in ALWAYS_URGENT:
        return True, "Failures always come through."
    if kind in NEVER_URGENT:
        return False, "Can wait until your focus time ends."
    out = llm.generate_json(f"""Someone is in a focus block{f' working on "{focus_task}"' if focus_task else ''}.
A notification arrived. Should it interrupt them now? Interrupt only if waiting would cause real harm in the
next hour (a deadline today, someone blocked right now, a production problem).
Notification ({kind}): {title}
{body[:600]}
Return JSON {{"interrupt": bool, "why": str (max 12 words)}}.""", tier="lite")
    if out and "interrupt" in out:
        return bool(out["interrupt"]), str(out.get("why") or "")[:300]
    return False, "Can wait until your focus time ends."


def notify(db: Session, user_id: int | None, kind: str, title: str, body: str = "",
           task_id: int | None = None) -> m.Notification | None:
    """Deliver now, or hold until the person's focus block ends."""
    user = db.get(m.User, user_id) if user_id else None
    if user is None or user.kind != "human":
        return None
    focus = active_focus(db, user.id)
    focus_task = db.get(m.Task, focus.task_id).title if focus and focus.task_id else None
    urgent, why = (True, "") if not focus else _is_urgent(kind, title, body, focus_task)
    n = m.Notification(org_id=user.org_id, user_id=user.id, kind=kind, title=title[:300], body=body, urgent=urgent,
                       why=why, task_id=task_id, status="delivered" if urgent or not focus else "held",
                       delivered_at=now() if urgent or not focus else None)
    db.add(n)
    db.flush()
    return n


def release(db: Session, user_id: int | None = None) -> int:
    """Deliver held notifications for everyone whose focus block has ended."""
    q = select(m.Notification).where(m.Notification.status == "held")
    if user_id:
        q = q.where(m.Notification.user_id == user_id)
    released = 0
    for n in db.scalars(q):
        if active_focus(db, n.user_id) is None:
            n.status, n.delivered_at = "released", now()
            released += 1
    return released


def inbox(db: Session, user: m.User) -> dict:
    start, _ = day_bounds(today())
    focus = active_focus(db, user.id)
    rows = db.scalars(select(m.Notification).where(m.Notification.user_id == user.id, m.Notification.created_at >= start - timedelta(days=1))
                      .order_by(m.Notification.created_at.desc()).limit(60)).all()
    def out(n):
        return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "urgent": n.urgent, "why": n.why,
                "status": n.status, "task_id": n.task_id, "created_at": n.created_at, "delivered_at": n.delivered_at}
    held_today = db.scalar(select(func.count()).select_from(m.Notification).where(
        m.Notification.user_id == user.id, m.Notification.created_at >= start,
        m.Notification.status.in_(["held", "released"])))
    let_through = db.scalar(select(func.count()).select_from(m.Notification).where(
        m.Notification.user_id == user.id, m.Notification.created_at >= start, m.Notification.urgent.is_(True),
        m.Notification.why != ""))
    return {
        "focus": {"active": bool(focus), "ends_at": focus.end if focus else None, "title": focus.title if focus else None,
                  "task_id": focus.task_id if focus else None},
        "held": [out(n) for n in rows if n.status == "held"],
        "delivered": [out(n) for n in rows if n.status != "held"],
        "stats": {"held_today": held_today, "let_through_today": let_through},
    }


def clear_relay_focus(db: Session, user_id: int, day: date) -> None:
    start, end = day_bounds(day)
    db.execute(delete(m.CalendarEvent).where(m.CalendarEvent.user_id == user_id, m.CalendarEvent.kind == "focus",
                                             m.CalendarEvent.source == "relay", m.CalendarEvent.start >= max(start, now()),
                                             m.CalendarEvent.start < end))


def label(dt: datetime) -> str:
    return local(dt).strftime("%H:%M")
