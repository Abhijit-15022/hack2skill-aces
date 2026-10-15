"""Background worker: drains the events queue, runs the daily schedule, releases held notifications."""
import logging
import time
import traceback
from pathlib import Path

from sqlalchemy import select, text

from . import models as m
from .db import SessionLocal, init_db, org_session
from .services import feed, focus, ingest, llm, meetings, myday, oncall, pipeline, sessions
from .services.core import now
from .services.timeutil import local, workday

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")

FEED_EVERY = 30 * 60
# (local hour, minute, job) — run once per working day, in the org's timezone.
DAILY = [(6, 0, "pipelines"), (7, 0, "plans"), (8, 0, "feed")]


def handle(db, event: m.Event) -> None:
    p = event.payload
    if event.kind.startswith("ingest_"):
        {"session": sessions.ingest_session, "claude": ingest.ingest_claude, "git": ingest.ingest_git,
         "email": ingest.ingest_email, "calendar": ingest.ingest_calendar}[event.kind.removeprefix("ingest_")](db, event.org_id, p)
    elif event.kind == "investigate":
        oncall.investigate(db, p["incident_id"])
    elif event.kind == "rerun":
        oncall.rerun(db, db.get(m.Incident, p["incident_id"]))
    elif event.kind == "pipeline_success":
        oncall.on_success(db, p["namespace"], p["flow_id"])
    elif event.kind == "feed_rebuild":
        feed.rebuild(db, event.org_id)
    elif event.kind == "plan_day":
        myday.plan(db, db.get(m.User, p["user_id"]))
    elif event.kind == "meeting_process":
        meetings.process(db, db.get(m.Meeting, p["meeting_id"]), Path(p["path"]), db.get(m.User, p["user_id"]))
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
    started = time.monotonic()
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
    log.info("Event %s %s -> %s (%.1fs)", event_id, kind, "retry" if retry and status == "failed" else status,
             time.monotonic() - started)
    return True


def _meta(key: str) -> str | None:
    with SessionLocal() as s:
        s.execute(text("CREATE TABLE IF NOT EXISTS app_meta (key text PRIMARY KEY, value text)"))
        value = s.execute(text("SELECT value FROM app_meta WHERE key=:k"), {"k": key}).scalar()
        s.commit()
        return value


def _set_meta(key: str, value: str) -> None:
    with SessionLocal() as s:
        s.execute(text("INSERT INTO app_meta VALUES (:k, :v) ON CONFLICT (key) DO UPDATE SET value = excluded.value"),
                  {"k": key, "v": value})
        s.commit()


def reembed_all() -> bool:
    """Compute every stored embedding with the current provider, in batches. Returns False if Gemini failed."""
    jobs = [
        (m.Task, lambda t: f"{t.title}\n{t.description}", "embedding", None),
        (m.WorkLog, lambda lg: lg.summary, "embedding", None),
        (m.Incident, lambda i: f"{i.flow_id} {i.root_cause}", "embedding", m.Incident.root_cause.isnot(None)),
        (m.Team, lambda t: f"{t.name}: {t.handles}", "handles_embedding", None),
    ]
    with org_session(None, bypass=True) as db:
        for model, text_of, column, cond in jobs:
            rows = db.scalars(select(model).where(cond) if cond is not None else select(model)).all()
            vectors = llm.embed([text_of(r) for r in rows]) if rows else []
            if vectors is None:
                log.warning("Embedding %s failed; will retry on next start", model.__tablename__)
                return False
            for r, v in zip(rows, vectors):
                setattr(r, column, v)
            log.info("Embedded %d %s", len(rows), model.__tablename__)
    return True


def ensure_embeddings() -> None:
    provider = f"gemini:{llm.settings.gemini_embed_model}" if llm.enabled() else "offline"
    if _meta("embed_provider") == provider:
        return
    log.info("Computing embeddings for %s", provider)
    if reembed_all():
        _set_meta("embed_provider", provider)


def org_ids() -> list[int]:
    with org_session(None, bypass=True) as db:
        return list(db.scalars(select(m.Org.id)))


def run_daily_jobs() -> None:
    t = local(now())
    if not workday(t.date()):
        return
    for hour, minute, job in DAILY:
        key = f"daily:{job}"
        if (t.hour, t.minute) < (hour, minute) or _meta(key) == t.date().isoformat():
            continue
        _set_meta(key, t.date().isoformat())
        log.info("Running daily job %s", job)
        if job == "pipelines":
            for name in pipeline.PIPELINES:
                pipeline.run_and_report(name)
        for oid in org_ids():
            with org_session(oid) as db:
                if job == "plans":
                    for u in db.scalars(select(m.User).where(m.User.kind == "human")):
                        from .services.core import enqueue
                        enqueue(db, oid, "plan_day", {"user_id": u.id})
                elif job == "feed":
                    feed.rebuild(db, oid)


def requeue_interrupted() -> None:
    """Jobs left 'running' by a previous worker that stopped mid-job go back in the queue."""
    with SessionLocal() as s:
        n = s.execute(text("UPDATE events SET status='pending' WHERE status='running'")).rowcount
        s.commit()
    if n:
        log.info("Re-queued %d interrupted job(s)", n)


def main() -> None:
    init_db()
    requeue_interrupted()
    from .seed import seed_if_empty
    seed_if_empty()
    ensure_embeddings()
    log.info("Worker started (Gemini %s)", llm.model_names() or "off: offline fallbacks")
    last_feed = last_release = 0.0
    while True:
        try:
            run_daily_jobs()
            if time.time() - last_release > 20:
                with org_session(None, bypass=True) as db:
                    focus.release(db)
                last_release = time.time()
            if time.time() - last_feed > FEED_EVERY:
                for oid in org_ids():
                    with org_session(oid) as db:
                        feed.rebuild(db, oid)
                last_feed = time.time()
        except Exception as exc:
            log.error("Scheduled job failed: %s", exc)
        if not process_one():
            time.sleep(1.0)


if __name__ == "__main__":
    main()
