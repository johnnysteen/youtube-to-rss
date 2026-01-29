from __future__ import annotations

import argparse
from .download import main as download_main
from .update_rss import main as update_rss_main


def main() -> None:
    ap = argparse.ArgumentParser(prog="youtube_to_rss")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # Pass-through subcommands (each module has its own argparse)
    sub.add_parser("download", add_help=False)
    sub.add_parser("update-rss", add_help=False)

    args, rest = ap.parse_known_args()

    if args.cmd == "download":
        import sys
        sys.argv = [sys.argv[0], *rest]
        download_main()
    elif args.cmd == "update-rss":
        import sys
        sys.argv = [sys.argv[0], *rest]
        update_rss_main()


if __name__ == "__main__":
    main()

