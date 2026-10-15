"""Ask: answer questions from the company's work history, citing sources, within what the asker may see."""
import re

from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from . import llm
from .core import user_teams


def _visible_tasks(db: Session, viewer: m.User):
    if viewer.is_org_admin:
        return select(m.Task.id)
    teams = user_teams(db, viewer.id)
    return select(m.Task.id).where(or_(m.Task.team_id.in_(teams or [-1]), m.Task.assignee_id == viewer.id))


def search(db: Session, viewer: m.User, question: str, k: int = 10) -> list[dict]:
    vec = llm.embed_one(question, "RETRIEVAL_QUERY")
    visible = _visible_tasks(db, viewer)
    out: list[dict] = []
    if vec is None:
        return _keyword_search(db, viewer, question, visible, k)
    tasks = db.scalars(select(m.Task).where(m.Task.id.in_(visible)).order_by(m.Task.embedding.cosine_distance(vec)).limit(k)).all()
    for t in tasks:
        out.append({"type": "task", "id": t.id, "title": f"{t.title}", "meta": f"{t.key} · {t.status}",
                    "text": f"{t.key} {t.title}: {t.description}", "snippet": (t.description or t.title).split(". ")[0], "score": llm.cosine(vec, t.embedding)})
    logs = db.scalars(select(m.WorkLog).where(or_(m.WorkLog.task_id.in_(visible),
                                                  m.WorkLog.author_id == viewer.id,
                                                  m.WorkLog.on_behalf_of_id == viewer.id))
                      .order_by(m.WorkLog.embedding.cosine_distance(vec)).limit(k)).all()
    for lg in logs:
        task = db.get(m.Task, lg.task_id) if lg.task_id else None
        who = db.get(m.User, lg.author_id) if lg.author_id else None
        label = {"claude": "Claude session", "git": "Commit", "email": "Email", "calendar": "Calendar",
                 "oncall": "On-call agent", "sop": "SOP"}.get(lg.source, lg.source.title())
        out.append({"type": "log", "id": lg.id, "task_id": lg.task_id,
                    "title": f"{label}" + (f" on {task.key}" if task else ""),
                    "meta": f"{lg.created_at:%d %b}" + (f" · {who.name}" if who else ""),
                    "text": f"{lg.created_at:%d %b %Y} {who.name if who else ''} ({label}): {lg.summary}",
                    "snippet": f"{who.name.split()[0] + ' ' if who else ''}{lg.summary[0].lower() + lg.summary[1:] if who else lg.summary}",
                    "score": llm.cosine(vec, lg.embedding)})
    incidents = db.scalars(select(m.Incident).where(m.Incident.task_id.in_(visible), m.Incident.embedding.isnot(None))
                           .order_by(m.Incident.embedding.cosine_distance(vec)).limit(3)).all()
    for inc in incidents:
        out.append({"type": "incident", "id": inc.id, "title": f"{inc.flow_id} failed", "meta": f"{inc.key} · {inc.status}",
                    "text": f"{inc.key} {inc.flow_id} failed {inc.detected_at:%d %b}: {inc.root_cause or ''} status {inc.status}",
                    "snippet": f"{inc.flow_id} failed on {inc.detected_at:%d %b}: {inc.root_cause or 'cause unknown'}",
                    "score": llm.cosine(vec, inc.embedding)})
    words = [w for w in re.findall(r"[a-z]{4,}", question.lower())]
    for step in db.scalars(select(m.SopStep).where(or_(*[m.SopStep.title.ilike(f"%{w}%") for w in words]) if words else false()).limit(5)):
        sop = db.get(m.Sop, step.sop_id)
        out.append({"type": "sop", "id": sop.id, "title": sop.title, "meta": f"SOP v{sop.version} · step {step.seq}",
                    "text": f"SOP {sop.title} step {step.seq}: {step.title}" + (f" (done when {step.evidence_hint})" if step.evidence_hint else ""),
                    "snippet": f"the {sop.title} SOP covers this in step {step.seq}, \u201c{step.title}\u201d", "score": 0.2})
    out.sort(key=lambda s: s["score"], reverse=True)
    seen, unique = set(), []
    for s in out:
        key = (s["type"], s["id"])
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique[:k]


def _keyword_search(db: Session, viewer: m.User, question: str, visible, k: int) -> list[dict]:
    words = [w for w in re.findall(r"[a-z0-9_]{4,}", question.lower())][:6]
    if not words:
        return []
    cond = or_(*[m.WorkLog.summary.ilike(f"%{w}%") for w in words])
    logs = db.scalars(select(m.WorkLog).where(cond, or_(m.WorkLog.task_id.in_(visible), m.WorkLog.author_id == viewer.id))
                      .order_by(m.WorkLog.created_at.desc()).limit(k)).all()
    return [{"type": "log", "id": lg.id, "task_id": lg.task_id, "title": "Work log", "meta": f"{lg.created_at:%d %b}",
             "text": lg.summary, "snippet": lg.summary, "score": 0.2} for lg in logs]


def answer(db: Session, viewer: m.User, question: str) -> dict:
    sources = search(db, viewer, question)
    if not sources:
        return {"answer": "I couldn't find anything about that in the work you can see.", "segments": [], "sources": []}
    numbered = "\n".join(f"[{i + 1}] {s['text'][:600]}" for i, s in enumerate(sources))
    out = llm.generate_json(f"""Answer the question using ONLY these sources. Be brief (max 4 sentences), plain
English, specific (names, keys, dates). Cite sources with their numbers. If the sources don't answer it, say so.
Return JSON {{"segments": [{{"text": str, "cite": int or 0}}]}} — consecutive pieces of the answer, each with the
source number that supports it (0 if none).
Question: {question}
Sources:
{numbered}""")
    if out and out.get("segments"):
        segs = [{"text": s.get("text", ""), "cite": int(s.get("cite") or 0)} for s in out["segments"]]
    else:
        segs = []
        for i, s in enumerate(sources[:3]):
            snippet = s.get("snippet") or s["text"]
            snippet = snippet[0].upper() + snippet[1:]
            segs.append({"text": ("" if i == 0 else " ") + snippet[:240].rstrip(". ") + ".", "cite": i + 1})
    used = sorted({s["cite"] for s in segs if s["cite"]})
    keep = [sources[c - 1] | {"n": c} for c in used if 0 < c <= len(sources)]
    return {"answer": "".join(s["text"] for s in segs), "segments": segs,
            "sources": [{k: v for k, v in s.items() if k not in ("text", "snippet")} for s in keep], "searched": len(sources)}
