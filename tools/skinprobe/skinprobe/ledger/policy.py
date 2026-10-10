"""Fetch policy: robots.txt, per-host spacing, conditional GET, an on-disk cache, offline mode.

Nothing here decides what a licence means. It decides only whether and how a page is asked for,
and it keeps a record of that decision so a run can be reproduced or disputed later.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.robotparser import RobotFileParser

DEFAULT_UA = "skinprobe-ledger/0.1 (+contact: set your contact address before running this)"


@dataclass
class FetchResult:
    url: str
    status: int = 0
    text: str = ""
    cached: bool = False
    source: str = "network"  # network | cache | offline | blocked
    robots: str = "unknown"  # allowed | disallowed | unknown | unreadable | not-checked
    error: str = ""
    bytes: int = 0

    def to_json(self) -> dict:
        return asdict(self)


def key_for(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:24]


@dataclass
class FetchPolicy:
    user_agent: str = DEFAULT_UA
    min_interval_sec: float = 3.0
    jitter_sec: float = 1.5
    timeout_sec: float = 25.0
    max_retries: int = 2
    respect_robots: bool = True
    cache_dir: Path | None = None
    offline_dir: Path | None = None
    max_bytes: int = 4_000_000

    def __post_init__(self) -> None:
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._index: dict[str, dict] = {}
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            index = self.cache_dir / "index.json"
            if index.exists():
                try:
                    self._index = json.loads(index.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    self._index = {}

    def save(self) -> None:
        if not self.cache_dir:
            return
        (self.cache_dir / "index.json").write_text(json.dumps(self._index, indent=2, sort_keys=True), encoding="utf-8")

    def _host(self, url: str) -> str:
        parts = urllib.parse.urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    def _robots_allows(self, url: str) -> str:
        if not self.respect_robots:
            return "not-checked"
        host = self._host(url)
        if host not in self._robots:
            self._robots[host] = self._load_robots(host)
        parser = self._robots[host]
        if parser is None:
            return "unreadable"
        return "allowed" if parser.can_fetch(self.user_agent, url) else "disallowed"

    def _load_robots(self, host: str) -> RobotFileParser | None:
        url = f"{host}/robots.txt"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:  # noqa: S310 - https/http only, host from the config
                body = response.read(200_000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return None
        parser = RobotFileParser()
        parser.parse(body.splitlines())
        return parser

    def _space(self, url: str) -> None:
        host = self._host(url)
        last = self._last_hit.get(host, 0.0)
        wait = self.min_interval_sec - (time.time() - last)
        if wait > 0:
            time.sleep(wait + random.uniform(0, self.jitter_sec))
        self._last_hit[host] = time.time()

    def fetch(self, url: str, *, binary: bool = False) -> FetchResult:
        if self.offline_dir:
            return self._offline(url)

        robots = self._robots_allows(url)
        if robots == "disallowed":
            return FetchResult(url=url, status=0, robots=robots, source="blocked", error="robots.txt disallows this path")

        cached = self._index.get(key_for(url), {})
        headers = {"User-Agent": self.user_agent, "Accept": "text/html,image/*;q=0.5,*/*;q=0.2"}
        if cached.get("etag"):
            headers["If-None-Match"] = str(cached["etag"])
        elif cached.get("lastModified"):
            headers["If-Modified-Since"] = str(cached["lastModified"])

        self._space(url)
        attempt = 0
        while True:
            attempt += 1
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                    raw = response.read(self.max_bytes)
                    ctype = response.headers.get("Content-Type", "")
                    encoding = "identity"
                    if "charset=" in ctype:
                        encoding = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
                    result = FetchResult(
                        url=url,
                        status=response.status,
                        text="" if binary else raw.decode(encoding, "replace"),
                        robots=robots,
                        source="network",
                        bytes=len(raw),
                    )
                    if not binary:
                        self._remember(url, response.headers, raw)
                    if binary:
                        result.text = ""
                        self._write_bytes(url, raw)
                    return result
            except urllib.error.HTTPError as exc:
                if exc.code == 304 and cached.get("file"):
                    path = self.cache_dir / cached["file"] if self.cache_dir else None
                    if path and path.exists():
                        raw = path.read_bytes()
                        return FetchResult(url=url, status=304, cached=True, robots=robots, source="cache", text="" if binary else raw.decode("utf-8", "replace"), bytes=len(raw))
                if exc.code in (429, 500, 502, 503, 504) and attempt <= self.max_retries:
                    delay = float(exc.headers.get("Retry-After") or 0) or (2.0 ** attempt)
                    time.sleep(min(delay, 60.0))
                    continue
                return FetchResult(url=url, status=exc.code, robots=robots, error=f"HTTP {exc.code}", bytes=0)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt <= self.max_retries:
                    time.sleep(2.0 ** attempt)
                    continue
                return FetchResult(url=url, robots=robots, error=f"{type(exc).__name__}: {exc}")

    def _remember(self, url: str, headers, raw: bytes) -> None:
        if not self.cache_dir:
            return
        name = f"{key_for(url)}.html"
        (self.cache_dir / name).write_bytes(raw)
        self._index[key_for(url)] = {
            "url": url,
            "file": name,
            "etag": headers.get("ETag"),
            "lastModified": headers.get("Last-Modified"),
            "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sha1": hashlib.sha1(raw).hexdigest(),
        }

    def _write_bytes(self, url: str, raw: bytes) -> None:
        if not self.cache_dir:
            return
        images = self.cache_dir / "images"
        images.mkdir(parents=True, exist_ok=True)
        (images / f"{key_for(url)}.img").write_bytes(raw)

    def image_bytes(self, url: str) -> bytes | None:
        if self.offline_dir:
            path = self.offline_dir / f"{key_for(url)}.img"
            return path.read_bytes() if path.exists() else None
        entry = self._index.get(key_for(url))
        if entry and self.cache_dir:
            path = self.cache_dir / "images" / f"{key_for(url)}.img"
            if path.exists():
                return path.read_bytes()
        result = self.fetch(url, binary=True)
        if result.source == "network" and self.cache_dir:
            return (self.cache_dir / "images" / f"{key_for(url)}.img").read_bytes() if (self.cache_dir / "images" / f"{key_for(url)}.img").exists() else None
        return None

    def _offline(self, url: str) -> FetchResult:
        assert self.offline_dir is not None
        for name in (f"{key_for(url)}.html", f"{key_for(url)}.bin", f"{Path(urllib.parse.urlsplit(url).path).name}"):
            path = self.offline_dir / name
            if path.exists():
                raw = path.read_bytes()
                return FetchResult(url=url, status=200, text=raw.decode("utf-8", "replace"), source="offline", robots="not-checked", bytes=len(raw))
        return FetchResult(url=url, status=404, source="offline", robots="not-checked", error="not in the offline corpus")
