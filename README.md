# youtube-to-rss

A small, reliable system for turning YouTube (and similar platforms supported by `yt-dlp`) into podcast-style RSS feeds.

This project is designed for **long-running, unattended use** (cron + systemd), with an emphasis on:
- robustness against partial failures
- not reprocessing old content
- not loading huge RSS files into memory
- tolerating YouTube’s frequent breakage without human babysitting

---

## High-level design

The system is deliberately split into **two phases**:

1. **Download phase** (`y2r download`)
   - Triggered by cron
   - Uses `yt-dlp`
   - Writes audio files and metadata into a per-feed `inbox/`
   - Quiet by default; detailed output goes to log files

2. **RSS update phase** (`y2r update-rss`)
   - Triggered automatically by systemd path watchers
   - Consumes `.info.json` files from `inbox/`
   - Appends new `<item>` entries to the RSS feed without loading the whole file
   - Moves processed files out of the inbox

This separation avoids lock-file hacks and makes failure modes obvious and recoverable.

---

## Directory layout

### Repository
```

youtube-to-rss/
├── youtube_to_rss/        # Python package
├── configs/
│   ├── app.yaml           # Global config (paths, yt-dlp options, etc.)
│   └── feeds.yaml         # Feed definitions
├── env/                   # Python virtualenv (not committed)
├── install-watchers.sh
├── uninstall-watchers.sh
├── status-watchers.sh
├── pyproject.toml
└── README.md

```

### Per-feed media directories (under document root)
```

<document_root>/<feed>/
├── feed.rss
├── feed.body              # RSS item body (append-only)
├── inbox/                 # New downloads waiting to be processed
├── processing/            # Temporary working area for update-rss
├── archive                 # yt-dlp download archive
├── download.log
└── cron.log

````

Only files in `inbox/` are considered “new”.

---

## Configuration

### `configs/app.yaml`
Global settings, including:
- document root
- site URL
- yt-dlp executable path (absolute!)
- common yt-dlp arguments
- cookie handling

Example (abridged):

```yaml
site:
  base_url: https://example.com
  document_root: /media/Tuscany/Library/WebServer/Documents

yt_dlp:
  executable: /usr/local/bin/yt-dlp
  common_args:
    - --restrict-filenames
    - --write-info-json
    - -x
    - -c
    - -i
  extractor_args: youtube:player_client=default,-android_sdkless
````

> **Important:** Use an absolute path for `yt-dlp`. Cron does not inherit your shell `$PATH`.

---

### `configs/feeds.yaml`

Defines each feed:

```yaml
feeds:
  - id: sensusfidelium
    title: "Sensus Fidelium"
    channel_url: https://www.youtube.com/user/onearmsteve4192/videos
    image_url: https://example.com/image.jpg
```

The `id` must match the directory name under the document root.

---

## Installation

### 1. Create and install the virtualenv

```bash
python3 -m venv env
source env/bin/activate
pip install -e .
```

### 2. Install systemd watchers

```bash
./install-watchers.sh
```

This:

* creates `inbox/` and `processing/` directories
* installs systemd *user* units
* enables linger so they run without login
* enables and starts watchers for all feeds

---

## Cron jobs (downloads only)

Cron should **only** run downloads. RSS updates are handled by systemd.

Example:

```cron
*/10 0,4-23 * * * cd /home/pi/youtube-to-rss && /home/pi/youtube-to-rss/env/bin/y2r download random -n 1 >> /media/Tuscany/Library/WebServer/Documents/random/cron.log 2>&1
```

Notes:

* Always `cd` into the repo (or rely on absolute config defaults).
* Output is logged, not printed.
* Partial failures are tolerated.

---

## Runtime behavior and failure policy

* `yt-dlp` return code `101` is treated as non-fatal.
* Playlist items that:

  * are premieres
  * are age-gated
  * require login
    are skipped without failing the run.
* If **any new `.info.json`** is produced, the run is considered successful.
* Cookie fallback is only attempted for global failures.

This matches real-world `yt-dlp` behavior and avoids constant false alarms.

---

## Monitoring and debugging

### View cron logs

```bash
tail -f <document_root>/<feed>/cron.log
```

### View yt-dlp logs

```bash
tail -f <document_root>/<feed>/download.log
```

### View RSS update activity

```bash
journalctl --user -u 'y2r-update@*.service' -f
```

### Check system status

```bash
./status-watchers.sh
```

---

## Development notes

* RSS updates are append-only; large feeds are never fully loaded into memory.
* The code favors explicit behavior over clever abstractions.

---

## License

MIT


