"""relay-agent installs: heartbeats from laptops, and whether each person's AI coding tools are connected."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .timeutil import now

ONLINE_MINUTES = 15  # the agent syncs every 5 minutes; three missed beats means offline
TOOL_LABEL = {"claude": "Claude Code", "cursor": "Cursor", "codex": "Codex", "antigravity": "Antigravity"}


def heartbeat(db: Session, user: m.User, p: dict) -> m.AgentDevice:
    host = (p.get("hostname") or "unknown")[:200]
    dev = db.scalar(select(m.AgentDevice).where(m.AgentDevice.user_id == user.id, m.AgentDevice.hostname == host))
    if dev is None:
        dev = m.AgentDevice(org_id=user.org_id, user_id=user.id, hostname=host)
        db.add(dev)
    dev.platform, dev.version = (p.get("platform") or "")[:60], (p.get("version") or "")[:20]
    dev.tools = [{"tool": t.get("tool"), "label": TOOL_LABEL.get(t.get("tool"), t.get("tool")), "found": bool(t.get("found")),
                  "sessions_7d": int(t.get("sessions_7d") or 0), "last_session_at": t.get("last_session_at"),
                  "error": (t.get("error") or None)} for t in (p.get("tools") or [])]
    dev.last_seen_at = now()
    if p.get("synced"):
        dev.last_sync_at = now()
        dev.sessions_sent = (dev.sessions_sent or 0) + int(p.get("sent") or 0)
    db.flush()
    return dev


def serialize(db: Session, dev: m.AgentDevice) -> dict:
    u = db.get(m.User, dev.user_id)
    online = now() - dev.last_seen_at < timedelta(minutes=ONLINE_MINUTES)
    return {"id": dev.id, "user": {"id": u.id, "name": u.name, "initials": u.initials, "color": u.color},
            "hostname": dev.hostname, "platform": dev.platform, "version": dev.version, "tools": dev.tools,
            "online": online, "last_seen_at": dev.last_seen_at, "last_sync_at": dev.last_sync_at,
            "sessions_sent": dev.sessions_sent}


def for_user(db: Session, user: m.User) -> dict:
    devs = db.scalars(select(m.AgentDevice).where(m.AgentDevice.user_id == user.id)
                      .order_by(m.AgentDevice.last_seen_at.desc())).all()
    return {"devices": [serialize(db, d) for d in devs]}


def for_org(db: Session) -> dict:
    devs = db.scalars(select(m.AgentDevice).order_by(m.AgentDevice.last_seen_at.desc())).all()
    return {"devices": [serialize(db, d) for d in devs]}
