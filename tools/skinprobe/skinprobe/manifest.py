"""Skin file readers. Output is one Skin record with groups, slots and resolved paths.

The modern manifest schema and the legacy .mat layouts are transcribed from a maintained
importer (see README "Sources"), not guessed. Anything this module cannot read is reported
as status "unknown-format" rather than silently skipped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

TEXTURE_SLOTS = (
    "_MainTex",
    "_BumpMap",
    "_SpecGlossMap",
    "_MetallicGlossMap",
    "_OcclusionMap",
    "_EmissionMap",
)

SLOT_KEYWORDS = {
    "_MainTex": ("diff", "albedo", "colour", "color", "base", "main"),
    "_BumpMap": ("normal", "norm", "bump"),
    "_SpecGlossMap": ("spec",),
    "_MetallicGlossMap": ("metal",),
    "_OcclusionMap": ("occlu", ".ao"),
    "_EmissionMap": ("emiss", "glow"),
}

IGNORED_STEMS = ("icon", "preview", "screenshot", "thumb")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tga", ".psd", ".bmp", ".dds", ".ktx", ".ktx2"}

_NUM = r"-?[\d.]+(?:[eE][-+]?\d+)?"
TEX_PATTERNS = (
    re.compile(r"name:\s*(_\w+)\s*\r?\n\s*second:\s*\r?\n\s*m_Texture:\s*\{fileID:\s*-?\d+(?:,\s*guid:\s*([0-9a-f]{32}))?"),
    re.compile(r"-\s*(_\w+):\s*\r?\n\s*m_Texture:\s*\{fileID:\s*-?\d+(?:,\s*guid:\s*([0-9a-f]{32}))?"),
)
FLOAT_PATTERNS = (
    re.compile(r"name:\s*(_\w+)\s*\r?\n\s*second:\s*(" + _NUM + r")\s*\r?\n"),
    re.compile(r"-\s*(_\w+):\s*(" + _NUM + r")\s*\r?\n"),
)
COLOR_RE = re.compile(r"_Color\w*:\s*\{\s*r:\s*(" + _NUM + r")\s*,\s*g:\s*(" + _NUM + r")\s*,\s*b:\s*(" + _NUM + r")")
META_GUID_RE = re.compile(r"^guid:\s*([0-9a-f]{32})", re.MULTILINE)


@dataclass
class Group:
    index: int
    textures: dict[str, str | None] = field(default_factory=dict)
    floats: dict[str, float] = field(default_factory=dict)
    colors: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    paths: dict[str, Path] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def cutoff(self) -> float:
        return float(self.floats.get("_Cutoff", 0.0))

    @property
    def emissive(self) -> bool:
        color = self.colors.get("_EmissionColor")
        return self.textures.get("_EmissionMap") not in (None, "none") and bool(color and any(v > 0 for v in color))

    @property
    def cutout(self) -> bool:
        return 0.0 < self.cutoff < 1.0


@dataclass
class Skin:
    skin_id: str
    root: Path
    format: str
    item_type: str | None
    groups: list[Group]
    status: str = "ok"
    notes: list[str] = field(default_factory=list)
    extras: list[Path] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "skinId": self.skin_id,
            "format": self.format,
            "itemShortname": self.item_type,
            "status": self.status,
            "notes": self.notes,
            "groups": [
                {
                    "index": g.index,
                    "textures": g.textures,
                    "resolved": {k: str(v.relative_to(self.root)) for k, v in g.paths.items()},
                    "floats": g.floats,
                    "colors": {k: list(v) for k, v in g.colors.items()},
                    "emissive": g.emissive,
                    "cutout": g.cutout,
                    "notes": g.notes,
                }
                for g in self.groups
            ],
            "unmappedFiles": [str(p.relative_to(self.root)) for p in self.extras],
        }


def _index_files(root: Path) -> tuple[dict[str, Path], dict[str, Path], list[Path]]:
    by_name: dict[str, Path] = {}
    by_lower: dict[str, Path] = {}
    images: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in IMAGE_EXTS:
            images.append(path)
        key = path.name
        by_name.setdefault(key, path)
        by_lower.setdefault(key.lower(), path)
    return by_name, by_lower, images


def _resolve(name: str, group: Group, by_name: dict[str, Path], by_lower: dict[str, Path], images: list[Path]) -> Path | None:
    if not name or name == "none":
        return None
    for table in (by_name, by_lower):
        if name in table or name.lower() in table:
            return table.get(name) or table.get(name.lower())
    # AssetStudio re-encodes every texture as PNG, so a manifest that names a .jpg is often a .png on disk.
    stem = Path(name).stem
    for cand in images:
        if cand.stem.lower() == stem.lower():
            return cand
    slot_folders = [f"{slot.lower()}{group.index}" for slot in TEXTURE_SLOTS]
    for cand in images:
        if cand.parent.name.lower() in slot_folders and stem.lower().startswith(cand.parent.name.lower().rstrip("0123456789")):
            return cand
    return None


def _assign_by_keyword(group: Group, images: list[Path]) -> None:
    used: set[Path] = set()
    for slot, keywords in SLOT_KEYWORDS.items():
        if group.textures.get(slot) not in (None, "none"):
            continue
        for path in images:
            stem = path.stem.lower()
            if path in used or any(b in stem for b in IGNORED_STEMS):
                continue
            if any(k in stem for k in keywords):
                group.paths[slot] = path
                used.add(path)
                group.notes.append(f"{slot} assigned by filename keyword, not by manifest")
                break


def parse_modern(manifest_path: Path, root: Path, group_hint: int | None = None) -> Skin:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    item_type = data.get("ItemType")
    raw_groups = data.get("Groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise ValueError("manifest.txt has no Groups array")

    by_name, by_lower, images = _index_files(root)
    groups: list[Group] = []
    for i, entry in enumerate(raw_groups):
        entry = entry if isinstance(entry, dict) else {}
        textures = {k: v for k, v in (entry.get("Textures") or {}).items() if isinstance(v, str)}
        group = Group(index=i, textures={slot: textures.get(slot) for slot in TEXTURE_SLOTS})
        for slot, name in textures.items():
            if slot not in group.textures:
                group.textures[slot] = name
        floats = entry.get("Floats") or {}
        if isinstance(floats, dict):
            group.floats = {k: float(v) for k, v in floats.items() if isinstance(v, (int, float))}
        colors = entry.get("Colors") or {}
        if isinstance(colors, dict):
            parsed: dict[str, tuple[float, float, float]] = {}
            for key, val in colors.items():
                if isinstance(val, dict) and all(c in val for c in ("r", "g", "b")):
                    try:
                        parsed[key] = (float(val["r"]), float(val["g"]), float(val["b"]))
                    except (TypeError, ValueError):
                        continue
            group.colors = parsed

        for slot, name in group.textures.items():
            path = _resolve(name or "", group, by_name, by_lower, images)
            if path is not None:
                group.paths[slot] = path
            elif name and name != "none":
                group.notes.append(f"{slot} named '{name}' not found on disk")
        _assign_by_keyword(group, images)
        groups.append(group)

    claimed = {p for g in groups for p in g.paths.values()}
    extras = [p for p in images if p not in claimed and not any(b in p.stem.lower() for b in IGNORED_STEMS)]
    skin = Skin(
        skin_id=root.name,
        root=root,
        format="modern",
        item_type=item_type if isinstance(item_type, str) else None,
        groups=groups,
    )
    skin.extras = extras
    if not any(g.paths.get("_MainTex") for g in groups) and not any(g.colors.get("_Color") for g in groups):
        skin.status = "no-texture"
        skin.notes.append("no group has a usable _MainTex or _Color")
    return skin


def _guid_map(root: Path) -> dict[str, Path]:
    guids: dict[str, Path] = {}
    for meta in root.rglob("*.meta"):
        try:
            match = META_GUID_RE.search(meta.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        if not match:
            continue
        target = meta.with_suffix("")
        if target.exists():
            guids[match.group(1)] = target
    return guids


def parse_legacy(skin_dir: Path) -> Skin:
    mats = sorted(p for p in skin_dir.rglob("*.mat") if p.parent.name != "default")
    guids = _guid_map(skin_dir)
    _, _, images = _index_files(skin_dir)

    chosen: Path | None = None
    if not mats:
        raise ValueError("no .mat files")
    non_default = [m for m in mats if m.stem.lower() != "default"]
    chosen = (non_default or mats)[0]

    text = chosen.read_text(encoding="utf-8", errors="ignore")
    group = Group(index=0)
    for pattern in TEX_PATTERNS:
        for slot, guid in pattern.findall(text):
            if slot in TEXTURE_SLOTS and guid:
                path = guids.get(guid)
                if path is not None:
                    group.textures[slot] = path.name
                    group.paths[slot] = path
                else:
                    group.notes.append(f"{slot} GUID {guid[:8]} is stale, its file is not in this upload")
        if group.paths:
            break
    for pattern in FLOAT_PATTERNS:
        found = dict(pattern.findall(text))
        if found:
            group.floats = {k: float(v) for k, v in found.items() if k.startswith("_")}
            break
    for match in COLOR_RE.finditer(text):
        name = "_EmissionColor" if "Emission" in text[max(0, match.start() - 20):match.start()] else "_Color"
        if name not in group.colors:
            group.colors[name] = tuple(float(match.group(i)) for i in (1, 2, 3))  # type: ignore[assignment]
    _assign_by_keyword(group, images)

    meta_asset = next(skin_dir.rglob("meta.asset"), None)
    notes = [] if meta_asset else ["no meta.asset: single material assumed, skinMaterial0..N groups unread"]
    claimed = {group.paths.get(s) for s in TEXTURE_SLOTS if group.paths.get(s)}
    extras = [p for p in images if p not in claimed and not any(b in p.stem.lower() for b in IGNORED_STEMS)]
    skin = Skin(
        skin_id=skin_dir.name,
        root=skin_dir,
        format="legacy",
        item_type=None,
        groups=[group],
        notes=notes,
    )
    skin.extras = extras
    return skin


def load(skin_dir: Path) -> Skin:
    """Read one skin directory, whichever format it is in."""
    skin_dir = skin_dir.resolve()
    manifest = skin_dir / "manifest" / "manifest.txt"
    if not manifest.exists():
        candidate = next((p for p in skin_dir.rglob("manifest.txt") if p.is_file()), None)
        if candidate is not None:
            manifest = candidate
    if manifest.exists():
        return parse_modern(manifest, skin_dir)
    if any(skin_dir.rglob("*.mat")):
        return parse_legacy(skin_dir)
    assets = [p for p in skin_dir.rglob("*.asset")]
    raise ValueError(
        f"unknown-format: no manifest.txt and no .mat in {skin_dir}"
        + (f" (found {len(assets)} .asset file(s), needs a Unity serialised-file reader)" if assets else "")
    )
