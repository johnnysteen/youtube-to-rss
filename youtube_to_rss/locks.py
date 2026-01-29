# youtube_to_rss/locks.py
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import fcntl

@contextmanager
def exclusive_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield

