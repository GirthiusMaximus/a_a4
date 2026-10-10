"""Discord: two channels, one queue table, delivered over REST with no bot library.

Without a token nothing here fails or pretends. Posts are written to the `outbox` table with
state `queued`, and the dashboard has a tab that shows exactly what would have been sent. That is a
testable integration long before a token exists, and it is what an operator needs when the bot is
quiet and someone asks why.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .db import Store, utcnow

API = "https://discord.com/api/v10"

COLOUR = {
    "oxide": 0xEF7A3D,
    "patina": 0x4FB8A5,
    "amber": 0xD9A442,
    "danger": 0xE05C5C,
}

SEVERITY_COLOUR = {"high": COLOUR["danger"], "medium": COLOUR["amber"], "low": COLOUR["patina"]}

MEASURED_LINE = "This is a measurement against a captured page, not a claim about ownership. Open the source before acting on it."


def _post_message(cfg, channel: str, payload: dict) -> tuple[bool, str]:
    if not cfg.discord_token or not channel:
        return False, "no token or channel id configured"
    url = f"{API}/channels/{channel}/messages"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Authorization": f"Bot {cfg.discord_token}", "Content-Type": "application/json", "User-Agent": "rustwatch/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed Discord host
            return 200 <= response.status < 300, ""
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(400).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        return False, f"HTTP {exc.code} {detail}".strip()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def rotation_payload(store: Store, rotation: dict, base_url: str) -> dict:
    skins = store.rows("SELECT id, name, item_shortname FROM skin WHERE first_seen_rotation = ? ORDER BY name", (rotation["id"],))
    flagged = store.rows(
        "SELECT DISTINCT s.id FROM finding f JOIN skin s ON s.id = f.skin_id WHERE s.first_seen_rotation = ? AND f.status = 'open'",
        (rotation["id"],),
    )
    fields = [{"name": "Skins in this rotation", "value": str(len(skins)), "inline": True}]
    fields.append({"name": "Flagged for review", "value": str(len(flagged)), "inline": True})
    if skins:
        names = "\n".join(f"{s['name'] or s['id']} (`{s['id']}`)" for s in skins[:10])
        more = "" if len(skins) <= 10 else f"\n{len(skins) - 10} more"
        fields.append({"name": "Items", "value": f"{names}{more}"[:1024]})
    return {
        "embeds": [
            {
                "title": f"Rust store rotation #{rotation['id']}",
                "description": f"First seen by this watcher at {rotation['first_seen']}. Rotation dates are not published, so this is an observation, not a release date.",
                "color": COLOUR["oxide"],
                "fields": fields,
                "url": f"{base_url}/?view=browse&rotation={rotation['id']}",
            }
        ]
    }


def flag_payload(store: Store, finding: dict, base_url: str) -> dict:
    sources = json.loads(finding.get("sources") or "[]")
    links = [s.get("url") for s in sources if s.get("url")]
    verified = any(s.get("verified") for s in sources)
    fields = [
        {"name": "Skin", "value": f"{finding.get('skin_name') or finding['skin_id']} (`{finding['skin_id']}`)", "inline": False},
        {"name": "Measured", "value": (finding.get("title") or finding["code"])[:256], "inline": False},
        {"name": "Why it was raised", "value": (finding.get("detail") or "")[:1024], "inline": False},
        {"name": "Source checked by a person", "value": "yes" if verified else "no", "inline": True},
    ]
    if links:
        fields.append({"name": "Sources", "value": "\n".join(f"<{u}>" for u in links[:5])[:1024], "inline": False})
    return {
        "content": None,
        "embeds": [
            {
                "title": f"{finding['severity'].upper()}  {finding['code']}",
                "description": MEASURED_LINE,
                "color": SEVERITY_COLOUR.get(finding["severity"], COLOUR["patina"]),
                "fields": fields,
                "url": f"{base_url}/?view=review&finding={finding['id']}",
                "footer": {"text": f"rustwatch finding #{finding['id']}  ·  no creator is named by this bot"},
            }
        ],
    }


def queue_new(store: Store, cfg, log=print) -> int:
    rotation = store.open_rotation()
    if rotation and store.get_meta("last_posted_rotation") != str(rotation["id"]):
        store.record_outbox("rotation", "rotation", rotation_payload(store, rotation, cfg.public_base_url), rotation_id=rotation["id"])
        store.set_meta("last_posted_rotation", str(rotation["id"]))
        log(f"queued rotation post for #{rotation['id']}")

    fresh = store.rows(
        """
        SELECT f.*, s.name AS skin_name FROM finding f JOIN skin s ON s.id = f.skin_id
        WHERE f.status = 'open' AND f.severity IN ('high', 'medium')
          AND NOT EXISTS (SELECT 1 FROM outbox o WHERE o.kind = 'finding' AND o.finding_id = f.id)
        ORDER BY CASE f.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, f.id
        LIMIT 20
        """
    )
    for finding in fresh:
        store.record_outbox(
            "flags", "finding", flag_payload(store, finding, cfg.public_base_url), skin_id=finding["skin_id"], finding_id=finding["id"]
        )
        log(f"queued flag post for finding #{finding['id']} on {finding['skin_id']}")
    return len(fresh)


def deliver(store: Store, cfg, log=print) -> dict:
    sent = failed = queued = 0
    for row in store.pending_outbox():
        channel = cfg.discord_rotation_channel if row["channel"] == "rotation" else cfg.discord_flag_channel
        payload = json.loads(row["payload"])
        if not cfg.discord_live:
            store.mark_queued(row["id"], "not sent: no DISCORD_TOKEN, no channel id, or BOT_DRY_RUN")
            queued += 1
            continue
        ok, error = _post_message(cfg, channel, payload)
        store.mark_sent(row["id"], "" if ok else error)
        if ok:
            sent += 1
            log(f"sent {row['kind']} to #{row['channel']}")
        else:
            failed += 1
            log(f"discord delivery failed: {error}")
    return {"sent": sent, "failed": failed, "queuedForReview": queued, "dryRun": not cfg.discord_live}


def run_once(store: Store, cfg, log=print) -> dict:
    queued = queue_new(store, cfg, log)
    delivery = deliver(store, cfg, log)
    return {"queued": queued, **delivery}


def loop(store: Store, cfg, log=print) -> None:
    log(f"bot started: mode {'live' if cfg.discord_live else 'outbox'}, poll every {cfg.bot_interval_sec}s")
    while True:
        try:
            run_once(store, cfg, log)
        except Exception as exc:  # noqa: BLE001 - a failed tick must not kill the container
            log(f"bot tick failed: {type(exc).__name__}: {exc}")
        time.sleep(max(15, cfg.bot_interval_sec))
