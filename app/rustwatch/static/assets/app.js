/* rustwatch front end. Vanilla JS, no build step, no framework: three panels and a grid do not
   need a bundler, and the container can serve a static file that never changes at runtime.

   Every control here calls the API and reports what came back. There is no disabled-looking
   decoration, no countdown (rotation end dates are not published by anyone), and no price shown
   without a source. */

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, html) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html !== undefined) node.innerHTML = html;
  return node;
};
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  view: "review",
  rotation: "current",
  flag: "",
  query: "",
  queue: [],
  findingId: null,
  detail: null,
  skins: [],
  weeks: [],
  meta: null,
  gKey: false,
};

async function api(path, options) {
  const response = await fetch(path, options);
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(`${response.status} ${response.statusText}: ${text.slice(0, 120)}`);
  }
  if (!response.ok) {
    throw new Error((body && (body.detail || body.error)) || `${response.status}`);
  }
  return body;
}

function toast(message, kind) {
  const node = $("#toast");
  node.textContent = message;
  node.dataset.show = "1";
  node.dataset.kind = kind || "info";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    node.dataset.show = "0";
  }, 4200);
}

function errorBlock(error, lastGood) {
  return `<div class="err"><b>Request failed.</b> ${esc(error)}${
    lastGood ? `<time>last good read ${esc(lastGood)}</time>` : ""
  }</div>`;
}

function ago(iso) {
  if (!iso) return "never";
  const then = new Date(iso.replace(" ", "T")).getTime();
  if (Number.isNaN(then)) return esc(iso);
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

function syncUrl() {
  const params = new URLSearchParams();
  params.set("view", state.view);
  if (state.view === "browse") params.set("rotation", state.rotation);
  if (state.view === "review" && state.findingId) params.set("finding", String(state.findingId));
  history.replaceState(null, "", `?${params.toString()}`);
}

/* ---------------------------------------------------------------- views */

function setView(view) {
  state.view = view;
  ["review", "browse", "outbox"].forEach((name) => {
    const panel = $(`#view-${name}`);
    const tab = $(`#nav-${name}`);
    panel.hidden = name !== view;
    tab.classList.toggle("is-on", name === view);
    tab.setAttribute("aria-pressed", String(name === view));
  });
  syncUrl();
  if (view === "review") loadQueue();
  if (view === "browse") loadBrowse();
  if (view === "outbox") loadOutbox();
}

/* ---------------------------------------------------------------- review */

async function loadQueue() {
  const list = $("#queue");
  list.innerHTML = '<li class="skel" style="height:52px"></li><li class="skel" style="height:52px"></li><li class="skel" style="height:52px"></li>';
  try {
    const data = await api("/api/queue");
    state.queue = data.queue;
    renderQueue(data);
    if (!state.findingId && data.queue.length) selectFinding(data.queue[0].id, false);
    if (!data.queue.length) {
      $("#evidence").innerHTML = `<div class="empty"><span class="big">0</span>Nothing waiting. ${data.counts.screenedSkins} skins screened, ${data.counts.openFindings} open flags.</div>`;
      state.detail = null;
      setDecisionEnabled(false);
    }
  } catch (error) {
    list.innerHTML = "";
    $("#evidence").innerHTML = errorBlock(error, state.meta && state.meta.lastWatchAt);
  }
}

function renderQueue(data) {
  const list = $("#queue");
  list.innerHTML = "";
  $("#queue-count").textContent = String(data.waiting);
  $("#queue-count").dataset.zero = data.waiting ? "0" : "1";
  $("#queue-note").textContent = data.waiting
    ? `${data.counts.openFindings} open, oldest at the bottom. ${data.counts.clearedFindings} cleared.`
    : "Sorted by severity, then newest first.";
  data.queue.forEach((item, index) => {
    const li = el("li");
    li.dataset.id = String(item.id);
    li.setAttribute("role", "option");
    li.setAttribute("aria-selected", String(item.id === state.findingId));
    li.innerHTML = `
      <span class="q-name">${esc(item.name || item.skin_id)}</span>
      <span class="q-meta">
        <span class="sev sev-${esc(item.severity)}">${esc(item.code)}</span>
        <span>${esc(item.open_on_skin > 1 ? item.open_on_skin + " flags on this skin" : (item.item_shortname || "no item"))}</span>
        <span style="margin-left:auto">${esc(ago(item.created_at))}</span>
      </span>`;
    li.addEventListener("click", () => selectFinding(item.id, false));
    list.append(li);
    if (index === -1) void li;
  });
}

function setDecisionEnabled(on) {
  $("#decide-clear").disabled = !on;
  $("#decide-escalate").disabled = !on;
}

async function selectFinding(id, scroll = true) {
  state.findingId = Number(id);
  setDecisionEnabled(true);
  syncUrl();
  document.querySelectorAll("#queue li").forEach((li) => li.setAttribute("aria-selected", String(Number(li.dataset.id) === state.findingId)));
  if (scroll) {
    const active = document.querySelector(`#queue li[data-id="${id}"]`);
    if (active) active.scrollIntoView({ block: "nearest" });
  }
  const panel = $("#evidence");
  panel.innerHTML = '<div class="skel" style="height:120px"></div><div class="skel" style="height:220px"></div>';
  try {
    state.detail = await api(`/api/findings/${id}`);
    renderEvidence(state.detail);
  } catch (error) {
    panel.innerHTML = errorBlock(error, state.meta && state.meta.lastWatchAt);
  }
}

function textureUrl(rel) {
  return rel ? `/files/texture/${rel.split("/").map(encodeURIComponent).join("/")}` : "";
}
function cropUrl(rel) {
  return rel ? `/files/crop/${rel.split("/").map(encodeURIComponent).join("/")}` : "";
}

function renderEvidence(finding) {
  const index = state.queue.findIndex((row) => row.id === finding.id);
  const sources = finding.sources || [];
  const hasCrop = Boolean(finding.crop_path);

  const media = [
    finding.crop_path
      ? `<figure><img class="crop" alt="Cropped colour island from the skin texture" src="${cropUrl(finding.crop_path)}"><figcaption>crop, bbox noted below</figcaption></figure>`
      : "",
    finding.texture_path
      ? `<figure><img alt="Skin texture named by this finding" src="${textureUrl(finding.texture_path)}"><figcaption>${esc(finding.texture_path.split("/").pop())}</figcaption></figure>`
      : "",
  ].join("");

  const clause = finding.detail && finding.detail.includes("personal use") ? finding.detail : "";
  const sourceRows = sources.length
    ? sources
        .map(
          (src) => `<li>
            <span class="tag ${src.verified ? "tag-yes" : "tag-no"}">${src.verified ? "checked" : "unverified"}</span>
            ${src.url ? `<a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.label || src.url)}</a>` : `<span>no url recorded</span>`}
            ${src.license ? `<span class="detail">${esc(src.license)}</span>` : ""}
          </li>`
        )
        .join("")
    : '<li><span class="detail">No source linked. This finding came from a measurement on the file, with nothing external to compare it to yet.</span></li>';

  const textures = (finding.textures || [])
    .map(
      (t) => `<tr>
        <td class="name">${esc(t.slot)}</td>
        <td>${t.width}x${t.height}</td>
        <td class="${t.is_power_of_two ? "" : "flag-cell"}">${t.is_power_of_two ? "pot" : "not pot"}</td>
        <td>${Number(t.seam_ratio).toFixed(2)}</td>
        <td>${t.blank ? "blank" : t.unique_colors}</td>
      </tr>`
    )
    .join("");

  const siblings = (finding.skinFindings || [])
    .filter((row) => row.id !== finding.id)
    .map((row) => `<li><span class="sev sev-${esc(row.severity)}">${esc(row.code)}</span> ${esc(row.title)} <span class="card-id">(${esc(row.status)})</span></li>`)
    .join("");

  $("#evidence").innerHTML = `
    <div class="evi-head">
      <div>
        <div class="evi-title">${esc(finding.skin_name || finding.skin_id)}</div>
        <div class="evi-sub">${esc(finding.code)} &middot; <span class="sev sev-${esc(finding.severity)}">${esc(finding.severity)}</span> &middot; item <code>${esc(finding.item_shortname || "?")}</code> &middot; skin <code>${esc(finding.skin_id)}</code></div>
      </div>
      <div class="hero-num">${index >= 0 ? String(index + 1).padStart(2, "0") : "--"}<small>of ${state.queue.length} in queue</small></div>
    </div>

    ${media ? `<div class="media">${media}</div>` : ""}

    <div class="block">
      <h3>What was measured</h3>
      <p class="detail">${esc(finding.title)}</p>
      <p class="detail">${esc(finding.detail)}</p>
      ${hasCrop ? `<p class="note">The crop is the evidence. Keep the file until the decision is recorded.</p>` : ""}
      ${clause ? `<div class="quote" style="margin-top:10px">${esc(clause)}</div>` : ""}
    </div>

    <div class="block">
      <h3>Sources</h3>
      <ul class="src-list">${sourceRows}</ul>
    </div>

    ${
      textures
        ? `<div class="block"><h3>Textures on this skin</h3>
      <table class="tx-table"><thead><tr><th>slot</th><th>size</th><th>po2</th><th>seam</th><th>colours</th></tr></thead><tbody>${textures}</tbody></table></div>`
        : ""
    }

    ${siblings ? `<div class="block"><h3>Also open on this skin</h3><ul class="src-list">${siblings}</ul></div>` : ""}

    ${
      finding.status !== "open"
        ? `<div class="block"><h3>Recorded decision</h3><p class="detail">${esc(finding.status)} by <code>${esc(finding.decided_by || "?")}</code> at <code>${esc(finding.decided_at || "")}</code>${finding.decision_note ? `: ${esc(finding.decision_note)}` : ""}</p></div>`
        : ""
    }`;
}

async function decide(action) {
  if (!state.findingId) return;
  const note = $("#decision-note").value.trim();
  try {
    const result = await api(`/api/findings/${state.findingId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, note }),
    });
    toast(`${action === "clear" ? "Cleared" : "Escalated"} finding ${state.findingId}. It stays ${action === "clear" ? "closed on re-scan" : "with you"}; ${result.counts.openFindings} still open.`);
    $("#decision-note").value = "";
    await loadQueue();
    if (state.queue.length) selectFinding(state.queue[0].id, false);
  } catch (error) {
    toast(`Decision not recorded: ${error.message}`, "error");
  }
}

function move(delta) {
  if (!state.queue.length) return;
  const index = state.queue.findIndex((row) => row.id === state.findingId);
  const next = Math.min(state.queue.length - 1, Math.max(0, (index < 0 ? 0 : index) + delta));
  selectFinding(state.queue[next].id);
}

/* ---------------------------------------------------------------- browse */

async function loadBrowse() {
  try {
    const weeks = await api("/api/rotations");
    state.weeks = weeks.rotations;
    renderWeeks();
    const params = new URLSearchParams();
    if (state.rotation !== "current" && state.rotation !== "all") params.set("rotation", state.rotation);
    else params.set("rotation", String(state.weeks.length ? state.weeks[0].id : "all"));
    if (state.flag) params.set("flag", state.flag);
    if (state.query) params.set("q", state.query);
    const grid = $("#grid");
    grid.innerHTML = '<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
    const data = await api(`/api/skins?${params.toString()}`);
    state.skins = data.skins;
    $("#skin-count").textContent = `${data.total} skin${data.total === 1 ? "" : "s"}`;
    renderGrid(data.skins);
  } catch (error) {
    $("#grid").innerHTML = errorBlock(error, state.meta && state.meta.lastWatchAt);
  }
}

function renderWeeks() {
  const wrap = $("#weeks");
  wrap.innerHTML = "";
  if (!state.weeks.length) {
    wrap.innerHTML = '<span class="note">No rotation recorded yet. Run Watch now, or set STUB_CATALOG.</span>';
    return;
  }
  state.weeks.forEach((week, index) => {
    const button = el("button", "week");
    button.type = "button";
    button.setAttribute("role", "tab");
    const selected = String(week.id) === state.rotation || (index === 0 && state.rotation === "current");
    button.setAttribute("aria-selected", String(selected));
    button.innerHTML = `<b>Week of ${esc(String(week.first_seen).slice(0, 10))}</b><span>${week.new_skins} new &middot; ${week.open_findings} open${index === 0 ? " &middot; current" : ""}</span>`;
    button.addEventListener("click", () => {
      state.rotation = String(week.id);
      syncUrl();
      loadBrowse();
    });
    wrap.append(button);
  });

  const all = el("button", "week");
  all.type = "button";
  all.setAttribute("aria-selected", String(state.rotation === "all"));
  all.innerHTML = "<b>All weeks</b><span>every skin this watcher has seen</span>";
  all.addEventListener("click", () => {
    state.rotation = "all";
    syncUrl();
    loadBrowse();
  });
  wrap.append(all);
}

function renderGrid(skins) {
  const grid = $("#grid");
  grid.innerHTML = "";
  if (!skins.length) {
    grid.innerHTML = '<div class="empty" style="grid-column:1/-1"><span class="big">0</span>No skins match this filter.</div>';
    return;
  }
  skins.forEach((skin, index) => {
    const card = el("button", "card");
    card.type = "button";
    if (index === 0) card.classList.add("featured");
    else if (skin.open_findings > 0) card.classList.add("wide");
    card.dataset.open = skin.open_findings ? "1" : "0";
    const dotClass = skin.worst === "high" ? "dot-danger" : skin.open_findings ? "dot-amber" : skin.scan_status === "no-files" ? "" : "dot-patina";
    const price = skin.price_cents
      ? `<span class="num">$${(skin.price_cents / 100).toFixed(2)}</span>`
      : '<span class="note">no price source configured</span>';
    card.innerHTML = `
      <div class="card-top">
        <div>
          <div class="card-name">${esc(skin.name || skin.id)}</div>
          <div class="card-id">${esc(skin.id)} &middot; ${esc(skin.item_shortname || "no item")}</div>
        </div>
        ${skin.main_tex ? `<img class="swatch" alt="" src="${textureUrl(skin.main_tex)}">` : ""}
      </div>
      <div class="card-row">
        <span class="dot ${dotClass}"></span>
        <span>${esc(skin.scan_status)}</span>
        <span>${price}</span>
        ${skin.open_findings ? `<span class="badge">${skin.open_findings} open flag${skin.open_findings === 1 ? "" : "s"}</span>` : ""}
        ${skin.cleared_findings && !skin.open_findings ? `<span class="badge badge-clear">${skin.cleared_findings} cleared</span>` : ""}
      </div>
      ${index === 0 ? `<div class="hero-num">${skins.length}<small>skins in this view</small></div>
        <p class="note">First seen is what this watcher observed, not a release date. Nobody publishes those, so the app does not imply one.</p>` : ""}`;
    card.addEventListener("click", () => openSkin(skin));
    grid.append(card);
  });
}

async function openSkin(skin) {
  try {
    const detail = await api(`/api/skins/${encodeURIComponent(skin.id)}`);
    const open = (detail.findings || []).find((row) => row.status === "open");
    if (open) {
      setView("review");
      selectFinding(open.id, true);
      return;
    }
    toast(`${detail.name || detail.id}: ${detail.findings.length} finding(s), ${detail.textures.length} texture(s), nothing open.`);
  } catch (error) {
    toast(`Could not open that skin: ${error.message}`, "error");
  }
}

/* ---------------------------------------------------------------- outbox */

async function loadOutbox() {
  const wrap = $("#outbox-list");
  wrap.innerHTML = '<div class="skel" style="height:120px"></div>';
  try {
    const data = await api("/api/outbox");
    $("#discord-mode").textContent = data.discord.mode;
    if (!data.outbox.length) {
      wrap.innerHTML = '<div class="empty"><span class="big">0</span>No posts built yet. A new rotation or a new flag puts one here.</div>';
      return;
    }
    wrap.innerHTML = "";
    data.outbox.forEach((row) => {
      const card = el("div", "post");
      card.dataset.state = row.state;
      const embeds = (row.payload.embeds || [])
        .map(
          (embed) => `<div class="embed"><h3>${esc(embed.title || "")}</h3><p class="detail">${esc(embed.description || "")}</p>
            ${(embed.fields || []).map((f) => `<p class="f"><b>${esc(f.name)}</b>${esc(f.value)}</p>`).join("")}
            ${embed.footer ? `<p class="note">${esc(embed.footer.text)}</p>` : ""}</div>`
        )
        .join("");
      card.innerHTML = `
        <div class="post-head">
          <span class="tag ${row.state === "sent" ? "tag-yes" : "tag-no"}">${esc(row.state)}</span>
          <span>#${esc(row.channel)}</span>
          <span>${esc(row.kind)}</span>
          <span>${esc(ago(row.created_at))}</span>
          ${row.error ? `<span class="detail">${esc(row.error)}</span>` : ""}
        </div>${embeds}`;
      wrap.append(card);
    });
  } catch (error) {
    wrap.innerHTML = errorBlock(error);
  }
}

/* ---------------------------------------------------------------- runs */

async function run(kind, label) {
  const button = $(`#run-${kind}`);
  const original = button.textContent;
  button.disabled = true;
  button.textContent = `${label}...`;
  try {
    const result = await api(`/api/run/${kind}`, { method: "POST" });
    const payload = result.result || result;
    if (payload.error) toast(`${label} failed: ${payload.error}`, "error");
    else if (kind === "watch")
      toast(payload.changed ? `Rotation #${payload.rotationId} opened: ${payload.new.length} new skin(s) from ${payload.source}` : `No change: ${payload.items} store items, digest unchanged (${payload.source})`);
    else if (kind === "ingest") toast(payload.skipped ? payload.reason : `Screened ${payload.scanned} skin(s)`);
    else toast(payload.sent ? `Sent ${payload.sent} post(s) to Discord` : `No token configured: ${payload.queuedForReview} post(s) kept in the outbox`);
    await loadState();
    if (state.view === "review") await loadQueue();
    if (state.view === "browse") await loadBrowse();
    if (state.view === "outbox") await loadOutbox();
  } catch (error) {
    toast(`${label} failed: ${error.message}`, "error");
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

/* ---------------------------------------------------------------- boot */

async function loadState() {
  try {
    state.meta = await api("/api/state");
    $("#demo-banner").hidden = !state.meta.demo;
    $("#catalog-source").textContent = `catalog: ${state.meta.catalogSource || "none"}`;
    $("#reviewer").textContent = state.meta.reviewer;
    const status = $("#watch-status");
    const error = state.meta.lastWatchError;
    const minutesOld = state.meta.lastWatchAt ? (Date.now() - new Date(state.meta.lastWatchAt.replace(" ", "T")).getTime()) / 60000 : Infinity;
    const interval = (state.meta.config.watch && state.meta.config.watch.intervalMin) || 60;
    status.textContent = error ? "watch failed" : `watched ${ago(state.meta.lastWatchAt)}`;
    status.dataset.state = error ? "error" : minutesOld > interval * 2 ? "stale" : "ok";
    if (error) status.title = error;
  } catch (error) {
    $("#watch-status").textContent = "state unavailable";
    $("#watch-status").dataset.state = "error";
    $("#watch-status").title = String(error);
  }
}

function boot() {
  const params = new URLSearchParams(location.search);
  if (params.get("view")) state.view = params.get("view");
  if (params.get("rotation")) state.rotation = params.get("rotation");
  if (params.get("finding")) state.findingId = Number(params.get("finding"));

  ["review", "browse", "outbox"].forEach((name) => $(`#nav-${name}`).addEventListener("click", () => setView(name)));
  $("#run-watch").addEventListener("click", () => run("watch", "Watching"));
  $("#run-ingest").addEventListener("click", () => run("ingest", "Scanning"));
  $("#run-bot").addEventListener("click", () => run("bot", "Bot tick"));
  $("#decide-clear").addEventListener("click", () => decide("clear"));
  $("#decide-escalate").addEventListener("click", () => decide("escalate"));
  $("#help-close").addEventListener("click", () => {
    $("#help").hidden = true;
  });
  $("#weeks").addEventListener("click", (event) => event.stopPropagation());

  let searchTimer;
  $("#q").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = event.target.value.trim();
      loadBrowse();
    }, 220);
  });
  document.querySelectorAll(".seg-btn").forEach((button) =>
    button.addEventListener("click", () => {
      document.querySelectorAll(".seg-btn").forEach((other) => {
        other.classList.toggle("is-on", other === button);
        other.setAttribute("aria-pressed", String(other === button));
      });
      state.flag = button.dataset.flag;
      loadBrowse();
    })
  );

  document.addEventListener("keydown", (event) => {
    const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
    if (event.key === "Escape") {
      $("#help").hidden = true;
      return;
    }
    if (typing) return;
    if (state.gKey) {
      state.gKey = false;
      if (event.key === "r") return setView("review");
      if (event.key === "b") return setView("browse");
      if (event.key === "d") return setView("outbox");
    }
    switch (event.key) {
      case "j":
        event.preventDefault();
        return move(1);
      case "k":
        event.preventDefault();
        return move(-1);
      case "Enter": {
        const link = document.querySelector("#evidence .src-list a");
        if (link) {
          event.preventDefault();
          window.open(link.href, "_blank", "noopener");
        }
        return;
      }
      case "c":
        if (state.findingId) decide("clear");
        return;
      case "e":
        if (state.findingId) decide("escalate");
        return;
      case "?":
        $("#help").hidden = !$("#help").hidden;
        return;
      case "g":
        state.gKey = true;
        setTimeout(() => {
          state.gKey = false;
        }, 900);
    }
  });

  loadState();
  setView(state.view);
  if (state.findingId) selectFinding(state.findingId, true);
  setInterval(loadState, 45000);
}

boot();
