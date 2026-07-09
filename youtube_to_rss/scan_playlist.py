"""
scan_playlist.py — enumerate ALL items in a YouTube playlist via the InnerTube API
(bypassing yt-dlp's broken continuation handling for long playlists) and download
any that are missing from the archive.

Background: yt-dlp's YouTube extractor calls the InnerTube browse endpoint with
params='wgYCCAA=' to get playlist items including unavailable videos. The response
contains a `continuationItemViewModel` (not `continuationItemRenderer`) for pagination,
which yt-dlp's `_extract_continuation` doesn't handle. This caps yt-dlp at ~115 items
even for playlists with 400+ entries. This module follows the continuation correctly.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import sys
import time
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APP = REPO_ROOT / "configs" / "app.yaml"
DEFAULT_FEEDS = REPO_ROOT / "configs" / "feeds.yaml"

_PLAYLIST_RE = re.compile(r"[?&]list=([A-Za-z0-9_-]+)")
_INNERTUBE_API_KEY_RE = re.compile(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"')
_INNERTUBE_VERSION_RE = re.compile(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"')
_VISITOR_DATA_RE = re.compile(r'"visitorData"\s*:\s*"([^"]+)"')


# ------------------------------------------------------------------
# InnerTube API helpers
# ------------------------------------------------------------------

def _make_session(cookies_file: str | None):
    try:
        import requests
    except ImportError:
        raise SystemExit("ERROR: 'requests' package is required. Install it with: pip install requests")

    import requests as req
    session = req.Session()
    if cookies_file:
        cj = http.cookiejar.MozillaCookieJar()
        try:
            cj.load(cookies_file, ignore_discard=True, ignore_expires=True)
            session.cookies = cj
        except Exception as e:
            print(f"[scan-playlist] Warning: could not load cookies from {cookies_file}: {e}", file=sys.stderr)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    })
    return session


def _get_innertube_info(session, playlist_id: str) -> tuple[str, str, str, str]:
    """Fetch the playlist webpage to extract API key, client version, visitor data."""
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    page = r.text

    api_key_m = _INNERTUBE_API_KEY_RE.search(page)
    version_m = _INNERTUBE_VERSION_RE.search(page)
    visitor_m = _VISITOR_DATA_RE.search(page)

    if not api_key_m:
        raise RuntimeError("Could not extract INNERTUBE_API_KEY from YouTube page")

    api_key = api_key_m.group(1)
    client_version = version_m.group(1) if version_m else "2.20240101.00.00"
    visitor_data = visitor_m.group(1) if visitor_m else ""

    browse_url = f"https://www.youtube.com/youtubei/v1/browse?key={api_key}&prettyPrint=false"
    context = {
        "client": {
            "clientName": "WEB",
            "clientVersion": client_version,
            "visitorData": visitor_data,
            "gl": "US",
            "hl": "en",
        }
    }
    return browse_url, api_key, context, visitor_data


def _extract_ids_from_lockups(obj, depth: int = 0) -> list[str]:
    """Recursively find lockupViewModel.contentId values."""
    if depth > 15:
        return []
    ids: list[str] = []
    if isinstance(obj, dict):
        lvm = obj.get("lockupViewModel")
        if isinstance(lvm, dict):
            cid = lvm.get("contentId")
            if cid:
                ids.append(cid)
        for v in obj.values():
            ids.extend(_extract_ids_from_lockups(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            ids.extend(_extract_ids_from_lockups(item, depth + 1))
    return ids


def _find_cont_token_initial(obj, depth: int = 0) -> str | None:
    """Find the continuation token in the initial wgYCCAA= response."""
    if depth > 15:
        return None
    if isinstance(obj, dict):
        civ = obj.get("continuationItemViewModel")
        if isinstance(civ, dict):
            token = (
                civ.get("continuationCommand", {})
                .get("innertubeCommand", {})
                .get("continuationCommand", {})
                .get("token")
            )
            if token:
                return token  # return raw (may contain %XX) — YouTube expects it as-is
        for v in obj.values():
            result = _find_cont_token_initial(v, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_cont_token_initial(item, depth + 1)
            if result:
                return result
    return None


def _extract_continuation_page(data: dict) -> tuple[list[str], str | None]:
    """Extract video IDs and next token from a continuation response."""
    ids: list[str] = []
    token: str | None = None

    for action in data.get("onResponseReceivedActions", []):
        acia = action.get("appendContinuationItemsAction", {})
        for item in acia.get("continuationItems", []):
            if isinstance(item, dict):
                lvm = item.get("lockupViewModel")
                if isinstance(lvm, dict):
                    cid = lvm.get("contentId")
                    if cid:
                        ids.append(cid)
                civ = item.get("continuationItemViewModel")
                if isinstance(civ, dict):
                    t = (
                        civ.get("continuationCommand", {})
                        .get("innertubeCommand", {})
                        .get("continuationCommand", {})
                        .get("token")
                    )
                    if t:
                        token = t
    return ids, token


def enumerate_playlist_ids(playlist_url: str, cookies_file: str | None, verbose: bool = False) -> list[str]:
    """
    Return list of all video IDs in a YouTube playlist by following
    InnerTube API continuation tokens (up to 50 pages as a safety cap).
    """
    m = _PLAYLIST_RE.search(playlist_url)
    if not m:
        print(f"[scan-playlist] URL does not contain a playlist ID: {playlist_url}", file=sys.stderr)
        return []

    playlist_id = m.group(1)
    if verbose:
        print(f"[scan-playlist] playlist_id={playlist_id}", file=sys.stderr)

    session = _make_session(cookies_file)

    try:
        browse_url, _, context, _ = _get_innertube_info(session, playlist_id)
    except Exception as e:
        print(f"[scan-playlist] Failed to get InnerTube client info: {e}", file=sys.stderr)
        return []

    # Page 1: initial wgYCCAA= request
    try:
        r = session.post(
            browse_url,
            json={"browseId": f"VL{playlist_id}", "params": "wgYCCAA=", "context": context},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[scan-playlist] Page 1 request failed: {e}", file=sys.stderr)
        return []

    all_ids = _extract_ids_from_lockups(data)
    token = _find_cont_token_initial(data)
    if verbose:
        print(f"[scan-playlist] Page 1: {len(all_ids)} items, continuation: {'yes' if token else 'no'}", file=sys.stderr)

    page = 2
    while token and page <= 50:
        try:
            r = session.post(
                browse_url,
                json={"continuation": token, "context": context, "clickTracking": {"clickTrackingParams": ""}},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[scan-playlist] Page {page} request failed: {e}", file=sys.stderr)
            break

        new_ids, token = _extract_continuation_page(data)
        all_ids.extend(new_ids)
        if verbose:
            print(f"[scan-playlist] Page {page}: {len(new_ids)} items, continuation: {'yes' if token else 'no'}", file=sys.stderr)
        if not new_ids:
            break
        page += 1

    return all_ids


# ------------------------------------------------------------------
# Archive helpers
# ------------------------------------------------------------------

def load_archive_ids(archive_path: Path) -> set[str]:
    """Return set of YouTube video IDs already in the yt-dlp download archive."""
    if not archive_path.exists():
        return set()
    ids: set[str] = set()
    for line in archive_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[0] == "youtube":
            ids.add(parts[1])
    return ids


# ------------------------------------------------------------------
# Main scan+download logic
# ------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def scan_and_download(
    app_yaml: Path,
    feeds_yaml: Path,
    feed_id: str,
    max_new: int,
    verbose: bool,
    dry_run: bool,
) -> None:
    from .download import load_configs, download_feed

    cfg, feeds = load_configs(app_yaml, feeds_yaml)
    feed = feeds.get(feed_id)
    if not feed:
        raise SystemExit(f"Unknown feed_id: {feed_id}")

    archive_path = cfg.document_root / feed.id / "archive"

    print(f"[scan-playlist] Enumerating {feed.channelurl} ...", file=sys.stderr)
    t0 = time.time()
    all_ids = enumerate_playlist_ids(feed.channelurl, cfg.cookies_file, verbose=verbose)
    elapsed = time.time() - t0
    print(f"[scan-playlist] Found {len(all_ids)} playlist items in {elapsed:.1f}s", file=sys.stderr)

    if not all_ids:
        print("[scan-playlist] No items found (playlist URL may not be a playlist, or API error)", file=sys.stderr)
        return

    archived = load_archive_ids(archive_path)
    new_ids = [vid for vid in all_ids if vid not in archived]
    # deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for vid in new_ids:
        if vid not in seen:
            seen.add(vid)
            deduped.append(vid)
    new_ids = deduped

    print(f"[scan-playlist] {len(new_ids)} new item(s) not in archive (of {len(all_ids)} total, {len(archived)} archived)", file=sys.stderr)

    if not new_ids:
        print("[scan-playlist] Nothing to download.", file=sys.stderr)
        return

    to_download = new_ids[:max_new]
    if len(new_ids) > max_new:
        print(f"[scan-playlist] Capping at {max_new} downloads this run (use --max-new to change)", file=sys.stderr)

    for i, vid_id in enumerate(to_download, 1):
        video_url = f"https://www.youtube.com/watch?v={vid_id}"
        print(f"[scan-playlist] [{i}/{len(to_download)}] Downloading {video_url}", file=sys.stderr)
        if dry_run:
            print(f"[scan-playlist]   (dry-run: skipping actual download)", file=sys.stderr)
            continue
        try:
            download_feed(cfg, feed, max_downloads=1, override_url=video_url)
        except Exception as e:
            print(f"[scan-playlist]   ERROR: {e}", file=sys.stderr)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    from datetime import datetime
    print(f"Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    ap = argparse.ArgumentParser(
        description="Enumerate all YouTube playlist items via InnerTube API and download new ones"
    )
    ap.add_argument("feed_id", help="Feed id (directory name under document_root)")
    ap.add_argument("--max-new", type=int, default=10, help="Max new videos to download per run (default: 10)")
    ap.add_argument("--dry-run", action="store_true", help="Enumerate and report new IDs without downloading")
    ap.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    ap.add_argument("--app", default=str(DEFAULT_APP))
    ap.add_argument("--feeds", default=str(DEFAULT_FEEDS))
    args = ap.parse_args()

    scan_and_download(
        app_yaml=Path(args.app),
        feeds_yaml=Path(args.feeds),
        feed_id=args.feed_id,
        max_new=args.max_new,
        verbose=args.verbose,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
