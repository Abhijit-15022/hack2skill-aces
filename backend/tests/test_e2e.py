"""End-to-end checks against a running API (docker compose up). Run: docker compose exec api pytest -q tests"""
import os
import uuid

import httpx
import pytest

API = os.environ.get("RELAY_API", "http://localhost:8000")
TOKEN = os.environ.get("RELAY_INGEST_TOKEN", "change-me-ingest-token")


def login(email: str) -> httpx.Client:
    r = httpx.post(f"{API}/auth/login", json={"email": email})
    r.raise_for_status()
    return httpx.Client(base_url=API, headers={"Authorization": f"Bearer {r.json()['token']}"}, timeout=60)


def ingest(kind: str, payload: dict) -> dict:
    r = httpx.post(f"{API}/ingest/{kind}?sync=true", json=payload, headers={"X-Relay-Token": TOKEN}, timeout=60)
    r.raise_for_status()
    return r.json()["result"]


@pytest.fixture(scope="module")
def kavya():
    return login("kavya@acme.test")


def test_other_company_is_invisible(kavya):
    acme_titles = [t["title"] for t in kavya.get("/tasks").json()["tasks"]]
    assert not any("Globex" in t for t in acme_titles)
    grace = login("grace@globex.test")
    globex = grace.get("/tasks").json()["tasks"]
    assert [t["title"] for t in globex] == ["Confidential: Globex acquisition checklist"]
    answer = kavya.post("/ask", json={"question": "Globex acquisition checklist Initech"}).json()
    assert answer["sources"] == [], "Acme must not get sources from Globex"
    assert "due diligence" not in answer["answer"].lower()


def test_claude_session_updates_the_matching_task(kavya):
    tx = "\n".join([
        '{"type":"user","message":{"role":"user","content":"Add data quality checks to fct_revenue: '
        'row counts and nulls before the dashboard refresh. api_key=sk-test-0123456789abcdefghij"}}',
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Added not-null '
        'and row-count checks for fct_revenue."},{"type":"tool_use","name":"Write","input":'
        '{"file_path":"tests/fct_revenue_checks.sql"}}]}}',
    ])
    out = ingest("claude", {"user_email": "rohan@acme.test", "session_id": str(uuid.uuid4()),
                            "git_branch": "feature/dq-checks", "transcript": tx})
    assert out["created"] is False and out["redactions"] >= 1
    task = kavya.get(f"/tasks/by-key/{out['task']}").json()
    assert "quality" in task["title"].lower()
    assert task["status"] in ("doing", "review")
    assert task["timeline"][-1]["source"] == "claude"


def test_email_request_becomes_task_and_reply_closes_it(kavya):
    thread = f"thread-{uuid.uuid4()}"
    out = ingest("email", {"from": "ananya@acme.test", "to": "meera@acme.test", "thread_id": thread,
                           "subject": "Vendor payouts for Q4", "body": "Hi Meera, can you send the Q4 vendor payouts by Friday?"})
    created = out["meera@acme.test"]
    assert created["request"] is True and created["found_previous"] is True
    task = kavya.get(f"/tasks/by-key/{created['task']}").json()
    assert task["type"] == "request" and task["status"] == "todo"
    assert "Last time" in task["description"] and ".xlsx" in task["description"]
    out = ingest("email", {"from": "meera@acme.test", "to": "ananya@acme.test", "thread_id": thread,
                           "subject": "Re: Vendor payouts for Q4", "body": "Attached.",
                           "attachments": [{"name": "Vendor_Payouts_Q4.xlsx"}]})
    assert out["closed_task"] == created["task"]
    assert kavya.get(f"/tasks/by-key/{created['task']}").json()["status"] == "done"


def test_calendar_invite_ticks_off_sop_step(kavya):
    priya = login("priya@acme.test")
    sop = next(s for s in priya.get("/sops").json()["sops"]
               if s["title"] == "New Joiner Onboarding" and s["status"] == "published")
    joiner = f"Zoya {uuid.uuid4().hex[:5].title()}"
    project = priya.post("/projects", json={"sop_id": sop["id"], "name": f"Onboard {joiner}", "subject": joiner}).json()
    assert len(project["steps"]) == len(sop["steps"]) and project["done"] == 0
    ingest("calendar", {"organizer": "priya@acme.test", "title": f"Induction - {joiner}",
                        "start": "2026-10-20T10:00:00+05:30", "attendees": ["new.joiner@acme.test"]})
    after = priya.get(f"/projects/{project['id']}").json()
    step = next(s for s in after["steps"] if s["title"] == "Book induction")
    assert step["status"] in ("done_out_of_order", "done", "needs_confirmation")
    if step["status"] == "needs_confirmation":
        after = priya.post(f"/step-progress/{step['step_progress_id']}/confirm", json={"yes": True}).json()
        step = next(s for s in after["steps"] if s["title"] == "Book induction")
    # Accounts (step 2) aren't done yet, so the SOP order wasn't followed.
    assert step["status"] == "done_out_of_order"
    assert after["drift"], "8 of 10 onboardings shipped the laptop early, so drift should be reported"


def test_sop_draft_from_text_and_publish():
    priya = login("priya@acme.test")
    team_id = next(t["id"] for t in priya.get("/me").json()["teams"])
    sop = priya.post("/sops/draft", data={"team_id": team_id, "text": (
        "Employee exit\n1. Collect resignation letter by email\n2. Schedule exit interview\n"
        "3. Revoke laptop and SSO access\n4. Upload final settlement document")}).json()
    assert len(sop["steps"]) == 4
    assert [s["evidence_type"] for s in sop["steps"]][:2] == ["email", "calendar"]
    published = priya.post(f"/sops/{sop['id']}/publish").json()
    assert published["status"] == "published"


def test_ask_cites_sources(kavya):
    out = kavya.post("/ask", json={"question": "Why did we change the orders model to net_amount?"}).json()
    assert out["sources"], out
    assert any(s["cite"] for s in out["segments"])


def test_feed_is_finite_and_ranked(kavya):
    feed = kavya.get("/feed").json()
    kinds = [c["kind"] for c in feed["cards"]]
    order = {"needs": 0, "incident": 1, "stuck": 2, "win": 3, "decision": 4, "trend": 5, "invisible": 6}
    assert kinds == sorted(kinds, key=order.get)
    assert feed["summary"]["total"] == len(feed["cards"])
    assert {s["name"] for s in feed["stories"]} >= {"Data Platform", "Finance"}
