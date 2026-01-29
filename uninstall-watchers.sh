#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

PY="$REPO_ROOT/env/bin/python"
FEEDS_YAML="$REPO_ROOT/configs/feeds.yaml"

FEEDS=()

if [[ -x "$PY" && -f "$FEEDS_YAML" ]]; then
  # Best-effort: parse feeds from YAML
  readarray -t FEEDS < <("$PY" - <<'PY'
import yaml
from pathlib import Path
feeds = yaml.safe_load(Path("configs/feeds.yaml").read_text()) or {}
for f in feeds.get("feeds", []):
    fid = str(f.get("id","")).strip()
    if fid:
        print(fid)
PY
)
fi

UNIT_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$UNIT_DIR/y2r-update@.service"
PATH_FILE="$UNIT_DIR/y2r-watch@.path"

echo "Stopping/disabling watchers..."
if [[ "${#FEEDS[@]}" -gt 0 ]]; then
  for f in "${FEEDS[@]}"; do
    systemctl --user disable --now "y2r-watch@${f}.path" 2>/dev/null || true
  done
else
  # If YAML parsing isn't available, disable any that exist
  systemctl --user disable --now 'y2r-watch@*.path' 2>/dev/null || true
fi

echo "Removing unit files..."
rm -f "$SERVICE_FILE" "$PATH_FILE"

echo "Reloading systemd user daemon..."
systemctl --user daemon-reload

echo
echo "Uninstalled watchers."
echo "Remaining units (should be none):"
echo "  systemctl --user list-units 'y2r-watch@*.path' || true"

