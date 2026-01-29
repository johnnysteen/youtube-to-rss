#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

PY="$REPO_ROOT/env/bin/python"
APP_YAML="$REPO_ROOT/configs/app.yaml"
FEEDS_YAML="$REPO_ROOT/configs/feeds.yaml"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: venv python not found at: $PY" >&2
  echo "Activate/create env and install deps (pip install -e .) then retry." >&2
  exit 1
fi
if [[ ! -f "$APP_YAML" ]]; then
  echo "ERROR: missing $APP_YAML" >&2
  exit 1
fi
if [[ ! -f "$FEEDS_YAML" ]]; then
  echo "ERROR: missing $FEEDS_YAML" >&2
  exit 1
fi

# Extract document_root and feed ids using PyYAML from your venv
readarray -t LINES < <("$PY" - <<'PY'
import yaml
from pathlib import Path

app = yaml.safe_load(Path("configs/app.yaml").read_text())
feeds = yaml.safe_load(Path("configs/feeds.yaml").read_text())

docroot = app["site"]["document_root"].rstrip("/")
print("DOCROOT=" + docroot)

for f in feeds.get("feeds", []):
    fid = str(f["id"]).strip()
    if fid:
        print("FEED=" + fid)
PY
)

DOCROOT=""
FEEDS=()

for line in "${LINES[@]}"; do
  case "$line" in
    DOCROOT=*)
      DOCROOT="${line#DOCROOT=}"
      ;;
    FEED=*)
      FEEDS+=("${line#FEED=}")
      ;;
  esac
done

if [[ -z "$DOCROOT" ]]; then
  echo "ERROR: could not parse document_root from configs/app.yaml" >&2
  exit 1
fi
if [[ "${#FEEDS[@]}" -eq 0 ]]; then
  echo "ERROR: no feeds found in configs/feeds.yaml" >&2
  exit 1
fi

echo "Repo:      $REPO_ROOT"
echo "Docroot:   $DOCROOT"
echo "Feeds:     ${FEEDS[*]}"

# 1) Ensure per-feed directories exist: inbox + processing
echo "Creating inbox/ and processing/ for each feed under docroot..."
for f in "${FEEDS[@]}"; do
  mkdir -p "$DOCROOT/$f/inbox" "$DOCROOT/$f/processing"
done

# 2) Install systemd user unit templates
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"

SERVICE_FILE="$UNIT_DIR/y2r-update@.service"
PATH_FILE="$UNIT_DIR/y2r-watch@.path"

echo "Installing systemd user units to: $UNIT_DIR"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=y2r update-rss for feed %i

[Service]
Type=oneshot
WorkingDirectory=$REPO_ROOT
ExecStart=$REPO_ROOT/env/bin/y2r update-rss %i
EOF

cat > "$PATH_FILE" <<EOF
[Unit]
Description=Watch y2r inbox for feed %i

[Path]
PathExistsGlob=$DOCROOT/%i/inbox/*.info.json
Unit=y2r-update@%i.service

[Install]
WantedBy=default.target
EOF

# 3) Reload user systemd
echo "Reloading systemd user daemon..."
systemctl --user daemon-reload

# 4) Enable linger so user units run without an interactive login
echo "Enabling linger for user: $(whoami)"
sudo loginctl enable-linger "$(whoami)"

# 5) Enable + start watchers
echo "Enabling and starting watchers..."
for f in "${FEEDS[@]}"; do
  systemctl --user enable --now "y2r-watch@${f}.path"
done

echo
echo "Installed and started watchers."
echo "Check status:"
echo "  systemctl --user list-units 'y2r-watch@*.path'"
echo "Follow logs:"
echo "  journalctl --user -u 'y2r-update@*.service' -f"

