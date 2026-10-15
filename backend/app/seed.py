"""Demo data matching the UI concept: Acme Corp (5 teams) and a second company, Globex, to show isolation."""
import logging
import shutil
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select, text

from . import models as m
from .config import get_settings
from .db import org_session, warehouse_engine
from .services import llm
from .services.core import add_log, create_task, feed, now

log = logging.getLogger(__name__)
settings = get_settings()


def seed_if_empty() -> bool:
    with org_session(None, bypass=True) as db:
        if db.scalar(select(m.Org.id).limit(1)):
            return False
    seed_warehouse()
    acme = _org("Acme Corp", "acme")
    _seed_acme(acme)
    globex = _org("Globex", "globex")
    _seed_globex(globex)
    log.info("Seeded demo data")
    return True


def _org(name: str, slug: str) -> int:
    with org_session(None, bypass=True) as db:
        org = m.Org(name=name, slug=slug)
        db.add(org)
        db.flush()
        return org.id


def seed_warehouse() -> None:
    with warehouse_engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS raw.orders (order_id int PRIMARY KEY, customer_id int, amount numeric(12,2), "
            "status text, created_at timestamptz)"))
        conn.execute(text(
            "INSERT INTO raw.orders SELECT g, 1000 + (g % 97), round((300 + random() * 4700)::numeric, 2), "
            "CASE WHEN g % 23 = 0 THEN 'refunded' ELSE 'paid' END, now() - (g % 30) * interval '1 day' "
            "FROM generate_series(1, 2400) g ON CONFLICT DO NOTHING"))
    models = Path(settings.pipelines_dir) / "models"
    models.mkdir(parents=True, exist_ok=True)
    for f in (Path(settings.pipelines_dir) / "templates").glob("*.sql"):
        shutil.copy(f, models / f.name)
    with warehouse_engine.begin() as conn:
        for name in ("stg_orders", "fct_revenue"):
            conn.execute(text((models / f"{name}.sql").read_text()))


def _seed_acme(org_id: int) -> None:
    t0 = now()
    with org_session(org_id) as db:
        def user(name, email, title, initials, color, admin=False, kind="human"):
            u = m.User(org_id=org_id, name=name, email=email, title=title, initials=initials, color=color,
                       is_org_admin=admin, kind=kind)
            db.add(u)
            db.flush()
            return u

        kavya = user("Kavya Rao", "kavya@acme.test", "Head of Operations", "KR", "#5E5CE6", admin=True)
        abhijit = user("Abhijit Singh", "abhijit@acme.test", "Data Engineer", "AS", "#0058B0")
        rohan = user("Rohan Iyer", "rohan@acme.test", "Data Platform lead", "RI", "#1D4ED8")
        meera = user("Meera Rao", "meera@acme.test", "Finance lead", "MR", "#B25E00")
        ananya = user("Ananya Gupta", "ananya@acme.test", "Sales Operations", "AG", "#8A4B00")
        priya = user("Priya Shah", "priya@acme.test", "People lead", "PS", "#1A7431")
        arjun = user("Arjun Rao", "arjun@acme.test", "Procurement lead", "AR", "#7E3BA0")
        sam = user("Sam Mathew", "sam@acme.test", "IT lead", "SM", "#3A3A3C")
        agent = user("Relay", "relay@acme.test", "On-call agent", "AI", "#1D1D1F", kind="agent")

        def team(name, short, color, handles, lead, members, autonomy="draft"):
            t = m.Team(org_id=org_id, name=name, short=short, color=color, handles=handles, lead_id=lead.id,
                       autonomy=autonomy)
            t.handles_embedding = llm.embed_one(f"{name}: {handles}")
            db.add(t)
            db.flush()
            for u in members:
                db.add(m.TeamMember(org_id=org_id, team_id=t.id, user_id=u.id,
                                    role="lead" if u.id == lead.id else "member"))
            return t

        data = team("Data Platform", "DP", "#0071E3", "Pipelines, dbt models, Kestra flows, warehouse tables and "
                    "dashboards.", rohan, [rohan, abhijit])
        fin = team("Finance", "FIN", "#B25E00", "Payouts, reconciliation, month-end close, invoices and accruals.",
                   meera, [meera, ananya], autonomy="suggest")
        hr = team("People (HR)", "HR", "#1A7431", "Hiring, onboarding, exits, leave and policies.", priya, [priya])
        proc = team("Procurement", "PRC", "#7E3BA0", "Vendor master data, purchase orders, KYC and vendor bank "
                    "details.", arjun, [arjun], autonomy="suggest")
        it = team("IT", "IT", "#3A3A3C", "Access, SSO, laptops, network and the ERP connection.", sam, [sam],
                  autonomy="act")
        db.add(m.TeamMember(org_id=org_id, team_id=data.id, user_id=agent.id, role="member"))
        db.flush()

        def res(name, kind, owner, business=None, meta=None):
            r = m.Resource(org_id=org_id, name=name, kind=kind, owner_team_id=owner.id,
                           business_team_id=business.id if business else None, meta=meta or {})
            db.add(r)
            db.flush()
            return r

        flow = res("orders_daily", "kestra_flow", data, fin, {"namespace": "data"})
        raw_orders = res("raw.orders", "table", data)
        stg = res("stg_orders", "model", data, fin, {"path": "models/stg_orders.sql"})
        fct = res("fct_revenue", "model", data, fin, {"path": "models/fct_revenue.sql"})
        dash = res("Revenue dashboard", "dashboard", data, fin)
        res("acme/analytics", "repository", data)
        res("ERP connection", "connection", it)
        res("Vendor master", "table", proc)
        res("Sales targets", "google_sheet", fin)
        res("finance@acme.test", "inbox", fin)
        for up, down in [(raw_orders, stg), (stg, fct), (fct, dash), (flow, stg)]:
            db.add(m.Lineage(org_id=org_id, upstream_id=up.id, downstream_id=down.id))

        def back(task, days=0, hours=0):
            task.created_at = t0 - timedelta(days=days, hours=hours)
            return task

        refactor = back(create_task(
            db, org_id, title="Refactor orders model", team=data, created_by=abhijit, assignee_id=abhijit.id,
            status="doing", description_by_ai=True,
            description="Switch the orders model from gross amount to net_amount so refunds stop being counted "
                        "twice in revenue. The raw.orders column was renamed; tests added. The Revenue dashboard "
                        "still needs the new column mapped."), days=2)
        add_log(db, org_id, source="manual", summary="created this task", task=refactor,
                author=abhijit).created_at = t0 - timedelta(days=2)
        lg = add_log(db, org_id, source="claude", task=refactor, author=abhijit, raw_ref="demo-session-1",
                     summary="Renamed raw.orders.amount to net_amount so refunds are no longer double counted in "
                             "revenue, and added tests for the orders model.",
                     meta={"files": ["warehouse/migrations/0042_orders_net_amount.sql", "models/stg_orders.sql"],
                           "decisions": ["Use net_amount: refunds were counted twice"]})
        lg.created_at = t0 - timedelta(hours=14)
        lg2 = add_log(db, org_id, source="git", task=refactor, author=abhijit, raw_ref="a1b2c3d",
                      summary="Commit a1b2c3d: rename amount to net_amount in raw.orders migration.")
        lg2.created_at = t0 - timedelta(hours=13, minutes=58)
        refactor.links = [{"kind": "commit", "label": "Commit a1b2c3d", "ref": "a1b2c3d"}]
        feed(db, org_id, kind="decision", team_id=data.id, task_id=refactor.id, subject_user_id=abhijit.id,
             title="Orders model now uses net_amount",
             body="Why: refunds were being counted twice in revenue. Captured from Abhijit's Claude session.",
             sources=["Claude session", "Commit a1b2c3d", refactor.key], score=0.4)

        back(create_task(db, org_id, title="Add data quality checks to fct_revenue", team=data, created_by=rohan,
                         assignee_id=rohan.id, description="Row-count and null checks before the dashboard "
                         "refresh."), days=5)

        # Finance: last quarter's request (replied, with the file) and this quarter's (open, stuck)
        old = back(create_task(db, org_id, title="Q2 vendor payouts for Ananya", team=fin, created_by=None,
                               assignee_id=meera.id, type="request", status="done", description_by_ai=True,
                               description="Ananya asked for the Q2 vendor payout sheet."), days=95)
        old.closed_at = t0 - timedelta(days=93)
        db.add(m.EmailRequest(org_id=org_id, task_id=old.id, thread_id="thread-q2-payouts", from_addr=ananya.email,
                              to_user_id=meera.id, subject="Vendor payouts for Q2",
                              body="Hi Meera, can you send me the vendor payouts for Q2 by Friday? Thanks, Ananya",
                              replied_at=t0 - timedelta(days=93),
                              attachments=[{"name": "Vendor_Payouts_Q2.xlsx"}]))
        q3 = back(create_task(
            db, org_id, title="Send Q3 vendor payouts to Ananya", team=fin, created_by=None, assignee_id=meera.id,
            type="request", description_by_ai=True, due_at=t0 + timedelta(days=2),
            description=f"{ananya.email} asked for the Q3 vendor payout sheet.\n\nLast time you replied to "
                        "“Vendor payouts for Q2” with Vendor_Payouts_Q2.xlsx. Relay can start from that.",
            links=[{"kind": "email", "label": "Email from Ananya", "ref": "thread-q3-payouts"},
                   {"kind": "file", "label": "Vendor_Payouts_Q2.xlsx", "ref": "Vendor_Payouts_Q2.xlsx"}]), days=3)
        db.add(m.EmailRequest(org_id=org_id, task_id=q3.id, thread_id="thread-q3-payouts", from_addr=ananya.email,
                              to_user_id=meera.id, subject="Vendor payouts for Q3",
                              body="Hi Meera, need the vendor payouts for Q3 please. Thanks!"))
        lq = add_log(db, org_id, source="email", task=q3, on_behalf_of=meera,
                     summary=f"Email from {ananya.email}: needs the Q3 vendor payouts")
        lq.created_at = t0 - timedelta(days=3)
        for i, subj in enumerate(["GST input credit report for September", "Reimbursement status for Rahul",
                                  "Updated cost centre list", "Bank statement for audit"]):
            t = back(create_task(db, org_id, title=subj, team=fin, created_by=None, assignee_id=meera.id,
                                 type="request", status="done" if i < 3 else "doing", description_by_ai=True,
                                 description=f"Request picked up from email: {subj.lower()}."), days=i + 1)
            if i < 3:
                t.closed_at = t0 - timedelta(hours=10 + i)
        back(create_task(db, org_id, title="Month-end close — accruals", team=fin, created_by=meera,
                         assignee_id=meera.id, status="doing", description="Two of five vendor confirmations "
                         "received by email; three pending."), days=4)

        back(create_task(db, org_id, title="Vendor KYC — Lumen Logistics", team=proc, created_by=arjun,
                         assignee_id=arjun.id, status="review", description="KYC documents and cancelled cheque "
                         "received. Waiting for Finance lead approval."), days=1)

        # SOPs
        def sop(team_, title, desc, version, steps, owner):
            s = m.Sop(org_id=org_id, team_id=team_.id, title=title, description=desc, status="published",
                      version=version, owner_id=owner.id, source_file=f"{title.replace(' ', '_')}.pdf")
            db.add(s)
            db.flush()
            out = []
            for i, (title_, owner_team, role, ev, hint, due, deps, appr) in enumerate(steps, start=1):
                st = m.SopStep(org_id=org_id, sop_id=s.id, seq=i, title=title_,
                               owner_team_id=owner_team.id if owner_team else None, owner_role=role,
                               evidence_type=ev, evidence_hint=hint, due_offset_days=due, depends_on=deps,
                               needs_approval=appr)
                db.add(st)
                out.append(st)
            db.flush()
            return s, out

        onboarding, ob_steps = sop(hr, "New Joiner Onboarding",
                                   "Everything between an accepted offer and a new joiner's first month.", 3, [
            ("Collect signed offer letter", hr, None, "email", "email with the signed offer letter attached", 0, [], False),
            ("Create email and SSO accounts", it, None, "task", "IT ticket for accounts closed", 3, [1], False),
            ("Ship laptop", it, None, "email", "courier delivery confirmation email", 2, [2], False),
            ("Book induction", hr, None, "calendar", "calendar invite for the induction or welcome session", 5, [2], False),
            ("30-day check-in", None, "hiring manager", "manual", "", 30, [4], False),
        ], priya)
        sop(fin, "Month-end Close", "Close the books by the 5th working day.", 5, [
            ("Collect vendor confirmations", fin, None, "email", "confirmation email from each vendor", 1, [], False),
            ("Book accruals", fin, None, "task", "accruals task closed", 3, [1], False),
            ("Reconcile bank accounts", fin, None, "file", "bank reconciliation file uploaded", 3, [], False),
            ("Finance lead sign-off", fin, None, "manual", "", 5, [2, 3], True),
        ], meera)
        sop(proc, "Vendor Onboarding", "From first contact to an active vendor in the ERP.", 2, [
            ("Collect KYC documents", proc, None, "email", "email with PAN, GST and cancelled cheque", 0, [], False),
            ("Verify bank details", proc, None, "manual", "", 2, [1], False),
            ("Finance approval", fin, None, "manual", "", 3, [2], True),
            ("Add vendor to ERP", it, None, "task", "ERP vendor-creation task closed", 4, [3], False),
        ], arjun)
        sop(data, "orders_daily runbook", "What to check when orders_daily fails.", 2, [
            ("Read the dbt error", data, None, "manual", "", 0, [], False),
            ("Check upstream schema changes", data, None, "manual", "", 0, [1], False),
            ("Patch the model and rerun", data, None, "task", "fix PR merged", 0, [2], True),
        ], rohan)

        # Current onboarding project + 9 finished ones (8 of them shipped the laptop before accounts: drift)
        project = m.Project(org_id=org_id, team_id=hr.id, name="Onboard Rahul Menon", subject="Rahul Menon",
                            sop_id=onboarding.id, sop_version=3, owner_id=priya.id, started_at=t0 - timedelta(days=2))
        db.add(project)
        db.flush()
        statuses = ["done", "done", "done_out_of_order", "pending", "pending"]
        evidence = ["Signed offer letter found in Priya's inbox", "IT closed Accounts & SSO",
                    "Courier delivery email matched (94%)", None, None]
        for st, status, ev in zip(ob_steps, statuses, evidence):
            team_ = db.get(m.Team, st.owner_team_id) if st.owner_team_id else None
            task = create_task(db, org_id, title=f"{st.title} — Rahul Menon", team=team_, created_by=priya,
                               assignee_id=None if team_ else kavya.id, type="sop_step",
                               status="done" if status.startswith("done") else "todo", project_id=project.id,
                               description=f"Step {st.seq} of New Joiner Onboarding (v3). Done when: "
                                           f"{st.evidence_hint or 'ticked off by hand'}.", description_by_ai=True,
                               due_at=project.started_at + timedelta(days=st.due_offset_days))
            log_ = add_log(db, org_id, source="sop" if ev else "manual", summary=ev or "created from the SOP", task=task)
            sp = m.StepProgress(org_id=org_id, project_id=project.id, sop_step_id=st.id, task_id=task.id,
                                status=status, matched_log_id=log_.id if ev else None,
                                confidence=0.94 if ev else None, due_at=task.due_at,
                                done_at=t0 - timedelta(days=1) if status.startswith("done") else None)
            if status.startswith("done"):
                task.closed_at = t0 - timedelta(hours=20)
            db.add(sp)
        for k in range(9):
            past = m.Project(org_id=org_id, team_id=hr.id, name=f"Onboard joiner #{k + 1}", subject=f"Joiner {k + 1}",
                             sop_id=onboarding.id, sop_version=3, owner_id=priya.id, status="done",
                             started_at=t0 - timedelta(days=30 + k * 12))
            db.add(past)
            db.flush()
            for st in ob_steps:
                early = st.seq == 3 and k < 7
                db.add(m.StepProgress(org_id=org_id, project_id=past.id, sop_step_id=st.id,
                                      status="done_out_of_order" if early else "done",
                                      done_at=past.started_at + timedelta(days=st.due_offset_days)))

        # A past incident with the same root cause, so the agent's memory step has something to find.
        inc = m.Incident(org_id=org_id, key="INC-031", namespace="data", flow_id="orders_daily",
                         execution_id="past-031", status="resolved", category="technical",
                         cause_kind="upstream_column_renamed", root_cause_title="An upstream column was renamed",
                         root_cause="raw.orders.customer was renamed to customer_id; stg_orders still read the old "
                                    "name. Fixed by mapping the new column.",
                         confidence=0.9, detected_at=t0 - timedelta(days=60), resolved_at=t0 - timedelta(days=60))
        inc.embedding = llm.embed_one(f"orders_daily column does not exist {inc.root_cause}")
        db.add(inc)
        db.flush()


def _seed_globex(org_id: int) -> None:
    with org_session(org_id) as db:
        u = m.User(org_id=org_id, name="Grace Hopper", email="grace@globex.test", title="COO", initials="GH",
                   color="#7E3BA0", is_org_admin=True)
        agent = m.User(org_id=org_id, name="Relay", email="relay@globex.test", initials="AI", color="#1D1D1F",
                       kind="agent")
        db.add_all([u, agent])
        db.flush()
        t = m.Team(org_id=org_id, name="Strategy", short="ST", color="#7E3BA0", handles="Mergers and planning.",
                   lead_id=u.id)
        t.handles_embedding = llm.embed_one("Strategy: mergers and planning")
        db.add(t)
        db.flush()
        db.add(m.TeamMember(org_id=org_id, team_id=t.id, user_id=u.id, role="lead"))
        create_task(db, org_id, title="Confidential: Globex acquisition checklist", team=t, created_by=u,
                    description="Due diligence for the acquisition of Initech. Only Globex can see this.")
