#!/usr/bin/env python3
"""Claude Code SessionEnd hook: sends the session transcript to Relay, which updates the matching task.

Reads the hook's JSON from stdin ({session_id, transcript_path, cwd, ...}). Standard library only.
Config (env vars): RELAY_URL (default http://localhost:8000), RELAY_INGEST_TOKEN, RELAY_USER_EMAIL
(defaults to `git config user.email`). Never blocks or fails the session: errors are printed to stderr.
"""
import json
import os
import subprocess
import sys
import urllib.request

MAX_BYTES = 400_000


def git(cwd: str, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def main() -> None:
    hook = json.load(sys.stdin)
    path = hook.get("transcript_path")
    if not path or not os.path.exists(path):
        return
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - MAX_BYTES))
        transcript = f.read().decode("utf-8", errors="ignore")
    transcript = transcript[transcript.find("\n") + 1:] if os.path.getsize(path) > MAX_BYTES else transcript
    cwd = hook.get("cwd") or os.getcwd()
    payload = {
        "session_id": hook.get("session_id"),
        "cwd": cwd,
        "git_branch": git(cwd, "rev-parse", "--abbrev-ref", "HEAD"),
        "repo": os.path.basename(git(cwd, "rev-parse", "--show-toplevel") or cwd),
        "user_email": os.environ.get("RELAY_USER_EMAIL") or git(cwd, "config", "user.email"),
        "transcript": transcript,
    }
    req = urllib.request.Request(
        os.environ.get("RELAY_URL", "http://localhost:8000").rstrip("/") + "/ingest/claude",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Relay-Token": os.environ.get("RELAY_INGEST_TOKEN", "")},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"Relay: session sent ({resp.status})", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a hook must never break the user's session
        print(f"Relay hook skipped: {exc}", file=sys.stderr)
