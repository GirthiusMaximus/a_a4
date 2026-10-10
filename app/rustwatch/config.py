"""Environment configuration. Every knob is one env var, read once, echoed by /api/state."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _default_skins_dir() -> Path:
    """The seed writes its fixtures here too, so DATA_DIR/skins is the fallback outside the container.
    One root for both means a Scan click in the UI analyses what the demo actually created."""
    override = os.environ.get("SKINS_DIR", "").strip()
    if override:
        return Path(override)
    container = Path("/skins")
    return container if container.is_dir() else _default_data_dir() / "skins"


def _default_data_dir() -> Path:
    """/data inside the image, ./data anywhere it is not writable, so `python -m rustwatch` works outside Docker."""
    override = os.environ.get("DATA_DIR", "").strip()
    if override:
        return Path(override)
    container = Path("/data")
    if container.is_dir() and os.access(container, os.W_OK):
        return container
    return Path.cwd() / "data"


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class Config:
    data_dir: Path = field(default_factory=_default_data_dir)
    skins_dir: Path = field(default_factory=_default_skins_dir)
    host: str = field(default_factory=lambda: os.environ.get("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _int("PORT", 8000))

    steam_api_key: str = field(default_factory=lambda: os.environ.get("STEAM_API_KEY", ""))
    steam_appid: int = field(default_factory=lambda: _int("STEAM_APPID", 252490))
    stub_catalog: Path | None = field(default_factory=lambda: Path(p) if (p := os.environ.get("STUB_CATALOG", "").strip()) else None)

    watch_interval_min: int = field(default_factory=lambda: _int("WATCH_INTERVAL_MIN", 60))
    watch_on_start: bool = field(default_factory=lambda: _bool("WATCH_ON_START", True))
    ingest_limit: int = field(default_factory=lambda: _int("INGEST_LIMIT", 50))
    # Distance in bits out of 64. Crops get the looser number on purpose: see ipcheck.match_pixels.
    ledger_crop_max_distance: int = field(default_factory=lambda: _int("LEDGER_CROP_MAX_DISTANCE", 8))
    ledger_texture_max_distance: int = field(default_factory=lambda: _int("LEDGER_TEXTURE_MAX_DISTANCE", 3))

    discord_token: str = field(default_factory=lambda: os.environ.get("DISCORD_TOKEN", ""))
    discord_rotation_channel: str = field(default_factory=lambda: os.environ.get("DISCORD_ROTATION_CHANNEL", ""))
    discord_flag_channel: str = field(default_factory=lambda: os.environ.get("DISCORD_FLAG_CHANNEL", ""))
    bot_interval_sec: int = field(default_factory=lambda: _int("BOT_INTERVAL_SEC", 60))
    bot_dry_run: bool = field(default_factory=lambda: _bool("BOT_DRY_RUN", False))
    public_base_url: str = field(default_factory=lambda: os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000"))

    demo: bool = field(default_factory=lambda: _bool("RUSTWATCH_DEMO", False))
    review_host: str = field(default_factory=lambda: os.environ.get("REVIEW_HOST", "reviewer"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "rustwatch.sqlite3"

    @property
    def crops_dir(self) -> Path:
        return self.data_dir / "crops"

    @property
    def ledger_dir(self) -> Path:
        return self.data_dir / "ledger"

    @property
    def discord_live(self) -> bool:
        return bool(self.discord_token and self.discord_rotation_channel and not self.bot_dry_run)

    def resolved_stub(self) -> Path | None:
        """Explicit STUB_CATALOG wins. Otherwise, if a seed left catalogs on disk, use the newest.

        That is what lets `Watch now` work after a demo seed with no Steam key, instead of failing
        with a missing-key error that looks like the button is broken.
        """
        if self.stub_catalog:
            return self.stub_catalog
        demo = self.data_dir / "demo" / "catalogs"
        if demo.is_dir():
            files = sorted(demo.glob("cat-*.json"))
            if files:
                return files[-1]
        return None

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.crops_dir, self.ledger_dir):
            path.mkdir(parents=True, exist_ok=True)

    def to_json(self) -> dict:
        return {
            "dataDir": str(self.data_dir),
            "ledger": {
                "cropMaxDistance": self.ledger_crop_max_distance,
                "textureMaxDistance": self.ledger_texture_max_distance,
            },
            "skinsDir": str(self.skins_dir),
            "skinsMounted": self.skins_dir.is_dir(),
            "steam": {
                "configured": bool(self.steam_api_key),
                "appid": self.steam_appid,
                "stub": str(self.resolved_stub()) if self.resolved_stub() else None,
            },
            "discord": {
                "configured": bool(self.discord_token),
                "channels": {
                    "rotation": self.discord_rotation_channel or None,
                    "flags": self.discord_flag_channel or None,
                },
                "mode": "live" if self.discord_live else "outbox only (no token, or BOT_DRY_RUN)",
            },
            "watch": {"intervalMin": self.watch_interval_min, "onStart": self.watch_on_start},
            "demo": self.demo,
        }
