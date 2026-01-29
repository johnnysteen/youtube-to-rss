# youtube_to_rss/download.py
from __future__ import annotations

import argparse
import sys
import os
import subprocess
import time
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from .locks import exclusive_lock


# ----------------------------
# Config models + loading
# ----------------------------

@dataclass(frozen=True)
class AppConfig:
    host: str
    document_root: Path
    default_numdl: int
    dateafter: str  # YYYYMMDD
    yt_dlp_exe: str
    yt_common_args: list[str]
    yt_extractor_args: str | None
    cookies_file: str | None
    use_cookies_on_fail: bool
    fail_signatures: list[str]



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

    auth = app.get("auth", {}) or {}
    yt = app.get("yt_dlp", {}) or {}

    cfg = AppConfig(
        host=str(app["site"]["host"]).strip().replace("https://", "").replace("http://", ""),
        document_root=Path(app["site"]["document_root"]).expanduser().resolve(),
        default_numdl=int(app["defaults"]["numdl"]),
        dateafter=str(app["defaults"]["dateafter"]).replace("-", ""),
        yt_dlp_exe=str(yt.get("executable", "yt-dlp")),
        yt_common_args=list(yt.get("common_args", [])),
        yt_extractor_args=yt.get("extractor_args"),
        cookies_file=auth.get("cookies_file"),
        use_cookies_on_fail=bool(auth.get("use_cookies_on_fail", False)),
        fail_signatures=list(auth.get("fail_signatures", [])),
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
# Subprocess helpers
# ----------------------------

@dataclass
class RunResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str



def run(cmd: list[str], cwd: Path, *, log_path: Path | None = None, append: bool = True) -> RunResult:
    log = None
    try:
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log = log_path.open("a" if append else "w", encoding="utf-8")

        p = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        assert p.stdout is not None
        # If you want to keep *some* text for error messages, buffer only last N lines:
        tail: list[str] = []
        TAIL_N = 0

        for line in p.stdout:
            #sys.stdout.write(line)
            #sys.stdout.flush()
            if log:
                log.write(line)
                log.flush()

            tail.append(line)
            if len(tail) > TAIL_N:
                tail.pop(0)

        rc = p.wait()

        return RunResult(
            ok=(rc in (0, 101)),        # 101 is "early stop" / partial in yt-dlp-land
            returncode=rc,
            stdout="".join(tail),       # last N lines only (bounded memory)
            stderr="",                  # stderr merged into stdout
        )
    finally:
        if log:
            log.close()


def looks_auth_related(text: str, signatures: Iterable[str]) -> bool:
    t = text.lower()
    return any(sig.lower() in t for sig in signatures)

def inbox_has_new_video_json(cwd: Path, run_id: str) -> bool:
    # video info jsons are like <id><run_id>.info.json
    # playlist jsons are like UC...<run_id>.info.json (and have _type=playlist)
    for p in cwd.glob(f"*{run_id}.info.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("_type", "video") != "playlist":
                return True
        except Exception:
            continue
    return False


def yt_dlp_with_cookie_fallback(
    cfg: AppConfig,
    cwd: Path,
    url: str,
    outtmpl: str,
    extra_args: list[str],
    log_path: Path,
    append_log: bool,
    run_id: str
) -> None:
    """
    Run yt-dlp once without cookies, and only retry with cookies if:
      - enabled in config
      - cookies_file is set
      - stderr/stdout looks auth-related per signatures
    """
    cmd = [cfg.yt_dlp_exe, "-o", outtmpl, *cfg.yt_common_args, url]
    if cfg.yt_extractor_args:
        cmd.extend(["--extractor-args", cfg.yt_extractor_args])
    cmd.extend(extra_args)


    mode = "a" if append_log else "w"
    with log_path.open(mode, encoding="utf-8") as f:
        f.write(f"\n===== yt-dlp (no cookies) =====\n")
        f.write("CMD: " + " ".join(cmd) + "\n\n")
        #f.write(r1.stdout)
        #f.write(r1.stderr)
    r1 = run(cmd, cwd=cwd, log_path=log_path, append=True)

    # Consider success if yt-dlp exited cleanly (0) OR "stopped early" (101)
    if r1.returncode in (0, 101):
        return

    # Even with non-zero rc, tolerate partial failures if we produced any video .info.json
    if inbox_has_new_video_json(cwd, run_id):
        return



    # Retry with cookies only when appropriate
    if (
        cfg.use_cookies_on_fail
        and cfg.cookies_file
        and looks_auth_related(r1.stdout + "\n" + r1.stderr, cfg.fail_signatures)
    ):
        cmd2 = [cfg.yt_dlp_exe, "--cookies", cfg.cookies_file, "-o", outtmpl, *cfg.yt_common_args, url]
        if cfg.yt_extractor_args:
            cmd2.extend(["--extractor-args", cfg.yt_extractor_args])
        cmd2.extend(extra_args)

        r2 = run(cmd2, cwd=cwd, log_path=log_path, append=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n===== yt-dlp (WITH cookies retry) =====\n")
            f.write("CMD: " + " ".join(cmd2) + "\n\n")
            f.write(r2.stdout)
            f.write(r2.stderr)

        if r2.ok:
            return

    raise RuntimeError(f"yt-dlp failed (rc={r1.returncode}). See log: {log_path}")


# ----------------------------
# Download phase
# ----------------------------

def download_feed(cfg: AppConfig, feed: FeedConfig, max_downloads: int | None, override_url: str | None) -> None:
    feed_dir = cfg.document_root / feed.id
    inbox_dir = feed_dir / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    # One lock per feed, download phase only
    lock_path = feed_dir / "download.lock"

    # Per-run version token (same idea as your uniqid)
    run_id = str(int(time.time()))

    # Keep your current filename scheme: %(id)s{run_id}.%(ext)s
    outtmpl = f"%(id)s{run_id}.%(ext)s"

    # Log in feed root (like you currently do). Could also put it under inbox/.
    log_path = feed_dir / "download.log"

    channel_url = override_url or feed.channelurl
    numdl = cfg.default_numdl if max_downloads is None else int(max_downloads)

    # Use archive in feed root (stable), but run yt-dlp *inside inbox* so outputs stage there.
    # We override the archive path by replacing "--download-archive archive" with "../archive".
    # If your common_args already include ["--download-archive", "archive"], this rewrites it safely.
    rewritten_common: list[str] = []
    i = 0
    while i < len(cfg.yt_common_args):
        a = cfg.yt_common_args[i]
        if a == "--download-archive" and i + 1 < len(cfg.yt_common_args):
            # point archive to feed root
            rewritten_common.extend(["--download-archive", str(feed_dir / "archive")])
            i += 2
            continue
        rewritten_common.append(a)
        i += 1

    cfg2 = AppConfig(
        host=cfg.host,
        document_root=cfg.document_root,
        default_numdl=cfg.default_numdl,
        dateafter=cfg.dateafter,
        yt_dlp_exe=cfg.yt_dlp_exe,
        yt_common_args=rewritten_common,
        yt_extractor_args=cfg.yt_extractor_args,
        cookies_file=cfg.cookies_file,
        use_cookies_on_fail=cfg.use_cookies_on_fail,
        fail_signatures=cfg.fail_signatures,
    )

    with exclusive_lock(lock_path):
        print(f"[download] feed={feed.id} url={channel_url}", file=os.sys.stderr)
        print(f"[download] staging into {inbox_dir}", file=os.sys.stderr)

        # Call 1: "Downloading {numdl} videos..." (skip if numdl == 0)
        if numdl != 0:
            yt_dlp_with_cookie_fallback(
                cfg=cfg2,
                cwd=inbox_dir,
                url=channel_url,
                outtmpl=outtmpl,
                extra_args=["--max-downloads", str(numdl)],
                log_path=log_path,
                append_log=False,
                run_id=run_id
            )

        # Call 2: up to 30 videos after dateafter
        yt_dlp_with_cookie_fallback(
            cfg=cfg2,
            cwd=inbox_dir,
            url=channel_url,
            outtmpl=outtmpl,
            extra_args=[
                "--break-match-filter", f"upload_date>{cfg2.dateafter}",
                "--max-downloads", "30",
            ],
            log_path=log_path,
            append_log=True,
            run_id=run_id
        )


# ----------------------------
# CLI
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="youtube-to-rss download phase (stages into inbox/)")
    ap.add_argument("--app", default="configs/app.yaml")
    ap.add_argument("--feeds", default="configs/feeds.yaml")

    ap.add_argument("feed_id", help="Feed id (directory name under document_root / podcasts/)")
    ap.add_argument("-n", "--max-downloads", type=int, default=None, help="Override numdl for this run")
    ap.add_argument("-v", "--override-url", default=None, help="Override channel URL for this run")

    args = ap.parse_args()

    cfg, feeds = load_configs(Path(args.app), Path(args.feeds))
    feed = feeds.get(args.feed_id)
    if not feed:
        raise SystemExit(f"Unknown feed_id: {args.feed_id}")

    download_feed(cfg, feed, args.max_downloads, args.override_url)


if __name__ == "__main__":
    main()

