"""Play a demo scenario (demo/scenario.json) through Relay's real pipeline.

    python -m app.demo_seed /app/demo/scenario.json [--meeting] [--incident] [--focus EMAIL]

Sessions, emails and calendar invites go through the same code relay-agent and the hooks use, so the result shows
exactly what the product does: Gemini summaries, task matching, blockers, outcome questions, SOP evidence.
"""
import argparse
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import select

from . import models as m
from .db import init_db, org_session
from .services import devices, focus, ingest, meetings, myday, pipeline
from .services.sessions import ingest_session

logging.basicConfig(level=logging.WARNING)
SAMPLE_MEETING = Path(__file__).resolve().parent / "assets" / "sample-meeting.wav"


def say(text: str) -> None:
    print(text, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scenario", nargs="?", default="/app/demo/scenario.json")
    ap.add_argument("--meeting", action="store_true", help="also process the sample meeting recording (~30 s)")
    ap.add_argument("--incident", action="store_true", help="also break the demo pipeline so the on-call agent runs")
    ap.add_argument("--focus", metavar="EMAIL", help="start a focus block for this person and send five pings")
    args = ap.parse_args()

    init_db()
    sc = json.loads(Path(args.scenario).read_text())
    with org_session(None, bypass=True) as db:
        org = db.scalar(select(m.Org).where(m.Org.slug == sc.get("org", "acme")))
    if org is None:
        sys.exit(f"No organisation {sc.get('org')!r}. Start the stack once so the base seed runs.")
    say(f"Playing {args.scenario} for {org.name}")

    with org_session(org.id) as db:
        for d in sc.get("devices", []):
            user = db.scalar(select(m.User).where(m.User.email == d["user_email"]))
            if user:
                devices.heartbeat(db, user, d | {"version": "0.2.0", "synced": True, "sent": sum(t.get("sessions_7d", 0) for t in d["tools"])})
                say(f"  laptop    {d['hostname']:<18} {user.name}: " + ", ".join(t["tool"] for t in d["tools"] if t.get("found")))

    # The meeting first: it assigns work that the AI sessions below then move forward.
    if args.meeting:
        with org_session(org.id) as db:
            creator = db.scalar(select(m.User).where(m.User.email == "kavya@acme.test"))
            mt = m.Meeting(org_id=org.id, created_by_id=creator.id, title="Data and Finance sync", file_name=SAMPLE_MEETING.name)
            db.add(mt)
            db.flush()
            meetings.process(db, mt, SAMPLE_MEETING, creator)
            say(f"  meeting   {mt.title}: {mt.status}, {len(mt.result.get('created', []))} new tasks, "
                f"{len(mt.result.get('decisions', []))} decisions")
    for s in sc.get("sessions", []):
        payload = s | {"transcript": "\n".join(s["transcript"]) if isinstance(s["transcript"], list) else s["transcript"]}
        with org_session(org.id) as db:
            r = ingest_session(db, org.id, payload)
        extra = []
        if r.get("blockers"):
            extra.append(f"blocked: {r['blockers'][0][:60]}")
        if r.get("asked_outcome"):
            extra.append("asked for expected outcome")
        say(f"  session   {s['tool']:<11} {s['user_email']:<18} -> {r.get('task')} "
            f"({'new' if r.get('created') else r.get('matched', '')}){'; ' + '; '.join(extra) if extra else ''}")

    for e in sc.get("emails", []):
        with org_session(org.id) as db:
            r = ingest.ingest_email(db, org.id, e)
        say(f"  email     {e['from']} -> {e['to']}: {r}")
    for c in sc.get("calendar", []):
        with org_session(org.id) as db:
            r = ingest.ingest_calendar(db, org.id, c)
        say(f"  calendar  {c['title']}: SOP steps {[s['status'] for s in r['sop_steps']]}")

    if args.incident:
        from sqlalchemy import text

        from .db import warehouse_engine
        with warehouse_engine.begin() as conn:
            if conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_schema='raw' "
                                 "AND table_name='orders' AND column_name='amount'")).scalar():
                conn.execute(text("ALTER TABLE raw.orders RENAME COLUMN amount TO net_amount"))
        r = pipeline.run_and_report("orders_daily")
        say(f"  pipeline  orders_daily {r['state'].lower()} -> {r.get('incident') or 'no incident'} (the worker investigates)")
    if args.focus:
        with org_session(org.id) as db:
            user = db.scalar(select(m.User).where(m.User.email == args.focus))
            plan = myday.get_or_plan(db, user)
            task = db.get(m.Task, plan.items[0]["task_id"]) if plan.items else None
            focus.start_focus(db, user, 50, task)
            for kind, title in [("kudos", "Kavya sent you kudos"), ("fyi", "Weekly finance newsletter is out"),
                                ("request", "Ananya replied on the Q3 payouts thread"),
                                ("incident", "orders_daily failed: Revenue dashboard will be late")]:
                focus.notify(db, user.id, kind, title)
        say(f"  focus     {args.focus}: 50-minute block started, 4 notifications sent")

    with org_session(org.id) as db:
        for u in db.scalars(select(m.User).where(m.User.kind == "human")):
            myday.plan(db, u)
    say("Done. Day plans refreshed. Open http://localhost:3100 (Kavya: Team · Abhijit: Today · Meera: Today).")


if __name__ == "__main__":
    main()
