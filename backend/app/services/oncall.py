"""On-call agent: a structured investigation (fixed, auditable steps) with Gemini doing the reasoning."""
import difflib
import logging
import re
import time
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from . import focus, llm, runner
from .core import add_log, agent_user, audit, create_task, enqueue, feed, now, set_status

log = logging.getLogger(__name__)
settings = get_settings()

MISSING_COLUMN = re.compile(r'column "?([\w.]+)"? does not exist', re.I)
MISSING_TABLE = re.compile(r'relation "?([\w.]+)"? does not exist', re.I)


# ---------------------------------------------------------------- opening an incident

def open_incident(db: Session, org_id: int, *, namespace: str, flow_id: str, execution_id: str) -> m.Incident:
    existing = db.scalar(select(m.Incident).where(m.Incident.execution_id == execution_id))
    if existing:
        return existing
    agent = agent_user(db, org_id)
    resource = db.scalar(select(m.Resource).where(m.Resource.kind == "pipeline", m.Resource.name == flow_id))
    team = db.get(m.Team, resource.owner_team_id) if resource and resource.owner_team_id else None
    numbers = [int(k.split("-")[1]) for k in db.scalars(select(m.Incident.key)) if k.split("-")[-1].isdigit()]
    incident = m.Incident(org_id=org_id, key=f"INC-{max(numbers, default=0) + 1:03d}", resource_id=resource.id if resource else None,
                          namespace=namespace, flow_id=flow_id, execution_id=execution_id, status="investigating")
    db.add(incident)
    db.flush()
    task = create_task(db, org_id, title=f"{flow_id} failed", team=team, created_by=agent, assignee_id=agent.id,
                       type="incident", status="doing", priority="high", description_by_ai=True,
                       description=f"The {namespace}.{flow_id} pipeline failed (run {execution_id}). "
                                   "The on-call agent is investigating.",
                       links=[{"kind": "run", "label": f"Run {execution_id[:8]}", "ref": execution_id}])
    task.key = incident.key
    incident.task_id = task.id
    add_log(db, org_id, source="oncall", summary="opened this from a pipeline failure", task=task, author=agent)
    audit(db, org_id, actor=agent, action=f"Opened {incident.key}", target_type="incident", target_id=incident.id,
          reason=f"The {namespace}.{flow_id} pipeline failed", approved_by="Automatic")
    enqueue(db, org_id, "investigate", {"incident_id": incident.id})
    if team and team.lead_id:
        focus.notify(db, team.lead_id, "incident", f"{flow_id} failed", "The on-call agent is investigating.", task.id)
    return incident


# ---------------------------------------------------------------- investigation steps

def _step(incident: m.Incident, title: str, detail: str, started: float, code: str | None = None,
          found: bool = False) -> None:
    incident.steps = (incident.steps or []) + [{
        "title": title, "detail": detail, "code": code, "found": found,
        "t": round(time.monotonic() - started, 1),
    }]


def _runner_errors(db: Session, execution_id: str) -> list[m.RunnerRun]:
    return db.scalars(select(m.RunnerRun).where(
        or_(m.RunnerRun.execution_id == execution_id, m.RunnerRun.created_at >= now() - timedelta(minutes=30)),
        m.RunnerRun.status == "failed").order_by(m.RunnerRun.id.desc()).limit(3)).all()


def _neighbours(db: Session, resource_id: int, direction: str) -> list[m.Resource]:
    col_from, col_to = (m.Lineage.downstream_id, m.Lineage.upstream_id) if direction == "up" else (
        m.Lineage.upstream_id, m.Lineage.downstream_id)
    ids = db.scalars(select(col_to).where(col_from == resource_id)).all()
    return db.scalars(select(m.Resource).where(m.Resource.id.in_(ids or [-1]))).all()


def _walk(db: Session, start: m.Resource, direction: str) -> list[m.Resource]:
    seen, queue, out = {start.id}, [start], []
    while queue:
        node = queue.pop(0)
        for nb in _neighbours(db, node.id, direction):
            if nb.id not in seen:
                seen.add(nb.id)
                out.append(nb)
                queue.append(nb)
    return out


def investigate(db: Session, incident_id: int) -> m.Incident:
    incident = db.get(m.Incident, incident_id)
    org_id = incident.org_id
    agent = agent_user(db, org_id)
    task = db.get(m.Task, incident.task_id)
    started = time.monotonic()
    incident.steps = []

    # 1. logs
    errors = _runner_errors(db, incident.execution_id)
    failing = errors[0] if errors else None
    error_msg = (failing.error if failing else "") or "No error message found."
    model_name = failing.model if failing else None
    first_line = error_msg.strip().splitlines()[0][:300]
    _step(incident, "Read the failure logs",
          f"{'Model ' + model_name + ' failed' if model_name else 'The run failed'}.", started, code=first_line)

    # 2. lineage
    model_res = db.scalar(select(m.Resource).where(m.Resource.name == model_name)) if model_name else None
    flow_res = db.get(m.Resource, incident.resource_id) if incident.resource_id else None
    anchor = model_res or flow_res
    upstream = _walk(db, anchor, "up") if anchor else []
    downstream = _walk(db, anchor, "down") if anchor else []
    impacted_owners = {db.get(m.Team, r.business_team_id or r.owner_team_id).name
                       for r in downstream if (r.business_team_id or r.owner_team_id)}
    incident.impact = [{"name": r.name, "kind": r.kind, "state": "stale" if r.kind == "dashboard" else "skipped"}
                       for r in downstream]
    _step(incident, "Traced what depends on it",
          f"{len(upstream)} upstream, {len(downstream)} downstream"
          + (f"; affects {', '.join(sorted(impacted_owners))}." if impacted_owners else "."), started)

    # 3. data checks
    evidence: dict = {"error": error_msg[:1500], "model": model_name}
    col = MISSING_COLUMN.search(error_msg)
    rename_from = rename_to = None
    if col:
        missing = col.group(1).split(".")[-1]
        for up in upstream:
            if up.kind != "table":
                continue
            schema, _, table = up.name.partition(".")
            cols = runner.table_columns(schema, table)
            close = difflib.get_close_matches(missing, cols, n=1, cutoff=0.3) or [c for c in cols if missing in c]
            if close:
                rename_from, rename_to = missing, close[0]
                evidence.update({"table": up.name, "columns": cols, "candidate": close[0]})
                _step(incident, "Checked the data",
                      f"{up.name} has no column {missing} but has {close[0]}. Row count {runner.row_count(schema, table)}.",
                      started, code=f"{up.name}: {missing} → {close[0]}")
                break
        else:
            _step(incident, "Checked the data", f"No upstream table has a column like {missing}.", started)
    else:
        _step(incident, "Checked the data", "The error is not about a missing column; checked row counts.", started)

    # 4. recent work that touched these objects
    terms = [t for t in [rename_from, rename_to, model_name] + [u.name.split(".")[-1] for u in upstream] if t]
    recent = []
    if terms:
        cond = or_(*[m.WorkLog.summary.ilike(f"%{t}%") for t in terms])
        recent = db.scalars(select(m.WorkLog).where(cond, m.WorkLog.created_at >= now() - timedelta(days=7),
                                                    m.WorkLog.source.in_(["claude", "git", "manual"]))
                            .order_by(m.WorkLog.created_at.desc()).limit(3)).all()
    culprit_task = db.get(m.Task, recent[0].task_id) if recent and recent[0].task_id else None
    if recent:
        who = db.get(m.User, recent[0].author_id) if recent[0].author_id else None
        names = {"claude": "Claude session", "git": "commit", "manual": "update"}
        how = " and ".join(dict.fromkeys(names.get(r.source, r.source) for r in recent
                                         if r.task_id == recent[0].task_id))
        _step(incident, "Checked recent work",
              f"{culprit_task.key + ' ' if culprit_task else ''}“{culprit_task.title if culprit_task else recent[0].summary[:80]}”"
              f" changed this {recent[0].created_at:%d %b}"
              + (f", captured from {who.name.split()[0]}'s {how}." if who else "."),
              started, found=True)
        evidence["recent_work"] = [r.summary for r in recent]
    else:
        _step(incident, "Checked recent work", "No logged work touched these tables in the last 7 days.", started)

    # 5. memory of past incidents
    query = f"{incident.flow_id} {first_line}"
    vec = llm.embed_one(query, "RETRIEVAL_QUERY")
    past = [i for i in db.scalars(select(m.Incident).where(m.Incident.id != incident.id,
                                                          m.Incident.root_cause.isnot(None))).all()]

    def similarity(p: m.Incident) -> float:
        score = llm.cosine(vec, p.embedding)
        if p.flow_id == incident.flow_id:
            score += 0.15
        if col and "column" in (p.cause_kind or ""):
            score += 0.3
        return score

    past.sort(key=similarity, reverse=True)
    similar = [p for p in past[:3] if similarity(p) >= (0.6 if llm.enabled() else 0.4)]
    if similar:
        _step(incident, "Compared with past failures",
              f"Same pattern as {similar[0].key}: {similar[0].root_cause_title}.", started)
        evidence["past"] = [f"{p.key}: {p.root_cause}" for p in similar]
    else:
        _step(incident, "Compared with past failures", "No similar failure on record.", started)

    # 6. diagnosis + fix
    sql = runner.model_path(model_name).read_text() if model_name else ""
    diagnosis = _diagnose(incident, evidence, sql, rename_from, rename_to, culprit_task)
    incident.root_cause_title = diagnosis["title"]
    incident.root_cause = diagnosis["explanation"]
    incident.confidence = diagnosis["confidence"]
    incident.category = diagnosis["category"]
    incident.cause_kind = diagnosis["cause_kind"]
    incident.embedding = llm.embed_one(f"{incident.flow_id} {first_line} {incident.root_cause}")

    fix = None
    if model_name and diagnosis.get("new_sql") and diagnosis["new_sql"].strip() != sql.strip():
        fix = _propose_fix(incident, model_name, sql, diagnosis["new_sql"], diagnosis["title"], culprit_task)
        incident.fix = fix
        _step(incident, "Drafted the fix", fix["summary"], started)
    else:
        _step(incident, "Could not draft a fix", "Needs a person: the cause is not something a code change fixes.",
              started)

    _hand_off(db, incident, task, agent, fix, culprit_task, impacted_owners, downstream)
    return incident


def _diagnose(incident, evidence, sql, rename_from, rename_to, culprit_task) -> dict:
    out = llm.generate_json(f"""You are the on-call data engineer. A pipeline failed. Using ONLY the evidence,
explain the root cause and propose the smallest SQL change that fixes the failing model.
Return JSON {{"title": str (max 10 words), "explanation": str (2 sentences, plain English, name the task/commit if
the evidence shows one), "confidence": number 0-1, "category": "technical"|"business",
"cause_kind": short snake_case label, "new_sql": str (full corrected SQL of the model, or "" if no code fix)}}.
Evidence: {evidence}
Current SQL of the model:
---
{sql}
---""", tier="smart")
    if out and out.get("title"):
        out.setdefault("category", "technical")
        out.setdefault("cause_kind", "unknown")
        out["confidence"] = float(out.get("confidence", 0.5))
        return out
    if rename_from and rename_to:
        who = f" in {culprit_task.key}" if culprit_task else ""
        new_sql = re.sub(rf"\b{re.escape(rename_from)}\b", rename_to, sql)
        return {"title": "An upstream column was renamed",
                "explanation": f"{evidence.get('table')}.{rename_from} became {rename_to}{who}. "
                               f"{evidence.get('model')} still reads the old name.",
                "confidence": 0.9 if culprit_task else 0.75, "category": "technical",
                "cause_kind": "upstream_column_renamed", "new_sql": new_sql}
    return {"title": "Pipeline failed", "explanation": evidence.get("error", "")[:300], "confidence": 0.3,
            "category": "technical", "cause_kind": "unknown", "new_sql": ""}


def _propose_fix(incident, model_name, old_sql, new_sql, title, culprit_task) -> dict:
    path = f"models/{model_name}.sql"
    diff = list(difflib.unified_diff(old_sql.splitlines(), new_sql.splitlines(), f"a/{path}", f"b/{path}", lineterm=""))
    added = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))
    fix = {"path": path, "model": model_name, "old_sql": old_sql, "new_sql": new_sql, "diff": "\n".join(diff),
           "added": added, "removed": removed, "pr_url": None, "pr_number": None,
           "summary": f"Prepared a change to {path} (+{added} −{removed})."}
    if settings.github_token and settings.github_repo:
        try:
            number, url = _open_github_pr(incident, path, new_sql, title, culprit_task)
            fix.update(pr_number=number, pr_url=url, summary=f"Opened PR #{number} changing {path}.")
        except httpx.HTTPError as exc:
            log.error("GitHub PR failed, keeping local fix: %s", exc)
    return fix


def _open_github_pr(incident, path, new_sql, title, culprit_task) -> tuple[int, str]:
    import base64
    repo = settings.github_repo
    h = {"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json"}
    with httpx.Client(base_url="https://api.github.com", headers=h, timeout=20) as gh:
        base = gh.get(f"/repos/{repo}").json()["default_branch"]
        sha = gh.get(f"/repos/{repo}/git/ref/heads/{base}").json()["object"]["sha"]
        branch = f"relay/{incident.key.lower()}"
        gh.post(f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha})
        gh_path = f"pipelines/{path}"
        current = gh.get(f"/repos/{repo}/contents/{gh_path}", params={"ref": branch})
        body = {"message": f"fix({incident.flow_id}): {title}", "branch": branch,
                "content": base64.b64encode(new_sql.encode()).decode()}
        if current.status_code == 200:
            body["sha"] = current.json()["sha"]
        gh.put(f"/repos/{repo}/contents/{gh_path}", json=body).raise_for_status()
        pr = gh.post(f"/repos/{repo}/pulls", json={
            "title": f"fix({incident.flow_id}): {title}", "head": branch, "base": base,
            "body": f"Raised by Relay's on-call agent for {incident.key}.\n\n{incident.root_cause}"
                    + (f"\n\nRelated: {culprit_task.key}" if culprit_task else "")})
        pr.raise_for_status()
        return pr.json()["number"], pr.json()["html_url"]


def _hand_off(db, incident, task, agent, fix, culprit_task, impacted_owners, downstream) -> None:
    org_id = incident.org_id
    resource = db.get(m.Resource, incident.resource_id) if incident.resource_id else None
    owner_team = db.get(m.Team, resource.owner_team_id) if resource and resource.owner_team_id else None
    business = db.get(m.Team, resource.business_team_id) if resource and resource.business_team_id else None
    links = list(task.links or [])
    if culprit_task:
        links.append({"kind": "task", "label": culprit_task.key, "ref": culprit_task.key})
    fix_label = f"PR #{fix['pr_number']}" if fix and fix.get("pr_number") else "Proposed fix"
    task.description = (f"{incident.root_cause_title}. {incident.root_cause} "
                        + (f"{fix_label} is ready for review." if fix else "Needs a person to decide the fix."))
    task.links = links

    if fix:
        incident.status = "fix_proposed"
        reviewer = owner_team.lead_id if owner_team else None
        review = create_task(
            db, org_id, title=f"Review & merge {fix_label} ({incident.flow_id})", team=owner_team, created_by=agent,
            assignee_id=reviewer, type="review", status="review", parent_id=task.id, priority="high",
            description_by_ai=True,
            description=(f"{fix['summary']} {incident.root_cause} Low risk: one model, "
                         f"{fix['added'] + fix['removed']} changed lines. Once approved, Relay applies it, "
                         f"reruns {incident.flow_id} and closes {incident.key} if it passes."),
            due_at=now() + timedelta(hours=4),
            links=[{"kind": "incident", "label": incident.key, "ref": incident.key}]
            + ([{"kind": "pr", "label": fix_label, "url": fix.get("pr_url")}] if fix.get("pr_url") else []),
        )
        incident.review_task_id = review.id
        add_log(db, org_id, source="oncall", task=task, author=agent,
                summary=f"raised {fix_label} and created review task {review.key}")
        reviewer_user = db.get(m.User, reviewer) if reviewer else None
        focus.notify(db, reviewer, "review", f"Review {fix_label} for {incident.flow_id}",
                     f"{incident.root_cause_title}. The dashboard refreshes once it's merged.", review.id)
        feed(db, org_id, kind="needs", team_id=owner_team.id if owner_team else None, task_id=review.id,
             incident_id=incident.id, subject_user_id=reviewer,
             title=f"{fix_label} is waiting on {reviewer_user.name.split()[0] if reviewer_user else 'review'}",
             body=f"Fix for {incident.flow_id}. {incident.root_cause}",
             sources=[fix_label, incident.key] + ([culprit_task.key] if culprit_task else []),
             actions=[{"type": "nudge", "user_id": reviewer}, {"type": "open_task", "task_id": review.id}],
             score=0.95, dedupe_key=f"review-{incident.id}")
    else:
        incident.status = "needs_human"
        set_status(db, task, "todo", agent, "needs a person", source="oncall")
        task.assignee_id = owner_team.lead_id if owner_team else None

    took = incident.steps[-1]["t"] if incident.steps else 0
    feed(db, org_id, kind="incident", team_id=owner_team.id if owner_team else None, incident_id=incident.id,
         task_id=task.id, title=f"{incident.flow_id} failed — {'cause found, fix raised' if fix else 'needs a person'}",
         body=f"Investigated in {'under a second' if took < 1 else f'{took:.0f} s'}: {incident.root_cause_title.lower()}."
              + (f" {', '.join(sorted(impacted_owners))} told the dashboard is delayed." if impacted_owners else ""),
         sources=[f"Pipeline · {incident.namespace}.{incident.flow_id}", incident.key],
         actions=[{"type": "open_incident", "incident_id": incident.id}], score=0.9,
         dedupe_key=f"incident-{incident.id}")
    if business and business.id != (owner_team.id if owner_team else None):
        dash = next((d.name for d in downstream if d.kind == "dashboard"), "downstream reports")
        feed(db, org_id, kind="incident", team_id=business.id, incident_id=incident.id,
             title=f"{dash} will be late", body=f"{incident.flow_id} failed at {incident.detected_at:%H:%M}. "
                                                 f"{owner_team.name if owner_team else 'The data team'} has a fix in review.",
             sources=[incident.key], score=0.6, dedupe_key=f"fyi-{incident.id}")
        audit(db, org_id, actor=agent, action=f"Told {business.name} that {dash} is late",
              target_type="incident", target_id=incident.id, reason=f"Business owner of {incident.flow_id}",
              approved_by="Automatic (FYI only)")
    audit(db, org_id, actor=agent, action=f"Investigated {incident.key}" + (f" and raised {fix_label}" if fix else ""),
          target_type="incident", target_id=incident.id, reason=incident.root_cause_title,
          approved_by=f"Waiting for {owner_team.name if owner_team else 'owner'}" if fix else "—")
    _maybe_permanent_fix(db, incident, agent, owner_team)


def _maybe_permanent_fix(db, incident, agent, owner_team) -> None:
    if not incident.cause_kind or incident.cause_kind == "unknown":
        return
    same = db.scalars(select(m.Incident).where(m.Incident.flow_id == incident.flow_id,
                                               m.Incident.cause_kind == incident.cause_kind)).all()
    title = f"Permanent fix: stop {incident.cause_kind.replace('_', ' ')} breaking {incident.flow_id}"
    if len(same) >= 3 and not db.scalar(select(m.Task).where(m.Task.title == title)):
        keys = ", ".join(i.key for i in same)
        create_task(db, incident.org_id, title=title, team=owner_team, created_by=agent, type="chore",
                    description=f"The same cause has broken {incident.flow_id} {len(same)} times ({keys}). "
                                "Add a check that catches it before the pipeline runs.", description_by_ai=True)


# ---------------------------------------------------------------- approval and verification

def approve(db: Session, incident: m.Incident, approver: m.User) -> m.Incident:
    if incident.status != "fix_proposed":
        raise ValueError(f"{incident.key} has no fix waiting for approval.")
    fix = incident.fix or {}
    if fix.get("pr_number") and settings.github_token:
        h = {"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json"}
        httpx.put(f"https://api.github.com/repos/{settings.github_repo}/pulls/{fix['pr_number']}/merge",
                  headers=h, json={"merge_method": "squash"}, timeout=20).raise_for_status()
    Path(runner.model_path(fix["model"])).write_text(fix["new_sql"])
    review = db.get(m.Task, incident.review_task_id) if incident.review_task_id else None
    if review:
        set_status(db, review, "done", approver, "approved and merged")
    incident.status = "verifying"
    db.execute(delete(m.FeedItem).where(m.FeedItem.dedupe_key == f"review-{incident.id}"))
    audit(db, incident.org_id, actor=approver, action=f"Approved the fix for {incident.key}",
          target_type="incident", target_id=incident.id, reason=incident.root_cause_title or "",
          approved_by=approver.name)
    enqueue(db, incident.org_id, "rerun", {"incident_id": incident.id})
    return incident


def rerun(db: Session, incident: m.Incident) -> str | None:
    from . import pipeline

    result = pipeline.run(incident.flow_id)
    task = db.get(m.Task, incident.task_id)
    add_log(db, incident.org_id, source="oncall", task=task, author=agent_user(db, incident.org_id),
            summary=f"reran {incident.flow_id}: " + ("passed" if result["state"] == "SUCCESS"
                                                      else f"failed again on {result['failed_model']}"))
    if result["state"] == "SUCCESS":
        on_success(db, incident.namespace, incident.flow_id)
    else:
        incident.status = "needs_human"
    return result["execution_id"]


def on_success(db: Session, namespace: str, flow_id: str) -> list[m.Incident]:
    open_ones = db.scalars(select(m.Incident).where(m.Incident.namespace == namespace, m.Incident.flow_id == flow_id,
                                                    m.Incident.status.in_(["verifying", "fix_proposed", "needs_human"]))).all()
    for inc in open_ones:
        if inc.status != "verifying":
            continue
        inc.status, inc.resolved_at = "resolved", now()
        agent = agent_user(db, inc.org_id)
        task = db.get(m.Task, inc.task_id)
        if task:
            set_status(db, task, "done", agent, f"{flow_id} passed after the fix", source="oncall")
        mins = max((inc.resolved_at - inc.detected_at).total_seconds() / 60, 1)
        feed(db, inc.org_id, kind="win", incident_id=inc.id, task_id=inc.task_id,
             team_id=task.team_id if task else None, title=f"{flow_id} is fixed and green again",
             body=f"{inc.root_cause_title}. Fixed and verified {mins:.0f} min after it was detected.",
             sources=[inc.key, f"Pipeline \u00b7 {inc.namespace}.{flow_id}"], score=0.5,
             actions=[{"type": "open_incident", "incident_id": inc.id}], dedupe_key=f"incident-{inc.id}")
        fyi = db.scalar(select(m.FeedItem).where(m.FeedItem.dedupe_key == f"fyi-{inc.id}"))
        if fyi:
            fyi.kind, fyi.title = "win", fyi.title.replace("will be late", "is up to date again")
            fyi.body = f"{flow_id} was fixed and reran successfully."
        audit(db, inc.org_id, actor=agent, action=f"Closed {inc.key}", target_type="incident", target_id=inc.id,
              reason=f"{flow_id} reran successfully", approved_by="Automatic")
    return open_ones
