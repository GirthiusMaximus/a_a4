"""Steam item-definition catalog: digest poll, archive fetch, and a stub path for offline runs.

This is the documented Web API, not a scraper. One call per poll when nothing changed.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

META_URL = "https://api.steampowered.com/IInventoryService/GetItemDefMeta/v1/?{query}"
ARCHIVE_URL = "https://api.steampowered.com/IGameInventory/GetItemDefArchive/v1/?{query}"
UA = "rustwatch/0.1 (rotation watcher; set RUSTWATCH_CONTACT for a real contact address)"


class SteamError(RuntimeError):
    pass


def _get_json(url: str, timeout: float = 30.0) -> dict | list:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https hosts
            raw = response.read(40_000_000)
    except urllib.error.HTTPError as exc:
        raise SteamError(f"Steam returned HTTP {exc.code} for {url.split('?')[0]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SteamError(f"could not reach Steam: {type(exc).__name__}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise SteamError("Steam returned a body that is not JSON") from exc


def _find(value, name: str):
    if isinstance(value, dict):
        if name in value:
            return value[name]
        for nested in value.values():
            found = _find(nested, name)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find(item, name)
            if found is not None:
                return found
    return None


def fetch_digest(appid: int, key: str) -> str:
    if not key:
        raise SteamError("STEAM_API_KEY is not set. Get a key at steamcommunity.com/dev/apikey, or run with STUB_CATALOG.")
    query = urllib.parse.urlencode({"key": key, "appid": appid})
    payload = _get_json(META_URL.format(query=query))
    digest = _find(payload, "digest")
    if not digest:
        raise SteamError(f"GetItemDefMeta returned no digest: {str(payload)[:200]}")
    return str(digest)


def fetch_catalog(appid: int, key: str, digest: str) -> list[dict]:
    query = urllib.parse.urlencode({"appid": appid, "digest": digest})
    payload = _get_json(ARCHIVE_URL.format(query=query), timeout=60.0)
    if isinstance(payload, str):
        rows = []
        for line in payload.splitlines():
            line = line.strip().rstrip(",")
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return [r for r in rows if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    raise SteamError("GetItemDefArchive returned a shape this build does not understand")


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize(item: dict) -> dict:
    """One item definition row to the fields the app stores. Missing keys become None, not guesses."""
    store_tags = item.get("store_tags") or ""
    tags = item.get("tags") or ""
    shortname = item.get("item_shortname") or item.get("itemshortname")
    if not shortname:
        for token in str(tags).replace(";", ",").split(","):
            if token.strip().lower().startswith("itemshortname:"):
                shortname = token.split(":", 1)[1].strip()
                break
    return {
        "id": str(item.get("itemdefid") or item.get("id") or ""),
        "name": item.get("name") or "",
        "item_shortname": shortname,
        "store_tags": store_tags,
        "tradable": _int(item.get("tradable"), 0),
        "icon_url": item.get("icon_url") or "",
        "limited": "time.limited" in str(store_tags),
        "display_type": item.get("display_type") or item.get("type") or "",
        "raw_modified": item.get("modified") or item.get("Timestamp") or "",
    }


def stub_observed_at(cfg) -> str:
    """A stub catalog may carry observedAt, so a replayed fixture can say when it was really seen."""
    stub = cfg.resolved_stub() if hasattr(cfg, "resolved_stub") else cfg.stub_catalog
    if not stub or not Path(stub).exists():
        return ""
    try:
        data = json.loads(Path(stub).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("observedAt") or "") if isinstance(data, dict) else ""


def load_catalog(cfg) -> tuple[str, list[dict], str]:
    """Returns (digest, items, source). Source is steam or stub."""
    stub = cfg.resolved_stub() if hasattr(cfg, "resolved_stub") else cfg.stub_catalog
    if stub:
        if not stub.exists():
            raise SteamError(f"STUB_CATALOG points at {stub}, which does not exist")
        raw = stub.read_text(encoding="utf-8")
        data = json.loads(raw)
        items = data.get("items") if isinstance(data, dict) else data
        digest = (data.get("digest") if isinstance(data, dict) else None) or f"stub-{abs(hash(raw)) % (10**12):012d}"
        return str(digest), [normalize(i) for i in items if isinstance(i, dict)], "stub"
    digest = fetch_digest(cfg.steam_appid, cfg.steam_api_key)
    items = [normalize(i) for i in fetch_catalog(cfg.steam_appid, cfg.steam_api_key, digest)]
    return digest, items, "steam"
