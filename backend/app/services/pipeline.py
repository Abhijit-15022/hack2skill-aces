"""Built-in pipeline runner: runs a flow's SQL models in order and reports the result to the on-call agent.

Any external orchestrator (Kestra, Airflow, Dagster) can do the same job by calling the runner endpoint and
POST /webhooks/orchestrator; see KESTRA.md.
"""
import logging
import uuid

from sqlalchemy import select

from .. import models as m
from ..db import org_session
from . import oncall, runner

log = logging.getLogger(__name__)

PIPELINES = {
    "orders_daily": {"namespace": "data", "models": ["stg_orders", "fct_revenue"], "daily_at": (6, 0)},
}


def run(name: str) -> dict:
    """Run every model of the pipeline, stopping at the first failure."""
    spec = PIPELINES[name]
    execution_id = uuid.uuid4().hex[:22]
    for model in spec["models"]:
        ok, error = runner.run_model(model, execution_id)
        if not ok:
            log.warning("Pipeline %s failed on %s: %s", name, model, error)
            return {"execution_id": execution_id, "state": "FAILED", "failed_model": model, "error": error}
    return {"execution_id": execution_id, "state": "SUCCESS"}


def report(name: str, result: dict) -> str | None:
    """Tell Relay about a finished run: failures open an incident, successes verify pending fixes."""
    namespace = PIPELINES[name]["namespace"] if name in PIPELINES else "data"
    with org_session(None, bypass=True) as db:
        org_id = db.scalar(select(m.Resource.org_id).where(m.Resource.kind == "pipeline", m.Resource.name == name))
    if not org_id:
        return None
    with org_session(org_id) as db:
        if result["state"] == "SUCCESS":
            oncall.on_success(db, namespace, name)
            return None
        incident = oncall.open_incident(db, org_id, namespace=namespace, flow_id=name,
                                        execution_id=result["execution_id"])
        return incident.key


def run_and_report(name: str) -> dict:
    result = run(name)
    result["incident"] = report(name, result)
    return result
