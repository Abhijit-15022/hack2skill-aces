"""End-to-end checks for My Day, Focus Guard, Team Health, standups and meetings (needs the running stack)."""
import os
import time

import httpx
import pytest

from tests.test_e2e import API, login

GEMINI = httpx.get(f"{API}/health").json().get("gemini")


@pytest.fixture(scope="module")
def kavya():
    return login("kavya@acme.test")


@pytest.fixture(scope="module")
def meera():
    return login("meera@acme.test")


def test_my_day_picks_three_with_estimates_and_context(meera):
    day = meera.post("/me/day/plan").json()
    assert 1 <= len(day["items"]) <= 3
    first = day["items"][0]
    assert first["estimate_min"] >= 15 and first["estimate_basis"]
    assert first["why"]
    assert any(c["kind"] == "email" for i in day["items"] for c in i["context"]), "requests should carry their email"
    booked = [i for i in day["items"] if i["focus_start"]]
    assert day["focus_minutes"] == sum(i["estimate_min"] for i in booked)
    focus_events = [e for e in day["calendar"] if e["kind"] == "focus" and e["source"] == "relay"]
    assert len(focus_events) == len(booked)
    for ev in focus_events:
        meetings = [e for e in day["calendar"] if e["kind"] == "meeting"]
        assert all(not (ev["start"] < mt["end"] and mt["start"] < ev["end"]) for mt in meetings), "focus overlaps a meeting"


def test_focus_guard_holds_routine_pings_and_lets_failures_through(kavya, meera):
    out = kavya.post("/demo/focus/meera@acme.test").json()
    assert out["delivered"] >= 1 and out["held"] >= 3
    inbox = meera.get("/me/notifications").json()
    assert inbox["focus"]["active"]
    assert all(not n["urgent"] for n in inbox["held"])
    assert any(n["kind"] == "incident" and n["urgent"] for n in inbox["delivered"])
    released = meera.post("/me/focus/end").json()
    assert released["released"] >= 3 and not released["focus"]["active"] and not released["held"]


def test_team_health_flags_meera_and_applies_reassignment(kavya):
    report = kavya.get("/health/teams").json()
    finance = next(t for t in report["teams"] if t["team"]["name"] == "Finance")
    meera = next(p for p in finance["people"] if p["user"]["name"] == "Meera Rao")
    assert meera["level"] == "high"
    kinds = {s["kind"] for s in meera["signals"]}
    assert {"overload", "after_hours"} <= kinds
    assert meera["action"]["type"] == "reassign"
    data = next(t for t in report["teams"] if t["team"]["name"] == "Data Platform")
    rohan = next(p for p in data["people"] if p["user"]["name"] == "Rohan Iyer")
    assert any(s["kind"] == "review_stuck" for s in rohan["signals"])
    not_shared = next(p for p in data["people"] if p["user"]["name"] == "Rohan Iyer")
    assert not_shared["after_hours_nights"] is None, "after-hours data must stay private without consent"
    done = kavya.post("/health/actions", json={k: meera["action"][k] for k in ("type", "task_id", "to_user_id")}).json()
    assert "now with" in done["done"]


def test_written_standup_covers_every_member(kavya):
    report = kavya.get("/health/teams").json()
    team = next(t for t in report["teams"] if t["team"]["name"] == "Data Platform")
    st = kavya.get(f"/teams/{team['team']['id']}/standup?refresh=true").json()
    assert {p["name"] for p in st["people"]} == {p["user"]["name"] for p in team["people"]}
    assert all(p["yesterday"] and p["today"] for p in st["people"])


@pytest.mark.skipif(not GEMINI, reason="meeting capture needs Gemini")
def test_sample_meeting_becomes_decisions_and_tasks(kavya):
    mt = kavya.post("/demo/meeting/sample").json()
    for _ in range(45):
        time.sleep(3)
        mt = kavya.get(f"/meetings/{mt['id']}").json()
        if mt["status"] != "processing":
            break
    assert mt["status"] == "done", mt.get("error")
    r = mt["result"]
    assert r["decisions"], "the recording contains two explicit decisions"
    touched = [(c["title"], c.get("owner")) for c in r["created"]] + [(u["title"], None) for u in r["updated"]]
    assert any("schema" in title.lower() for title, _ in touched), touched
