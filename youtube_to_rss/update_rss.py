# youtube_to_rss/update_rss.py
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import yaml
from xml.sax.saxutils import escape


# ----------------------------
# Config models + loading
# ----------------------------

@dataclass(frozen=True)
class AppConfig:
    host: str
    document_root: Path


@dataclass(frozen=True)
class FeedConfig:
    id: str
    title: str
    channelurl: str
    thumburl: str


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_configs(app_yaml: Path, feeds_yaml: Path) -> tuple[AppConfig, dict[str, FeedConfig]]:
    app = _load_yaml(app_yaml)
    feeds = _load_yaml(feeds_yaml)

    cfg = AppConfig(
        host=str(app["site"]["host"]).strip().replace("https://", "").replace("http://", ""),
        document_root=Path(app["site"]["document_root"]).expanduser().resolve(),
    )

    feed_map: dict[str, FeedConfig] = {}
    for f in (feeds.get("feeds", []) or []):
        fc = FeedConfig(
            id=str(f["id"]),
            title=str(f["title"]),
            channelurl=str(f["channelurl"]),
            thumburl=str(f.get("thumburl", "")),
        )
        feed_map[fc.id] = fc

    return cfg, feed_map


# ----------------------------
# Media duration helper
# ----------------------------

def ffprobe_duration_seconds(media_path: Path) -> int:
    """
    Returns integer seconds (rounded down). Requires ffprobe installed.
    """
    import subprocess

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(media_path),
    ]
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode != 0:
        return 0
    out = (p.stdout or "").strip()
    if not out:
        return 0
    try:
        return int(float(out))
    except ValueError:
        return 0


# ----------------------------
# Queue claiming + processing
# ----------------------------

def iter_info_json(inbox_dir: Path) -> Iterator[Path]:
    # Oldest first (optional). You can reverse if you prefer newest first.
    yield from sorted(inbox_dir.glob("*.info.json"), key=lambda p: p.stat().st_mtime)


def claim_info_json(info_path: Path, processing_dir: Path) -> Path | None:
    """
    Atomically "claim" a pending .info.json by renaming it into processing/
    as *.processing. Returns the claimed path, or None if it couldn't be claimed.
    """
    processing_dir.mkdir(parents=True, exist_ok=True)
    claimed = processing_dir / (info_path.name + ".processing")
    try:
        os.replace(info_path, claimed)  # atomic within same filesystem
        return claimed
    except FileNotFoundError:
        return None
    except PermissionError:
        return None
    except OSError:
        return None


def delete_if_playlist_json(path: Path) -> bool:
    """
    Mirrors your bash logic: if _type == playlist, delete and return True.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if data.get("_type", "video") == "playlist":
        path.unlink(missing_ok=True)
        return True
    return False


PREFERRED_MEDIA_EXTS = (
    ".m4a",
    ".mp3",
    ".opus",
    ".aac",
    ".mka",
    ".ogg",
    ".wav",
    ".flac",
    ".webm",  # keep as last resort
    ".mp4",   # last resort
)

TEMP_SUFFIXES = (
    ".part",
    ".ytdl",
    ".temp",
    ".tmp",
)

def find_staged_media(inbox_dir: Path, filebase: str) -> Optional[Path]:
    """
    Given filebase like 'abc1231706551234', find the *final* staged media file.

    Rules:
      - Ignore *.info.json and *.info.json.processing
      - Ignore temp/partial artifacts (*.part, *.ytdl, etc.)
      - Prefer extracted audio outputs (m4a/mp3/...) over container formats
      - If nothing final exists yet (download still running), return None
    """
    all_matches = list(inbox_dir.glob(filebase + ".*"))

    candidates: list[Path] = []
    for p in all_matches:
        name = p.name
        if name.endswith(".info.json") or name.endswith(".info.json.processing"):
            continue
        if any(name.endswith(suf) for suf in TEMP_SUFFIXES):
            continue
        # Also exclude files like foo.m4a.part by suffix check above; keep this for safety:
        if ".part" in name:
            continue
        candidates.append(p)

    if not candidates:
        # Not ready yet (or nothing downloaded). Let caller decide.
        return None

    # Prefer known media extensions in priority order
    lowered = {p: p.suffix.lower() for p in candidates}
    for ext in PREFERRED_MEDIA_EXTS:
        preferred = [p for p in candidates if lowered[p] == ext]
        if preferred:
            # If multiple, pick the largest (most likely the complete one)
            return max(preferred, key=lambda p: p.stat().st_size)

    # Fallback: pick the largest non-temp file
    return max(candidates, key=lambda p: p.stat().st_size)



def publish_media(staged_media: Path, feed_dir: Path) -> Path:
    """
    Move staged media from inbox/ into feed root (served path).
    Atomic within same filesystem.
    """
    dst = feed_dir / staged_media.name
    if dst.exists():
        raise FileExistsError(f"Destination exists (won't overwrite): {dst}")
    os.replace(staged_media, dst)
    return dst


def prepend_feed_item(feed_body: Path, item_xml: str) -> None:
    old = feed_body.read_text(encoding="utf-8") if feed_body.exists() else ""
    feed_body.write_text(item_xml + old, encoding="utf-8")


# NOTE:
# feed.body may be very large. We prepend new <item> blocks
# and never load or parse the full RSS feed into memory.
def write_rss(feed_dir: Path, title: str, host: str, feed_id: str, thumburl: str) -> None:
    body_path = feed_dir / "feed.body"
    feed_body = body_path.read_text(encoding="utf-8") if body_path.exists() else ""

    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        '<channel>\n'
        f'    <title>{escape(title)}</title>\n'
        f'    <link>https://{escape(host)}/{escape(feed_id)}/</link>\n'
        f'    <description>{escape(title)} Youtube rips</description>\n'
        f'    <image>{escape(thumburl)}</image>\n'
        '    <generator>Visit johnnysteen/youtube-to-rss on Github</generator>\n'
        f'{feed_body}\n'
        '</channel>\n'
        '</rss>\n'
    )
    (feed_dir / "feed.rss").write_text(rss, encoding="utf-8")


def update_rss_for_feed(cfg: AppConfig, feed: FeedConfig, *, max_items: int | None = None) -> None:
    feed_dir = cfg.document_root / feed.id
    inbox_dir = feed_dir / "inbox"
    processing_dir = feed_dir / "processing"
    feed_body_path = feed_dir / "feed.body"

    inbox_dir.mkdir(parents=True, exist_ok=True)
    processing_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    for info_path in iter_info_json(inbox_dir):
        if max_items is not None and processed >= max_items:
            break

        # Claim it (atomic); if we can't, skip.
        claimed = claim_info_json(info_path, processing_dir)
        if not claimed:
            continue

        try:
            # Drop playlist JSONs like your script does
            if delete_if_playlist_json(claimed):
                continue

            # Parse JSON
            data = json.loads(claimed.read_text(encoding="utf-8"))

            title_raw = (data.get("title") or "").encode("ascii", "ignore").decode()
            vidurl = data.get("webpage_url") or ""
            upload_date = data.get("upload_date") or ""  # YYYYMMDD
            desc_raw = (data.get("description") or "").encode("ascii", "ignore").decode()

            # Convert upload_date -> local timezone string, like: "%a, %d %b %Y %H:%M:%S %z"
            pubstring = ""
            if len(upload_date) == 8 and upload_date.isdigit():
                import datetime
                dt = datetime.datetime.strptime(upload_date, "%Y%m%d")
                local = dt.replace(hour=0, minute=0, second=0)
                pubstring = local.astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")

            # Identify filebase from JSON filename stem
            # e.g. abc1231706....info.json.processing -> abc1231706...
            name = claimed.name
            if name.endswith(".info.json.processing"):
                filebase = name[: -len(".info.json.processing")]
            elif name.endswith(".info.json"):
                filebase = name[: -len(".info.json")]
            else:
                filebase = claimed.stem

            # Find staged media, publish it to feed root (served path)
            staged_media = find_staged_media(inbox_dir, filebase)
            if staged_media is None:
                # Download/extraction not finished yet; skip for now.
                continue
            published_media = publish_media(staged_media, feed_dir)

            # GUID = filename minus extension (your chosen rule)
            guid = published_media.stem

            # Duration (seconds)
            length = ffprobe_duration_seconds(published_media)

            # XML escaping (replaces your sed)
            title_x = escape(title_raw)
            desc_x = escape(desc_raw)
            vidurl_x = escape(vidurl)
            guid_x = escape(guid)
            fname_x = escape(published_media.name)
            pub_x = escape(pubstring)

            now_str = time.strftime("%a, %d %b %Y %H:%M:%S%p%Z")
            now_x = escape(now_str)

            # Build item XML: preserve your overall structure, but GUID is now stem-only
            item_xml = (
                "    <item>\n"
                f"    <title>{title_x}</title>\n"
                f"    <pubdate>{pub_x}</pubdate>\n"
                f'    <guid isPermaLink="false">{guid_x}</guid>\n'
                f'    <enclosure url="http://{escape(cfg.host)}/{escape(feed.id)}/{fname_x}" type="audio/mpeg" length="{length}"></enclosure>\n'
                "    <description>\n"
                f"    {title_x}\n\n"
                f"    Filename: {fname_x}\n"
                f"    Original video: {vidurl_x}\n"
                f"    Downloaded: {now_x}\n\n"
                f"    {desc_x}\n"
                "    </description>\n"
                "    </item>\n"
            )

            prepend_feed_item(feed_body_path, item_xml)
            processed += 1

        except Exception as e:
            # Put the claimed file back into inbox for another try (best-effort)
            try:
                os.replace(claimed, inbox_dir / claimed.name.replace(".processing", ""))
            except Exception:
                pass
            raise e
        finally:
            # If we successfully processed, delete claimed JSON
            # (If we requeued it above, this unlink will be a no-op.)
            claimed.unlink(missing_ok=True)

    # Rewrite feed.rss once at end (efficient + consistent)
    write_rss(feed_dir, feed.title, cfg.host, feed.id, feed.thumburl)


# ----------------------------
# CLI
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="youtube-to-rss RSS update phase (consumes inbox/*.info.json)")
    ap.add_argument("--app", default="configs/app.yaml")
    ap.add_argument("--feeds", default="configs/feeds.yaml")

    ap.add_argument("feed_id", help="Feed id (directory name under document_root / podcasts/)")
    ap.add_argument("--max-items", type=int, default=None, help="Process at most this many pending items")

    args = ap.parse_args()

    cfg, feeds = load_configs(Path(args.app), Path(args.feeds))
    feed = feeds.get(args.feed_id)
    if not feed:
        raise SystemExit(f"Unknown feed_id: {args.feed_id}")

    update_rss_for_feed(cfg, feed, max_items=args.max_items)


if __name__ == "__main__":
    main()

