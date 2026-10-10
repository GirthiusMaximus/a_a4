# rustwatch

Internal dashboard for the current Rust item-store rotation: detect the week from Steam's catalog digest, screen the skin files, and put every flag in a review queue. Discord posts are built even when no bot token is configured; they sit in an outbox you can read.

This is not a public tool. Flags state a measurement. They never say a skin is infringing.

## Run it

Docker is the install. This sandbox cannot build an image (no daemon), so the same entrypoint is also runnable with a local venv, which is how it is tested here.

```bash
cp .env.example .env          # optional for the demo
docker compose --profile seed run --rm seed
docker compose up -d
```

Dashboard: `http://localhost:8000`. Three long-running containers share one SQLite file on `./data`.

| Container | Command | What it does |
|---|---|---|
| `app` | `serve` | dashboard + API |
| `watch` | `watch` | poll the catalog, then scan pending skin files |
| `bot` | `bot` | build Discord posts; send them only if `DISCORD_TOKEN` is set |

One-shot profiles: `seed` (demo data), `smoke` (hits every route the UI uses, then exits), `ledger` (crawl one marketplace config).

Without Docker:

```bash
python3 -m venv .venv && .venv/bin/pip install -r app/requirements.txt
PYTHONPATH=app:tools/skinprobe .venv/bin/python -m rustwatch seed --reset
PYTHONPATH=app:tools/skinprobe .venv/bin/python -m rustwatch serve
```

`python -m rustwatch smoke` is the test: it seeds a temp directory, serves it, checks the routes, and exits 0 or 1.

## What you need for a live store

1. A Steam Web API key (`STEAM_API_KEY`). Without one the watcher reads the demo catalogs left by `seed`, which is deliberate.
2. Skin files at `SKINS_HOST_DIR`, one folder per `itemdefid`. That is the path SteamCMD writes under `steamapps/workshop/content/252490`. The analyser does not download them.
3. Optional: `DISCORD_TOKEN` plus two channel ids. Empty token is a supported mode, not a broken one: open the Outbox tab.

Env vars are listed in `.env.example`. Thresholds `LEDGER_CROP_MAX_DISTANCE` (default 8) and `LEDGER_TEXTURE_MAX_DISTANCE` (default 3) are bits out of 64; the whole-texture number is tight because two unrelated flat patterns sit about 4 bits apart.

More detail: `docs/run.md`, `docs/rotation-and-screening.md`, `DESIGN.md`, `tools/skinprobe/README.md`.
