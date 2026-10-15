#!/bin/sh
# Install Relay's hooks.
#   ./hooks/install.sh git /path/to/repo   -> git post-commit hook in that repo
#   ./hooks/install.sh agent               -> relay-agent: Claude Code, Cursor, Codex, Antigravity (recommended)
#   ./hooks/install.sh claude              -> prints the Claude Code settings.json snippet (Claude only)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

case "$1" in
  git)
    REPO="${2:-.}"
    # Respect core.hooksPath (global or per-repo) instead of assuming .git/hooks.
    HOOKS="$(cd "$REPO" && git rev-parse --git-path hooks)"
    case "$HOOKS" in /*) ;; *) HOOKS="$REPO/$HOOKS" ;; esac
    mkdir -p "$HOOKS"
    TARGET="$HOOKS/post-commit"
    if [ -e "$TARGET" ] && ! grep -q "Relay git hook" "$TARGET"; then
      TARGET="$HOOKS/post-commit.relay"
      echo "A post-commit hook already exists; installed Relay's as $TARGET. Call it from your hook."
    fi
    cp "$HERE/git/post-commit" "$TARGET"
    chmod +x "$TARGET"
    echo "Installed $TARGET. Export RELAY_URL and RELAY_INGEST_TOKEN in your shell."
    ;;
  agent)
    python3 "$HERE/../agent/relay_agent.py" scan --since 2d
    echo
    echo "Looks right? Run: python3 $HERE/../agent/relay_agent.py install   (needs RELAY_URL, RELAY_INGEST_TOKEN, RELAY_USER_EMAIL)"
    ;;
  claude)
    chmod +x "$HERE/claude/relay_session_end.py"
    cat <<EOF
Add this to ~/.claude/settings.json (merge with any existing "hooks"):

{
  "hooks": {
    "SessionEnd": [
      { "hooks": [ { "type": "command", "command": "python3 $HERE/claude/relay_session_end.py" } ] }
    ]
  }
}

Then export RELAY_URL, RELAY_INGEST_TOKEN (and RELAY_USER_EMAIL if your git email differs from Relay's).
EOF
    ;;
  *)
    echo "usage: $0 agent | git [repo] | claude"; exit 1 ;;
esac
