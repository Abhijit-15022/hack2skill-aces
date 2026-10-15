"""Written standups from logged work, and meeting recordings turned into decisions, tasks and updates."""
import mimetypes
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from . import focus, llm
from .core import add_log, audit, create_task, feed, refresh_task_embedding, set_status, user_teams
from .timeutil import at, local, now, today, workday

settings = get_settings()


# ---------------------------------------------------------------- written standup

def _previous_workday():
    d = today() - timedelta(days=1)
    while not workday(d):
        d -= timedelta(days=1)
    return d


def standup(db: Session, team: m.Team, refresh: bool = False) -> m.Standup:
    key = today().isoformat()
    cached = db.scalar(select(m.Standup).where(m.Standup.team_id == team.id, m.Standup.day == key))
    if cached and not refresh:
        return cached
    since = at(_previous_workday(), 0)
    members = db.scalars(select(m.User).join(m.TeamMember, m.TeamMember.user_id == m.User.id)
                         .where(m.TeamMember.team_id == team.id, m.User.kind == "human").order_by(m.User.name)).all()
    raw = []
    for u in members:
        logs = db.scalars(select(m.WorkLog).where(m.WorkLog.author_id == u.id, m.WorkLog.created_at >= since,
                                                  m.WorkLog.source != "manual").order_by(m.WorkLog.created_at)).all()
        closed = db.scalars(select(m.Task).where(m.Task.assignee_id == u.id, m.Task.closed_at >= since)).all()
        plan = db.scalar(select(m.DayPlan).where(m.DayPlan.user_id == u.id, m.DayPlan.day == key))
        doing = db.scalars(select(m.Task).where(m.Task.assignee_id == u.id, m.Task.status.in_(["doing", "review"]))).all()
        blocked = [t for t in db.scalars(select(m.Task).where(m.Task.assignee_id == u.id, m.Task.status != "done"))
                   if t.due_at and t.due_at < now()]
        waiting = db.scalars(select(m.Task).where(m.Task.created_by_id == u.id, m.Task.type == "review",
                                                  m.Task.status != "done")).all()
        open_blockers = [f"{t.key}: {b['text']}" + (f" (waiting on {b['waiting_on']})" if b.get("waiting_on") else "")
                         for t in db.scalars(select(m.Task).where(m.Task.assignee_id == u.id, m.Task.status != "done"))
                         for b in (t.blockers or []) if not b.get("resolved_at")]
        raw.append({"user": u, "yesterday": [f"{lg.summary}" for lg in logs][-6:] + [f"Closed {t.key} {t.title}" for t in closed][:4],
                    "today": [i["title"] for i in plan.items] if plan else [t.title for t in doing][:3],
                    "blocked": open_blockers[:3] + [f"{t.key} {t.title} is overdue" for t in blocked][:2]
                               + [f"waiting on review of {t.key}" for t in waiting][:2]})
    out = llm.generate_json(f"""Write today's async standup for the {team.name} team from what each person actually
logged. For each person: up to 2 short bullet points for yesterday (past tense, concrete, no filler), up to 2
for today, and blockers (empty list if none). Never invent work that isn't in the data.
Data: {[{"name": r["user"].name, "yesterday": r["yesterday"], "today": r["today"], "blocked": r["blocked"]} for r in raw]}
Return JSON {{"people": [{{"name": str, "yesterday": [str], "today": [str], "blocked": [str]}}]}}""", tier="fast")
    by_name = {p.get("name"): p for p in (out or {}).get("people", [])}
    people = []
    for r in raw:
        p = by_name.get(r["user"].name)
        people.append({"user_id": r["user"].id, "name": r["user"].name, "initials": r["user"].initials,
                       "color": r["user"].color,
                       "yesterday": (p or {}).get("yesterday") or r["yesterday"][:2] or ["Nothing logged."],
                       "today": (p or {}).get("today") or r["today"][:2] or ["Not planned yet."],
                       "blocked": (p or {}).get("blocked", r["blocked"][:2]) if p else r["blocked"][:2]})
    db.execute(delete(m.Standup).where(m.Standup.team_id == team.id, m.Standup.day == key))
    s = m.Standup(org_id=team.org_id, team_id=team.id, day=key, people=people, by_ai=bool(by_name))
    db.add(s)
    db.flush()
    return s


# ---------------------------------------------------------------- meeting recordings

def meetings_dir() -> Path:
    p = Path(settings.data_dir) / "meetings"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _match_user(users: list[m.User], name: str | None) -> m.User | None:
    if not name:
        return None
    n = name.lower().strip()
    for u in users:
        if u.name.lower() == n or u.name.split()[0].lower() == n.split()[0]:
            return u
    return None


def process(db: Session, meeting: m.Meeting, path: Path, creator: m.User) -> m.Meeting:
    if not llm.enabled():
        meeting.status, meeting.error = "failed", "Meeting capture needs Gemini. Add GEMINI_API_KEY to .env."
        return meeting
    mime = mimetypes.guess_type(path.name)[0] or "audio/wav"
    uploaded = llm.upload_file(str(path), mime)
    if uploaded is None:
        meeting.status, meeting.error = "failed", "Gemini couldn't read the recording. Try again in a minute."
        return meeting
    users = db.scalars(select(m.User).where(m.User.kind == "human")).all()
    open_tasks = db.scalars(select(m.Task).where(m.Task.status != "done").order_by(m.Task.updated_at.desc()).limit(60)).all()
    result = llm.generate_json(f"""Listen to this team meeting and turn it into work updates.
People in the company: {[{"name": u.name, "title": u.title} for u in users]}
Open tasks you may refer to by key: {[{"key": t.key, "title": t.title} for t in open_tasks]}
Today is {today().isoformat()} ({today():%A}).
Return JSON {{"title": str (short meeting title), "summary": str (2 sentences),
"decisions": [{{"text": str, "why": str, "said_by": str, "at": "mm:ss"}}],
"action_items": [{{"title": str (imperative), "owner": str (a person's name from the list), "due": "YYYY-MM-DD" or null,
"task_key": str or null (only if it clearly continues an existing task)}}],
"task_updates": [{{"task_key": str, "update": str (past tense), "status": "doing"|"review"|"done"|null,
"new_owner": str or null (a person's name, only when the meeting handed this task to someone else)}}]}}
Every decision the group agreed on counts, including process changes (e.g. how they'll run standups).
Only include what was actually said. Use the people's real names from the list. Set "status" only when the
meeting explicitly says that specific task is started or finished; a related problem being fixed doesn't finish
a different task. When someone agrees to do
something new for a colleague's task (e.g. "I'll send you the query"), that's a new action item for them, not
an update to the colleague's task.""", tier="meeting", parts=[uploaded])
    if not result:
        meeting.status, meeting.error = "failed", "Gemini couldn't analyse the recording."
        return meeting

    team_ids = user_teams(db, creator.id)
    team = db.get(m.Team, team_ids[0]) if team_ids else None
    created, updated, decisions = [], [], []
    for u in result.get("task_updates") or []:
        t = db.scalar(select(m.Task).where(m.Task.key == u.get("task_key")))
        if not t:
            continue
        add_log(db, meeting.org_id, source="meeting", task=t, author=None, summary=f"In “{meeting.title}”: {u.get('update')}",
                raw_ref=f"meeting-{meeting.id}")
        if u.get("status") in ("doing", "review", "done") and u["status"] != t.status:
            set_status(db, t, u["status"], None, f"agreed in {meeting.title}", source="meeting")
        new_owner = _match_user(users, u.get("new_owner"))
        if new_owner and new_owner.id != t.assignee_id:
            old_owner = db.get(m.User, t.assignee_id) if t.assignee_id else None
            t.assignee_id = new_owner.id
            add_log(db, meeting.org_id, source="meeting", task=t,
                    summary=f"handed from {old_owner.name if old_owner else 'nobody'} to {new_owner.name} in \u201c{meeting.title}\u201d")
            focus.notify(db, new_owner.id, "meeting", f"{t.key} is yours now", f"Agreed in {meeting.title}: {t.title}", t.id)
            u["update"] = f"{u.get('update')} Now with {new_owner.name.split()[0]}."
        refresh_task_embedding(t)
        updated.append({"task_id": t.id, "key": t.key, "title": t.title, "update": u.get("update")})
    for a in result.get("action_items") or []:
        owner = _match_user(users, a.get("owner"))
        due = None
        if a.get("due"):
            try:
                due = at(date.fromisoformat(a["due"]), 18)
            except ValueError:
                due = None
        existing = db.scalar(select(m.Task).where(m.Task.key == a.get("task_key"))) if a.get("task_key") else None
        if existing:
            add_log(db, meeting.org_id, source="meeting", task=existing, summary=f"Action from “{meeting.title}”: {a.get('title')}",
                    raw_ref=f"meeting-{meeting.id}")
            updated.append({"task_id": existing.id, "key": existing.key, "title": existing.title, "update": a.get("title")})
            continue
        owner_team = db.get(m.Team, user_teams(db, owner.id)[0]) if owner and user_teams(db, owner.id) else team
        t = create_task(db, meeting.org_id, title=a.get("title") or "Follow-up", team=owner_team, created_by=creator,
                        assignee_id=owner.id if owner else None, due_at=due, description_by_ai=True,
                        description=f"Agreed in “{meeting.title}” ({local(now()):%d %b}).",
                        links=[{"kind": "meeting", "label": meeting.title, "ref": f"meeting-{meeting.id}"}])
        add_log(db, meeting.org_id, source="meeting", task=t, summary=f"created from “{meeting.title}”",
                raw_ref=f"meeting-{meeting.id}")
        if owner:
            focus.notify(db, owner.id, "meeting", f"New action from {meeting.title}", t.title, t.id)
        created.append({"task_id": t.id, "key": t.key, "title": t.title, "owner": owner.name if owner else None,
                        "due": a.get("due")})
    for d in result.get("decisions") or []:
        item = feed(db, meeting.org_id, kind="decision", team_id=team.id if team else None, title=d.get("text", "")[:280],
                    body=f"Why: {d.get('why') or 'not stated'}. Decided in “{meeting.title}”"
                         + (f" by {d['said_by']}" if d.get("said_by") else "") + (f" at {d['at']}" if d.get("at") else "") + ".",
                    sources=[meeting.title], score=0.45)
        decisions.append(d | {"feed_item_id": item.id})
    meeting.title = result.get("title") or meeting.title
    meeting.summary = result.get("summary") or ""
    meeting.result = {"decisions": decisions, "created": created, "updated": updated}
    meeting.status = "done"
    audit(db, meeting.org_id, actor=None, action=f"Processed meeting “{meeting.title}”",
          target_type="meeting", target_id=meeting.id,
          reason=f"{len(created)} tasks created, {len(updated)} updated, {len(decisions)} decisions",
          approved_by=f"Uploaded by {creator.name}")
    return meeting


def serialize(mt: m.Meeting) -> dict:
    return {"id": mt.id, "title": mt.title, "status": mt.status, "summary": mt.summary, "result": mt.result,
            "error": mt.error, "file_name": mt.file_name, "created_at": mt.created_at}
