"""One image, one package, four commands. Compose runs serve, watch and bot as separate
containers; seed and ledger are things an operator runs by hand.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rustwatch", description="Rust store rotation watcher and skin review")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the dashboard API")
    sub.add_parser("watch", help="poll the catalog on an interval")
    sub.add_parser("once", help="one watch pass, then exit (for cron)")
    sub.add_parser("scan", help="analyse mounted skin files once")
    sub.add_parser("bot", help="build and deliver Discord posts on an interval")
    seed = sub.add_parser("seed", help="generate demo listings, then analyse them for real")
    seed.add_argument("--reset", action="store_true")
    ledger = sub.add_parser("ledger", help="crawl one marketplace config into the licence ledger")
    ledger.add_argument("--site", required=True)
    ledger.add_argument("--out", default=None)
    ledger.add_argument("--max-items", type=int, default=None)
    ledger.add_argument("--offline", default=None)
    ledger.add_argument("--dry-run", action="store_true")
    sub.add_parser("smoke", help="seed a temp dir, serve it, hit the routes, exit")
    sub.add_parser("version", help="print the version")
    args = parser.parse_args(argv)

    if args.command == "version":
        from . import __version__

        print(__version__)
        return 0

    config = Config()
    config.ensure_dirs()

    if args.command == "serve":
        import uvicorn

        from .server import create

        # create() wires the config and the store into the module globals the routes read. Passing
        # the bare `app` instead answers 503 on every JSON route, which is how this was caught.
        uvicorn.run(create(config), host=config.host, port=config.port, log_level="info")
        return 0

    if args.command in ("watch", "once"):
        from .db import Store
        from .watcher import loop as watch_loop
        from .watcher import run_once as watch_once

        store = Store(config.db_path)
        if args.command == "once":
            print(watch_once(store, config))
            return 0
        watch_loop(store, config)
        return 0

    if args.command == "scan":
        from .db import Store
        from .ingest import run as ingest_run

        print(ingest_run(Store(config.db_path), config))
        return 0

    if args.command == "bot":
        from .bot import loop as bot_loop
        from .db import Store

        bot_loop(Store(config.db_path), config)
        return 0

    if args.command == "seed":
        import shutil

        from .seed import seed as seed_demo

        if args.reset:
            for suffix in ("", "-wal", "-shm"):
                Path(str(config.db_path) + suffix).unlink(missing_ok=True)
            shutil.rmtree(config.data_dir / "demo", ignore_errors=True)
            shutil.rmtree(config.crops_dir, ignore_errors=True)
            (config.ledger_dir / "ledger.jsonl").unlink(missing_ok=True)
            (config.ledger_dir / "marks.jsonl").unlink(missing_ok=True)
            # Never rmtree the mount point itself: inside Docker SKINS_DIR is a bind mount.
            if config.skins_dir.is_dir():
                for child in config.skins_dir.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        child.unlink(missing_ok=True)
        seed_demo(config)
        return 0

    if args.command == "ledger":
        from skinprobe.ledger.build import build as ledger_build

        out = Path(args.out or (config.ledger_dir / "runs" / Path(args.site).stem))
        summary = ledger_build(
            Path(args.site),
            out,
            offline_dir=Path(args.offline) if args.offline else None,
            max_items=args.max_items,
            dry_run=args.dry_run,
        )
        print(summary)
        return 0

    if args.command == "smoke":
        from .smoke import run as smoke_run

        return smoke_run()

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
