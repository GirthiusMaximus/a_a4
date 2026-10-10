"""Selftest: synthetic skins in, assertions out. No network, no real assets.

Run with: python -m skinprobe selftest
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from .imaging import find_logo_candidates, measure
from .scan import run

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))


def _tile(size: int, cells: int) -> np.ndarray:
    step = size // cells
    grid = (np.arange(size) // step) % 2
    mask = (grid[:, None] + grid[None, :]) % 2
    base = np.where(mask > 0, 190, 70).astype(np.uint8)
    return np.dstack([base, base // 2 + 20, 255 - base])


def _pasted(size: int) -> np.ndarray:
    arr = np.zeros((size, size, 3), dtype=np.uint8)
    arr[:] = (60, 70, 90)
    arr[:, : size // 3] = (210, 190, 40)
    arr[size // 2 :, -size // 4 :] = (20, 200, 160)
    return arr


def _save(arr: np.ndarray, path: Path, mode: str = "RGB") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr, mode).save(path)


def build_fixtures(root: Path) -> None:
    size = 256
    modern = root / "700001"
    texture = _tile(size, 8).astype(np.int16)
    texture[96:152, 150:206] = (246, 8, 8)
    texture[108:140, 162:194] = (255, 255, 255)
    _save(np.clip(texture, 0, 255).astype(np.uint8), modern / "_maintex0" / "_MainTex0.png")
    bump = np.full((size, size, 3), 128, dtype=np.uint8)
    bump[..., 1] = (np.arange(size)[None, :] * 3 % 90 + 90).astype(np.uint8)
    _save(bump, modern / "_bumpmap0" / "_BumpMap0.png")
    blank = np.full((size, size, 3), 255, dtype=np.uint8)
    _save(blank, modern / "_maintex1" / "_MainTex1.png")
    manifest = {
        "ItemType": "rifle.ak",
        "Groups": [
            {
                "Textures": {"_MainTex": "_MainTex0.png", "_BumpMap": "_BumpMap0.png", "_EmissionMap": "none"},
                "Floats": {"_Glossiness": 0.7, "_Cutoff": 0.0, "_BumpScale": 1.0},
                "Colors": {"_Color": {"r": 1.0, "g": 1.0, "b": 1.0}},
            },
            {"Textures": {"_MainTex": "_MainTex1.png"}, "Floats": {"_Glossiness": 0.2}, "Colors": {}},
        ],
    }
    (modern / "manifest").mkdir(parents=True, exist_ok=True)
    (modern / "manifest" / "manifest.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    legacy = root / "700002"
    legacy.mkdir(parents=True, exist_ok=True)
    _save(_pasted(size), legacy / "mydiffuse.png")
    (legacy / "mydiffuse.png.meta").write_text("fileFormatVersion: 2\nguid: 0f1e2d3c4b5a69788796a5b4c3d2e1f0\n", encoding="utf-8")
    (legacy / "skin.mat").write_text(
        "%YAML 1.1\n---\nMaterial:\n  m_Shader: {fileID: 4800000, guid: abc, type: 3}\n  m_Floats:\n  - _Glossiness: 0.55\n  - _Cutoff: 0.4\n  m_TextureBumpParams:\n  - _MainTex:\n    m_Texture: {fileID: 2800000, guid: 0f1e2d3c4b5a69788796a5b4c3d2e1f0, type: 3}\n",
        encoding="utf-8",
    )

    odd = root / "700003"
    _save(_tile(300, 6), odd / "_maintex0" / "_MainTex0.png")
    (odd / "manifest").mkdir(parents=True, exist_ok=True)
    (odd / "manifest" / "manifest.txt").write_text(
        json.dumps({"ItemType": "hat.boonie", "Groups": [{"Textures": {"_MainTex": "_MainTex0.png"}, "Floats": {"_Cutoff": 0.0}}]}),
        encoding="utf-8",
    )

    transparent = _tile(size, 4).astype(np.uint8)
    rgba = np.dstack([transparent, np.full((size, size), 255, dtype=np.uint8)])
    rgba[: size * 3 // 10, :, 3] = 0
    see_through = root / "700004"
    _save(rgba, see_through / "_maintex0" / "_MainTex0.png", mode="RGBA")
    (see_through / "manifest").mkdir(parents=True, exist_ok=True)
    (see_through / "manifest" / "manifest.txt").write_text(
        json.dumps(
            {
                "ItemType": "shirt.tanktop",
                "Groups": [{"Textures": {"_MainTex": "_MainTex0.png"}, "Floats": {"_Cutoff": 0.5}, "Colors": {}}],
            }
        ),
        encoding="utf-8",
    )

    junk = root / "700005"
    junk.mkdir(parents=True, exist_ok=True)
    (junk / "notes.txt").write_text("this is not a skin\n", encoding="utf-8")
    # a texture with no manifest is what a half-finished download leaves behind: report it, never skip it
    _save(_pasted(128), junk / "loose_diffuse.png")


def ledger_checks(tmp: Path) -> None:
    """Offline crawler test: a fake marketplace with an NC clause and one sample PNG."""
    from .ledger.build import SiteConfig, build
    from .ledger.extract import extract
    from .ledger.policy import key_for

    offline = tmp / "offline"
    offline.mkdir(parents=True, exist_ok=True)
    site = "https://shop.test"
    listing = f'<html><head><title>Shop</title></head><body><a href="/brushes/grunge-14">Grunge 14</a><a href="/brushes/plain-2">Plain 2</a></body></html>'
    (offline / f"{key_for(site + '/brushes')}.html").write_text(listing, encoding="utf-8")

    item_html = (
        "<html><head><title>Grunge Brush Pack 14</title></head><body>"
        "<div class='licence'>Every brush in this pack is for personal use only. You may not resell the "
        "artwork or include it in any commercial product. Attribution is requested but not required."
        "</div>"
        "<img src='/brushes/grunge-14/sample.png'>"
        "</body></html>"
    )
    (offline / f"{key_for(site + '/brushes/grunge-14')}.html").write_text(item_html, encoding="utf-8")

    sample = _logo_map(128)
    img_path = tmp / "sample.png"
    _save(sample, img_path)
    (offline / f"{key_for(site + '/brushes/grunge-14/sample.png')}.img").write_bytes(img_path.read_bytes())

    ok_html = "<html><head><title>Plain Brush Pack 2</title></head><body><div class='licence'>Use these brushes in anything you like, including commercial work.</div></body></html>"
    (offline / f"{key_for(site + '/brushes/plain-2')}.html").write_text(ok_html, encoding="utf-8")

    config = {
        "name": "shop-test",
        "startUrls": [site + "/brushes"],
        "itemUrlPatterns": ["/brushes/*"],
        "followListingPatterns": ["/brushes"],
        "licenceSelectors": ["div.licence"],
        "imageHostAllow": ["shop.test"],
        "minIntervalSec": 0.0,
        "maxItems": 10,
    }
    config_path = tmp / "site.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    SiteConfig.load(config_path)

    out = tmp / "ledger-out"
    summary = build(config_path, out, offline_dir=offline, cache_dir=out / "cache", max_items=10)
    check("crawler walks the listing and reaches both items", summary["items"] == 2, str(summary["items"]))
    check("crawler emits one ledger row, for the NC pack only", summary["ledgerRows"] == 1, str(summary["ledgerRows"]))

    rows = [json.loads(line) for line in (out / "ledger.jsonl").read_text().splitlines() if line.strip()]
    row = rows[0] if rows else {}
    check("ledger row carries the verbatim clause", "personal use only" in row.get("licenseClause", ""), row.get("licenseClause", "")[:80])
    check("ledger row records a sample dhash", bool(re.fullmatch(r"[0-9a-f]{16}", row.get("dhash", ""))), str(row.get("dhash")))
    check("ledger row is marked unverified", row.get("verified") is False)
    offsets = row.get("offsets") or {}
    page = extract(item_html, site + "/brushes/grunge-14", {"licenceSelectors": ["div.licence"]})
    recovered = page.text[offsets.get("start", 0) : offsets.get("end", 0)]
    check("recorded offsets recover the exact quote from the captured text", recovered == row.get("licenseClause"), f"got {recovered[:60]!r}")
    check("stored text hash matches a fresh extract", offsets.get("textSha1") == page.text_sha1)

    watch = {json.loads(l)["itemUrl"]: json.loads(l) for l in (out / "watch.jsonl").read_text().splitlines() if l.strip()}
    check("permissive pack is classified, not treated as a hit", watch.get(site + "/brushes/plain-2", {}).get("licenceStatus") in ("unclear", "unknown", "conditional"))
    check("nc pack is classified nc", watch.get(site + "/brushes/grunge-14", {}).get("licenceStatus") == "nc")

    (offline / f"{key_for(site + '/brushes/grunge-14')}.html").write_text(
        item_html.replace("for personal use only", "for personal and commercial use, resale of the raw files still not allowed"),
        encoding="utf-8",
    )
    second = build(config_path, out, offline_dir=offline, cache_dir=out / "cache", max_items=10)
    check("a later run notices the licence text changed", second["changes"] >= 1, str(second["changes"]))
    changes = [json.loads(line) for line in (out / "changes.jsonl").read_text().splitlines() if line.strip()]
    check("the change row keeps both hashes", bool(changes and changes[-1].get("previousTextSha1") and changes[-1].get("nowTextSha1")))


def run_selftest() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="skinprobe-selftest-"))
    try:
        skins = tmp / "skins"
        build_fixtures(skins)

        seamless = measure(_write(tmp / "seamless.png", _tile(256, 8)), "_MainTex")
        pasted = measure(_write(tmp / "pasted.png", _pasted(256)), "_MainTex")
        check("seam ratio separates a tileable pattern from a pasted image", pasted.seam_ratio > seamless.seam_ratio, f"pasted {pasted.seam_ratio} vs seamless {seamless.seam_ratio}")
        check("a uniform white map is reported blank", measure(_write(tmp / "white.png", np.full((64, 64, 3), 255, dtype=np.uint8)), "_MainTex").is_blank)
        check("non power-of-two is caught", not measure(_write(tmp / "odd.png", _tile(300, 6)), "_MainTex").is_power_of_two)

        crops = find_logo_candidates(_write(tmp / "logo.png", _logo_map(256)), tmp / "crops", limit=4)
        check("a planted mark is found as a colour island", len(crops) >= 1, f"{len(crops)} crop(s)")

        # The coherence gate has to keep grain out without also throwing away real marks. Both
        # directions are tested because an earlier revision got the denominator wrong and killed all crops.
        solid = np.full((256, 256, 3), 90, dtype=np.uint8)
        solid[100:140, 100:140] = 242
        solid_crops = find_logo_candidates(_write(tmp / "solid.png", solid), tmp / "crops-solid", limit=4)
        check("a solid mark survives the coherence gate", len(solid_crops) == 1, f"{len(solid_crops)} crop(s)")

        speckle = np.full((256, 256, 3), 90, dtype=np.uint8)
        flat = speckle.reshape(-1, 3)
        flat[np.random.default_rng(3).choice(256 * 256, size=40 * 40, replace=False)] = 242
        speckle_crops = find_logo_candidates(_write(tmp / "speckle.png", speckle), tmp / "crops-speckle", limit=4)
        check("the same area as scattered pixels is rejected as grain", speckle_crops == [], f"{len(speckle_crops)} crop(s)")

        payload = run(skins, tmp / "out", provider="none", max_logos=4)
        by_id = {s["skinId"]: s for s in payload["skins"]}
        check("modern manifest parsed with two groups", len(by_id.get("700001", {}).get("groups", [])) == 2)
        check("manifest slot resolved to a file on disk", bool(by_id.get("700001", {}).get("groups", [{}])[0].get("resolved", {}).get("_MainTex")))
        check("emissive flag off when _EmissionMap is none", by_id.get("700001", {}).get("groups", [{}])[0].get("emissive") is False)
        check("legacy .mat GUID resolved", bool(by_id.get("700002", {}).get("groups", [{}])[0].get("resolved", {}).get("_MainTex")), json.dumps(by_id.get("700002", {}).get("groups", [{}])[0].get("notes", [])))
        check("blank main tex produces TEC-BLANK-MAINTEX", "TEC-BLANK-MAINTEX" in {f["code"] for f in by_id.get("700001", {}).get("findings", [])})
        check("non power-of-two produces TEC-NON-POT", "TEC-NON-POT" in {f["code"] for f in by_id.get("700003", {}).get("findings", [])})
        check("cutoff alpha produces a cut fraction near 0.30", abs(by_id.get("700004", {}).get("textures", [{}])[0].get("cut_fraction", 0) - 0.3) < 0.02, str(by_id.get("700004", {}).get("textures", [{}])))
        check("unknown format is reported, not skipped", any(e["skinId"] == "700005" for e in payload["errors"]), json.dumps(payload["errors"]))
        check("every IP finding is marked for a human", all(f["needsHuman"] for s in payload["skins"] for f in s["findings"] if f["code"].startswith(("IP", "TM", "LIC", "COPY"))))

        report = (tmp / "out" / "report.md").read_text(encoding="utf-8")
        check("report contains no em dash (core rule R-02)", chr(0x2014) not in report)

        crop_hash = payload["skins"][0]["logoCandidates"][0]["dhash"] if payload["skins"][0]["logoCandidates"] else ""
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(
            json.dumps({"id": "nc-brush-14", "kind": "nc-license", "title": "Grunge Brush Pack 14", "owner": "Example Brushes", "sourceUrl": "https://example.test/nc-brush-14", "licenseClause": "Personal use only, no resale", "dhash": crop_hash, "verified": False}) + "\n"
            + json.dumps({"id": "mark-nike", "kind": "trademark", "mark": "Nike", "sourceUrl": "https://example.test/tm/nike", "verified": False}) + "\n",
            encoding="utf-8",
        )
        names = tmp / "names.json"
        names.write_text(json.dumps({"700001": "Nike Swoosh AK"}), encoding="utf-8")
        again = run(skins, tmp / "out2", corpus=ledger, trademark_ledger=ledger, skin_names=json.loads(names.read_text()), provider="none", max_logos=4)
        codes = {f["code"] for s in again["skins"] for f in s["findings"]}
        check("crop hash matching a ledger entry fires LIC-NC-HIT", "LIC-NC-HIT" in codes, str(sorted(codes)))
        check("skin name against the mark ledger fires TM-NAME-HIT", "TM-NAME-HIT" in codes)

        ledger_checks(tmp)

        failed = [c for c in CHECKS if not c[1]]
        for name, ok, detail in CHECKS:
            print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
        print(f"\n{len(CHECKS) - len(failed)} of {len(CHECKS)} checks passed")
        return 1 if failed else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _logo_map(size: int) -> np.ndarray:
    arr = _tile(size, 8)
    arr[80:176, 80:176] = (12, 240, 12)
    arr[104:152, 104:152] = (255, 255, 255)
    return arr


def _write(path: Path, arr: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr.astype(np.uint8), "RGB").save(path)
    return path
