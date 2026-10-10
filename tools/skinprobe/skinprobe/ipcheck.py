"""Findings: what the pixels say, and which ledger entry (if any) they match.

Every IP finding is needs_human=true by design. This tool measures and links; it does not
decide ownership, and a report that reads like a verdict would be worse than no report.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .imaging import hamming_hex

SEVERITY = {
    "LIC-NC-HIT": "high",
    "TM-PIXEL-HIT": "high",
    "TM-NAME-HIT": "medium",
    "COPY-AUTHOR-META": "medium",
    "IP-PASTE-SEAM": "medium",
    "IP-LOGO-CANDIDATE": "medium",
    "TEC-NON-POT": "low",
    "TEC-OVER-CAP": "low",
    "TEC-BLANK-MAINTEX": "low",
    "TEC-UNREADABLE": "low",
    "TEC-UNKNOWN-FORMAT": "medium",
}


@dataclass
class Finding:
    code: str
    title: str
    detail: str
    texture: str | None = None
    sources: list[dict] | None = None
    severity: str = "low"

    def __post_init__(self) -> None:
        self.severity = SEVERITY.get(self.code, self.severity)

    def to_json(self) -> dict:
        return {
            "code": self.code,
            "title": self.title,
            "detail": self.detail,
            "texture": self.texture,
            "severity": self.severity,
            "needsHuman": self.code.startswith(("LIC", "TM", "COPY", "IP")),
            "sources": self.sources or [],
        }


def load_ledger(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    entries = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno} is not JSON: {exc}") from exc
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _name_tokens(name: str) -> set[str]:
    return {t for t in _norm(name).split() if len(t) > 2}


def match_name(skin_name: str, ledger: list[dict]) -> list[Finding]:
    hits: list[Finding] = []
    tokens = _name_tokens(skin_name)
    for entry in ledger:
        mark = entry.get("mark") or ""
        if not mark:
            continue
        mark_norm = _norm(mark)
        exact = mark_norm and mark_norm in _norm(skin_name)
        partial = bool(tokens & _name_tokens(mark)) and len(_norm(mark).split()) == 1
        if not (exact or partial):
            continue
        hits.append(
            Finding(
                code="TM-NAME-HIT",
                title=f"Skin name references a registered mark: {mark}",
                detail=(
                    f"'{skin_name}' matched ledger entry '{entry.get('id', '?')}'. "
                    "A name match is not infringement: many marks are generic when used descriptively. "
                    "Check the register and the goods class before flagging the listing."
                ),
                sources=[{"label": entry.get("sourceLabel", "register"), "url": entry.get("sourceUrl", ""), "verified": entry.get("verified", False)}],
            )
        )
    return hits


def _code_for(kind: str, level: str) -> str:
    """The ledger entry's kind decides the code. Which list it matched decides the evidence."""
    if kind == "nc-license":
        return "LIC-NC-HIT"
    return "TM-PIXEL-HIT"


# Slots that carry a colour decision. A normal map's grayscale ramp and a height map's blobs can
# land within a few bits of any flat asset, and comparing them to a colour ledger invents findings.
COLOUR_SLOTS = ("_MainTex", "_EmissionMap")


def match_pixels(
    metrics: list[dict],
    logos: list[dict],
    ledger: list[dict],
    max_distance: int | None = None,
    crop_max_distance: int = 8,
    texture_max_distance: int = 3,
) -> list[Finding]:
    """Two thresholds, because the two levels are not equally meaningful.

    A crop is a small region with a specific shape, so an 8-bit agreement still says something. A
    whole texture is one 64-bit summary of composition, and two different flat patterns sit within
    4 bits of each other all day long; only near-identity means anything there. `max_distance` is kept
    as an override for callers that want one number for both.
    """
    crop_limit = max_distance if max_distance is not None else crop_max_distance
    texture_limit = max_distance if max_distance is not None else texture_max_distance
    hits: list[Finding] = []
    for entry in ledger:
        reference = entry.get("dhash")
        if not reference:
            continue
        kind = entry.get("kind", "copyright")
        for item in metrics:
            if not item.get("dhash") or item.get("slot") not in COLOUR_SLOTS:
                continue
            distance = hamming_hex(item["dhash"], reference)
            if distance > texture_limit:
                continue
            hits.append(
                Finding(
                    code=_code_for(kind, "texture"),
                    title=f"{'Non-commercial licensed source' if kind == 'nc-license' else 'Pixel match to registered artwork'}: {entry.get('title', 'untitled')}",
                    detail=(
                        f"{item['slot']} of this skin is {distance} bits from a ledger asset "
                        f"({entry.get('owner', 'owner unknown')}). A full-texture hash says one thing: the "
                        "two images are built the same way. Treat it as a lead, not a match, and open the source."
                    ),
                    texture=item["path"],
                    sources=[
                        {
                            "label": entry.get("sourceLabel", "source"),
                            "url": entry.get("sourceUrl", ""),
                            "license": entry.get("licenseClause", ""),
                            "verified": entry.get("verified", False),
                        }
                    ],
                )
            )
        for logo in logos:
            if not logo.get("dhash"):
                continue
            distance = hamming_hex(logo["dhash"], reference)
            if distance > crop_limit:
                continue
            hits.append(
                Finding(
                    code=_code_for(kind, "crop"),
                    title=f"{'Crop matches a non-commercial licensed asset' if kind == 'nc-license' else 'Cropped mark matches ledger artwork'}: {entry.get('title', 'untitled')}",
                    detail=(
                        f"A colour island at bbox {logo['bbox']} is {distance} bits from "
                        f"'{entry.get('title', '?')}'. Crop-level matches are the strong signal; keep the crop file."
                    ),
                    texture=logo.get("crop"),
                    sources=[
                        {
                            "label": entry.get("sourceLabel", "source"),
                            "url": entry.get("sourceUrl", ""),
                            "license": entry.get("licenseClause", ""),
                            "verified": entry.get("verified", False),
                        }
                    ],
                )
            )
    return hits


def technical(metrics: list[dict], skin) -> list[Finding]:
    findings: list[Finding] = []
    if skin.status == "no-texture":
        findings.append(Finding("TEC-UNKNOWN-FORMAT", "Manifest read, no usable texture or colour", "; ".join(skin.notes) or "see status"))
    for item in metrics:
        path = item["path"]
        if item.get("error"):
            findings.append(Finding("TEC-UNREADABLE", f"Texture not analysed: {item['slot']}", item["error"], texture=path))
            continue
        if item["slot"] == "_MainTex" and item["is_blank"]:
            findings.append(
                Finding("TEC-BLANK-MAINTEX", "Blank _MainTex", "This group does not override the base texture; the part shows the default. Not an IP signal, but it must not be counted as a designed surface.", texture=path)
            )
        if not item["is_power_of_two"]:
            findings.append(Finding("TEC-NON-POT", f"Non power-of-two {item['slot']}", f"{item['width']}x{item['height']}. The published guideline is power of two, and mip chaining behaves differently on odd sizes.", texture=path))
        if item["exceeds_size_guideline"]:
            findings.append(Finding("TEC-OVER-CAP", f"{item['slot']} exceeds the size cap", f"{item['width']}x{item['height']} and {item['size_bytes']} bytes.", texture=path))
        if item["seam_ratio"] > 1.6 and item["unique_colors"] > 400:
            findings.append(
                Finding(
                    "IP-PASTE-SEAM",
                    f"{item['slot']} is a pasted image, not a tileable pattern",
                    f"Edge discontinuity is {item['seam_ratio']}x the interior contrast, so the left/right and top/bottom borders do not meet. Hand-painted tiling patterns close across the wrap; a photo dropped onto UVs does not.",
                    texture=path,
                )
            )
    return findings


def build(
    skin,
    metrics: list[dict],
    logos: list[dict],
    ledger: list[dict],
    skin_name: str = "",
    name_max: int = 12,
    crop_max_distance: int = 8,
    texture_max_distance: int = 3,
) -> list[Finding]:
    findings = technical(metrics, skin)
    if skin_name:
        findings.extend(match_name(skin_name, ledger)[:name_max])
    findings.extend(match_pixels(metrics, logos, ledger, crop_max_distance=crop_max_distance, texture_max_distance=texture_max_distance))
    for logo in logos:
        findings.append(
            Finding(
                "IP-LOGO-CANDIDATE",
                f"Isolated colour island at {logo['bbox']}",
                f"Colour covers {logo['colorShare']:.2%} of the map, aspect {logo['aspect']}, fill {logo['fill']}. Candidate only: no claim is made about what it depicts.",
                texture=logo.get("crop"),
            )
        )
    return findings
