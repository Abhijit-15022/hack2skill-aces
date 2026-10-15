"""Sign-in, people, teams, resource ownership, AI settings, audit log."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from .. import models as m
from .. import serialize as ser
from ..auth import Ctx, admin_ctx, ctx, find_user_any_org, issue_token
from ..services import llm
from ..services.core import audit, user_teams

router = APIRouter(tags=["org"])


class LoginIn(BaseModel):
    email: str


@router.post("/auth/login")
def login(body: LoginIn):
    user = find_user_any_org(body.email)
    if not user:
        raise HTTPException(404, "No account with that email.")
    return {"token": issue_token(user), "user": ser.user(user)}


@router.get("/me")
def me(c: Ctx = Depends(ctx)):
    org = c.db.get(m.Org, c.org_id)
    teams = [ser.team(c.db.get(m.Team, t)) for t in user_teams(c.db, c.user.id)]
    return {"user": ser.user(c.user), "org": {"id": org.id, "name": org.name, "region": org.region}, "teams": teams}


@router.get("/users")
def users(c: Ctx = Depends(ctx)):
    return {"users": [ser.user(u) for u in c.db.scalars(select(m.User).order_by(m.User.name))]}


@router.get("/teams")
def teams(c: Ctx = Depends(ctx)):
    out = []
    for t in c.db.scalars(select(m.Team).order_by(m.Team.name)):
        rows = c.db.execute(select(m.TeamMember, m.User).join(m.User, m.User.id == m.TeamMember.user_id)
                            .where(m.TeamMember.team_id == t.id)).all()
        out.append(ser.team(t) | {
            "lead": ser.user(c.db.get(m.User, t.lead_id)) if t.lead_id else None,
            "members": [ser.user(u) | {"role": tm.role} for tm, u in rows],
        })
    return {"teams": out}


class TeamIn(BaseModel):
    name: str
    short: str
    color: str = "#3A3A3C"
    handles: str = ""
    lead_id: int | None = None
    autonomy: str = "draft"


@router.post("/teams")
def create_team(body: TeamIn, c: Ctx = Depends(admin_ctx)):
    team = m.Team(org_id=c.org_id, **body.model_dump())
    team.handles_embedding = llm.embed_one(f"{body.name}: {body.handles}")
    c.db.add(team)
    c.db.flush()
    audit(c.db, c.org_id, actor=c.user, action=f"Created team {team.name}", target_type="team", target_id=team.id)
    return ser.team(team)


class TeamPatch(BaseModel):
    name: str | None = None
    handles: str | None = None
    lead_id: int | None = None
    autonomy: str | None = None
    color: str | None = None


@router.patch("/teams/{team_id}")
def update_team(team_id: int, body: TeamPatch, c: Ctx = Depends(admin_ctx)):
    team = c.db.get(m.Team, team_id) or _404("team")
    changes = body.model_dump(exclude_unset=True)
    if "autonomy" in changes and changes["autonomy"] not in ("suggest", "draft", "act"):
        raise HTTPException(422, "autonomy must be suggest, draft or act.")
    for k, v in changes.items():
        setattr(team, k, v)
    if "handles" in changes or "name" in changes:
        team.handles_embedding = llm.embed_one(f"{team.name}: {team.handles}")
    audit(c.db, c.org_id, actor=c.user, action=f"Updated team {team.name}: {', '.join(changes)}",
          target_type="team", target_id=team.id)
    return ser.team(team)


class MemberIn(BaseModel):
    user_id: int
    role: str = "member"


@router.post("/teams/{team_id}/members")
def add_member(team_id: int, body: MemberIn, c: Ctx = Depends(admin_ctx)):
    c.db.get(m.Team, team_id) or _404("team")
    c.db.execute(delete(m.TeamMember).where(m.TeamMember.team_id == team_id, m.TeamMember.user_id == body.user_id))
    c.db.add(m.TeamMember(org_id=c.org_id, team_id=team_id, user_id=body.user_id, role=body.role))
    return {"ok": True}


@router.delete("/teams/{team_id}/members/{user_id}")
def remove_member(team_id: int, user_id: int, c: Ctx = Depends(admin_ctx)):
    c.db.execute(delete(m.TeamMember).where(m.TeamMember.team_id == team_id, m.TeamMember.user_id == user_id))
    return {"ok": True}


@router.get("/resources")
def resources(c: Ctx = Depends(ctx)):
    teams = {t.id: t.name for t in c.db.scalars(select(m.Team))}
    out = []
    for r in c.db.scalars(select(m.Resource).order_by(m.Resource.kind, m.Resource.name)):
        out.append({"id": r.id, "name": r.name, "kind": r.kind, "owner_team_id": r.owner_team_id,
                    "owner_team": teams.get(r.owner_team_id), "business_team_id": r.business_team_id,
                    "business_team": teams.get(r.business_team_id), "meta": r.meta})
    return {"resources": out}


class ResourcePatch(BaseModel):
    owner_team_id: int | None = None
    business_team_id: int | None = None


@router.patch("/resources/{resource_id}")
def update_resource(resource_id: int, body: ResourcePatch, c: Ctx = Depends(admin_ctx)):
    r = c.db.get(m.Resource, resource_id) or _404("resource")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    audit(c.db, c.org_id, actor=c.user, action=f"Changed ownership of {r.name}", target_type="resource",
          target_id=r.id)
    return {"ok": True}


@router.get("/audit")
def audit_log(limit: int = 100, c: Ctx = Depends(admin_ctx)):
    rows = c.db.scalars(select(m.AuditLog).order_by(m.AuditLog.created_at.desc()).limit(min(limit, 500))).all()
    return {"entries": [{
        "id": a.id, "at": a.created_at, "actor": ser.user(c.db.get(m.User, a.actor_id)) if a.actor_id else None,
        "action": a.action, "target_type": a.target_type, "target_id": a.target_id, "reason": a.reason,
        "approved_by": a.approved_by,
    } for a in rows]}


class PrefsIn(BaseModel):
    email_capture: bool


@router.patch("/me/preferences")
def prefs(body: PrefsIn, c: Ctx = Depends(ctx)):
    c.user.email_capture = body.email_capture
    return {"ok": True, "email_capture": body.email_capture}


def _404(what: str):
    raise HTTPException(404, f"No such {what}.")
