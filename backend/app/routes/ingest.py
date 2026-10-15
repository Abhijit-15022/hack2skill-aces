"""Inbound signals: hooks (Claude, git), email/calendar, orchestrator webhooks, the warehouse runner, demo controls."""
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from .. import models as m
from ..auth import Ctx, admin_ctx, require_ingest_token
from ..config import get_settings
from ..db import org_session, warehouse_engine
from ..services import ingest, oncall, pipeline, runner, sessions
from ..services.core import enqueue

router = APIRouter(tags=["ingest"])
settings = get_settings()

HANDLERS = {
    "session": sessions.ingest_session,
    "claude": ingest.ingest_claude,
    "git": ingest.ingest_git,
    "email": ingest.ingest_email,
    "calendar": ingest.ingest_calendar,
}
EMAIL_FIELD = {"session": "user_email", "claude": "user_email", "git": "author_email", "email": None, "calendar": "organizer"}


def _org_for(kind: str, payload: dict) -> int:
    emails = []
    if EMAIL_FIELD[kind]:
        emails.append(payload.get(EMAIL_FIELD[kind]))
    else:
        to = payload.get("to")
        emails += (to if isinstance(to, list) else [to]) + [payload.get("from")]
    with org_session(None, bypass=True) as db:
        for e in emails:
            org = db.scalar(select(m.User.org_id).where(m.User.email == (e or "").lower()))
            if org:
                return org
    raise HTTPException(404, "None of the people in this payload belong to an organisation in Relay.")


@router.post("/ingest/{kind}", dependencies=[Depends(require_ingest_token)])
async def ingest_signal(kind: str, request: Request, sync: bool = False):
    if kind not in HANDLERS:
        raise HTTPException(404, f"Unknown source {kind!r}. Use one of {', '.join(HANDLERS)}.")
    payload = await request.json()
    org_id = _org_for(kind, payload)
    if sync:
        with org_session(org_id) as db:
            try:
                return {"processed": True, "result": HANDLERS[kind](db, org_id, payload)}
            except (ingest.IngestError, sessions.SessionError) as exc:
                raise HTTPException(422, str(exc))
    with org_session(org_id) as db:
        event = enqueue(db, org_id, f"ingest_{kind}", payload)
        return JSONResponse({"queued": True, "event_id": event.id}, status_code=202)


@router.post("/webhooks/orchestrator", dependencies=[Depends(require_ingest_token)])
@router.post("/webhooks/kestra", dependencies=[Depends(require_ingest_token)], include_in_schema=False)
async def orchestrator_webhook(request: Request):
    """For an external orchestrator (Kestra, Airflow, Dagster): {executionId, namespace, flowId, state}."""
    p = await request.json()
    namespace, flow_id, state = p.get("namespace"), p.get("flowId"), (p.get("state") or "").upper()
    with org_session(None, bypass=True) as db:
        org_id = db.scalar(select(m.Resource.org_id).where(m.Resource.kind == "pipeline", m.Resource.name == flow_id))
    if not org_id:
        return {"ignored": f"{namespace}.{flow_id} is not a flow Relay watches."}
    with org_session(org_id) as db:
        if state == "SUCCESS":
            enqueue(db, org_id, "pipeline_success", {"namespace": namespace, "flow_id": flow_id})
            return {"ok": True}
        if state in ("FAILED", "WARNING", "KILLED"):
            inc = oncall.open_incident(db, org_id, namespace=namespace, flow_id=flow_id,
                                       execution_id=p.get("executionId") or "unknown")
            return {"incident": inc.key}
    return {"ignored": state}


@router.post("/runner/models/{name}/run", dependencies=[Depends(require_ingest_token)])
def run_model(name: str, x_execution_id: str | None = Header(default=None)):
    try:
        ok, error = runner.run_model(name, x_execution_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, f"No model named {name}.")
    if not ok:
        return JSONResponse({"model": name, "status": "failed", "error": error}, status_code=422)
    return {"model": name, "status": "success"}


@router.post("/internal/feed/rebuild-all", dependencies=[Depends(require_ingest_token)])
def rebuild_all_feeds():
    with org_session(None, bypass=True) as db:
        org_ids = list(db.scalars(select(m.Org.id)))
    for oid in org_ids:
        with org_session(oid) as db:
            enqueue(db, oid, "feed_rebuild", {})
    return {"queued": len(org_ids)}


# ---------------------------------------------------------------- demo controls

def _models_dir() -> Path:
    return Path(settings.pipelines_dir) / "models"


@router.post("/demo/pipeline/break")
def break_pipeline(c: Ctx = Depends(admin_ctx)):
    """Simulate yesterday's refactor: rename raw.orders.amount to net_amount, then run orders_daily."""
    with warehouse_engine.begin() as conn:
        has_amount = conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='raw' AND table_name='orders' "
            "AND column_name='amount'")).scalar()
        if has_amount:
            conn.execute(text("ALTER TABLE raw.orders RENAME COLUMN amount TO net_amount"))
    result = pipeline.run_and_report("orders_daily")
    return {"renamed": bool(has_amount), "run": result["execution_id"], "state": result["state"],
            "incident": result["incident"]}


@router.post("/demo/pipeline/reset")
def reset_pipeline(c: Ctx = Depends(admin_ctx)):
    with warehouse_engine.begin() as conn:
        has_net = conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='raw' AND table_name='orders' "
            "AND column_name='net_amount'")).scalar()
        if has_net:
            conn.execute(text("ALTER TABLE raw.orders RENAME COLUMN net_amount TO amount"))
    pristine = Path(settings.pipelines_dir) / "templates"
    for f in pristine.glob("*.sql"):
        shutil.copy(f, _models_dir() / f.name)
    return {"ok": True}


DEMO_SIGNALS = {
    "email": {"from": "ananya@acme.test", "to": "meera@acme.test", "subject": "Vendor payouts for Q3",
              "body": "Hi Meera, could you send me the Q3 vendor payouts by Friday? Thanks, Ananya"},
    "calendar": {"organizer": "priya@acme.test", "title": "Induction - Rahul Menon",
                 "start": "Monday 10:00", "attendees": ["rahul.menon@acme.test"]},
    "claude": {"user_email": "rohan@acme.test", "git_branch": "feature/dq-checks", "transcript": "\n".join([
        '{"type":"user","message":{"role":"user","content":"Add data quality checks to fct_revenue: row counts and '
        'nulls before the dashboard refresh"}}',
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Added not-null and '
        'row-count tests for fct_revenue; they run before the 11:00 refresh."},{"type":"tool_use","name":"Write",'
        '"input":{"file_path":"tests/fct_revenue_checks.sql"}}]}}'])},
}


DEMO_SIGNALS["session"] = {
    "tool": "cursor", "session_id": "cursor:demo-fct-revenue-weekly", "title": "Weekly revenue rollup for Finance",
    "user_email": "abhijit@acme.test", "git_branch": "feature/weekly-revenue", "repo": "acme-analytics",
    "files": ["models/fct_revenue_weekly.sql", "tests/fct_revenue_weekly.yml"],
    "transcript": "\n".join([
        "user: Build a weekly revenue rollup on top of fct_revenue for the Finance close dashboard",
        "assistant: Created models/fct_revenue_weekly.sql grouping fct_revenue by ISO week, plus not-null and "
        "uniqueness tests on week_start.",
        "user: The refunds column should come from the refunds table, can you join it?",
        "assistant: I can't read the finance.refunds table: permission denied for schema finance. The join is written "
        "but can't run until someone grants SELECT on finance.refunds to the analytics role.",
        "user: ok, I've asked Meera from Finance for access. Leave it there for now.",
        "assistant: Done for now. Next: run the model once access is granted and compare totals with Finance's sheet."])}


@router.post("/demo/signal/{kind}")
def demo_signal(kind: str, c: Ctx = Depends(admin_ctx)):
    """Send a realistic sample email / calendar invite / Claude session, as the hooks would."""
    if kind not in DEMO_SIGNALS:
        raise HTTPException(404, f"Use one of {', '.join(DEMO_SIGNALS)}.")
    payload = dict(DEMO_SIGNALS[kind])
    if kind == "email":
        import uuid
        payload["thread_id"] = f"demo-{uuid.uuid4().hex[:8]}"
    return {"kind": kind, "result": HANDLERS[kind](c.db, c.org_id, payload)}


@router.post("/demo/pipeline/run")
def run_pipeline(c: Ctx = Depends(admin_ctx)):
    result = pipeline.run_and_report("orders_daily")
    return {"run": result["execution_id"], "state": result["state"], "incident": result["incident"]}
