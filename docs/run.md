# Running rustwatch

## What gets installed

One Docker image, tagged `rustwatch:0.1`. `docker-compose.yml` runs it three times:

- **app** on port 8000. The dashboard. The only process that has to be reachable from a browser.
- **watch**. Polls Steam (or a stub catalog) on `WATCH_INTERVAL_MIN`, diffs `itemdefid`, opens a rotation when the digest moves, then runs the analyser over any skin folder that has not been screened yet.
- **bot**. Builds Discord embeds into the `outbox` table. Delivers them only when `DISCORD_TOKEN` and a channel id are set. Otherwise the row stays `queued` and the Outbox tab is how you read it.

SQLite lives on the `./data` bind mount (`DATA_DIR=/data` in the container). Crops, the licence ledger, and demo fixtures live there too. Skin files are a second mount at `/skins`.

There is no Postgres, no Redis, no nginx, no bot library. Adding any of those would be a decision, not a default.

## First run, demo, no keys

```bash
cp .env.example .env
docker compose --profile seed run --rm seed
docker compose up -d
```

`seed` writes 18 synthetic store listings and real PNG + manifest files, then runs the real analyser over them. Defects are planted on purpose so every state in `DESIGN.md` section 7 exists on screen:

| id | what you should see |
|---|---|
| 700001 | clean, no findings |
| 700002 | planted emblem, then a non-commercial ledger hit |
| 700003 | pasted image, wrap does not close (`IP-PASTE-SEAM`) |
| 700004 | blank `_MainTex` on group 1 |
| 700005 | 300x300 map (`TEC-NON-POT`) |
| 700006 | legacy Unity `.mat` upload, parsed |
| 700007 | name contains `ACOG` (`TM-NAME-HIT`) |
| 700008 | never downloaded (`no-files`) |
| 700009 | textures, no manifest (`unreadable`) |

The item list is fake. The numbers are not: they come from the same `scan_skin` path a live file would take.

After seed, `Watch now` keeps working without a Steam key because the watcher falls back to `data/demo/catalogs/cat-3.json`.

## First run, live store

1. Get a key at `steamcommunity.com/dev/apikey`. Put it in `.env` as `STEAM_API_KEY`.
2. Ingest workshop files with SteamCMD into some host path, then set `SKINS_HOST_DIR` to that path. The analyser looks up `SKINS_DIR/<itemdefid>/`.
3. `docker compose up -d --build`. Do not run `seed` against a live database you care about: `--reset` deletes it.
4. Discord is optional. Channel ids, not names. The bot needs View Channel, Send Messages, Embed Links.

A SteamCMD one-liner is out of scope for this file because it needs a live login. The workshop content path for Rust is `steamapps/workshop/content/252490/<publishedfileid>`, and `publishedfileid` is the same number as `itemdefid` on a store skin.

## Commands the image understands

```
python -m rustwatch serve     # dashboard
python -m rustwatch watch     # poll loop
python -m rustwatch once      # one poll, then exit
python -m rustwatch scan      # analyse pending skins once
python -m rustwatch bot       # outbox loop
python -m rustwatch seed [--reset]
python -m rustwatch ledger --site /site/example-shop.json --out /data/ledger/runs/manual
python -m rustwatch smoke     # seed a temp dir, hit every UI route, exit 0/1
python -m rustwatch version
```

## Without Docker

Same code, same env vars. `DATA_DIR` defaults to `./data` when `/data` is not writable, which is why `python -m rustwatch serve` works on a laptop.

```bash
python3 -m venv .venv
.venv/bin/pip install -r app/requirements.txt
PYTHONPATH=app:tools/skinprobe .venv/bin/python -m rustwatch smoke
PYTHONPATH=app:tools/skinprobe .venv/bin/python -m rustwatch seed --reset
PYTHONPATH=app:tools/skinprobe .venv/bin/python -m rustwatch serve
```

## Things that look like bugs and are not

- **Empty Discord token.** The Outbox tab fills up and nothing leaves the machine. That is the documented mode.
- **`Watch now` after a demo seed, no Steam key.** It re-reads the stub catalog. Digest unchanged, so it reports no change. That is success.
- **A flag you cleared comes back on re-scan.** It must not. `finding.dedupe_key` is unique; a re-scan skips the row. If it comes back, the key drifted and that is a bug.
- **No countdown, no "released on".** Nobody publishes rotation dates. Weeks are labelled `First seen`.
- **`verified: false` on every source** until a person opens it. The UI says `unverified` in words.

## Bind mounts and uid

The image runs as root. A bind-mounted `./data` owned by your login is otherwise unwritable from uid 10001, which is how `docker compose up` fails on a fresh clone. This is an internal tool; that trade is recorded here rather than hidden behind an entrypoint.

## Stopping

```bash
docker compose down          # keep ./data
docker compose down -v       # there are no named volumes; this changes nothing
rm -rf data                  # actually wipe the database and demo files
```
