"""Decide which task a piece of work belongs to, and which team a problem belongs to."""
import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models as m
from . import llm
from .core import user_teams

KEY_RE = re.compile(r"\b([A-Z]{2,5}-\d{1,6})\b")


def _threshold() -> float:
    return 0.62 if llm.enabled() else 0.30


def find_keys(*texts: str) -> list[str]:
    keys: list[str] = []
    for t in texts:
        for k in KEY_RE.findall(t or ""):
            if k not in keys:
                keys.append(k)
    return keys


def match_task(db: Session, user: m.User, text: str, hints: list[str] = ()) -> tuple[m.Task | None, float, str]:
    """Return (task, score, why). Explicit task keys win; otherwise the closest open task of the user's teams."""
    for key in find_keys(*hints, text[:4000]):
        task = db.scalar(select(m.Task).where(m.Task.key == key))
        if task:
            return task, 1.0, f"mentions {key}"

    teams = user_teams(db, user.id)
    candidates = db.scalars(
        select(m.Task).where(
            m.Task.status != "done",
            m.Task.type.notin_(["incident"]),
            or_(m.Task.assignee_id == user.id, m.Task.team_id.in_(teams or [-1])),
        )
    ).all()
    if not candidates:
        return None, 0.0, "no open tasks"
    vec = llm.embed_one(text, task="RETRIEVAL_QUERY")
    scored = []
    for t in candidates:
        score = llm.cosine(vec, t.embedding)
        if t.assignee_id == user.id:
            score += 0.05
        scored.append((score, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    if best_score >= _threshold():
        return best, best_score, f"similar to {best.key} ({best_score:.2f})"
    return None, best_score, "no close match"


def route_team(db: Session, text: str) -> tuple[m.Team | None, float]:
    """Pick the team whose 'handles' description best fits the text."""
    teams = db.scalars(select(m.Team)).all()
    if not teams:
        return None, 0.0
    vec = llm.embed_one(text, task="RETRIEVAL_QUERY")
    best = max(teams, key=lambda t: llm.cosine(vec, t.handles_embedding))
    return best, llm.cosine(vec, best.handles_embedding)
