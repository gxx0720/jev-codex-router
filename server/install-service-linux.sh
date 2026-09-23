#!/usr/bin/env bash
# Install Jev Router as a per-user systemd service (no root required).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$(command -v python3 || true)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/jev-codex-router.service"

if [[ -z "$PYTHON" || ! -x "$PYTHON" ]]; then
  echo "python3 not found; install Python 3.11+ first" >&2
  exit 1
fi
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11+ is required (found: $($PYTHON --version 2>&1))" >&2
  exit 1
fi
if [[ ! -f "$REPO/server/jev_server.py" ]]; then
  echo "Jev Router source not found under $REPO" >&2
  exit 1
fi

mkdir -p "$UNIT_DIR"
python3 - "$PYTHON" "$REPO/server/jev_server.py" "$REPO" "$UNIT" <<'PY'
import pathlib
import os
import sys

def quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

python, script, repo, unit_path = sys.argv[1:]
codex_home = os.path.expanduser(os.environ.get("CODEX_HOME", "~/.codex"))
unit = """[Unit]
Description=Jev Codex Router
After=network-online.target

[Service]
Type=simple
WorkingDirectory={repo}
ExecStart={python} {script}
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment={codex_home}

[Install]
WantedBy=default.target
""".format(repo=quote(repo), python=quote(python), script=quote(script),
           codex_home=quote("CODEX_HOME=" + codex_home))
pathlib.Path(unit_path).write_text(unit, encoding="utf-8")
PY

systemctl --user daemon-reload
systemctl --user enable --now jev-codex-router.service
echo "Installed and started jev-codex-router.service"
echo "Status: systemctl --user status jev-codex-router.service"
echo "Logs:   journalctl --user -u jev-codex-router.service -f"
echo "Stop:   systemctl --user disable --now jev-codex-router.service"
echo "Health: curl http://127.0.0.1:4319/health"
echo "If this is a headless host and it must run after logout, enable lingering explicitly with: loginctl enable-linger \"$USER\""
