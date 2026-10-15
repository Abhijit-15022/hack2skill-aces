#!/usr/bin/env python3
"""relay-agent: keeps Relay's task list current from your AI coding sessions.

Reads recently updated chat sessions from Claude Code, Cursor, Codex and Antigravity on this machine, removes
secrets locally, and sends what was worked on to Relay, which updates the matching task (progress, blockers,
expected outcome). Standard library only; Python 3.9+.

  relay-agent status             check the connection to Relay and which AI tools were found
  relay-agent scan               list sessions it can see (sends nothing)
  relay-agent sync [--since 2d]  send sessions updated since the last sync (or the given window)
  relay-agent watch              sync every few minutes, once a session has been quiet for a while
  relay-agent install            start `watch` at login (macOS launchd)

Config (env vars or ~/.relay-agent/config.json): RELAY_URL, RELAY_INGEST_TOKEN, RELAY_USER_EMAIL (defaults to
`git config user.email`), RELAY_TOOLS (comma list; default all).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

HOME = Path.home()
STATE_DIR = HOME / ".relay-agent"
STATE_FILE = STATE_DIR / "state.json"
CONFIG_FILE = STATE_DIR / "config.json"
VERSION = "0.2.0"
MAX_CHARS = 16000
QUIET_MINUTES = 5

if platform.system() == "Darwin":
    APP_SUPPORT = HOME / "Library" / "Application Support"
elif platform.system() == "Windows":
    APP_SUPPORT = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
else:
    APP_SUPPORT = HOME / ".config"


@dataclass
class Session:
    tool: str
    id: str
    title: str
    updated: datetime
    text: str
    cwd: str | None = None
    branch: str | None = None
    files: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- secrets never leave the machine

_SECRETS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED:private_key]"),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}"), "[REDACTED:api_key]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "[REDACTED:api_key]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), "[REDACTED:api_key]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED:api_key]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED:aws_key]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "[REDACTED:jwt]"),
    (re.compile(r"(://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED:credentials]@"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api_key|apikey)([\"']?\s*[:=]\s*[\"']?)[^\s\"',}]{4,}"),
     r"\1\2[REDACTED:password]"),
]


def redact(text: str) -> str:
    for pattern, repl in _SECRETS:
        text = pattern.sub(repl, text)
    return text


def _git(cwd: str | None, *args: str) -> str:
    if not cwd or not Path(cwd).is_dir():
        return ""
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _ms(ts) -> datetime:
    return datetime.fromtimestamp(float(ts) / 1000, tz=timezone.utc)


def _copy_db(path: Path) -> Path:
    """Read a copy so we never lock or corrupt the app's live database."""
    tmp = Path(tempfile.mkdtemp(prefix="relay-agent-")) / path.name
    shutil.copy2(path, tmp)
    for suffix in ("-wal", "-shm"):
        side = path.with_name(path.name + suffix)
        if side.exists():
            shutil.copy2(side, tmp.with_name(tmp.name + suffix))
    return tmp


# ---------------------------------------------------------------- Claude Code

def claude_sessions(since: datetime) -> Iterator[Session]:
    root = HOME / ".claude" / "projects"
    for path in root.glob("*/*.jsonl") if root.exists() else []:
        updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if updated < since:
            continue
        parts, files, cwd, branch, title = [], [], None, None, None
        with path.open(errors="ignore") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = e.get("cwd") or cwd
                branch = e.get("gitBranch") or branch
                if e.get("type") == "summary" and e.get("summary"):
                    title = e["summary"]
                msg = e.get("message")
                if not isinstance(msg, dict):
                    continue
                role, content = msg.get("role") or e.get("type"), msg.get("content")
                if isinstance(content, str):
                    parts.append(f"{role}: {content}")
                    title = title or (content[:400] if role == "user" else None)
                    continue
                for block in content or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and block.get("text"):
                        parts.append(f"{role}: {block['text']}")
                    elif block.get("type") == "tool_use":
                        inp = block.get("input") or {}
                        p = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
                        if p and p not in files:
                            files.append(p)
        if parts:
            yield Session("claude", path.stem, _clean_title(title) or path.parent.name, updated, "\n".join(parts),
                          cwd, branch, files)


def _clean_title(text: str | None) -> str:
    """First meaningful line of a prompt, without pasted blocks or markup."""
    if not text:
        return ""
    text = re.sub(r"<pasted_content[^>]*>.*?(</pasted_content[^>]*>|$)", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    line = next((ln.strip() for ln in text.splitlines() if len(ln.strip()) > 3), "")
    return re.sub(r"\s+", " ", line)[:80]


# ---------------------------------------------------------------- Cursor

def _cursor_workspaces() -> dict[str, str]:
    """composerId -> workspace folder, from each workspace's own database."""
    out: dict[str, str] = {}
    for ws in (APP_SUPPORT / "Cursor" / "User" / "workspaceStorage").glob("*"):
        meta, db = ws / "workspace.json", ws / "state.vscdb"
        if not (meta.exists() and db.exists()):
            continue
        try:
            folder = json.loads(meta.read_text()).get("folder", "")
            folder = re.sub(r"^file://", "", urllib.request.url2pathname(folder))
            con = sqlite3.connect(_copy_db(db))
            row = con.execute("SELECT value FROM ItemTable WHERE key='composer.composerData'").fetchone()
            for c in json.loads(row[0]).get("allComposers", []) if row else []:
                out[c.get("composerId")] = folder
        except (sqlite3.Error, json.JSONDecodeError, OSError):
            continue
    return out


def cursor_sessions(since: datetime) -> Iterator[Session]:
    db = APP_SUPPORT / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    if not db.exists():
        return
    con = sqlite3.connect(_copy_db(db))
    folders = _cursor_workspaces()
    for key, value in con.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"):
        try:
            data = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            continue
        updated = _ms(data.get("lastUpdatedAt") or data.get("createdAt") or 0)
        if updated < since:
            continue
        cid = data.get("composerId") or key.split(":", 1)[1]
        parts = []
        for h in (data.get("fullConversationHeadersOnly") or [])[-200:]:
            row = con.execute("SELECT value FROM cursorDiskKV WHERE key=?", (f"bubbleId:{cid}:{h['bubbleId']}",)).fetchone()
            if not row:
                continue
            try:
                bubble = json.loads(row[0])
            except json.JSONDecodeError:
                continue
            text = (bubble.get("text") or "").strip()
            if text:
                parts.append(f"{'user' if h.get('type') == 1 else 'assistant'}: {text}")
        if parts:
            cwd = folders.get(cid)
            yield Session("cursor", cid, data.get("name") or "Cursor chat", updated, "\n".join(parts), cwd,
                          _git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or None)


# ---------------------------------------------------------------- Codex CLI

def codex_sessions(since: datetime) -> Iterator[Session]:
    root = HOME / ".codex" / "sessions"
    for path in root.rglob("*.jsonl") if root.exists() else []:
        updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if updated < since:
            continue
        parts, cwd, title = [], None, None
        with path.open(errors="ignore") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                p = e.get("payload") if isinstance(e.get("payload"), dict) else e
                cwd = p.get("cwd") or cwd
                if p.get("type") == "message" and p.get("role") in ("user", "assistant"):
                    for c in p.get("content") or []:
                        t = c.get("text") if isinstance(c, dict) else None
                        if t and not t.startswith("<environment_context>"):
                            parts.append(f"{p['role']}: {t}")
                            title = title or (t[:80] if p["role"] == "user" else None)
        if parts:
            yield Session("codex", path.stem, title or "Codex session", updated, "\n".join(parts), cwd,
                          _git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or None)


# ---------------------------------------------------------------- Antigravity
# Conversation files are encrypted; Antigravity keeps a readable per-conversation summary in its app database
# (base64 protobuf). We decode it generically: title, workspace, timestamps, and its human-readable text.

def _varint(b: bytes, i: int) -> tuple[int, int]:
    r = s = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        s += 7
        if not x & 0x80:
            return r, i


def _pb(b: bytes) -> list[tuple[int, int, object]]:
    out, i = [], 0
    while i < len(b):
        key, i = _varint(b, i)
        f, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(b, i)
        elif wt == 2:
            n, i = _varint(b, i)
            v = b[i:i + n]
            i += n
        elif wt == 1:
            v, i = b[i:i + 8], i + 8
        elif wt == 5:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError("not protobuf")
        if i > len(b):
            raise ValueError("truncated")
        out.append((f, wt, v))
    return out


def _texts(b: bytes, depth: int = 0) -> list[str]:
    """Readable sentences anywhere in a protobuf message."""
    found: list[str] = []
    try:
        fields = _pb(b)
    except (ValueError, IndexError):
        return found
    for _, wt, v in fields:
        if wt != 2 or not v:
            continue
        inner = _texts(v, depth + 1) if depth < 8 else []
        if inner:
            found.extend(inner)
            continue
        try:
            s = v.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if len(s) >= 20 and s.count(" ") >= 3 and sum(c.isprintable() for c in s) / len(s) > 0.95:
            found.append(s)
    return found


def antigravity_sessions(since: datetime) -> Iterator[Session]:
    db = APP_SUPPORT / "Antigravity" / "User" / "globalStorage" / "state.vscdb"
    if not db.exists():
        return
    con = sqlite3.connect(_copy_db(db))
    row = con.execute("SELECT value FROM ItemTable WHERE key='antigravityUnifiedStateSync.trajectorySummaries'").fetchone()
    if not row:
        return
    try:
        entries = _pb(base64.b64decode(row[0]))
    except (ValueError, IndexError):
        return
    for _, _, entry in entries:
        try:
            fields = {f: v for f, _, v in _pb(entry)}
            conv_id = fields[1].decode()
            encoded = _pb(fields[2])[0][2].decode()
            summary = base64.b64decode(encoded + "=" * (-len(encoded) % 4))
            top = _pb(summary)
        except (KeyError, ValueError, IndexError, UnicodeDecodeError):
            continue
        by = {}
        for f, wt, v in top:
            by.setdefault(f, v)
        title = by.get(1, b"").decode("utf-8", "ignore") if isinstance(by.get(1), bytes) else "Antigravity task"
        try:
            ts = {f: v for f, _, v in _pb(by[3])}
            updated = datetime.fromtimestamp(ts.get(1, 0), tz=timezone.utc)
        except (KeyError, ValueError, IndexError):
            continue
        if updated < since:
            continue
        cwd = None
        try:
            ws = {f: v for f, _, v in _pb(by[9])}
            cwd = re.sub(r"^file://", "", urllib.request.url2pathname(ws[1].decode()))
        except (KeyError, ValueError, IndexError, UnicodeDecodeError):
            pass
        texts = list(dict.fromkeys(t for f, wt, v in top if f >= 10 and wt == 2 for t in _texts(v)))
        if texts:
            yield Session("antigravity", conv_id, title or "Antigravity task", updated,
                          "\n".join(f"agent: {t}" for t in texts), cwd, _git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or None)


TOOLS = {"claude": claude_sessions, "cursor": cursor_sessions, "codex": codex_sessions, "antigravity": antigravity_sessions}
TOOL_PATHS = {
    "claude": [HOME / ".claude" / "projects"],
    "cursor": [APP_SUPPORT / "Cursor" / "User" / "globalStorage" / "state.vscdb"],
    "codex": [HOME / ".codex" / "sessions"],
    "antigravity": [APP_SUPPORT / "Antigravity" / "User" / "globalStorage" / "state.vscdb"],
}


def detect(tools: list[str]) -> list[dict]:
    """Which tools are installed here, and how many sessions they had in the last 7 days."""
    week = datetime.now(timezone.utc) - timedelta(days=7)
    out = []
    for name in TOOLS:
        found = any(p.exists() for p in TOOL_PATHS[name])
        info = {"tool": name, "found": found, "enabled": name in tools, "sessions_7d": 0, "last_session_at": None}
        if found and name in tools:
            try:
                sessions = list(TOOLS[name](week))
                info["sessions_7d"] = len(sessions)
                info["last_session_at"] = max(s.updated for s in sessions).isoformat() if sessions else None
            except Exception as exc:
                info["error"] = f"{exc.__class__.__name__}: {exc}"[:200]
        out.append(info)
    return out


def heartbeat(cfg: dict, tools_info: list[dict], synced: bool = False, sent: int = 0) -> dict:
    payload = {"user_email": cfg["email"], "hostname": platform.node(), "platform": f"{platform.system()} {platform.machine()}",
               "version": VERSION, "tools": tools_info, "synced": synced, "sent": sent}
    req = urllib.request.Request(f"{cfg['url']}/agents/heartbeat", data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Relay-Token": cfg["token"]})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


# ---------------------------------------------------------------- sync

def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def config() -> dict:
    cfg = load(CONFIG_FILE)
    get = lambda k, d=None: os.environ.get(k) or cfg.get(k) or d
    email = get("RELAY_USER_EMAIL") or _git(str(HOME), "config", "--global", "user.email")
    tools = [t.strip() for t in get("RELAY_TOOLS", ",".join(TOOLS)).split(",") if t.strip() in TOOLS]
    return {"url": get("RELAY_URL", "http://localhost:8000").rstrip("/"), "token": get("RELAY_INGEST_TOKEN", ""),
            "email": email, "tools": tools}


def collect(since: datetime, tools: list[str]) -> list[Session]:
    found = []
    for name in tools:
        try:
            found.extend(TOOLS[name](since))
        except Exception as exc:  # one tool's format changing must not stop the others
            print(f"  {name}: skipped ({exc.__class__.__name__}: {exc})", file=sys.stderr)
    return sorted(found, key=lambda s: s.updated)


def send(cfg: dict, s: Session) -> dict:
    text = redact(s.text)[-MAX_CHARS:]
    payload = {"tool": s.tool, "session_id": f"{s.tool}:{s.id}", "title": s.title[:200], "cwd": s.cwd,
               "git_branch": s.branch, "repo": Path(s.cwd).name if s.cwd else None, "user_email": cfg["email"],
               "updated_at": s.updated.isoformat(), "files": s.files[:50], "transcript": text}
    req = urllib.request.Request(f"{cfg['url']}/ingest/session", data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Relay-Token": cfg["token"]})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def sync(cfg: dict, since: datetime | None, quiet_minutes: int, dry: bool = False) -> int:
    state = load(STATE_FILE)
    window = since or datetime.fromisoformat(state.get("last_sync", (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()))
    seen = state.setdefault("sent", {})
    quiet_before = datetime.now(timezone.utc) - timedelta(minutes=quiet_minutes)
    sent = 0
    for s in collect(window, cfg["tools"]):
        key = f"{s.tool}:{s.id}"
        if s.updated > quiet_before or seen.get(key) == s.updated.isoformat():
            continue  # still being worked on, or already sent at this version
        label = f"{s.tool:<11} {s.updated.astimezone():%d %b %H:%M}  {s.title[:60]}"
        if dry:
            print(f"  would send  {label}")
            continue
        try:
            result = send(cfg, s).get("result", {})
            seen[key] = s.updated.isoformat()
            sent += 1
            print(f"  sent  {label}  ->  {result.get('task') or 'queued'}")
        except Exception as exc:
            print(f"  failed {label}: {exc}", file=sys.stderr)
    if not dry:
        state["last_sync"] = datetime.now(timezone.utc).isoformat()
        STATE_DIR.mkdir(exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=1))
        try:
            heartbeat(cfg, detect(cfg["tools"]), synced=True, sent=sent)
        except Exception as exc:
            print(f"  heartbeat failed: {exc}", file=sys.stderr)
    return sent


def parse_window(text: str) -> datetime:
    n, unit = int(text[:-1]), text[-1]
    delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
    return datetime.now(timezone.utc) - delta


def install() -> None:
    if platform.system() != "Darwin":
        sys.exit("Automatic start is set up for macOS only. Run `relay-agent watch` from your startup tool.")
    plist = HOME / "Library" / "LaunchAgents" / "dev.relay.agent.plist"
    cfg = config()
    plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.relay.agent</string>
  <key>ProgramArguments</key><array><string>{sys.executable}</string><string>{Path(__file__).resolve()}</string><string>watch</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>RELAY_URL</key><string>{cfg['url']}</string>
    <key>RELAY_INGEST_TOKEN</key><string>{cfg['token']}</string>
    <key>RELAY_USER_EMAIL</key><string>{cfg['email']}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>{STATE_DIR}/agent.log</string>
  <key>StandardOutPath</key><string>{STATE_DIR}/agent.log</string>
</dict></plist>
""")
    subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
    subprocess.run(["launchctl", "load", str(plist)], check=False)
    print(f"Installed. relay-agent now starts at login; log: {STATE_DIR}/agent.log")


def main() -> None:
    ap = argparse.ArgumentParser(prog="relay-agent", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    for name in ("scan", "sync"):
        p = sub.add_parser(name)
        p.add_argument("--since", default=None, help="window like 30m, 6h, 2d")
        p.add_argument("--now", action="store_true", help="include sessions updated in the last few minutes")
    w = sub.add_parser("watch")
    w.add_argument("--every", type=int, default=300, help="seconds between syncs")
    sub.add_parser("install")
    args = ap.parse_args()
    cfg = config()
    if args.cmd == "install":
        return install()
    if args.cmd == "status":
        print(f"relay-agent {VERSION} on {platform.node()} ({platform.system()} {platform.machine()})")
        print(f"Relay:  {cfg['url']}")
        print(f"You:    {cfg['email'] or 'not set (RELAY_USER_EMAIL)'}")
        tools = detect(cfg["tools"])
        for t in tools:
            mark = "✓" if t["found"] else "·"
            detail = (f"{t['sessions_7d']} session(s) in the last 7 days" if t["found"] else "not installed")
            if t["found"] and not t["enabled"]:
                detail = "found, but turned off in RELAY_TOOLS"
            if t.get("error"):
                detail = f"found, but couldn't read it: {t['error']}"
            print(f"  {mark} {t['tool']:<12} {detail}")
        if not (cfg["token"] and cfg["email"]):
            sys.exit("Not connected: set RELAY_INGEST_TOKEN and RELAY_USER_EMAIL.")
        try:
            r = heartbeat(cfg, tools)
            print(f"Connected: Relay knows this laptop as {r['user']}'s ({r['org']}). It now shows on your Today page.")
        except urllib.error.HTTPError as exc:
            reason = {401: "wrong RELAY_INGEST_TOKEN", 404: f"{cfg['email']} isn't a Relay user"}.get(exc.code, exc.reason)
            sys.exit(f"Not connected: Relay answered {exc.code} ({reason}).")
        except OSError as exc:
            sys.exit(f"Not connected: can't reach {cfg['url']} ({exc}).")
        return
    if args.cmd in ("sync", "watch") and not (cfg["token"] and cfg["email"]):
        sys.exit("Set RELAY_INGEST_TOKEN and RELAY_USER_EMAIL (or `git config --global user.email`).")
    if args.cmd == "scan":
        since = parse_window(args.since or "2d")
        found = collect(since, cfg["tools"])
        print(f"{len(found)} session(s) since {since.astimezone():%d %b %H:%M} in {', '.join(cfg['tools'])}:")
        for s in found:
            print(f"  {s.tool:<11} {s.updated.astimezone():%d %b %H:%M}  {len(s.text):>6} chars  {s.title[:60]}"
                  f"{'  [' + Path(s.cwd).name + ']' if s.cwd else ''}")
        return
    if args.cmd == "sync":
        n = sync(cfg, parse_window(args.since) if args.since else None, 0 if args.now else QUIET_MINUTES)
        print(f"Sent {n} session(s) to {cfg['url']}.")
        return
    print(f"Watching {', '.join(cfg['tools'])} every {args.every}s. Ctrl-C to stop.")
    while True:
        sync(cfg, None, QUIET_MINUTES)
        time.sleep(args.every)


if __name__ == "__main__":
    main()
