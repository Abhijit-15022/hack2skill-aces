# relay-agent

Keeps Relay's task list current from your AI coding sessions in **Claude Code, Cursor, Codex and Antigravity**.
Nobody updates tasks by hand: every few minutes the agent finds sessions that have gone quiet, removes secrets on
your machine, and sends what was worked on to Relay. Relay's Gemini summary then:

- attaches the work to the right task (task key in the branch, same repo and branch as an earlier session, or Gemini
  deciding between "continues task X" and "new work"), or creates a new one;
- rewrites the task description, moves it to *In progress* or *In review*;
- records **blockers** ("permission denied on finance.refunds, waiting on Meera") and tells the team lead;
- records the **expected outcome** when you said it, and otherwise asks you once ("What should this achieve when
  it's done?") with a suggested answer you can accept in one tap.

Standard library only, Python 3.9+. Nothing is installed system-wide.

```bash
export RELAY_URL=http://localhost:8000 RELAY_INGEST_TOKEN=<from .env> RELAY_USER_EMAIL=you@company.com
python3 agent/relay_agent.py scan --since 2d     # what it can see (sends nothing)
python3 agent/relay_agent.py sync --since 1d     # send now
python3 agent/relay_agent.py watch               # keep syncing every 5 minutes
python3 agent/relay_agent.py install             # macOS: start `watch` at login
```

| Tool | Where it reads (macOS) | What it gets |
|---|---|---|
| Claude Code | `~/.claude/projects/*/*.jsonl` | Full transcript, folder, git branch, files touched |
| Cursor | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` (a copy, read-only) | Chat title, messages, timestamps, workspace folder |
| Codex | `~/.codex/sessions/**/*.jsonl` | Full transcript, folder |
| Antigravity | its app database (`trajectorySummaries`) | Title, workspace, timestamps, the agent's latest messages and task summary. Antigravity encrypts full conversations, so these summaries are what's available. |

**Privacy.** Secrets (API keys, tokens, passwords, private keys, credentials in URLs) are removed before anything
leaves your machine; Relay removes personal identifiers again on arrival. Only the last 16,000 characters of a session
are sent. `RELAY_TOOLS=claude,cursor` limits which tools are read. Sessions still in progress (updated in the last
5 minutes) wait until they go quiet.
