"""Build the non-commercial licence ledger by reading marketplace pages at your pace.

Three outputs per run, all append or replace, never overwrite blind:
  ledger.jsonl    one row per sample image that carries an NC or conditional clause
  watch.jsonl     per item: clause labels, textSha1, offsets. The point is to notice a clause appear
  changes.jsonl   items whose textSha1 moved since the last run, which is how a retrofitted
                  'no resale' term becomes a signal about skins already sold from that pack
"""

from __future__ import annotations

import fnmatch
import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from ..imaging import dhash_bytes
from .extract import extract, image_urls
from .policy import FetchPolicy


@dataclass
class SiteConfig:
    name: str
    startUrls: list[str]
    itemUrlPatterns: list[str]
    skipUrlPatterns: list[str]
    followListingPatterns: list[str]
    maxDepth: int
    maxItems: int
    minIntervalSec: float
    respectRobots: bool
    licenceSelectors: list[str]
    imageSelectors: list[str]
    imageHostAllow: list[str]
    maxImagesPerItem: int
    notes: str

    @classmethod
    def load(cls, path: Path) -> "SiteConfig":
        data = json.loads(path.read_text(encoding="utf-8"))
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"{path}: unknown keys {unknown}. Known: {sorted(allowed)}")
        for key in ("name", "startUrls", "itemUrlPatterns"):
            if not data.get(key):
                raise ValueError(f"{path}: {key} is required")
        return cls(
            name=data["name"],
            startUrls=list(data["startUrls"]),
            itemUrlPatterns=list(data["itemUrlPatterns"]),
            skipUrlPatterns=list(data.get("skipUrlPatterns", [])),
            followListingPatterns=list(data.get("followListingPatterns", [])),
            maxDepth=int(data.get("maxDepth", 2)),
            maxItems=int(data.get("maxItems", 25)),
            minIntervalSec=float(data.get("minIntervalSec", 3.0)),
            respectRobots=bool(data.get("respectRobots", True)),
            licenceSelectors=list(data.get("licenceSelectors", [])),
            imageSelectors=list(data.get("imageSelectors", [])),
            imageHostAllow=list(data.get("imageHostAllow", [])),
            maxImagesPerItem=int(data.get("maxImagesPerItem", 3)),
            notes=data.get("notes", ""),
        )


def _match(url: str, patterns: list[str]) -> bool:
    """Path glob (anything with * ? [), else a plain substring of the full url.

    Patterns are written against the path, so "/brushes/*" is matched against the path and, with a
    leading wildcard added, against a path that has extra segments in front of it.
    """
    lowered = url.lower()
    path = urllib.parse.urlsplit(lowered).path
    for raw in patterns:
        pattern = raw.lower().strip()
        if not pattern:
            continue
        if not any(ch in pattern for ch in "*?["):
            if pattern in lowered:
                return True
            continue
        variants = {pattern, f"*{pattern}", f"*/{pattern.lstrip('/')}"}
        if any(fnmatch.fnmatch(path, variant) or fnmatch.fnmatch(lowered, variant) for variant in variants):
            return True
    return False


def _links(html: str, base: str) -> list[str]:
    from bs4 import BeautifulSoup

    found = []
    for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = anchor["href"].strip()
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        found.append(urllib.parse.urljoin(base, href))
    return found


def _prior_watch(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("itemUrl"):
            out[row["itemUrl"]] = row
    return out


def build(
    config_path: Path,
    out_dir: Path,
    *,
    cache_dir: Path | None = None,
    offline_dir: Path | None = None,
    max_items: int | None = None,
    min_interval: float | None = None,
    user_agent: str | None = None,
    dry_run: bool = False,
) -> dict:
    cfg = SiteConfig.load(config_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    policy = FetchPolicy(
        user_agent=user_agent or FetchPolicy.user_agent,
        min_interval_sec=min_interval if min_interval is not None else cfg.minIntervalSec,
        respect_robots=cfg.respectRobots,
        cache_dir=cache_dir or (out_dir / "cache"),
        offline_dir=offline_dir,
    )

    prior = _prior_watch(out_dir / "watch.jsonl")
    queue: list[tuple[str, int]] = [(u, 0) for u in cfg.startUrls]
    seen: set[str] = set()
    items: list[str] = []
    listings_followed = 0
    fetches: list[dict] = []
    limits = {"blockedByRobots": 0, "httpErrors": 0}

    while queue:
        url, depth = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        result = policy.fetch(url)
        fetches.append(result.to_json())
        if result.status in (0, 404) or result.error:
            if result.source == "blocked":
                limits["blockedByRobots"] += 1
            else:
                limits["httpErrors"] += 1
            continue
        if max_items is not None and len(items) >= max_items:
            break
        if _match(url, cfg.skipUrlPatterns):
            continue
        if _match(url, cfg.itemUrlPatterns):
            if url not in items:
                items.append(url)
            continue
        if depth < cfg.maxDepth and (not cfg.followListingPatterns or _match(url, cfg.followListingPatterns)):
            listings_followed += 1
            for link in _links(result.text, url):
                if link not in seen and not _match(link, cfg.skipUrlPatterns):
                    if _match(link, cfg.itemUrlPatterns) or _match(link, cfg.followListingPatterns):
                        queue.append((link, depth + 1))

    ledger_rows: list[dict] = []
    watch_rows: list[dict] = []
    changes: list[dict] = []
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for item_url in items[: (max_items or cfg.maxItems)]:
        result = policy.fetch(item_url)
        fetches.append(result.to_json())
        if result.error or not result.text:
            continue
        page = extract(result.text, item_url, {"licenceSelectors": cfg.licenceSelectors, "imageSelectors": cfg.imageSelectors, "imageHostAllow": cfg.imageHostAllow})
        text_hash = page.text_sha1
        row = {
            "site": cfg.name,
            "itemUrl": item_url,
            "title": page.title,
            "licenceStatus": page.licence_status,
            "clauses": [c.to_json() for c in page.clauses],
            "textSha1": text_hash,
            "capturedAt": stamp,
            "licenceSelector": page.selectors.get("licenceSelector", ""),
            "notes": page.notes,
        }
        prior_row = prior.get(item_url)
        if prior_row and prior_row.get("textSha1") and prior_row["textSha1"] != text_hash:
            changes.append(
                {
                    "site": cfg.name,
                    "itemUrl": item_url,
                    "title": page.title,
                    "previousTextSha1": prior_row["textSha1"],
                    "nowTextSha1": text_hash,
                    "previousStatus": prior_row.get("licenceStatus"),
                    "nowStatus": page.licence_status,
                    "capturedAt": stamp,
                    "action": "compare the two captures before deciding anything. A page can change for reasons that have nothing to do with the licence.",
                }
            )
        watch_rows.append(row)

        if page.licence_status not in ("nc", "conditional"):
            continue
        for image_url in image_urls(result.text, item_url, {"imageSelectors": cfg.imageSelectors, "imageHostAllow": cfg.imageHostAllow})[: cfg.maxImagesPerItem]:
            raw = policy.image_bytes(image_url)
            hashed = dhash_bytes(raw) if raw else None
            if hashed is None:
                continue
            dhash, width, height = hashed
            clause = page.clauses[0] if page.clauses else None
            ledger_rows.append(
                {
                    "id": f"{cfg.name}:{dhash}",
                    "kind": "nc-license" if page.licence_status == "nc" else "conditional-license",
                    "title": page.title or item_url.rsplit("/", 1)[-1],
                    "owner": cfg.name,
                    "sourceUrl": item_url,
                    "sampleUrl": image_url,
                    "licenseClause": clause.quote if clause else "",
                    "clauseLabel": clause.label if clause else "",
                    "offsets": {"start": clause.start, "end": clause.end, "textSha1": text_hash} if clause else None,
                    "dhash": dhash,
                    "sampleDims": [width, height],
                    "capturedAt": stamp,
                    "verified": False,
                    "source": f"{cfg.name} at {stamp}, captured by the ledger crawler; a person has not opened it",
                }
            )

    policy.save()
    summary = {
        "schema": "skinprobe-ledger/0.1",
        "site": cfg.name,
        "generatedAt": stamp,
        "dryRun": dry_run,
        "visited": len(seen),
        "listingsFollowed": listings_followed,
        "items": len(items),
        "ledgerRows": len(ledger_rows),
        "changes": len(changes),
        "limits": limits,
        "policy": {
            "userAgent": policy.user_agent,
            "minIntervalSec": policy.min_interval_sec,
            "respectRobots": cfg.respectRobots,
            "offline": bool(offline_dir),
        },
    }

    if not dry_run:
        _write_jsonl(out_dir / "ledger.jsonl", ledger_rows)
        _write_jsonl(out_dir / "watch.jsonl", watch_rows, replace=True)
        if changes:
            _append_jsonl(out_dir / "changes.jsonl", changes)
        (out_dir / "run.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (out_dir / "fetch-log.jsonl").write_text("\n".join(json.dumps(f) for f in fetches) + ("\n" if fetches else ""), encoding="utf-8")
    return summary


def _write_jsonl(path: Path, rows: list[dict], replace: bool = False) -> None:
    existing = [] if replace else _read_jsonl(path)
    seen = {r.get("id") or r.get("itemUrl") for r in existing}
    for row in rows:
        key = row.get("id") or row.get("itemUrl")
        if key in seen:
            existing = [row if (r.get("id") or r.get("itemUrl")) == key else r for r in existing]
            continue
        existing.append(row)
        seen.add(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in existing), encoding="utf-8")


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows
