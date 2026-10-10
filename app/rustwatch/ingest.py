"""Run skinprobe over the mounted skin files and put the results in the database.

Everything the dashboard shows about a skin comes from this path, including in demo mode: the demo
generator writes real texture files and the real analyser reads them, so no finding here is hand
written. Only the item list is synthetic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SKINPROBE = REPO_ROOT / "tools" / "skinprobe"
if _SKINPROBE.is_dir() and str(_SKINPROBE) not in sys.path:
    sys.path.insert(0, str(_SKINPROBE))

from .db import Store, utcnow  # noqa: E402


def _rel_any(path: str | Path, cfg) -> str:
    for root in (Path(cfg.data_dir), Path(cfg.skins_dir)):
        try:
            return str(Path(path).resolve().relative_to(root.resolve()))
        except (ValueError, OSError):
            continue
    return Path(str(path)).name


def _rel(path: str | Path, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(root.resolve()))
    except (ValueError, OSError):
        return Path(str(path)).name


def _split_paths(raw: str | None, cfg) -> tuple[str, str]:
    """A finding points at either a mounted texture or a crop this run produced. Two roots, two columns."""
    if not raw:
        return "", ""
    path = Path(raw)
    try:
        resolved = path.resolve()
    except OSError:
        return "", ""
    crops_root = cfg.crops_dir.resolve()
    if str(resolved).startswith(str(crops_root)):
        return "", str(resolved.relative_to(crops_root))
    # DATA_DIR is tried first: the demo seed writes its skins under it, and a path stored relative to
    # the wrong root is a broken image tag three screens later. Production skins sit under SKINS_DIR.
    for root in (Path(cfg.data_dir), Path(cfg.skins_dir)):
        try:
            return str(resolved.relative_to(root.resolve())), ""
        except ValueError:
            continue
    return path.name, ""


def pending_skins(store: Store, cfg, limit: int, skin_ids: list[str] | None = None) -> list[dict]:
    if skin_ids:
        marks = ",".join("?" for _ in skin_ids)
        return store.rows(f"SELECT id, name, files_path FROM skin WHERE id IN ({marks}) ORDER BY id", tuple(skin_ids))
    return store.rows(
        """
        SELECT id, name, files_path FROM skin
        WHERE scan_status IN ('unscanned', 'unreadable') OR files_status = 'pending'
        ORDER BY id LIMIT ?
        """,
        (limit,),
    )


def ingest_one(store: Store, cfg, skin_id: str, name: str = "") -> dict:
    from skinprobe.scan import scan_skin  # noqa: PLC0415 - imported here so the CLI works before deps exist

    skin_dir = Path(cfg.skins_dir) / skin_id
    if not skin_dir.is_dir() or not any(skin_dir.iterdir()):
        with store.tx() as conn:
            conn.execute(
                "UPDATE skin SET files_status = 'missing', scan_status = 'no-files', analyzed_at = ? WHERE id = ?",
                (utcnow(), skin_id),
            )
        return {"skinId": skin_id, "status": "no-files"}

    out_dir = cfg.crops_dir / skin_id
    corpus = cfg.ledger_dir / "ledger.jsonl"
    marks = cfg.ledger_dir / "marks.jsonl"
    ledgers = [p for p in (corpus, marks) if p.exists()]

    try:
        from skinprobe.ipcheck import load_ledger  # noqa: PLC0415

        ledger: list[dict] = []
        for path in ledgers:
            ledger.extend(load_ledger(path))
        result = scan_skin(
            skin_dir,
            out_dir,
            ledger=ledger,
            skin_name=name,
            crop_max_distance=cfg.ledger_crop_max_distance,
            texture_max_distance=cfg.ledger_texture_max_distance,
        )
    except ValueError as exc:
        with store.tx() as conn:
            conn.execute(
                "UPDATE skin SET files_status = 'present', scan_status = 'unreadable', analyzed_at = ?, notes = ? WHERE id = ?",
                (utcnow(), json.dumps({"error": str(exc)}), skin_id),
            )
        return {"skinId": skin_id, "status": "unreadable", "error": str(exc)}

    inserted = 0
    skipped = 0
    with store.tx() as conn:
        conn.execute("DELETE FROM texture WHERE skin_id = ?", (skin_id,))
        conn.execute(
            "UPDATE skin SET files_status = 'present', files_path = ?, scan_status = ?, analyzed_at = ?, group_count = ?, notes = ? WHERE id = ?",
            (str(skin_dir), result.skin.status, utcnow(), len(result.skin.groups), json.dumps({"notes": result.skin.notes, "format": result.skin.format}), skin_id),
        )
        for item in result.metrics:
            conn.execute(
                """
                INSERT INTO texture(skin_id, group_index, slot, path, width, height, mode, md5, dhash,
                                    seam_ratio, blank, cut_fraction, unique_colors, is_power_of_two, error)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    skin_id,
                    next((g.index for g in result.skin.groups if any(p == Path(item["path"]) for p in g.paths.values())), 0),
                    item["slot"],
                    _rel_any(item["path"], cfg),
                    item.get("width", 0),
                    item.get("height", 0),
                    item.get("mode", ""),
                    item.get("md5", ""),
                    item.get("dhash", ""),
                    item.get("seam_ratio", 0.0),
                    1 if item.get("is_blank") else 0,
                    item.get("cut_fraction", 0.0),
                    item.get("unique_colors", 0),
                    1 if item.get("is_power_of_two") else 0,
                    item.get("error", ""),
                ),
            )
        for finding in result.findings:
            texture_rel, crop_rel = _split_paths(finding.get("texture"), cfg)
            source_url = (finding.get("sources") or [{}])[0].get("url", "") if finding.get("sources") else ""
            dedupe = f"{skin_id}:{finding['code']}:{source_url or finding.get('texture') or ''}"
            if conn.execute("SELECT 1 FROM finding WHERE dedupe_key = ?", (dedupe,)).fetchone():
                skipped += 1
                continue
            conn.execute(
                """
                INSERT INTO finding(skin_id, code, severity, title, detail, texture_path, crop_path, sources,
                                    needs_human, created_at, dedupe_key)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    skin_id,
                    finding["code"],
                    finding["severity"],
                    finding["title"],
                    finding["detail"],
                    texture_rel,
                    crop_rel,
                    json.dumps(finding.get("sources") or []),
                    1 if finding.get("needsHuman") else 0,
                    utcnow(),
                    dedupe,
                ),
            )
            inserted += 1
    return {
        "skinId": skin_id,
        "status": result.skin.status,
        "format": result.skin.format,
        "textures": len(result.metrics),
        "crops": len(result.logos),
        "findingsAdded": inserted,
        "findingsKept": skipped,
    }


def run(store: Store, cfg, limit: int | None = None, log=print, skin_ids: list[str] | None = None) -> dict:
    if not Path(cfg.skins_dir).is_dir():
        return {"skipped": True, "reason": f"no skin files mounted at {cfg.skins_dir}"}
    todo = pending_skins(store, cfg, limit or cfg.ingest_limit, skin_ids)
    results = []
    for row in todo:
        outcome = ingest_one(store, cfg, row["id"], row.get("name") or "")
        results.append(outcome)
        log(f"  {outcome['skinId']}: {outcome['status']}" + (f" (+{outcome.get('findingsAdded', 0)} findings)" if "findingsAdded" in outcome else ""))
    return {"scanned": len(results), "results": results, "counts": store.counts()}
