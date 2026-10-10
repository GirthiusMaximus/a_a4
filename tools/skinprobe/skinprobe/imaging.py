"""Texture decoding, composition metrics and logo-region extraction.

Everything here is measured from the file itself. Two deliberate limits: DDS and KTX are
not decoded (Pillow cannot, and pulling in texture2ddecoder is a dependency decision for
the user), and no judgement about ownership is made here, only geometry of pixels.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

UNSUPPORTED_SUFFIXES = {".dds", ".ktx", ".ktx2"}

MAX_USEFUL_SIZE = 2048
HASH_BITS = 64


@dataclass
class TextureMetrics:
    path: str
    slot: str
    decoded: bool
    width: int = 0
    height: int = 0
    mode: str = ""
    size_bytes: int = 0
    md5: str = ""
    is_power_of_two: bool = False
    exceeds_size_guideline: bool = False
    unique_colors: int = 0
    entropy_bits: float = 0.0
    dominant_share: float = 0.0
    mean_rgb: tuple[float, float, float] = (0.0, 0.0, 0.0)
    is_blank: bool = False
    alpha_coverage: float = 0.0
    cut_fraction: float = 0.0
    edge_energy: float = 0.0
    seam_ratio: float = 0.0
    normal_packing: str = "unknown"
    dhash: str = ""
    ahistsig: list[int] = field(default_factory=list)
    error: str = ""

    def to_json(self) -> dict:
        return asdict(self)


def _sha(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _entropy(channel: np.ndarray) -> float:
    counts = np.bincount(channel.ravel(), minlength=256).astype(np.float64)
    probs = counts[counts > 0] / max(counts.sum(), 1)
    return float(-(probs * np.log2(probs)).sum())


def measure(path: Path, slot: str, cutoff: float = 0.0) -> TextureMetrics:
    size = path.stat().st_size
    base = TextureMetrics(path=str(path), slot=slot, decoded=False, size_bytes=size, md5=_sha(path))
    if path.suffix.lower() in UNSUPPORTED_SUFFIXES:
        base.error = f"undecodable here: {path.suffix} needs a GPU texture decoder"
        return base
    try:
        with Image.open(path) as im:
            im.load()
            rgb = im.convert("RGBA") if "A" in im.getbands() or im.mode == "P" else im.convert("RGB")
            arr = np.asarray(rgb, dtype=np.uint8)
            base.decoded = True
            base.width, base.height, base.mode = im.width, im.height, im.mode
    except Exception as exc:  # noqa: BLE001 - a bad upload is data, not a crash
        base.error = f"decode failed: {type(exc).__name__}: {exc}"
        return base

    h, w = arr.shape[:2]
    pot = all(v and (v & (v - 1)) == 0 for v in (h, w))
    base.is_power_of_two = pot
    base.exceeds_size_guideline = max(h, w) > MAX_USEFUL_SIZE
    base.mean_rgb = tuple(float(c) for c in arr[..., :3].reshape(-1, 3).mean(axis=0))  # type: ignore[assignment]

    flat3 = arr[..., :3].reshape(-1, 3)
    base.unique_colors = int(np.unique(flat3, axis=0).shape[0])
    base.is_blank = base.unique_colors == 1
    base.entropy_bits = round(_entropy(flat3[:, 0]), 2)

    quant = np.right_shift(arr[..., :3], 3).astype(np.uint16)
    keys = (quant[..., 0] << 12) | (quant[..., 1] << 6) | quant[..., 2]
    counts = np.bincount(keys.ravel())
    base.dominant_share = round(float(counts.max() / keys.size), 4)

    if arr.shape[2] == 4:
        alpha = arr[..., 3]
        base.alpha_coverage = round(float((alpha < 255).mean()), 4)
        if 0.0 < cutoff < 1.0:
            base.cut_fraction = round(float((alpha < cutoff * 255).mean()), 4)

    gray = arr[..., :3].astype(np.float32).mean(axis=2)
    gx = np.abs(np.diff(gray, axis=1))
    gy = np.abs(np.diff(gray, axis=0))
    base.edge_energy = round(float(gx.mean() + gy.mean()), 2)

    if w > 8 and h > 8:
        seam = 0.0
        seam += float(np.abs(gray[:, -1] - gray[:, 0]).mean())
        seam += float(np.abs(gray[-1, :] - gray[0, :]).mean())
        interior = max(base.edge_energy, 1e-3)
        base.seam_ratio = round(float(seam / 2 / interior), 3)

    base.normal_packing = _normal_packing(slot, arr)
    base.dhash = _dhash(arr)
    base.ahistsig = _color_sig(arr)
    return base


def _normal_packing(slot: str, arr: np.ndarray) -> str:
    if slot != "_BumpMap":
        return "n/a"
    r, g = arr[..., 0].astype(np.int16), arr[..., 1].astype(np.int16)
    r_centred = abs(int(r.mean()) - 128) < 24
    g_centred = abs(int(g.mean()) - 128) < 24
    if r_centred and int(r.std()) < 4 and g_centred:
        return "dxt5nm"
    if r_centred and g_centred and (int(r.std()) > 4 or int(g.std()) > 4):
        return "rgb-raw (needs repack before use)"
    return "unclear"


def _grey_small(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    img = Image.fromarray(arr[..., :3], "RGB").resize((width, height), Image.Resampling.LANCZOS)
    return np.asarray(img.convert("L"), dtype=np.uint8)


def _dhash(arr: np.ndarray, size: int = 8) -> str:
    # width size+1 so each row yields exactly `size` comparisons: size * size bits, no stray row.
    grey = _grey_small(arr, size + 1, size).astype(np.int16)
    bits = (grey[:, 1:] > grey[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:0{size * size // 4}x}"


def _color_sig(arr: np.ndarray, bins: int = 16) -> list[int]:
    quant = np.right_shift(arr[..., :3], 8 - int(math.log2(bins))).astype(np.int64)
    keys = (quant[..., 0] * bins + quant[..., 1]) * bins + quant[..., 2]
    counts = np.bincount(keys.ravel(), minlength=bins**3)
    total = max(counts.sum(), 1)
    return [int(round(c / total * 1000)) for c in counts]


def hamming_hex(a: str, b: str) -> int:
    try:
        x, y = int(a, 16), int(b, 16)
    except (TypeError, ValueError):
        return 64
    return bin(x ^ y).count("1")


def find_logo_candidates(path: Path, out_dir: Path, limit: int = 8) -> list[dict]:
    """Isolated colour islands: a mark pasted onto a skin sits in a palette the base pattern never uses.

    This is a *candidate finder*, not a detector. It will miss a logo drawn in the base
    colours and will flag a bright camo blotch. A human decides, and the crop is the evidence.
    """
    try:
        with Image.open(path) as im:
            im.load()
            rgb = im.convert("RGB")
    except Exception:  # noqa: BLE001
        return []

    w, h = rgb.size
    if w < 32 or h < 32:
        return []
    scale = max(1, max(w, h) // 256)
    small = rgb.resize((max(w // scale, 1), max(h // scale, 1)), Image.Resampling.BOX)
    arr = np.asarray(small, dtype=np.uint8)
    quant = np.right_shift(arr, 4).astype(np.uint16)
    keys = (quant[..., 0] << 8) | (quant[..., 1] << 4) | quant[..., 2]

    counts = np.bincount(keys.ravel())
    total = keys.size
    candidates: list[dict] = []
    for colour, count in enumerate(counts):
        share = count / total
        if not (0.0008 <= share <= 0.05):
            continue
        mask = (keys == colour).astype(np.uint8)
        # A mark is a blob: its pixels sit next to each other. Noise, grain and dithered gradients hit
        # the same area window, so coherence is what keeps them out. Measured against the mask itself:
        # against the whole image even a solid 32px logo scores near zero, which is a bug I had first.
        padded = np.pad(mask, 1)
        neighbours = padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2] + padded[1:-1, 2:]
        solid = int(((neighbours >= 3) & (mask > 0)).sum())
        if float(solid) / float(max(1, int(mask.sum()))) < 0.5:
            continue
        for box, area in _label(mask):
            if area < max(14, int(total * 0.0004)):
                continue
            x0, y0, x1, y1 = box
            bw, bh = x1 - x0 + 1, y1 - y0 + 1
            if not (3 <= bw <= small.width // 2 and 3 <= bh <= small.height // 2):
                continue
            aspect = max(bw, bh) / max(1, min(bw, bh))
            fill = area / (bw * bh)
            if aspect > 3.2 or fill < 0.25:
                continue
            crop_box = (x0 * scale, y0 * scale, min(x1 * scale + scale, w), min(y1 * scale + scale, h))
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{path.stem}_c{len(candidates)}_{x0}-{y0}-{x1}-{y1}.png"
            crop_path = out_dir / stem
            with Image.open(path) as full:
                full.convert("RGB").crop(crop_box).save(crop_path)
            with Image.open(crop_path) as crop:
                crop_arr = np.asarray(crop.convert("RGB"), dtype=np.uint8)
            candidates.append(
                {
                    "crop": str(crop_path),
                    "bbox": list(crop_box),
                    "colorShare": round(share, 5),
                    "aspect": round(aspect, 2),
                    "fill": round(fill, 3),
                    "dhash": _dhash(crop_arr),
                    "note": "candidate only, not a match",
                }
            )
            if len(candidates) >= limit:
                return candidates
    return candidates


def _label(mask: np.ndarray) -> list[tuple[tuple[int, int, int, int], int]]:
    labels = np.zeros(mask.shape, dtype=np.int32)
    out: list[tuple[tuple[int, int, int, int], int]] = []
    current = 0
    h, w = mask.shape
    for y in range(h):
        for x in range(w):
            if mask[y, x] == 0 or labels[y, x]:
                continue
            current += 1
            stack = [(y, x)]
            area = 0
            min_x = max_x = x
            min_y = max_y = y
            while stack:
                cy, cx = stack.pop()
                if cy < 0 or cy >= h or cx < 0 or cx >= w or mask[cy, cx] == 0 or labels[cy, cx]:
                    continue
                labels[cy, cx] = current
                area += 1
                min_x, max_x = min(min_x, cx), max(max_x, cx)
                min_y, max_y = min(min_y, cy), max(max_y, cy)
                stack.extend(((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)))
            if area:
                out.append(((min_x, min_y, max_x, max_y), area))
    return out


def dhash_bytes(raw: bytes) -> tuple[str, int, int] | None:
    """dHash for bytes that were never written to disk. Returns (hash, width, height) or None."""
    import io

    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            arr = np.asarray(im.convert("RGB"), dtype=np.uint8)
            return _dhash(arr), im.width, im.height
    except Exception:  # noqa: BLE001 - an undecodable sample is a fact to record, not to raise on
        return None


def sharpen_hint(path: Path) -> str:
    """Report whether the texture has been filtered after the fact, which a resized
    stock image shows and a native 1024 paint usually does not."""
    try:
        with Image.open(path) as im:
            im.load()
            gray = im.convert("L")
            sharp = gray.filter(ImageFilter.UnsharpMask(radius=2, percent=200))
            before = float(np.asarray(gray, dtype=np.float32).std())
            after = float(np.asarray(sharp, dtype=np.float32).std())
    except Exception:  # noqa: BLE001
        return "unreadable"
    return "contrast-boosted" if after / max(before, 1e-3) > 1.22 else "normal"
