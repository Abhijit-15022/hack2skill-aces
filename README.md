# Relay: an AI chief of staff for every team

Google Cloud AI Builder Cup · theme: **Future of Work & Enterprise Productivity**

Relay removes the busywork around work. Tasks fill themselves in from where work already happens (Claude Code
sessions, git commits, email, calendar, meeting recordings). Every morning it plans each person's day, then guards
their focus. Managers see who needs help before anyone asks, and read a written standup instead of holding one.
Tech teams also get an on-call agent that diagnoses pipeline failures and raises a fix for a person to approve.

| Productivity blocker (from Atlassian, Asian Efficiency, ProjectManager) | Relay feature |
|---|---|
| Too many tasks, no idea where to start; bad estimates; back-to-back calendars | **My Day**: top 3 by urgency and importance, estimates from similar finished tasks, focus time booked in free gaps, a context pack per task |
| Notifications and interruptions | **Focus Guard**: non-urgent pings wait until the focus block ends; Gemini decides what's urgent enough to come through |
| Meetings eat focus time | **Written standup** from logged work; **meeting recordings** become decisions, tasks and hand-overs |
| Overload, burnout, uneven workload, late feedback | **Team Health**: overload, after-hours work (only with consent), stuck reviews, missing early feedback, each with one suggested action |
| Work nobody updates | **relay-agent** reads recent sessions from **Claude Code, Cursor, Codex and Antigravity**; Gemini updates the task with what was done, **blockers** (and who it's waiting on) and the **expected outcome**, asking the person once when the goal isn't clear. Plus git, email and calendar |
| Managers can't see progress or blockers | Per-person **AI summary** on Team: working towards, how far along, what's blocking; one-tap "ask X to unblock" |
| Searching emails and drives | **Ask** (⌘K) with citations |
| Tool and pipeline failures | **On-call agent**: failure → investigation → fix → review task → rerun → closed |
| Repeatable processes | **SOP builder**; projects whose steps tick themselves off from evidence; outdated-SOP detection |

## Run it

```bash
cp .env.example .env          # add GEMINI_API_KEY when you have it (works offline without)
docker compose up -d          # postgres, api, worker, web
open http://localhost:3100    # sign in as Kavya Rao (admin) or Meera Rao (busy Finance lead)
```

| Service | URL |
|---|---|
| Web app | http://localhost:3100 |
| API + interactive docs | http://localhost:8000/docs |

Fresh demo data: `./scripts/reset-demo.sh` (wipes everything, reseeds).
Tests: `docker compose exec api pytest -q tests` (end-to-end, against the running stack; reset afterwards).

### Gemini
Put `GEMINI_API_KEY` in `.env` (or set `GOOGLE_CLOUD_PROJECT` to use Vertex AI with the VM's service account), then
`docker compose up -d --force-recreate api worker`. Models are set in `.env`:

| Use | Model | Thinking |
|---|---|---|
| Diagnosis, SOP drafting | `gemini-3.8-flash` | high |
| Meeting recordings (audio) | `gemini-3.8-flash` | medium (about 25 s per minute-long recording) |
| Day plans, summaries, standups, Ask | `gemini-3.8-flash` | low (2–6 s) |
| "Is this urgent?" checks in Focus Guard | `gemini-3.5-flash-lite` | none |
| Search embeddings | `gemini-embedding-001` (768 dimensions, batched) | — |

`gemini-3.1-pro-preview` (what `gemini-pro-latest` points to) was tested and took over 3 minutes per call, so it
isn't used. Every AI step also has an offline fallback, so the app runs without a key (meeting capture excepted).

## Demo script (≈4 min)

Admin → **Demo** has a button for each step.

1. **Today (as Meera Rao):** her top 3 with reasons, estimates ("median of 5 similar tasks"), focus booked
   between her meetings, and a "What you need" pack per task.
2. **Focus Guard:** press *Meera starts focusing, 5 pings arrive*. Four wait; only the pipeline failure gets through.
3. **Team (as Kavya):** Meera is overloaded with late nights; Rohan's review has waited 30 h; Abhijit's refactor has
   had no feedback. One tap applies each suggestion. Switch to *Written standup*: no daily meeting needed.
4. **AI sessions:** press *Abhijit's Cursor session hits a blocker*. Relay creates "Build weekly revenue rollup",
   marks it **Blocked** (waiting on Meera for finance.refunds access), tells Rohan, and on Abhijit's Today asks
   "What should this achieve when it's done?" with a suggested answer. Team shows the AI summary and *Ask Meera to unblock*.
5. **Meetings:** process the 64-second sample. Gemini finds the decisions (with timestamps), creates "schema change
   check" for Abhijit due Friday, and hands the GST request from Meera to Ananya.
6. **Break the pipeline:** the on-call agent reads the error, traces lineage, finds the change in DP-1 (from
   Abhijit's Claude session), recalls INC-031 and drafts a one-line fix with a review task for Rohan. Approve →
   rerun → green.
7. **⌘K Ask** "Why did we change the orders model?" → answer with numbered sources.
8. Sign in as **Grace (Globex)**: a different company sees none of Acme's data (Postgres row-level security).

## Architecture

```
 Claude Code ─ SessionEnd hook ─┐
 git ─ post-commit hook ────────┤
 email / calendar ──────────────┼─► FastAPI ─► events queue ─► worker ─► Gemini (summarise, plan, diagnose, listen)
 meeting recordings ────────────┤                                 │
 any orchestrator ─ webhook ────┘                                 ├─ daily: 06:00 pipelines · 07:00 day plans · 08:00 feed
                                                                  └─ every 20 s: release notifications held during focus
 web (React, nginx) ◄── FastAPI REST ◄── Postgres + pgvector (row-level security per company) ── warehouse DB
```

- `backend/` FastAPI API + worker. Services: `myday.py` (plans), `focus.py` (calendar, Focus Guard),
  `health.py` (Team Health), `meetings.py` (standups, recordings), `oncall.py` + `pipeline.py` (on-call agent and
  the built-in pipeline runner), `ingest.py` (Claude / git / email / calendar), `sop.py`, `feed.py`, `ask.py`,
  `redact.py` (secrets and personal data removed before any text reaches the AI).
- `web/` React + Vite + Tailwind, Apple-style UI with shadcn-style components.
- `pipelines/` SQL models of the demo pipeline (`templates/` = originals).
- `hooks/` Claude Code SessionEnd hook and git post-commit hook (`./hooks/install.sh claude|git`).
- [`KESTRA.md`](KESTRA.md): optional. How to run the pipelines from Kestra (or another orchestrator) instead of
  the built-in runner; ready-made flows are in `docs/kestra/flows/`.

Every table carries `org_id`; the app connects as a non-superuser role so Postgres row-level security enforces the
isolation even if application code has a bug. All AI actions are written to the audit log; per-team autonomy
(suggest / draft for approval / act then tell) is set in Admin.

## Deploy to Google Cloud

```bash
PROJECT=your-project-id ./deploy/gcp-vm.sh     # one e2-standard-4 VM in asia-south1 running docker compose
```

The VM's service account can call Vertex AI, so set `GOOGLE_CLOUD_PROJECT` in `.env` instead of an API key.
Scaling path: Cloud SQL (Postgres + pgvector), API/worker on Cloud Run behind Pub/Sub, Identity Platform sign-in.

## relay-agent: updates from every AI coding tool

```bash
export RELAY_URL=http://localhost:8000 RELAY_INGEST_TOKEN=<from .env> RELAY_USER_EMAIL=abhijit@acme.test
python3 agent/relay_agent.py scan --since 2d    # what it can see; sends nothing
python3 agent/relay_agent.py watch              # sync every 5 minutes (or `install` to start at login on macOS)
```

Secrets are removed on your machine before anything is sent. Details and per-tool storage: [`agent/README.md`](agent/README.md).
Demo without the agent: Admin → Demo → *Abhijit's Cursor session hits a blocker*.

## Hooks for real use

```bash
export RELAY_URL=http://localhost:8000 RELAY_INGEST_TOKEN=<from .env>
./hooks/install.sh git /path/to/repo   # commits update the matching task
./hooks/install.sh claude              # prints the ~/.claude/settings.json snippet
```

Your git email (or `RELAY_USER_EMAIL`) must match a Relay user.
