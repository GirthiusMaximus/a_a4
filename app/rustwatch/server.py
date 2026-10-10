"""HTTP surface. Every control in the UI is wired to one of these; nothing is decorative.

Two file routes serve images from the two roots the analyser reads and writes. Both resolve the path
and reject anything that escapes its root, because the crop directory is written by a scanner that
walks a mounted volume.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .bot import run_once as bot_run_once
from .config import Config
from .db import Store, utcnow
from .ingest import run as ingest_run
from .watcher import run_once as watch_run_once

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="rustwatch", version=__version__)
store: Store | None = None
cfg: Config | None = None


def db() -> Store:
    if store is None:
        raise HTTPException(status_code=503, detail="database not initialised")
    return store


def conf() -> Config:
    if cfg is None:
        raise HTTPException(status_code=503, detail="config not initialised")
    return cfg


def create(config: Config) -> FastAPI:
    global store, cfg
    config.ensure_dirs()
    cfg = config
    store = Store(config.db_path)
    store.set_meta("started_at", utcnow())
    if config.demo:
        store.set_meta("demo_mode", "1")
    return app


class Decision(BaseModel):
    action: str = Field(pattern="^(clear|escalate)$")
    note: str = ""
    ids: list[int] = Field(default_factory=list)


def _safe_join(roots: Path | list[Path], rel: str) -> Path:
    """Resolve rel inside one of roots. Traversal in, or outside every root, is a 400."""
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        raise HTTPException(status_code=400, detail="unacceptable path")
    for root in (roots if isinstance(roots, list) else [roots]):
        try:
            target = (root / rel).resolve()
            target.relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        if target.is_file():
            return target
    raise HTTPException(status_code=404, detail="no such file under the mounted roots")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    page = STATIC / "index.html"
    if not page.exists():
        raise HTTPException(status_code=500, detail="static assets missing from the image")
    return page.read_text(encoding="utf-8")


@app.get("/assets/{name}")
def asset(name: str):
    return FileResponse(_safe_join(STATIC, f"assets/{name}"))


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__, "time": utcnow(), "counts": db().counts()}


@app.get("/api/state")
def state() -> dict:
    conf_ = conf()
    counts = db().counts()
    last = db().one("SELECT * FROM rotation ORDER BY id DESC LIMIT 1")
    return {
        "config": conf_.to_json(),
        "counts": counts,
        "lastRotation": last,
        "lastWatchAt": db().get_meta("last_watch_at"),
        "lastWatchError": db().get_meta("last_watch_error"),
        "catalogSource": db().get_meta("catalog_source"),
        "demo": conf_.demo or db().get_meta("demo_mode") == "1",
        "reviewer": conf_.review_host,
        "serverTime": utcnow(),
    }


@app.get("/api/rotations")
def rotations() -> dict:
    rows = db().rows(
        """
        SELECT r.*,
               (SELECT COUNT(*) FROM skin s WHERE s.first_seen_rotation = r.id) AS new_skins,
               (SELECT COUNT(*) FROM finding f JOIN skin s ON s.id = f.skin_id WHERE s.first_seen_rotation = r.id AND f.status = 'open') AS open_findings
        FROM rotation r ORDER BY r.id DESC
        """
    )
    return {"rotations": rows}


@app.get("/api/skins")
def skins(rotation: str | None = None, q: str = "", flag: str | None = None, limit: int = 60, offset: int = 0) -> dict:
    where, args = ["1=1"], []
    if rotation == "current":
        # An alias so a hand-written or shared link does not need to know the row id.
        newest = db().current_rotation_id()
        if newest is not None:
            where.append("s.first_seen_rotation = ?")
            args.append(newest)
    elif rotation and rotation != "all":
        try:
            where.append("s.first_seen_rotation = ?")
            args.append(int(rotation))
        except ValueError:
            raise HTTPException(status_code=400, detail="rotation must be an id, 'current' or 'all'") from None
    if q:
        where.append("(s.name LIKE ? OR s.id LIKE ? OR s.item_shortname LIKE ?)")
        args += [f"%{q}%"] * 3
    if flag == "open":
        where.append("EXISTS (SELECT 1 FROM finding f WHERE f.skin_id = s.id AND f.status = 'open')")
    elif flag == "clean":
        where.append("NOT EXISTS (SELECT 1 FROM finding f WHERE f.skin_id = s.id AND f.status = 'open')")
    clause = " AND ".join(where)
    total = (db().one(f"SELECT COUNT(*) AS n FROM skin s WHERE {clause}", tuple(args)) or {"n": 0})["n"]
    rows = db().rows(
        f"""
        SELECT s.*,
               (SELECT COUNT(*) FROM finding f WHERE f.skin_id = s.id AND f.status = 'open') AS open_findings,
               (SELECT MAX(f.severity) FROM finding f WHERE f.skin_id = s.id AND f.status = 'open') AS worst,
               (SELECT t.path FROM texture t WHERE t.skin_id = s.id AND t.slot = '_MainTex' AND (t.error IS NULL OR t.error = '') ORDER BY t.group_index LIMIT 1) AS main_tex,
               (SELECT COUNT(*) FROM finding f WHERE f.skin_id = s.id AND f.status = 'cleared') AS cleared_findings
        FROM skin s WHERE {clause}
        ORDER BY CASE WHEN open_findings > 0 THEN 0 ELSE 1 END, s.id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(args) + (min(limit, 200), max(offset, 0)),
    )
    return {"total": total, "skins": rows}


@app.get("/api/skins/{skin_id}")
def skin_detail(skin_id: str) -> dict:
    row = db().one("SELECT * FROM skin WHERE id = ?", (skin_id,))
    if not row:
        raise HTTPException(status_code=404, detail="no such skin")
    row["textures"] = db().rows("SELECT * FROM texture WHERE skin_id = ? ORDER BY group_index, slot", (skin_id,))
    row["findings"] = db().rows("SELECT * FROM finding WHERE skin_id = ? ORDER BY id", (skin_id,))
    for finding in row["findings"]:
        finding["sources"] = json.loads(finding.get("sources") or "[]")
    return row


@app.get("/api/queue")
def queue() -> dict:
    rows = db().queue()
    return {"queue": rows, "waiting": len(rows), "counts": db().counts()}


@app.get("/api/findings/{finding_id}")
def finding(finding_id: int) -> dict:
    row = db().evidence(finding_id)
    if not row:
        raise HTTPException(status_code=404, detail="no such finding")
    return row


@app.post("/api/findings/{finding_id}/decision")
def decide(finding_id: int, body: Decision) -> dict:
    changed = db().decide(body.ids or [finding_id], body.action, conf().review_host, body.note.strip())
    if not changed:
        raise HTTPException(status_code=404, detail="nothing matched those ids")
    return {"updated": changed, "action": body.action, "counts": db().counts()}


@app.get("/api/outbox")
def outbox() -> dict:
    return {"outbox": db().outbox(), "discord": conf().to_json()["discord"]}


@app.post("/api/run/watch")
def run_watch() -> dict:
    result = watch_run_once(db(), conf())
    return {"result": result, "counts": db().counts()}


@app.post("/api/run/ingest")
def run_ingest(limit: int = 0) -> dict:
    return {"result": ingest_run(db(), conf(), limit or None, log=lambda *_: None), "counts": db().counts()}


@app.post("/api/run/bot")
def run_bot() -> dict:
    return {"result": bot_run_once(db(), conf(), log=lambda *_: None)}


@app.get("/files/texture/{rel:path}")
def texture_file(rel: str):
    config = conf()
    return FileResponse(_safe_join([Path(config.data_dir), Path(config.skins_dir)], rel))


@app.get("/files/crop/{rel:path}")
def crop_file(rel: str):
    return FileResponse(_safe_join(Path(conf().crops_dir), rel))


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    """A queue screen that dies silently is worse than one that says what broke."""
    return JSONResponse(status_code=500, content={"error": f"{type(exc).__name__}: {exc}", "path": request.url.path})
