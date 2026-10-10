"""Rotation detection: poll the catalog digest, diff against what is stored, open a rotation.

A rotation is something we observe, not something we are told. `first_seen` is therefore the only
honest date in this table, and nothing in the app may present it as a release date.
"""

from __future__ import annotations

import json
import time

from .db import Store, utcnow
from .steam import SteamError, load_catalog


def run_once(store: Store, cfg) -> dict:
    started = time.time()
    try:
        digest, items, source = load_catalog(cfg)
    except SteamError as exc:
        store.set_meta("last_watch_error", f"{utcnow()} {exc}")
        return {"changed": False, "error": str(exc), "source": "none"}

    from .steam import stub_observed_at  # noqa: PLC0415

    observed = stub_observed_at(cfg) or utcnow()
    known = store.digest()
    store.set_meta("last_watch_at", observed)
    store.set_meta("catalog_source", source)
    store.set_meta("last_watch_error", "")

    limited = [i for i in items if i["limited"]] or items
    by_id = {i["id"]: i for i in limited if i["id"]}

    if digest == known:
        with store.tx() as conn:
            rotation = store.open_rotation()
            if rotation:
                conn.execute("UPDATE rotation SET last_seen = ?, item_count = ?, source = ? WHERE id = ?", (observed, len(by_id), source, rotation["id"]))
        return {"changed": False, "digest": digest, "items": len(by_id), "source": source, "elapsedSec": round(time.time() - started, 2)}

    rotation_id: int | None = None
    with store.tx() as conn:
        cur = conn.execute(
            "INSERT INTO rotation(digest, first_seen, last_seen, item_count, source) VALUES(?,?,?,?,?)",
            (digest, observed, observed, len(by_id), source),
        )
        rotation_id = int(cur.lastrowid or 0)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('steam_digest', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (digest,),
        )

    new_ids: list[str] = []
    gone: list[str] = []
    with store.tx() as conn:
        existing = {r["id"]: r for r in store.rows("SELECT id, name, first_seen_rotation FROM skin")}
        for item_id, item in by_id.items():
            row = existing.get(item_id)
            if row is None:
                conn.execute(
                    """
                    INSERT INTO skin(id, name, item_shortname, store_tags, tradable, icon_url,
                                     first_seen_rotation, last_seen_rotation, files_status, scan_status, notes)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        item_id,
                        item["name"],
                        item["item_shortname"],
                        item["store_tags"],
                        item["tradable"],
                        item["icon_url"],
                        rotation_id,
                        rotation_id,
                        "pending" if cfg.skins_dir.is_dir() else "not-mounted",
                        "unscanned",
                        json.dumps({"catalogSource": source, "displayType": item["display_type"], "rawModified": item["raw_modified"]}),
                    ),
                )
                new_ids.append(item_id)
            else:
                conn.execute(
                    "UPDATE skin SET name = ?, item_shortname = ?, store_tags = ?, icon_url = ?, last_seen_rotation = ? WHERE id = ?",
                    (item["name"], item["item_shortname"], item["store_tags"], item["icon_url"], rotation_id, item_id),
                )
        for item_id, row in existing.items():
            if item_id not in by_id:
                gone.append(item_id)

    return {
        "changed": True,
        "digest": digest,
        "rotationId": rotation_id,
        "items": len(by_id),
        "new": new_ids,
        "noLongerListed": gone,
        "source": source,
        "elapsedSec": round(time.time() - started, 2),
    }


def loop(store: Store, cfg, log=print) -> None:
    from pathlib import Path as _P

    from .ingest import run as ingest_run

    log(f"watcher started: every {cfg.watch_interval_min} min, source {'stub' if cfg.resolved_stub() else 'steam'}")
    first = True
    while True:
        if first and not cfg.watch_on_start:
            first = False
            time.sleep(max(30, cfg.watch_interval_min * 60))
            continue
        first = False
        result = run_once(store, cfg)
        if result.get("error"):
            log(f"watch failed: {result['error']}")
        elif result.get("changed"):
            log(f"rotation #{result.get('rotationId')} opened, {len(result.get('new') or [])} new skin(s)")
        else:
            log(f"no change ({result.get('items', 0)} store items, digest {str(result.get('digest'))[:12]})")
        if _P(cfg.skins_dir).is_dir():
            scan = ingest_run(store, cfg, log=log)
            if not scan.get("skipped") and scan.get("scanned"):
                log(f"scanned {scan['scanned']} pending skin(s)")
        time.sleep(max(30, cfg.watch_interval_min * 60))
