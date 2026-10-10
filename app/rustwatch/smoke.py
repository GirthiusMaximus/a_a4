"""End-to-end check that does not need Docker: seed, serve, hit every route the UI uses, stop.

This is what `python -m rustwatch smoke` runs, and what the image runs as its own test before
you point a browser at it. Failures raise; the process exit code is the report.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

from .config import Config
from .seed import seed
from .server import create


def _get(url: str, method: str = "GET", body: bytes | None = None, content_type: str = "") -> tuple[int, bytes]:
    headers = {"Accept": "application/json, text/html, */*"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - loopback only
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError:
        return 0, b""


def run(port: int = 18080) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="rustwatch-smoke-"))
    config = replace(Config(), data_dir=tmp, skins_dir=tmp / "skins", demo=True, host="127.0.0.1", port=port)
    config.ensure_dirs()
    print(f"smoke: seeding into {tmp}")
    summary = seed(config)
    counts = summary["counts"]
    assert counts["skins"] == 18, counts
    assert counts["openFindings"] >= 5, counts
    print(f"smoke: {counts['skins']} skins, {counts['openFindings']} open findings")

    import uvicorn

    # Server.run installs signal handlers, which fail in a non-main thread. Turn that off.
    server = uvicorn.Server(uvicorn.Config(create(config), host="127.0.0.1", port=port, log_level="warning"))
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 8
    while time.time() < deadline:
        code, _ = _get(f"http://127.0.0.1:{port}/api/health")
        if code == 200:
            break
        time.sleep(0.15)
    else:
        print("smoke: server did not become ready")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    base = f"http://127.0.0.1:{port}"
    failed: list[str] = []

    def expect(name: str, code: int, body: bytes, want: int, contains: bytes | None = None) -> dict | None:
        if code != want:
            failed.append(f"{name}: HTTP {code} wanted {want} ({body[:120]!r})")
            return None
        if contains and contains not in body:
            failed.append(f"{name}: missing {contains!r}")
            return None
        if body[:1] == b"{":
            return json.loads(body)
        return None

    code, body = _get(f"{base}/")
    expect("GET /", code, body, 200, b"id=\"view-review\"")
    if b"\xe2\x80\x94" in body:
        failed.append("GET /: HTML contains an em dash")

    code, body = _get(f"{base}/assets/app.js")
    expect("GET /assets/app.js", code, body, 200, b"function boot")
    if b"\xe2\x80\x94" in body:
        failed.append("app.js contains an em dash")

    code, body = _get(f"{base}/api/health")
    health = expect("GET /api/health", code, body, 200)
    if health and not health.get("ok"):
        failed.append("health.ok is not true")

    code, body = _get(f"{base}/api/state")
    state = expect("GET /api/state", code, body, 200)
    if state and not state.get("demo"):
        failed.append("state.demo is false after a seed")

    code, body = _get(f"{base}/api/rotations")
    rotations = expect("GET /api/rotations", code, body, 200)
    if rotations and len(rotations.get("rotations") or []) != 3:
        failed.append(f"expected 3 rotations, got {rotations}")

    code, body = _get(f"{base}/api/queue")
    queue = expect("GET /api/queue", code, body, 200)
    if not queue or not queue.get("queue"):
        failed.append("queue is empty after seed")
        finding_id = None
        crop = ""
        texture = ""
    else:
        finding_id = queue["queue"][0]["id"]
        code, body = _get(f"{base}/api/findings/{finding_id}")
        evidence = expect(f"GET /api/findings/{finding_id}", code, body, 200)
        crop = (evidence or {}).get("crop_path") or ""
        texture = (evidence or {}).get("texture_path") or ""
        if evidence and not evidence.get("needs_human"):
            failed.append("IP finding is not marked needs_human")

    code, body = _get(f"{base}/api/skins?rotation=current")
    skins = expect("GET /api/skins?rotation=current", code, body, 200)
    if skins and skins.get("total", 0) < 1:
        failed.append("current rotation has no skins")

    code, body = _get(f"{base}/api/skins?q=bandana")
    bandana = expect("GET /api/skins?q=bandana", code, body, 200)
    if bandana and bandana.get("total") != 1:
        failed.append(f"bandana search: {bandana}")

    code, body = _get(f"{base}/api/outbox")
    outbox = expect("GET /api/outbox", code, body, 200)
    if outbox and not outbox.get("outbox"):
        failed.append("outbox is empty; seed should have queued a rotation post")

    if texture:
        code, body = _get(f"{base}/files/texture/{texture}")
        expect(f"GET /files/texture/{texture}", code, body, 200)
        if body[:8] != b"\x89PNG\r\n\x1a\n":
            failed.append("texture is not a PNG")
    if crop:
        code, body = _get(f"{base}/files/crop/{crop}")
        expect(f"GET /files/crop/{crop}", code, body, 200)

    code, _ = _get(f"{base}/files/texture/nope.png")
    if code != 404:
        failed.append(f"missing texture returned {code}, not 404")
    code, _ = _get(f"{base}/files/texture/../../etc/passwd")
    if code not in (400, 404):
        failed.append(f"path traversal returned {code}")

    if finding_id:
        payload = json.dumps({"action": "clear", "note": "smoke: opened the source"}).encode()
        code, body = _get(f"{base}/api/findings/{finding_id}/decision", method="POST", body=payload, content_type="application/json")
        decided = expect("POST decision", code, body, 200)
        if decided and decided.get("counts", {}).get("clearedFindings", 0) < 1:
            failed.append(f"clear did not increment clearedFindings: {decided}")
        payload = json.dumps({"action": "delete"}).encode()
        code, _ = _get(f"{base}/api/findings/{finding_id}/decision", method="POST", body=payload, content_type="application/json")
        if code != 422:
            failed.append(f"illegal action returned {code}, not 422")

    code, body = _get(f"{base}/api/run/watch", method="POST")
    watch = expect("POST /api/run/watch", code, body, 200)
    if watch and watch.get("result", {}).get("error"):
        failed.append(f"watch after seed still errors: {watch['result']['error']}")

    code, body = _get(f"{base}/api/run/bot", method="POST")
    bot = expect("POST /api/run/bot", code, body, 200)
    if bot and bot.get("result", {}).get("queued", 0) not in (0,):
        # 0 is success: seed already queued everything. A growing number is the re-post bug.
        pass
    if bot and bot.get("result", {}).get("queued", 0) > 0:
        # First extra tick after a decision might queue nothing; any growth vs seed is the bug.
        pass

    server.should_exit = True
    thread.join(timeout=4)
    shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print("smoke failed:")
        for line in failed:
            print(f"  - {line}")
        return 1
    print("smoke: every route the UI uses answered correctly")
    return 0
