"""Demo seed: synthetic store listings, real texture files, real analysis.

What is fake here is only the item list and the marketplace page. The skins are genuine manifest plus
PNG files, and every number on screen comes from running the same analyser you would run in production
over them, including the deliberate defects. That keeps the demo honest and keeps it useful: the code
under test is the code you ship.

Deliberate defects, one per row, so every state in DESIGN.md section 7 and 11 exists on screen:
  700001 clean tileable pattern            -> no findings
  700002 planted emblem, later ledger hit  -> IP-LOGO-CANDIDATE then LIC-NC-HIT
  700003 pasted photo, no wrap closure     -> IP-PASTE-SEAM
  700004 blank _MainTex on group 1         -> TEC-BLANK-MAINTEX
  700005 300x300 map                       -> TEC-NON-POT
  700006 legacy Unity .mat upload          -> parsed as legacy format
  700007 name collides with a mark         -> TM-NAME-HIT
  700008 never downloaded                   -> no-files state
  700009 textures with no manifest          -> unreadable state, visible as a failure
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from .bot import run_once as bot_run_once
from .config import Config
from .db import Store
from .ingest import run as ingest_run
from .watcher import run_once as watch_run_once

NAMES = {
    "700001": ("Winter Camo Double Door", "door.double.housed_wood"),
    "700002": ("Salvage Bandana", "mask.bandana"),
    "700003": ("Desert Scorpian Rifle", "rifle.bolt"),
    "700004": ("Ridge Mining Helmet", "hat.miner"),
    "700005": ("Field Boots", "shoes.boots"),
    "700006": ("Old Wood Hatchet", "hatchet"),
    "700007": ("Tactical 4x ACOG Scope", "rifle.semiauto"),
    "700008": ("Deep Sea Sleeping Bag", "sleepingbag.lv2"),
    "700009": ("Workbench Panel", "workbench1"),
    "700010": ("Riot Face Mask", "metal.facemask"),
    "700011": ("Palm Shirt", "shirt.tanktop"),
    "700012": ("Cargo Longswords", "sword.launcher"),
    "700013": ("Scrap Plate Vest", "chest.plate"),
    "700014": ("Highland Kilt", "roadsign.kilt"),
    "700015": ("Harbour Rockets", "rocket.launcher"),
    "700016": ("Sunburst Bow", "bow.hunter"),
    "700017": ("Ember Tool Cabinet", "toolcabinet"),
    "700018": ("Tundra Snow Jacket", "jacket.snow"),
}

ROTATIONS = {
    "cat-1.json": ["700001", "700002", "700003", "700004", "700005", "700006", "700007", "700008"],
    "cat-2.json": ["700001", "700002", "700003", "700004", "700005", "700006", "700007", "700008", "700009", "700010", "700011", "700012", "700013"],
    "cat-3.json": ["700001", "700002", "700003", "700004", "700005", "700006", "700007", "700008", "700009", "700010", "700011", "700012", "700013", "700014", "700015", "700016", "700017", "700018"],
}


def _tile(size: int, cells: int, palette: tuple[tuple[int, int, int], tuple[int, int, int]]) -> np.ndarray:
    step = max(1, size // cells)
    grid = (np.arange(size) // step) % 2
    mask = (grid[:, None] + grid[None, :]) % 2
    a = np.array(palette[0], dtype=np.uint8)
    b = np.array(palette[1], dtype=np.uint8)
    return np.where(mask[..., None] > 0, a, b).astype(np.uint8)


def _pattern(size: int, variant: int) -> np.ndarray:
    """Structurally different test maps. Varying the layout, not adding grain: fine noise makes every
    colour rare, which is what turned a demo into 70 bogus logo crops in an earlier revision."""
    y, x = np.mgrid[0:size, 0:size]
    dark = (24, 30, 36)
    light = (150, 138, 116)
    mid = (72, 96, 104)
    if variant % 6 == 0:
        cells = 8
        step = size // cells
        mask = ((x // step) + (y // step)) % 2
        base = np.where(mask[..., None] > 0, light, dark)
    elif variant % 6 == 1:
        step = max(6, size // (4 + variant))
        base = np.where(((x // step) % 2)[..., None] > 0, mid, dark)
    elif variant % 6 == 2:
        step = size // 6
        base = np.where(((y // step) % 3 == 0)[..., None], light, (40, 46, 52))
    elif variant % 6 == 3:
        step = size // 10
        base = np.where((((x + y) // step) % 2)[..., None] > 0, light, (30, 52, 44))
    elif variant % 6 == 4:
        frame = ((x // 16) + (y // 16)) % 3
        base = np.where((frame == 0)[..., None], light, np.where((frame == 1)[..., None], mid, dark))
    else:
        wedge = (x > size // 2) ^ (y > x - size // 3)
        base = np.where(wedge[..., None], (168, 92, 40), (36, 40, 48))
    return np.clip(base, 0, 255).astype(np.uint8)


def _noise(size: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.integers(40, 200, size * size * 3, dtype=np.uint8).reshape(size, size, 3)
    smooth = np.zeros_like(base)
    smooth[2:-2, 2:-2] = base[2:-2, 2:-2]
    return smooth if smooth.any() else base


def _write(arr: np.ndarray, path: Path, mode: str = "RGB") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr.astype(np.uint8), mode).save(path)


def _manifest(item_shortname: str, groups: list[dict]) -> str:
    return json.dumps({"ItemType": item_shortname, "Groups": groups}, indent=2)


def build_skins(skins_dir: Path, ledger_dir: Path) -> None:
    size = 256
    # Clear children, not the directory: inside Docker SKINS_DIR is a bind mount and rmtree on it fails.
    if skins_dir.exists():
        for child in skins_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    skins_dir.mkdir(parents=True, exist_ok=True)

    base = _pattern(size, 0)
    _write(base, skins_dir / "700001" / "_maintex0" / "_MainTex0.png")
    (skins_dir / "700001" / "manifest").mkdir(parents=True, exist_ok=True)
    (skins_dir / "700001" / "manifest" / "manifest.txt").write_text(_manifest("door.double.housed_wood", [{"Textures": {"_MainTex": "_MainTex0.png"}, "Floats": {"_Glossiness": 0.4}}]), encoding="utf-8")

    # Its own gross layout, deliberately: dHash compares composition, so a mark placed on 700001's
    # checkerboard reads as a near-duplicate of that checkerboard and one seeded corpus row would
    # light up every flat tile in the demo.
    emblem = _pattern(size, 3)
    emblem[88:168, 88:168] = (14, 226, 20)
    emblem[112:144, 112:144] = (250, 250, 250)
    _write(emblem, skins_dir / "700002" / "_maintex0" / "_MainTex0.png")
    (skins_dir / "700002" / "manifest").mkdir(parents=True, exist_ok=True)
    (skins_dir / "700002" / "manifest" / "manifest.txt").write_text(_manifest("mask.bandana", [{"Textures": {"_MainTex": "_MainTex0.png"}, "Floats": {"_Glossiness": 0.5}, "Colors": {"_Color": {"r": 1, "g": 1, "b": 1}}}]), encoding="utf-8")

    # A photo pasted onto UVs: continuous inside, and the wrap does not close.
    ramp = np.linspace(18, 238, size, dtype=np.uint8)
    pasted = np.dstack([np.tile(ramp, (size, 1))] * 3).astype(np.uint8)
    pasted = np.clip(pasted.astype(np.int16) + _noise(size, 3).astype(np.int16) // 3, 0, 255).astype(np.uint8)
    _write(pasted, skins_dir / "700003" / "_maintex0" / "_MainTex0.png")
    (skins_dir / "700003" / "manifest").mkdir(parents=True, exist_ok=True)
    (skins_dir / "700003" / "manifest" / "manifest.txt").write_text(_manifest("rifle.bolt", [{"Textures": {"_MainTex": "_MainTex0.png"}, "Floats": {"_Glossiness": 0.8}}]), encoding="utf-8")

    _write(_pattern(size, 4), skins_dir / "700004" / "_maintex0" / "_MainTex0.png")
    _write(np.full((size, size, 3), 255, dtype=np.uint8), skins_dir / "700004" / "_maintex1" / "_MainTex1.png")
    (skins_dir / "700004" / "manifest").mkdir(parents=True, exist_ok=True)
    (skins_dir / "700004" / "manifest" / "manifest.txt").write_text(
        _manifest(
            "hat.miner",
            [
                {"Textures": {"_MainTex": "_MainTex0.png", "_EmissionMap": "none"}, "Floats": {"_Glossiness": 0.3}, "Colors": {"_Color": {"r": 1, "g": 1, "b": 1}}},
                {"Textures": {"_MainTex": "_MainTex1.png"}, "Floats": {"_Glossiness": 0.3}},
            ],
        ),
        encoding="utf-8",
    )

    _write(_tile(300, 7, ((90, 90, 96), (40, 40, 44))), skins_dir / "700005" / "_maintex0" / "_MainTex0.png")
    (skins_dir / "700005" / "manifest").mkdir(parents=True, exist_ok=True)
    (skins_dir / "700005" / "manifest" / "manifest.txt").write_text(_manifest("shoes.boots", [{"Textures": {"_MainTex": "_MainTex0.png"}, "Floats": {"_Glossiness": 0.2}}]), encoding="utf-8")

    legacy = skins_dir / "700006"
    legacy.mkdir(parents=True, exist_ok=True)
    _write(_tile(size, 5, ((120, 74, 40), (48, 30, 18))), legacy / "mydiffuse.png")
    (legacy / "mydiffuse.png.meta").write_text("fileFormatVersion: 2\nguid: 1a2b3c4d5e6f708192a3b4c5d6e7f809\n", encoding="utf-8")
    (legacy / "skin.mat").write_text(
        "%YAML 1.1\n---\nMaterial:\n  m_Floats:\n  - _Glossiness: 0.62\n  m_TextureBumpParams:\n  - _MainTex:\n    m_Texture: {fileID: 2800000, guid: 1a2b3c4d5e6f708192a3b4c5d6e7f809, type: 3}\n",
        encoding="utf-8",
    )

    _write(_pattern(size, 5), skins_dir / "700007" / "_maintex0" / "_MainTex0.png")
    (skins_dir / "700007" / "manifest").mkdir(parents=True, exist_ok=True)
    (skins_dir / "700007" / "manifest" / "manifest.txt").write_text(_manifest("rifle.semiauto", [{"Textures": {"_MainTex": "_MainTex0.png"}, "Floats": {"_Glossiness": 0.45}}]), encoding="utf-8")

    (skins_dir / "700008").mkdir(parents=True, exist_ok=True)

    broken = skins_dir / "700009"
    _write(_noise(size, 7), broken / "_maintex0" / "_MainTex0.png")

    for position, extra in enumerate(("700010", "700011", "700012", "700013", "700014", "700015", "700016", "700017", "700018"), start=1):
        variants = (1, 2, 4, 5, 6, 7, 8, 9, 1)
        _write(_pattern(size, variants[position - 1]), skins_dir / extra / "_maintex0" / "_MainTex0.png")
        (skins_dir / extra / "manifest").mkdir(parents=True, exist_ok=True)
        (skins_dir / extra / "manifest" / "manifest.txt").write_text(_manifest(NAMES[extra][1], [{"Textures": {"_MainTex": "_MainTex0.png"}, "Floats": {"_Glossiness": 0.4}}]), encoding="utf-8")

    marks = ledger_dir / "marks.jsonl"
    marks.parent.mkdir(parents=True, exist_ok=True)
    marks.write_text(
        json.dumps({"id": "mark-acog", "kind": "trademark", "mark": "ACOG", "title": "ACOG (Trijicon)", "owner": "Trijicon", "sourceUrl": "https://tsdr.uspto.gov/statuslist", "verified": False}) + "\n",
        encoding="utf-8",
    )


def build_catalogs(catalog_dir: Path) -> None:
    catalog_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date()
    for index, (name, ids) in enumerate(ROTATIONS.items(), 1):
        items = []
        for skin_id in ids:
            label, shortname = NAMES[skin_id]
            items.append(
                {
                    "appid": "252490",
                    "itemdefid": skin_id,
                    "name": label,
                    "item_shortname": shortname,
                    "store_tags": "cat.weapon;subcat.none;nocrate;time.limited;steamcat.weapon",
                    "tags": f"itemshortname:{shortname};steamcat:steamcat.weapon",
                    "tradable": 1,
                    "icon_url": "",
                    "type": "Skin",
                    "display_type": "Rust Item Skin",
                    "modified": f"2026091{index}T120000Z",
                }
            )
        # One week apart, and the newest is today. A rotation table where every row says the same
        # date makes the week tabs look broken, and "no release dates exist" is not a reason to lie.
        observed = (today - timedelta(days=7 * (len(ROTATIONS) - index))).isoformat() + "T12:00:00+00:00"
        (catalog_dir / name).write_text(
            json.dumps({"digest": f"demo-digest-{index}", "observedAt": observed, "items": items}, indent=2), encoding="utf-8"
        )


def seed(config: Config, log=print) -> dict:
    root = config.data_dir / "demo"
    catalog_dir = root / "catalogs"
    skins_dir = Path(config.skins_dir)
    ledger_dir = config.ledger_dir
    build_catalogs(catalog_dir)
    build_skins(skins_dir, ledger_dir)

    store = Store(config.db_path)
    store.set_meta("demo_mode", "1")
    for name in sorted(catalog_dir.glob("cat-*.json")):
        cfg = replace(config, stub_catalog=name)
        result = watch_run_once(store, cfg)
        log(f"  {name.name}: rotation {result.get('rotationId')} with {result.get('items')} item(s), {len(result.get('new') or [])} new")

    cfg = config
    scan = ingest_run(store, cfg, log=log)
    log(f"  first pass: {scan.get('scanned')} skin(s) analysed")

    # The ledger entry is seeded from 700002's own main texture, so the demo produces exactly one
    # non-commercial hit rather than four flat crops that all hash alike.
    from skinprobe.imaging import _dhash  # noqa: PLC0415

    target = skins_dir / "700002" / "_maintex0" / "_MainTex0.png"
    with Image.open(target) as im:
        arr = np.asarray(im.convert("RGB"), dtype=np.uint8)
    ledger_rows = []
    if target.exists():
        ledger_rows.append(
            {
                "id": "nc-brush-demo-14",
                "kind": "nc-license",
                "title": "Grunge Emblem Brush Pack 14",
                "owner": "Example Brushes Co",
                "sourceUrl": "https://example.test/marketplace/grunge-emblem-14",
                "licenseClause": "Every brush in this pack is for personal use only. You may not resell the artwork or include it in any commercial product.",
                "dhash": _dhash(arr),
                "sampleUrl": "",
                "offsets": {"start": 0, "end": 104, "textSha1": "seeded demo text, not a captured page"},
                "capturedAt": "seed",
                "verified": False,
                "source": "seeded for the demo, no page was fetched",
            }
        )
    if ledger_rows:
        ledger_dir.mkdir(parents=True, exist_ok=True)
        (ledger_dir / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ledger_rows), encoding="utf-8")
        again = ingest_run(store, config, log=lambda *a: None, skin_ids=["700002"])
        log(f"  second pass with a populated ledger: re-screened {again.get('scanned')} skin(s) against 1 corpus row")
    bot = bot_run_once(store, cfg, log=log)
    counts = store.counts()
    store.close()
    return {"counts": counts, "bot": bot, "demoRoot": str(root)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the demo dataset and fill the database")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--reset", action="store_true", help="delete the demo database and files first")
    args = parser.parse_args(argv)

    import sys
    from pathlib import Path as _P

    sys.path.insert(0, str(_P(__file__).resolve().parents[2] / "tools" / "skinprobe"))

    config = Config()
    if args.data_dir:
        config = replace(config, data_dir=Path(args.data_dir))
    config.ensure_dirs()
    if args.reset:
        for path in (config.db_path, config.db_path.with_name(config.db_path.name + "-wal"), config.db_path.with_name(config.db_path.name + "-shm")):
            path.unlink(missing_ok=True)
        shutil.rmtree(config.data_dir / "demo", ignore_errors=True)
        shutil.rmtree(config.crops_dir, ignore_errors=True)
        (config.ledger_dir / "ledger.jsonl").unlink(missing_ok=True)
    print("seeding demo data")
    summary = seed(config)
    print(json.dumps(summary["counts"], indent=2))
    print(f"demo files under {summary['demoRoot']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
