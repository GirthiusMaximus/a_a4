"""Licence text and sample-image extraction from a saved or fetched product page.

Design constraint that shapes this file: a clause is only worth storing if it can be re-checked
without re-fetching. So every clause carries the verbatim quote plus offsets into the normalised
text, and the caller stores that text's hash alongside the page snapshot.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

NOISE_TAGS = ("script", "style", "noscript", "svg", "nav", "footer", "header")

IMAGE_ATTRS = ("src", "data-src", "data-original", "data-original-src", "data-zoom-src")
IMAGE_EXT = re.compile(r"\.(png|jpe?g|webp|gif|bmp)(\?|#|$)", re.I)

CLAUSE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("personal-use-only", r"\b(?:for\s+)?personal\s+(?:use|projects?)\s+only\b"),
    ("non-commercial", r"\bnon[-\s]?commercial\b(?!\s+(?:use\s+only))"),
    ("no-resale", r"\b(?:may|cannot|can't|not)\s+(?:not\s+)?(?:be\s+)?(?:resold?|sold|redistribut\w+)\b"),
    ("no-commercial-use", r"\b(?:no|not\s+for|may\s+not\s+be\s+used\s+for)\s+commercial\s+(?:use|projects?|purposes?)\b"),
    ("commercial-license-required", r"\bcommercial\s+licen[cs]e\s+(?:required|must\s+be\s+purchased|available\s+separately)\b"),
    ("physical-goods-need-extended", r"\bphysical\s+(?:goods|products?)[^.]{0,80}(?:extended|separate|additional)\s+licen[cs]e\b"),
    ("print-on-demand-restricted", r"\bprint[-\s]on[-\s]demand[^.]{0,60}(?:not\s+allowed|prohibited|requires)\b"),
    ("ai-training-restricted", r"\b(?:machine\s+learning|ai\s+training|train\w*\s+ai)[^.]{0,60}(?:prohibited|not\s+allowed|forbidden)\b"),
    ("attribution-required", r"\b(?:credit|attribution)\s+(?:is\s+)?required\b"),
    ("per-seat-limit", r"\bup\s+to\s+(\d{1,3})\s+(?:end\s+users?|clients?|purchases?|units?)\b"),
)

BLOCKING = {"personal-use-only", "non-commercial", "no-resale", "no-commercial-use", "commercial-license-required", "print-on-demand-restricted", "per-seat-limit"}
WATCH_ONLY = {"physical-goods-need-extended", "ai-training-restricted", "attribution-required"}


@dataclass
class Clause:
    label: str
    quote: str
    start: int
    end: int

    def to_json(self) -> dict:
        return {"label": self.label, "quote": self.quote, "start": self.start, "end": self.end}


@dataclass
class Page:
    url: str
    text: str
    text_sha1: str
    title: str
    clauses: list[Clause] = field(default_factory=list)
    licence_status: str = "unknown"
    images: list[str] = field(default_factory=list)
    selectors: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "textSha1": self.text_sha1,
            "licenceStatus": self.licence_status,
            "clauses": [c.to_json() for c in self.clauses],
            "images": self.images,
            "selectors": self.selectors,
            "notes": self.notes,
        }


def normalise(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    body = soup.body or soup
    text = body.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _licence_region(html: str, selectors: list[str]) -> tuple[str, dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    for selector in selectors:
        try:
            found = soup.select(selector)
        except Exception:  # noqa: BLE001 - a bad selector from a hand-edited config is data
            continue
        if found:
            joined = re.sub(r"\s+", " ", " ".join(node.get_text(" ", strip=True) for node in found)).strip()
            if len(joined) > 40:
                return joined, {"licenceSelector": selector}
    return "", {}


def _labels(text: str) -> list[Clause]:
    clauses: list[Clause] = []
    lowered = text.lower()
    for label, pattern in CLAUSE_PATTERNS:
        for match in re.finditer(pattern, lowered):
            start = max(0, match.start() - 140)
            end = min(len(text), match.end() + 140)
            quote = text[start:end].strip()
            real_start = start + (len(text[start:end]) - len(text[start:end].lstrip()))
            clauses.append(Clause(label=label, quote=quote, start=real_start, end=real_start + len(quote)))
            break
    return clauses


def classify(text: str) -> tuple[str, list[Clause]]:
    clauses = _labels(text)
    labels = {c.label for c in clauses}
    if labels & BLOCKING:
        return "nc", clauses
    if labels & WATCH_ONLY:
        return "conditional", clauses
    if "commercial" in text.lower() or "you may use these" in text.lower():
        return "unclear", clauses
    return "unknown", clauses


def extract(html: str, url: str, selectors: dict | None = None) -> Page:
    """Classify a page, and keep only clause offsets that can be re-found in the captured text.

    Two passes on purpose. The selector-scoped pass tells you what the licence section says; the
    page-wide pass is the fallback whenever the block cannot be located inside the normalised text,
    because an offset that does not resolve is worse than no offset.
    """
    cfg = selectors or {}
    full = normalise(html)
    region, used = _licence_region(html, list(cfg.get("licenceSelectors", [])))

    status_full, clauses_full = classify(full)
    if region:
        status_region, clauses_region = classify(region)
        anchor = full.find(region)
        anchored: list[Clause] = []
        if anchor >= 0:
            for clause in clauses_region:
                index = full.find(clause.quote, anchor)
                if index >= 0:
                    anchored.append(Clause(clause.label, clause.quote, index, index + len(clause.quote)))
        if anchored:
            status, clauses = status_region, anchored
            used = {**used, "anchored": "true"}
        else:
            status, clauses = status_full, clauses_full
    else:
        status, clauses = status_full, clauses_full

    status, clauses = verify_offsets(full, clauses, status)
    soup = BeautifulSoup(html, "html.parser")
    page = Page(
        url=url,
        text=full,
        text_sha1=hashlib.sha1(full.encode("utf-8")).hexdigest(),
        title=soup.title.get_text(" ", strip=True) if soup.title else "",
        clauses=clauses,
        licence_status=status,
        images=image_urls(html, url, cfg),
        selectors=used,
    )
    if not region:
        page.notes.append("no licence block matched the configured selectors; whole page text was searched instead")
    elif "anchored" not in used:
        page.notes.append("licence block found but not locatable inside the page text; page-wide clauses were used instead")
    return page


def verify_offsets(text: str, clauses: list[Clause], status: str) -> tuple[str, list[Clause]]:
    """Keep only clauses whose quote really sits at the recorded offsets in the captured text.

    A quote that cannot be re-found makes re-verification impossible, so the clause is dropped
    and the page is marked unclear rather than trusted with a drifted pointer.
    """
    kept: list[Clause] = []
    for clause in clauses:
        window = text[clause.start : clause.end]
        if window and (window in text or clause.quote in text):
            if clause.quote not in text:
                index = text.find(clause.quote)
                if index < 0:
                    status = "unclear"
                    continue
                clause.start, clause.end = index, index + len(clause.quote)
            kept.append(clause)
        else:
            status = "unclear"
    return status, kept


def image_urls(html: str, base_url: str, cfg: dict | None = None) -> list[str]:
    cfg = cfg or {}
    allowed_host_ends = tuple(cfg.get("imageHostAllow", []) or [])
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        if not raw:
            return
        candidate = raw.strip()
        if not candidate or candidate.startswith("data:"):
            return
        absolute = urllib.parse.urljoin(base_url, candidate)
        parts = urllib.parse.urlsplit(absolute)
        if parts.scheme not in ("http", "https"):
            return
        if not IMAGE_EXT.search(parts.path):
            return
        if allowed_host_ends and not parts.netloc.lower().endswith(allowed_host_ends):
            return
        if absolute not in seen:
            seen.add(absolute)
            found.append(absolute)

    og = soup.find("meta", attrs={"property": "og:image"})
    add(og.get("content") if og else None)
    for img in soup.find_all("img"):
        for attr in IMAGE_ATTRS:
            add(img.get(attr))
        for candidate in (img.get("srcset") or "").split(","):
            add(candidate.split()[0] if candidate.split() else None)
    for selector in cfg.get("imageSelectors", []) or []:
        try:
            nodes = soup.select(selector)
        except Exception:  # noqa: BLE001
            continue
        for node in nodes:
            add(node.get("href") or node.get("src"))
    return found
