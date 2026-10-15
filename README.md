# Relay — the task manager that updates itself

Google Cloud AI Builder Cup · theme: **Future of Work & Enterprise Productivity**

Relay removes the busywork around work. Tasks are created, filled in and closed from where work already happens
(Claude Code sessions, git commits, email, calendar). SOPs become live checklists that tick themselves off. Managers
catch up through a feed that ends. Anyone can ask the company's work history a question. Tech teams also get an
on-call agent that diagnoses pipeline failures and raises a fix for a person to approve.

| Pillar | Feature |
|---|---|
| Productivity | Tasks that update themselves (Claude hook, git hook, email, calendar) · feed replaces status meetings |
| Efficiency | On-call agent: Kestra failure → investigation → fix → review task → rerun → closed |
| Knowledge accessibility | Ask (⌘K): answers with citations, filtered to what the asker may see |
| Workflow execution | SOP builder → projects whose steps are matched to real evidence; outdated-SOP detection |
| Collaboration | Routing by resource ownership, FYIs to business owners, nudges, kudos |

## Run it

```bash
cp .env.example .env          # add GEMINI_API_KEY when you have it (works offline without)
docker compose up -d          # postgres, kestra, api, worker, web
open http://localhost:3100    # sign in as Kavya Rao (admin)
```

| Service | URL |
|---|---|
| Web app | http://localhost:3100 |
| API + interactive docs | http://localhost:8000/docs |
| Kestra UI | http://localhost:8080 (KESTRA_USER / KESTRA_PASSWORD from `.env`) |

Fresh demo data: `./scripts/reset-demo.sh` (wipes everything, reseeds).
Tests: `docker compose exec api pytest -q tests` (end-to-end, against the running stack; reset afterwards).

### Gemini
Set `GEMINI_API_KEY` in `.env` (or `GOOGLE_CLOUD_PROJECT` to use Vertex AI with the VM's service account), then
`docker compose up -d api worker`. Every AI step has an offline fallback, so the demo runs without a key; with a key,
summaries, request detection, SOP drafting, diagnosis and Ask answers come from Gemini (Flash for high-volume calls,
Pro for diagnosis and SOP drafting). Embeddings are recomputed automatically when the provider changes.

## Demo script (≈3 min)

Sign in as **Kavya Rao** → **Admin → Demo** has a button for each step.

1. **Home** — the manager feed: team stories (ring colour = health), cards ranked "needs you" first, each with an
   action, ending in "You're all caught up".
2. **Break the pipeline** — renames `raw.orders.amount` (as yesterday's refactor did) and runs `orders_daily` on
   Kestra. Kestra fails → webhook → the **on-call agent** reads logs, traces lineage, checks the data, finds the
   change in task DP-1 (logged from Abhijit's Claude session), recalls INC-031, drafts the one-line fix and creates a
   review task for Rohan. Finance gets an FYI that the Revenue dashboard is late.
3. **Approve** on the On-call page → Relay applies the fix, reruns on Kestra, closes the incident; the feed turns green.
4. **Ananya emails Meera** → a task appears for Meera with "last time you replied with Vendor_Payouts_Q2.xlsx".
5. **Priya books the induction** → step 4 of Rahul's onboarding SOP ticks itself off; the project page shows the
   out-of-order step and the "SOP may be out of date" suggestion.
6. **⌘K Ask** "Why did we change the orders model?" → answer with numbered sources.
7. Sign in as **Grace (Globex)** → a different company sees none of Acme's data (Postgres row-level security).

## Architecture

```
 Claude Code ─ SessionEnd hook ─┐
 git ─ post-commit hook ────────┤
 email / calendar ──────────────┼─► FastAPI /ingest ─► events queue ─► worker ─► Gemini (summarise, match, diagnose)
 Kestra ─ notify_relay flow ────┘                                        │
                                                                         ▼
 web (React, nginx) ◄── FastAPI REST ◄──────────── Postgres + pgvector (row-level security per company)
                                                                         ▲
 Kestra data.orders_daily ─► /runner/models/{name}/run ─► warehouse DB ──┘
```

- `backend/` FastAPI API + worker. Key modules: `services/oncall.py` (agent), `services/ingest.py` (Claude / git /
  email / calendar), `services/sop.py` (SOP engine), `services/feed.py`, `services/ask.py`, `services/redact.py`
  (secrets and personal data removed before any text reaches the AI).
- `web/` React + Vite + Tailwind, Apple-style UI with shadcn-style components.
- `kestra-flows/` deployed automatically by the worker: the demo pipeline, the failure/success notifier, the 08:00 feed.
- `pipelines/` SQL models the demo pipeline builds (`templates/` = originals).
- `hooks/` Claude Code SessionEnd hook and git post-commit hook (`./hooks/install.sh claude|git`).

Every table carries `org_id`; the app connects as a non-superuser role so Postgres row-level security enforces the
isolation even if application code has a bug. All AI actions are written to the audit log; per-team autonomy
(suggest / draft for approval / act then tell) is set in Admin.

## Deploy to Google Cloud

```bash
PROJECT=your-project-id ./deploy/gcp-vm.sh     # one e2-standard-4 VM in asia-south1 running docker compose
```

The VM's service account can call Vertex AI, so set `GOOGLE_CLOUD_PROJECT` in `.env` instead of an API key.
Scaling path: Cloud SQL (Postgres + pgvector), API/worker on Cloud Run behind Pub/Sub, Identity Platform sign-in.

## Hooks for real use

```bash
export RELAY_URL=http://localhost:8000 RELAY_INGEST_TOKEN=<from .env>
./hooks/install.sh git /path/to/repo   # commits update the matching task
./hooks/install.sh claude              # prints the ~/.claude/settings.json snippet
```

Your git email (or `RELAY_USER_EMAIL`) must match a Relay user.
