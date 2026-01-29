#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

PY="$REPO_ROOT/env/bin/python"
APP_YAML="$REPO_ROOT/configs/app.yaml"
FEEDS_YAML="$REPO_ROOT/configs/feeds.yaml"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: venv python not found at: $PY" >&2
  exit 1
fi
if [[ ! -f "$APP_YAML" || ! -f "$FEEDS_YAML" ]]; then
  echo "ERROR: missing configs/app.yaml or configs/feeds.yaml" >&2
  exit 1
fi

# Extract docroot + feed ids
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
    DOCROOT=*) DOCROOT="${line#DOCROOT=}" ;;
    FEED=*)   FEEDS+=("${line#FEED=}") ;;
  esac
done

if [[ -z "$DOCROOT" || "${#FEEDS[@]}" -eq 0 ]]; then
  echo "ERROR: failed to parse docroot or feeds from configs" >&2
  exit 1
fi

echo "Repo:    $REPO_ROOT"
echo "Docroot: $DOCROOT"
echo

printf "%-16s %-10s %-10s %-9s %-24s %s\n" "feed" "enabled" "active" "pending" "last_run" "last_status"
printf "%-16s %-10s %-10s %-9s %-24s %s\n" "----------------" "--------" "------" "-------" "------------------------" "-----------"

for f in "${FEEDS[@]}"; do
  path_unit="y2r-watch@${f}.path"
  svc_unit="y2r-update@${f}.service"
  inbox="$DOCROOT/$f/inbox"

  enabled="$(systemctl --user is-enabled "$path_unit" 2>/dev/null || echo "no")"
  active="$(systemctl --user is-active "$path_unit" 2>/dev/null || echo "no")"

  pending="0"
  if [[ -d "$inbox" ]]; then
    # Count pending info.json safely
    pending="$(find "$inbox" -maxdepth 1 -type f -name '*.info.json' 2>/dev/null | wc -l | tr -d ' ')"
  else
    pending="(no inbox)"
  fi

  # Best-effort last service result/time (from systemd metadata)
  # "systemctl show" works even if it never ran.
  last_ts="$(systemctl --user show "$svc_unit" -p ExecMainExitTimestamp --value 2>/dev/null || true)"
  last_code="$(systemctl --user show "$svc_unit" -p ExecMainStatus --value 2>/dev/null || true)"
  last_result="$(systemctl --user show "$svc_unit" -p Result --value 2>/dev/null || true)"

  if [[ -z "$last_ts" || "$last_ts" == "n/a" ]]; then
    last_ts="(never)"
  fi
  if [[ -z "$last_code" ]]; then
    last_code="?"
  fi
  if [[ -z "$last_result" ]]; then
    last_result="?"
  fi

  printf "%-16s %-10s %-10s %-9s %-24s %s\n" \
    "$f" "$enabled" "$active" "$pending" "$last_ts" "${last_result}(${last_code})"
done

echo
echo "Tip: follow live runs with:"
echo "  journalctl --user -u 'y2r-update@*.service' -f"

