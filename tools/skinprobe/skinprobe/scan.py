"""Scan a skin directory (or a root of them) and write findings."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from . import manifest as mf
from .imaging import find_logo_candidates, measure, sharpen_hint
from .ipcheck import build as build_findings
from .ipcheck import load_ledger
from .providers import build as build_provider

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Result:
    skin: mf.Skin
    metrics: list[dict]
    logos: list[dict]
    findings: list[dict]

    @property
    def needs_review(self) -> bool:
        return any(f["needsHuman"] and f["severity"] in ("high", "medium") for f in self.findings)


def _looks_like_skin(path: Path) -> bool:
    """Shallow test on purpose. A recursive search would call a root of skins one skin."""
    if not path.is_dir():
        return False
    if (path / "manifest" / "manifest.txt").exists() or (path / "manifest.txt").exists():
        return True
    return any(p.suffix.lower() == ".mat" for p in path.iterdir())


def discover(root: Path) -> list[Path]:
    if _looks_like_skin(root):
        return [root]
    for depth in (1, 2):
        found = _children_at_depth(root, depth)
        if found:
            return found
    return [root]


PAYLOAD_SUFFIXES = {".png", ".jpg", ".jpeg", ".tga", ".psd", ".bmp", ".dds", ".ktx", ".ktx2", ".asset", ".unity3d", ".mat"}


def _has_payload_files(path: Path) -> bool:
    """A folder holding textures but no manifest is a failed download, which is a finding, not noise."""
    return any(p.suffix.lower() in PAYLOAD_SUFFIXES for p in path.rglob("*") if p.is_file())


def _children_at_depth(root: Path, depth: int) -> list[Path]:
    current = [root]
    for _ in range(depth):
        current = [child for parent in current for child in sorted(parent.iterdir()) if child.is_dir()]
    skins = [p for p in current if _looks_like_skin(p)]
    if not skins:
        return []
    suspects = [p for p in current if p not in skins and _has_payload_files(p)]
    return sorted(skins + suspects, key=lambda p: p.name)


def scan_skin(
    skin_dir: Path,
    out_dir: Path,
    *,
    ledger: list[dict],
    skin_name: str = "",
    max_logos: int = 8,
    all_slots: bool = False,
    crop_max_distance: int = 8,
    texture_max_distance: int = 3,
) -> Result:
    skin = mf.load(skin_dir)
    metrics: list[dict] = []
    seen: set[Path] = set()
    for group in skin.groups:
        for slot, path in group.paths.items():
            if path in seen:
                continue
            seen.add(path)
            item = measure(path, slot, cutoff=group.cutoff).to_json()
            if slot == "_MainTex":
                item["filterHint"] = sharpen_hint(path)
            metrics.append(item)

    main_tex = [m for m in metrics if m["slot"] == "_MainTex" and not m.get("error")]
    targets = [m for m in metrics if not m.get("error")] if all_slots else main_tex
    logos: list[dict] = []
    crop_dir = out_dir / "crops"
    for item in targets:
        logos.extend(find_logo_candidates(Path(item["path"]), crop_dir, limit=max_logos - len(logos)))
        if len(logos) >= max_logos:
            break

    findings = [f.to_json() for f in build_findings(
        skin, metrics, logos, ledger, skin_name=skin_name, crop_max_distance=crop_max_distance, texture_max_distance=texture_max_distance
    )]
    return Result(skin=skin, metrics=metrics, logos=logos, findings=findings)


def run(
    target: Path,
    out_dir: Path,
    *,
    corpus: Path | None = None,
    trademark_ledger: Path | None = None,
    skin_names: dict[str, str] | None = None,
    provider: str = "manual",
    max_logos: int = 8,
    all_slots: bool = False,
) -> dict:
    started = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = load_ledger(corpus) + load_ledger(trademark_ledger)

    engine = build_provider(provider, out_dir) if provider != "none" else None
    results: list[Result] = []
    errors: list[dict] = []
    for skin_dir in discover(target):
        try:
            result = scan_skin(
                skin_dir,
                out_dir / skin_dir.name,
                ledger=ledger,
                skin_name=(skin_names or {}).get(skin_dir.name, ""),
                max_logos=max_logos,
                all_slots=all_slots,
            )
        except Exception as exc:  # noqa: BLE001 - one unreadable skin must not stop a rotation
            errors.append({"skinId": skin_dir.name, "error": f"{type(exc).__name__}: {exc}", "status": "unknown-format"})
            continue
        if engine is not None:
            for logo in result.logos:
                try:
                    hits = [h.to_json() for h in engine.search(Path(logo["crop"]), logo["dhash"])]
                except Exception as exc:  # noqa: BLE001
                    hits = []
                    logo["providerError"] = f"{type(exc).__name__}: {exc}"
                logo["reverseHits"] = hits
        results.append(result)
    if engine is not None:
        engine.save()

    payload = {
        "schema": "skinprobe/0.1",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsedSec": round(time.time() - started, 2),
        "ledgerEntries": len(ledger),
        "provider": provider,
        "disclaimer": "Pixel and name measurements only. No finding is a legal conclusion, and none of these results should be posted to buyers without the linked source opened by a person.",
        "skins": [
            {
                **r.skin.to_json(),
                "textures": r.metrics,
                "logoCandidates": r.logos,
                "findings": r.findings,
                "needsReview": r.needs_review,
            }
            for r in results
        ],
        "errors": errors,
        "summary": {
            "skins": len(results) + len(errors),
            "read": len(results),
            "needsReview": sum(1 for r in results if r.needs_review),
            "high": sum(1 for r in results for f in r.findings if f["severity"] == "high"),
            "unreadable": len(errors),
        },
    }
    (out_dir / "findings.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(render(payload), encoding="utf-8")
    return payload


def render(payload: dict) -> str:
    lines = [
        "# skinprobe report",
        "",
        f"Generated {payload['generatedAt']}. {payload['summary']['skins']} skin(s) in scope, "
        f"{payload['summary']['needsReview']} need a person, {payload['summary']['high']} high severity finding(s).",
        "",
        f"> {payload['disclaimer']}",
        "",
    ]
    if payload["errors"]:
        lines += ["## Unreadable", ""]
        for err in payload["errors"]:
            lines.append(f"- `{err['skinId']}`: {err['error']}")
        lines.append("")
    for skin in payload["skins"]:
        flagged = [f for f in skin["findings"]]
        flagged.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 3))
        lines += [
            f"## {skin['skinId']}",
            "",
            f"- Format `{skin['format']}`, item `{skin.get('itemShortname') or '?'}`, status `{skin['status']}`",
            f"- Groups {len(skin['groups'])}, textures {len(skin['textures'])}, logo crops {len(skin['logoCandidates'])}",
        ]
        if not flagged:
            lines.append("- No findings. That means no ledger entry matched and no anomaly tripped a threshold. It does not mean the skin is clear.")
        for finding in flagged:
            lines.append(f"- **{finding['severity'].upper()}** `{finding['code']}` {finding['title']}")
            lines.append(f"  - {finding['detail']}")
            if finding.get("texture"):
                lines.append(f"  - file: `{finding['texture']}`")
            for source in finding.get("sources", []):
                mark = "verified" if source.get("verified") else "unverified"
                lines.append(f"  - source ({mark}): {source.get('url') or 'no url recorded'}")
        lines.append("")
    lines += [
        "## What this pass cannot see",
        "",
        "- Reverse image search only runs with a keyed provider; a `manual` run leaves `reverse-search-queue.csv` to work through in a browser.",
        "- DDS and KTX textures are listed, not decoded.",
        "- No mesh is loaded, so UV island placement and stretch are unmeasured. A logo can hide in a stretched island this pass cannot see.",
        "- An empty ledger means the only findings available are anomalies. Populate the ledger from registers and the marketplaces' licence text, with the URL and the date each entry was checked.",
        "",
    ]
    return "\n".join(lines)
