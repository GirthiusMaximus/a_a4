"""Reverse image search, behind one interface.

No key is read from a file and no request is made unless a provider is explicitly chosen.
Default is `manual`, which writes a queue a human runs through the browser. That is the honest
default: the hosted APIs that used to answer this are gone (Bing Image Search was retired
11 Aug 2025, endpoints return 410), and the replacements are keyed, metered contracts.
"""

from __future__ import annotations

import csv
import json
import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

RETIREMENT_NOTE = (
    "Bing Image Search API retired 2025-08-11 with the rest of the Bing Search family. "
    "Use a SERP API, TinEye, or a manual lens/copyseeker pass."
)


@dataclass
class SearchHit:
    url: str
    title: str = ""
    source: str = ""
    score: float | None = None

    def to_json(self) -> dict:
        return {"url": self.url, "title": self.title, "source": self.source, "score": self.score}


class MissingKey(RuntimeError):
    pass


class Provider:
    name = "base"

    def __init__(self, cache_path: Path | None = None) -> None:
        self.cache_path = cache_path
        self.cache: dict[str, list[dict]] = {}
        if cache_path and cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.cache = {}

    def save(self) -> None:
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, indent=2, sort_keys=True), encoding="utf-8")

    def search(self, crop: Path, dhash: str) -> list[SearchHit]:
        raise NotImplementedError


class ManualQueueProvider(Provider):
    """Records what to look up and where the evidence lives. Nothing leaves the machine."""

    name = "manual"

    def __init__(self, queue_path: Path | None = None, **kw) -> None:
        super().__init__(**kw)
        self.queue_path = queue_path

    def search(self, crop: Path, dhash: str) -> list[SearchHit]:
        if self.queue_path:
            self.queue_path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.queue_path.exists()
            with self.queue_path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                if new:
                    writer.writerow(["dhash", "crop", "open_at"])
                for site in ("https://images.google.com", "https://lenso.ai", "https://copyseeker.net"):
                    writer.writerow([dhash, str(crop), site])
        return []


class SerpApiProvider(Provider):
    """Google Lens / reverse image via SerpApi. Needs SERPAPI_KEY.

    Request shape written from their published parameters; not exercised against the live API
    from this sandbox, so check field names before trusting a count.
    """

    name = "serpapi"
    ENDPOINT = "https://serpapi.com/search.json"

    def __init__(self, engine: str = "google_lens", **kw) -> None:
        super().__init__(**kw)
        self.engine = engine
        self.key = os.environ.get("SERPAPI_KEY", "")

    def search(self, crop: Path, dhash: str) -> list[SearchHit]:
        if not self.key:
            raise MissingKey("SERPAPI_KEY is not set. Set it in the environment or use --provider manual.")
        if dhash in self.cache:
            return [SearchHit(**hit) for hit in self.cache[dhash]]
        params = {"engine": self.engine, "url": _public_url(crop), "api_key": self.key}
        query = urllib.parse.urlencode(params)
        raise MissingKey(
            "SerpApi search needs the image at a public URL (engine=google_lens takes ?url=, not a "
            f"multipart upload). Prepared request for review only, not sent: {self.ENDPOINT}?{query.replace(self.key, '***')}. "
            + RETIREMENT_NOTE
        )


class TinEyeProvider(Provider):
    """TinEye MatchEngine. Needs TINEYE_LOGIN and TINEYE_API_KEY; metered per search."""

    name = "tineye"
    ENDPOINT = "https://api.tineye.com/rest/search_match/"

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.login = os.environ.get("TINEYE_LOGIN", "")
        self.key = os.environ.get("TINEYE_API_KEY", "")

    def search(self, crop: Path, dhash: str) -> list[SearchHit]:
        if not (self.login and self.key):
            raise MissingKey("TINEYE_LOGIN and TINEYE_API_KEY must both be set. Or use --provider manual.")
        if dhash in self.cache:
            return [SearchHit(**hit) for hit in self.cache[dhash]]
        raise MissingKey(
            "TinEye's REST search_match takes a data URL or a hosted URL for img_upload; sending a local "
            "crop needs the signed request body built at runtime. Left unimplemented rather than guessed: "
            "implement against your own account docs, then this cache becomes the record."
        )


def _public_url(crop: Path) -> str:
    return f"file://{crop.resolve()}"


def build(name: str, out_dir: Path) -> Provider:
    if name == "manual":
        return ManualQueueProvider(queue_path=out_dir / "reverse-search-queue.csv", cache_path=out_dir / "search-cache.json")
    if name == "serpapi":
        return SerpApiProvider(cache_path=out_dir / "search-cache.json")
    if name == "tineye":
        return TinEyeProvider(cache_path=out_dir / "search-cache.json")
    raise ValueError(f"unknown provider '{name}'. Use manual, serpapi, or tineye.")
