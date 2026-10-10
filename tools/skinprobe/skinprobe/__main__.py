from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .scan import run
from .selftest import run_selftest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skinprobe", description="Read a Rust skin's files and score IP risk")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="scan one skin folder or a root of skin folders")
    scan.add_argument("target", type=Path)
    scan.add_argument("--out", type=Path, default=Path("skinprobe-out"))
    scan.add_argument("--corpus", type=Path, help="JSONL of licensed/known artwork: dhash, kind, title, owner, sourceUrl, licenseClause, verified")
    scan.add_argument("--trademarks", type=Path, help="JSONL of marks: mark, sourceUrl, verified")
    scan.add_argument("--names", type=Path, help="JSON file mapping skin id to display name, for the name check")
    scan.add_argument("--provider", default="manual", choices=["manual", "serpapi", "tineye", "none"])
    scan.add_argument("--max-logos", type=int, default=8)
    scan.add_argument("--all-slots", action="store_true", help="also hunt logo crops in bump, spec, emissive maps")
    scan.add_argument("--json", action="store_true", help="print findings JSON to stdout")

    sub.add_parser("selftest", help="build synthetic skins and assert the reader and scorer work")

    ledger = sub.add_parser("ledger", help="crawl marketplace pages for licence clauses and build the corpus")
    ledger.add_argument("--site", type=Path, required=True, help="site config JSON")
    ledger.add_argument("--out", type=Path, default=Path("ledger-out"))
    ledger.add_argument("--cache-dir", type=Path, help="where page snapshots live (default: <out>/cache)")
    ledger.add_argument("--offline", type=Path, help="read saved HTML from this dir instead of the network")
    ledger.add_argument("--max-items", type=int)
    ledger.add_argument("--min-interval", type=float, help="seconds between requests to one host")
    ledger.add_argument("--user-agent", help="put a contact address in it, that is what it is for")
    ledger.add_argument("--dry-run", action="store_true", help="walk and report, write nothing")

    args = parser.parse_args(argv)
    if args.command == "selftest":
        return run_selftest()

    if args.command == "ledger":
        from .ledger import build as build_ledger

        try:
            summary = build_ledger(
                args.site,
                args.out,
                cache_dir=args.cache_dir,
                offline_dir=args.offline,
                max_items=args.max_items,
                min_interval=args.min_interval,
                user_agent=args.user_agent,
                dry_run=args.dry_run,
            )
        except FileNotFoundError:
            print(f"skinprobe: no site config at {args.site}", file=sys.stderr)
            return 2
        except Exception as exc:  # noqa: BLE001
            print(f"skinprobe: ledger run stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(f"{summary['site']}: visited {summary['visited']}, items {summary['items']}, rows {summary['ledgerRows']}, changes {summary['changes']}")
        print(f"blocked by robots.txt: {summary['limits']['blockedByRobots']}, http errors: {summary['limits']['httpErrors']}")
        if not summary["items"]:
            print("nothing was recognised as a product page. Check itemUrlPatterns against a live URL.")
        return 0

    if not args.target.exists():
        print(f"skinprobe: no such path: {args.target}", file=sys.stderr)
        return 2
    if args.corpus and not args.corpus.exists():
        print(f"skinprobe: corpus not found: {args.corpus}", file=sys.stderr)
        return 2
    if args.trademarks and not args.trademarks.exists():
        print(f"skinprobe: marks ledger not found: {args.trademarks}", file=sys.stderr)
        return 2

    names = json.loads(args.names.read_text(encoding="utf-8")) if args.names else None
    payload = run(
        args.target,
        args.out,
        corpus=args.corpus,
        trademark_ledger=args.trademarks,
        skin_names=names,
        provider=args.provider,
        max_logos=args.max_logos,
        all_slots=args.all_slots,
    )
    if args.json:
        print(json.dumps(payload, indent=2))
    summary = payload["summary"]
    print(f"{summary['read']} of {summary['skins']} skin(s) read into {args.out}")
    for skin in payload["skins"]:
        marker = "REVIEW" if skin["needsReview"] else "clear  "
        print(f"  [{marker}] {skin['skinId']}: {len(skin['findings'])} finding(s), {len(skin['logoCandidates'])} crop(s)")
    for err in payload["errors"]:
        print(f"  [ERROR  ] {err['skinId']}: {err['error']}")
    return 2 if summary["skins"] == summary["unreadable"] else (1 if summary["needsReview"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
