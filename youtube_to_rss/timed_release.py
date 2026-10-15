# youtube_to_rss/timed_release.py
"""
Timed releases: hold matching downloads back from the RSS feed until a set time.

Each feed in feeds.yaml may carry a list of `timed_releases` rules:

    timed_releases:
      - name: "sunday-sermon"         # optional, used in logs
        match: "(?i)sermon"           # regex, searched (re.search) in `field`
        field: "title"                # optional, any .info.json key (default: title)
        release_at: "08:00"           # "HH:MM" (next occurrence) or "YYYY-MM-DD HH:MM"
        days: ["sun"]                 # optional weekday filter for HH:MM rules
        timezone: "America/Chicago"   # optional IANA zone (default: system local time)

When the download phase finishes, every new episode whose info JSON matches a
rule (first match wins) is moved to <feed>/held/ instead of <feed>/inbox/,
alongside a <filebase>.hold.json sidecar recording its release time.

`y2r release` (run from the systemd timer / cron, and after every download)
moves due episodes back into inbox/, where the normal watcher picks them up.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Optional

from .locks import exclusive_lock

HOLD_SUFFIX = ".hold.json"
INFO_SUFFIX = ".info.json"

_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# ----------------------------
# Rule model + parsing
# ----------------------------

@dataclass(frozen=True)
class TimedRelease:
    name: str
    pattern: re.Pattern
    field: str
    at_time: Optional[dtime]          # recurring time of day
    at_datetime: Optional[datetime]   # one-off absolute release (naive = wall time in `timezone`)
    days: frozenset[int]              # weekday numbers (Mon=0); empty = every day
    timezone: Optional[str]

    def matches(self, info: dict) -> bool:
        value = info.get(self.field)
        if value is None:
            return False
        return self.pattern.search(str(value)) is not None

    def next_release(self, now: datetime) -> datetime:
        """Return the aware datetime at which an episode held at `now` is released."""
        tz = _get_tz(self.timezone)

        if self.at_datetime is not None:
            return _localize(self.at_datetime, tz)

        assert self.at_time is not None
        now_wall = _to_wall(now, tz)
        for offset in range(8):
            d: date = now_wall.date() + timedelta(days=offset)
            if self.days and d.weekday() not in self.days:
                continue
            candidate = datetime.combine(d, self.at_time)
            if candidate > now_wall:
                return _localize(candidate, tz)
        raise AssertionError("unreachable: no release slot within 8 days")


def _get_tz(name: Optional[str]) -> Optional[tzinfo]:
    if not name:
        return None  # system local time
    from zoneinfo import ZoneInfo
    return ZoneInfo(name)


def _to_wall(dt: datetime, tz: Optional[tzinfo]) -> datetime:
    """Aware datetime -> naive wall-clock time in tz (None = system local)."""
    return dt.astimezone(tz).replace(tzinfo=None)


def _localize(wall: datetime, tz: Optional[tzinfo]) -> datetime:
    """Naive wall-clock time in tz (None = system local) -> aware datetime."""
    if tz is None:
        return wall.astimezone()  # naive is interpreted as local time
    return wall.replace(tzinfo=tz)


def _parse_days(raw, rule_name: str) -> frozenset[int]:
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        raw = [p for p in re.split(r"[,\s]+", raw) if p]
    days: set[int] = set()
    for item in raw:
        key = str(item).strip().lower()
        if key in ("daily", "all", "*"):
            return frozenset()
        if key[:3] not in _DAY_NAMES:
            raise ValueError(f"timed_releases[{rule_name}]: unknown day {item!r}")
        days.add(_DAY_NAMES.index(key[:3]))
    return frozenset(days)


def _parse_release_at(raw, rule_name: str) -> tuple[Optional[dtime], Optional[datetime]]:
    # Unquoted YAML like 16:30 is parsed by PyYAML as a base-60 int (990).
    if isinstance(raw, int) and not isinstance(raw, bool):
        hh, mm = divmod(raw, 60)
        if 0 <= hh < 24:
            return dtime(hh, mm), None
    if isinstance(raw, datetime):
        return None, raw
    s = str(raw).strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if m:
        hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        return dtime(hh, mm, ss), None
    try:
        return None, datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(
            f"timed_releases[{rule_name}]: release_at {raw!r} must be 'HH:MM' or 'YYYY-MM-DD HH:MM'"
        ) from None


def parse_timed_releases(raw_list, feed_id: str) -> tuple[TimedRelease, ...]:
    rules: list[TimedRelease] = []
    for i, raw in enumerate(raw_list or []):
        name = str(raw.get("name") or f"{feed_id}#{i}")
        if "match" not in raw or "release_at" not in raw:
            raise ValueError(f"timed_releases[{name}]: 'match' and 'release_at' are required")
        at_time, at_datetime = _parse_release_at(raw["release_at"], name)
        days = _parse_days(raw.get("days"), name)
        if at_datetime is not None and days:
            raise ValueError(f"timed_releases[{name}]: 'days' only applies to HH:MM release times")
        tz_name = raw.get("timezone")
        _get_tz(tz_name)  # validate early
        if at_datetime is not None and at_datetime.tzinfo is not None:
            tz_name = None  # explicit offset in release_at wins
        rules.append(TimedRelease(
            name=name,
            pattern=re.compile(str(raw["match"])),
            field=str(raw.get("field") or "title"),
            at_time=at_time,
            at_datetime=at_datetime,
            days=days,
            timezone=tz_name,
        ))
    return tuple(rules)


# ----------------------------
# Hold / release
# ----------------------------

def _filebase(info_path: Path) -> str:
    return info_path.name[: -len(INFO_SUFFIX)]


def _episode_files(directory: Path, filebase: str) -> list[Path]:
    return [p for p in directory.glob(filebase + ".*") if p.is_file()]


def move_episode(src_dir: Path, dst_dir: Path, filebase: str) -> None:
    """
    Move all files of one episode, media first and the .info.json last, so the
    inbox watcher never sees the JSON before its media is in place.
    """
    dst_dir.mkdir(parents=True, exist_ok=True)
    files = _episode_files(src_dir, filebase)
    files.sort(key=lambda p: p.name.endswith(INFO_SUFFIX))
    for p in files:
        if p.name.endswith(HOLD_SUFFIX):
            continue
        os.replace(p, dst_dir / p.name)


def find_rule(rules: tuple[TimedRelease, ...], info: dict) -> Optional[TimedRelease]:
    for rule in rules:
        if rule.matches(info):
            return rule
    return None


def hold_matching(feed_id: str, rules: tuple[TimedRelease, ...], staging_dir: Path, held_dir: Path,
                  now: Optional[datetime] = None) -> list[str]:
    """
    Move episodes in staging_dir that match a rule into held_dir.
    Returns the filebases that were held.
    """
    if not rules:
        return []
    now = now or datetime.now(timezone.utc)
    held: list[str] = []
    for info_path in sorted(staging_dir.glob("*" + INFO_SUFFIX)):
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if info.get("_type", "video") == "playlist":
            continue
        rule = find_rule(rules, info)
        if rule is None:
            continue

        filebase = _filebase(info_path)
        release_at = rule.next_release(now)
        move_episode(staging_dir, held_dir, filebase)
        sidecar = {
            "release_at": release_at.isoformat(),
            "rule": rule.name,
            "title": info.get("title"),
            "held_at": now.isoformat(),
        }
        (held_dir / (filebase + HOLD_SUFFIX)).write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        print(f"[hold] feed={feed_id} rule={rule.name} release_at={release_at.isoformat()} "
              f"title={info.get('title')!r}", file=sys.stderr)
        held.append(filebase)
    return held


def iter_held(held_dir: Path):
    """Yield (filebase, release_at, sidecar_dict) for each held episode, soonest first."""
    if not held_dir.is_dir():
        return
    items = []
    for sidecar_path in held_dir.glob("*" + HOLD_SUFFIX):
        filebase = sidecar_path.name[: -len(HOLD_SUFFIX)]
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
            release_at = datetime.fromisoformat(data["release_at"])
        except Exception as e:
            print(f"[release] WARNING: unreadable hold file {sidecar_path}: {e}", file=sys.stderr)
            continue
        if release_at.tzinfo is None:
            release_at = release_at.astimezone()
        items.append((filebase, release_at, data))
    yield from sorted(items, key=lambda t: t[1])


def release_due(feed_dir: Path, *, now: Optional[datetime] = None, force: bool = False) -> int:
    """Move held episodes whose release time has passed into inbox/. Returns count released."""
    held_dir = feed_dir / "held"
    if not held_dir.is_dir():
        return 0
    now = now or datetime.now(timezone.utc)
    inbox_dir = feed_dir / "inbox"
    released = 0
    with exclusive_lock(feed_dir / "release.lock"):
        for filebase, release_at, data in iter_held(held_dir):
            if not force and release_at > now:
                continue
            move_episode(held_dir, inbox_dir, filebase)
            (held_dir / (filebase + HOLD_SUFFIX)).unlink(missing_ok=True)
            print(f"[release] feed={feed_dir.name} rule={data.get('rule')} "
                  f"title={data.get('title')!r}", file=sys.stderr)
            released += 1
    return released


# ----------------------------
# CLI
# ----------------------------

def main() -> None:
    from .download import DEFAULT_APP, DEFAULT_FEEDS, load_configs

    ap = argparse.ArgumentParser(description="youtube-to-rss: release held (timed-release) episodes")
    ap.add_argument("feed_ids", nargs="*", help="Feed ids to process (default: all feeds)")
    ap.add_argument("--list", action="store_true", help="List held episodes instead of releasing")
    ap.add_argument("--now", action="store_true", help="Release all held episodes immediately")
    ap.add_argument("--app", default=str(DEFAULT_APP))
    ap.add_argument("--feeds", default=str(DEFAULT_FEEDS))
    args = ap.parse_args()

    cfg, feeds = load_configs(Path(args.app), Path(args.feeds))
    ids = args.feed_ids or list(feeds)
    for fid in ids:
        if fid not in feeds:
            raise SystemExit(f"Unknown feed_id: {fid}")

    for fid in ids:
        feed_dir = cfg.document_root / fid
        if args.list:
            for filebase, release_at, data in iter_held(feed_dir / "held"):
                print(f"{fid}\t{release_at.astimezone().strftime('%Y-%m-%d %H:%M %Z')}\t"
                      f"{data.get('rule')}\t{data.get('title')}")
        else:
            release_due(feed_dir, force=args.now)


if __name__ == "__main__":
    main()
