"""Background worker: drains the events queue, keeps Kestra flows deployed, rebuilds the feed."""
import logging
import time
import traceback

from sqlalchemy import select, text

from . import models as m
from .db import SessionLocal, init_db, org_session
from .services import feed, ingest, kestra, llm, oncall
from .services.core import now

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")

FEED_EVERY = 30 * 60


def handle(db, event: m.Event) -> None:
    p = event.payload
    if event.kind.startswith("ingest_"):
        ingest_kind = event.kind.removeprefix("ingest_")
        {"claude": ingest.ingest_claude, "git": ingest.ingest_git, "email": ingest.ingest_email,
         "calendar": ingest.ingest_calendar}[ingest_kind](db, event.org_id, p)
    elif event.kind == "investigate":
        oncall.investigate(db, p["incident_id"])
    elif event.kind == "rerun":
        oncall.rerun(db, db.get(m.Incident, p["incident_id"]))
    elif event.kind == "kestra_success":
        oncall.on_success(db, p["namespace"], p["flow_id"])
    elif event.kind == "feed_rebuild":
        feed.rebuild(db, event.org_id)
    else:
        raise ValueError(f"Unknown event kind {event.kind}")


def claim() -> tuple[int, int, str] | None:
    with SessionLocal() as s:
        row = s.execute(text(
            "UPDATE events SET status='running', attempts=attempts+1 WHERE id = ("
            " SELECT id FROM events WHERE status='pending' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)"
            " RETURNING id, org_id, kind")).first()
        s.commit()
        return tuple(row) if row else None


def process_one() -> bool:
    claimed = claim()
    if not claimed:
        return False
    event_id, org_id, kind = claimed
    try:
        with org_session(org_id) as db:
            handle(db, db.get(m.Event, event_id))
        status, error = "done", None
    except Exception as exc:
        log.error("Event %s (%s) failed: %s", event_id, kind, exc)
        status, error = "failed", traceback.format_exc()[-4000:]
    with SessionLocal() as s:
        ev = s.get(m.Event, event_id)
        retry = status == "failed" and ev.attempts < 3
        ev.status = "pending" if retry else status
        ev.error, ev.processed_at = error, now()
        s.commit()
    log.info("Event %s %s -> %s", event_id, kind, "retry" if status == "failed" and retry else status)
    return True


def ensure_embeddings_match_provider() -> None:
    """If Gemini was switched on/off since the last run, recompute every stored embedding."""
    provider = "gemini" if llm.enabled() else "offline"
    with SessionLocal() as s:
        s.execute(text("CREATE TABLE IF NOT EXISTS app_meta (key text PRIMARY KEY, value text)"))
        current = s.execute(text("SELECT value FROM app_meta WHERE key='embed_provider'")).scalar()
        s.commit()
    if current == provider:
        return
    log.info("Re-embedding everything for provider %s (was %s)", provider, current)
    with org_session(None, bypass=True) as db:
        for t in db.scalars(select(m.Task)):
            t.embedding = llm.embed_one(f"{t.title}\n{t.description}")
        for lg in db.scalars(select(m.WorkLog)):
            lg.embedding = llm.embed_one(lg.summary)
        for i in db.scalars(select(m.Incident).where(m.Incident.root_cause.isnot(None))):
            i.embedding = llm.embed_one(f"{i.flow_id} {i.root_cause}")
        for team in db.scalars(select(m.Team)):
            team.handles_embedding = llm.embed_one(f"{team.name}: {team.handles}")
    with SessionLocal() as s:
        s.execute(text("INSERT INTO app_meta VALUES ('embed_provider', :p) "
                       "ON CONFLICT (key) DO UPDATE SET value = excluded.value"), {"p": provider})
        s.commit()


def main() -> None:
    init_db()
    from .seed import seed_if_empty
    seed_if_empty()
    ensure_embeddings_match_provider()
    flows_deployed = False
    last_feed = 0.0
    log.info("Worker started (Gemini %s)", "on" if llm.enabled() else "off: offline fallbacks")
    while True:
        if not flows_deployed and kestra.is_up():
            try:
                log.info("Deployed Kestra flows: %s", kestra.deploy_all_flows())
                flows_deployed = True
            except Exception as exc:
                log.warning("Kestra flow deploy will retry: %s", exc)
        if time.time() - last_feed > FEED_EVERY:
            with org_session(None, bypass=True) as db:
                org_ids = list(db.scalars(select(m.Org.id)))
            for oid in org_ids:
                with org_session(oid) as db:
                    feed.rebuild(db, oid)
            last_feed = time.time()
        if not process_one():
            time.sleep(1.0)


if __name__ == "__main__":
    main()
