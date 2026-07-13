/* RC Engine GUI — vanilla JS, no build step. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const usd = (v) => v == null ? "—" : "$" + Number(v).toFixed(4);
const num = (v, d = 2) => v == null ? "—" : Number(v).toFixed(d);
const when = (iso) => iso ? String(iso).replace("T", " ").slice(0, 16) : "—";

async function jsonFetch(url, opts = {}) {
  const res = await fetch(url, opts);
  let body = null;
  try { body = await res.json(); } catch (_) { /* non-JSON */ }
  if (!res.ok) {
    const msg = body && body.detail ? body.detail : `${res.status} ${res.statusText}`;
    throw new Error(msg);
  }
  return body;
}

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

/* ============================= router ============================= */

const loaders = {
  dashboard: loadDashboard, generate: loadGeneratePage, resume: loadResume,
  library: loadLibrary, vet: loadVetPage, health: loadHealth,
  seeds: loadSeeds, tracker: loadTracker, settings: loadSettings,
};

function route() {
  const page = (location.hash || "#dashboard").slice(1).split("?")[0];
  const target = loaders[page] ? page : "dashboard";
  document.querySelectorAll("section[data-page]").forEach(
    (s) => s.hidden = s.dataset.page !== target);
  document.querySelectorAll("nav a").forEach(
    (a) => a.classList.toggle("active", a.dataset.nav === target));
  loaders[target]().catch((e) => toast(e.message, "bad"));
}
window.addEventListener("hashchange", route);

/* ======================= job console drawer ======================= */

let currentJobId = null;
let eventSrc = null;

function toggleDrawer(force) {
  const d = $("#drawer");
  const collapse = force !== undefined ? !force : !d.classList.contains("collapsed");
  d.classList.toggle("collapsed", collapse);
  $("#drawer-caret").textContent = collapse ? "▲" : "▼";
}

function setJobUI(running, meta) {
  const pill = $("#job-pill");
  pill.className = "job-pill " + (running ? "running" : "idle");
  pill.textContent = running ? `running: ${meta.kind}` : "idle";
  $("#drawer-kill").hidden = !running;
  document.querySelectorAll("#gen-run, #retry-all-btn, #tracker-btn")
    .forEach((b) => b.disabled = running);
  document.querySelectorAll("#resume-table .btn").forEach((b) => b.disabled = running);
}

function attachJob(jobId, kind) {
  currentJobId = jobId;
  if (eventSrc) eventSrc.close();
  const log = $("#drawer-log");
  log.textContent = "";
  $("#drawer-title").textContent = `Run console — ${kind}`;
  $("#drawer-status").className = "pill running";
  $("#drawer-status").textContent = "running";
  setJobUI(true, { kind });
  toggleDrawer(true);

  eventSrc = new EventSource(`/api/jobs/${jobId}/stream`);
  eventSrc.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "line") {
      const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
      log.textContent += msg.text + "\n";
      if (stick) log.scrollTop = log.scrollHeight;
    } else if (msg.type === "status") {
      $("#drawer-status").className = "pill " + msg.status;
      $("#drawer-status").textContent = msg.status;
      setJobUI(false, {});
      eventSrc.close(); eventSrc = null;
      if (msg.status === "done") toast(`${kind} finished`, "ok");
      else if (msg.status === "killed")
        toast("Run stopped — any paid passages whose questions hadn't completed " +
              "appear in the Resume queue.", "warn");
      else toast(`${kind} failed (exit ${msg.returncode})`, "bad");
      refreshBadges();
      const page = (location.hash || "#dashboard").slice(1);
      if (loaders[page]) loaders[page]().catch(() => {});
    } else if (msg.type === "error") {
      toast(msg.message, "bad");
      eventSrc.close(); eventSrc = null;
    }
  };
}

async function startJob(kind, url, body) {
  try {
    const res = await jsonFetch(url, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    attachJob(res.job_id, kind);
  } catch (e) { toast(e.message, "bad"); }
}

async function killJob(ev) {
  ev.stopPropagation();
  if (!currentJobId) return;
  try { await jsonFetch(`/api/jobs/${currentJobId}/kill`, { method: "POST" }); }
  catch (e) { toast(e.message, "bad"); }
}

async function syncJobState() {
  try {
    const j = await jsonFetch("/api/jobs");
    if (j.running) attachJob(j.running.id, j.running.kind);
    else setJobUI(false, {});
  } catch (_) { /* server starting */ }
}

/* ============================ dashboard ============================ */

const STATUS_ORDER = ["approved", "needs_review", "solver_dispute",
                      "rejected_novelty", "budget_abort"];

async function loadDashboard() {
  const d = await jsonFetch("/api/dashboard");
  const un = $("#dash-unavailable");
  if (!d.available) {
    un.hidden = false;
    un.textContent = `Database not found at ${d.db_path} — run a generation first.`;
    $("#dash-stats").innerHTML = ""; return;
  }
  un.hidden = true;

  const s = d.by_status || {};
  const tiles = [
    { v: d.total, l: "total RCs", cls: "accent" },
    { v: s.approved || 0, l: "approved", cls: "ok" },
    { v: s.needs_review || 0, l: "needs review", cls: (s.needs_review ? "warn" : "") },
    { v: s.solver_dispute || 0, l: "solver disputes", cls: (s.solver_dispute ? "warn" : "") },
    { v: d.resumable, l: "resumable passages", cls: (d.resumable ? "warn" : "") },
    { v: "$" + Number(d.total_spend || 0).toFixed(2), l: "total spend", cls: "" },
  ];
  $("#dash-stats").innerHTML = tiles.map((t) =>
    `<div class="stat ${t.cls}"><div class="v">${esc(t.v)}</div><div class="l">${esc(t.l)}</div></div>`).join("");

  $("#dash-recent").innerHTML =
    `<thead><tr><th>RC</th><th>Tier</th><th>Status</th><th class="num">Score</th>
      <th class="num">Cost</th><th>Provider</th><th>Created</th></tr></thead><tbody>` +
    (d.recent || []).map((r) => `
      <tr class="click" onclick="openRC('${esc(r.rc_id)}')">
        <td>${esc(r.rc_id)}</td><td><span class="pill tier">${esc(r.tier)}</span></td>
        <td><span class="pill ${esc(r.status)}">${esc(r.status)}</span></td>
        <td class="num">${num(r.average_score, 1)}</td>
        <td class="num">${usd(r.total_cost_usd)}</td>
        <td>${esc(r.provider || "—")}</td><td class="muted">${when(r.created_at)}</td>
      </tr>`).join("") + "</tbody>";

  const h = d.health;
  $("#dash-health").innerHTML = h ? `
    <div><span class="muted">family KL</span><b class="${h.family_kl > 0.15 ? "ln-warn" : ""}">${num(h.family_kl, 3)}</b></div>
    <div><span class="muted">topology KL</span><b>${num(h.topology_kl, 3)}</b></div>
    <div><span class="muted">letter runs p</span><b>${num(h.letter_runs_p, 3)}</b></div>
    <div><span class="muted">snapshot</span><b>${when(h.created_at)}</b></div>`
    : `<div class="muted">no snapshots yet — run a health check</div>`;

  const lj = d.running_job || d.last_job;
  $("#dash-lastjob").innerHTML = lj
    ? `<div><b>${esc(lj.kind)}</b> <span class="pill ${esc(lj.status)}">${esc(lj.status)}</span></div>
       <div class="muted small">${new Date(lj.started_at * 1000).toLocaleString()}</div>`
    : "no runs yet";
  refreshBadges(d.resumable);
}

async function refreshBadges(count) {
  try {
    if (count === undefined) {
      const rows = await jsonFetch("/api/resumable");
      count = rows.length;
    }
    const b = $("#nav-resume-badge");
    b.hidden = !count;
    b.textContent = count;
  } catch (_) {}
}

/* ============================ generate ============================ */

const tierCounts = { medium: 0, hard: 0, elite: 0 };
let settingsCache = null;

function step(tier, delta) {
  tierCounts[tier] = Math.max(0, Math.min(20, tierCounts[tier] + delta));
  $(`#n-${tier}`).textContent = tierCounts[tier];
}

async function getSettings() {
  if (!settingsCache) settingsCache = await jsonFetch("/api/settings");
  return settingsCache;
}

function fillProviderSelect(sel, settings, allowAll) {
  const cur = sel.value;
  sel.innerHTML = settings.providers.map((p) => {
    const dis = !allowAll && !p.key_present;
    return `<option value="${p.name}" ${dis ? "disabled" : ""}>
      ${p.name}${p.key_present ? "" : " (no API key)"}</option>`;
  }).join("");
  if (cur) sel.value = cur;
  if (sel.selectedIndex === -1 || sel.options[sel.selectedIndex].disabled) {
    const first = [...sel.options].find((o) => !o.disabled);
    if (first) sel.value = first.value;
  }
}

async function loadGeneratePage() {
  const st = await getSettings();
  fillProviderSelect($("#gen-provider"), st, $("#gen-dryrun").checked);
}

$("#gen-dryrun") && document.addEventListener("change", (ev) => {
  if (ev.target.id === "gen-dryrun" && settingsCache)
    fillProviderSelect($("#gen-provider"), settingsCache, ev.target.checked);
});

function runGenerate() {
  const total = tierCounts.medium + tierCounts.hard + tierCounts.elite;
  if (!total) { toast("Set at least one tier count above 0.", "warn"); return; }
  const body = {
    ...tierCounts,
    provider: $("#gen-provider").value,
    dry_run: $("#gen-dryrun").checked,
    no_seed: $("#gen-noseed").checked,
    no_embed: $("#gen-noembed").checked,
  };
  const maxUsd = parseFloat($("#gen-maxusd").value);
  if (!isNaN(maxUsd) && maxUsd > 0) body.max_usd = maxUsd;
  startJob("generate", "/api/jobs/generate", body);
}

async function loadEstimate() {
  $("#estimate-out").textContent = "…";
  try {
    const res = await jsonFetch(`/api/estimate?provider=${$("#gen-provider").value}`);
    $("#estimate-out").textContent = res.output;
  } catch (e) { $("#estimate-out").textContent = e.message; }
}

/* ============================= resume ============================= */

async function loadResume() {
  const st = await getSettings();
  fillProviderSelect($("#retry-provider"), st, $("#retry-dryrun").checked);
  const rows = await jsonFetch("/api/resumable");
  refreshBadges(rows.length);
  const t = $("#resume-table");
  if (!rows.length) {
    t.innerHTML = `<tbody><tr><td class="muted">No resumable passages — nothing was stranded. 🎉</td></tr></tbody>`;
    return;
  }
  t.innerHTML =
    `<thead><tr><th>Blueprint</th><th>Tier</th><th class="num">Spent</th>
      <th>Topic</th><th>Failure</th><th>When</th><th></th></tr></thead><tbody>` +
    rows.map((r) => `
      <tr><td class="mono">${esc(r.blueprint_id)}</td>
        <td><span class="pill tier">${esc(r.tier)}</span></td>
        <td class="num">${usd(r.spent_usd)}</td>
        <td>${esc(r.topic || r.seed_title || "")}</td>
        <td class="muted">${esc((r.fail_notes || "").slice(0, 80))}</td>
        <td class="muted">${when(r.created_at)}</td>
        <td><button class="btn small" onclick="runRetry('${esc(r.blueprint_id)}')">↻ Retry</button></td>
      </tr>`).join("") + "</tbody>";
}

function runRetry(blueprintId) {
  const body = {
    provider: $("#retry-provider").value,
    dry_run: $("#retry-dryrun").checked,
    note: $("#retry-note").value || null,
  };
  if (blueprintId) body.blueprint = blueprintId; else body.all = true;
  startJob("retry", "/api/jobs/retry", body);
}

/* ============================= library ============================ */

const lib = { status: "", tier: "", offset: 0, limit: 25, total: 0 };

document.addEventListener("click", (ev) => {
  const chip = ev.target.closest(".chip");
  if (!chip) return;
  const group = chip.parentElement;
  group.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
  chip.classList.add("active");
  lib[group.dataset.filter] = chip.dataset.val;
  lib.offset = 0;
  loadLibrary().catch((e) => toast(e.message, "bad"));
});

function libPage(dir) {
  const next = lib.offset + dir * lib.limit;
  if (next < 0 || next >= lib.total) return;
  lib.offset = next;
  loadLibrary().catch((e) => toast(e.message, "bad"));
}

async function loadLibrary() {
  const q = new URLSearchParams({ limit: lib.limit, offset: lib.offset });
  if (lib.status) q.set("status", lib.status);
  if (lib.tier) q.set("tier", lib.tier);
  const d = await jsonFetch("/api/rcs?" + q);
  lib.total = d.total;
  $("#lib-table").innerHTML =
    `<thead><tr><th>RC</th><th>Tier</th><th>Status</th><th class="num">Score</th>
      <th class="num">F1</th><th class="num">Novelty</th><th class="num">Cost</th>
      <th>Provider</th><th>Created</th></tr></thead><tbody>` +
    d.rows.map((r) => `
      <tr class="click" onclick="openRC('${esc(r.rc_id)}')">
        <td>${esc(r.rc_id)}</td><td><span class="pill tier">${esc(r.tier)}</span></td>
        <td><span class="pill ${esc(r.status)}">${esc(r.status)}</span></td>
        <td class="num">${num(r.average_score, 1)}</td>
        <td class="num">${num(r.compliance_f1, 2)}</td>
        <td class="num">${num(r.novelty_composite, 2)}</td>
        <td class="num">${usd(r.total_cost_usd)}</td>
        <td>${esc(r.provider || "—")}</td>
        <td class="muted">${when(r.created_at)}</td>
      </tr>`).join("") + "</tbody>";
  const page = Math.floor(lib.offset / lib.limit) + 1;
  const pages = Math.max(1, Math.ceil(lib.total / lib.limit));
  $("#lib-pageinfo").textContent = `page ${page} / ${pages} — ${lib.total} RCs`;
  $("#lib-prev").disabled = lib.offset === 0;
  $("#lib-next").disabled = lib.offset + lib.limit >= lib.total;
}

async function openRC(rcId) {
  try {
    const r = await jsonFetch(`/api/rcs/${encodeURIComponent(rcId)}`);
    $("#modal-title").textContent = r.rc_id;
    $("#modal-meta").innerHTML =
      `<span class="pill tier">${esc(r.tier)}</span>
       <span class="pill ${esc(r.status)}">${esc(r.status)}</span>
       score ${num(r.average_score, 1)} · f1 ${num(r.compliance_f1, 2)} ·
       novelty ${num(r.novelty_composite, 2)} · ${usd(r.total_cost_usd)} ·
       ${esc(r.provider || "?")}`;
    $("#modal-body").textContent = r.rc_text || "(no text)";
    $("#modal").hidden = false;
  } catch (e) { toast(e.message, "bad"); }
}
function closeModal() { $("#modal").hidden = true; }
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

async function runExport() {
  try {
    const res = await jsonFetch("/api/export", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: lib.status || null }),
    });
    toast(res.output.trim().split("\n").pop() || "export finished",
          res.returncode === 0 ? "ok" : "bad");
  } catch (e) { toast(e.message, "bad"); }
}

/* =============================== vet ============================== */

async function loadVetPage() { await loadAvoid().catch(() => {}); }

async function runVet() {
  const btn = $("#vet-run");
  btn.disabled = true; btn.textContent = "Running gates…";
  try {
    const fd = new FormData();
    const file = $("#vet-file").files[0];
    if (file) fd.append("file", file);
    else fd.append("text", $("#vet-text").value);
    if ($("#vet-tier").value) fd.append("tier", $("#vet-tier").value);
    fd.append("ingest", $("#vet-ingest").checked);
    fd.append("force", $("#vet-force").checked);
    fd.append("no_embed", !$("#vet-embed").checked);
    const res = await fetch("/api/vet", { method: "POST", body: fd });
    const body = await res.json().catch(() => null);
    if (!res.ok) throw new Error(body && body.detail || res.statusText);
    renderVetReport(body.output, body.returncode);
  } catch (e) { toast(e.message, "bad"); }
  finally { btn.disabled = false; btn.textContent = "✓ Run gates ($0)"; }
}

function renderVetReport(text, rc) {
  const html = text.split("\n").map((line) => {
    let cls = "";
    if (/BREACH|FAIL|✗|reject/i.test(line)) cls = "ln-bad";
    else if (/WARN/i.test(line)) cls = "ln-warn";
    else if (/PASS|OK|✓|ingested|clean/i.test(line)) cls = "ln-pass";
    return `<span class="${cls}">${esc(line)}</span>`;
  }).join("\n");
  $("#vet-out").innerHTML = html;
  toast(rc === 0 ? "Gates passed" : "Gates reported breaches — see report",
        rc === 0 ? "ok" : "warn");
}

async function loadAvoid() {
  const n = parseInt($("#avoid-n").value, 10) || 4;
  const res = await jsonFetch(`/api/avoid?n=${n}`);
  $("#avoid-out").textContent = res.output.trim();
  $("#manual-note").textContent = "AVOID line only — click “Full prompt” for the complete generator prompt.";
}
async function loadManualPrompt() {
  const n = parseInt($("#avoid-n").value, 10) || 4;
  const tier = $("#manual-tier").value;
  $("#avoid-out").textContent = "building full prompt…";
  try {
    const res = await jsonFetch(`/api/manual-prompt?n=${n}&tier=${tier}`);
    $("#avoid-out").textContent = res.full;
    $("#manual-note").textContent = res.avoid_line
      ? `Full ${tier} prompt ready — paste it into claude.ai, then send the first-set message at the bottom.`
      : `Full ${tier} prompt ready (no engine sets yet, so no AVOID line — add recent manual sets from RC_Tracker.xlsx).`;
  } catch (e) { $("#avoid-out").textContent = e.message; toast(e.message, "bad"); }
}
function copyManual() {
  const text = $("#avoid-out").textContent;
  if (!text || text === "—") { toast("Nothing to copy yet", "warn"); return; }
  navigator.clipboard.writeText(text)
    .then(() => toast("Copied to clipboard", "ok"));
}

/* ============================= health ============================= */

async function loadHealth() {
  const d = await jsonFetch("/api/health");
  const hist = d.history || [];
  const latest = hist[hist.length - 1];
  const tiles = latest ? [
    { v: num(latest.family_kl, 3), l: "family KL (alarm > 0.15)",
      cls: latest.family_kl > 0.15 ? "warn" : "ok" },
    { v: num(latest.topology_kl, 3), l: "topology KL (alarm > 0.15)",
      cls: latest.topology_kl > 0.15 ? "warn" : "ok" },
    { v: num(latest.letter_runs_p, 3), l: "answer-letter runs p",
      cls: latest.letter_runs_p != null && latest.letter_runs_p < 0.05 ? "warn" : "ok" },
    { v: (JSON.parse(latest.slot_chi2_flags || "[]") || []).length,
      l: "slot χ² flags", cls: "" },
    { v: latest.window_size, l: "window size", cls: "" },
    { v: when(latest.created_at), l: "last snapshot", cls: "" },
  ] : [];
  $("#health-stats").innerHTML = latest
    ? tiles.map((t) => `<div class="stat ${t.cls}"><div class="v">${esc(t.v)}</div><div class="l">${esc(t.l)}</div></div>`).join("")
    : `<div class="card muted">No health snapshots yet — click “Run full health check”.</div>`;
  drawSpark($("#spark-family"), hist.map((r) => r.family_kl), 0.15);
  drawSpark($("#spark-topology"), hist.map((r) => r.topology_kl), 0.15);
}

function drawSpark(box, values, alarm) {
  values = values.filter((v) => v != null);
  if (values.length < 2) { box.innerHTML = `<div class="muted small">not enough history</div>`; return; }
  const W = 320, H = 90, P = 8;
  const max = Math.max(...values, alarm) * 1.15 || 1;
  const x = (i) => P + (i / (values.length - 1)) * (W - 2 * P);
  const y = (v) => H - P - (v / max) * (H - 2 * P);
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = values[values.length - 1];
  box.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <line class="spark-alarm" x1="${P}" x2="${W - P}" y1="${y(alarm)}" y2="${y(alarm)}"/>
      <polyline class="spark-line" points="${pts}"/>
      <circle class="spark-dot" cx="${x(values.length - 1)}" cy="${y(last)}" r="3"/>
      <text class="spark-label" x="${W - P}" y="${Math.max(10, y(last) - 6)}" text-anchor="end">${last.toFixed(3)}</text>
    </svg>`;
}

function runHealthSnapshot() { startJob("health", "/api/jobs/health-snapshot"); }

/* ============================== seeds ============================= */

async function loadSeeds() {
  $("#seeds-stats").innerHTML = `<div class="card muted">Probing seed store…</div>`;
  const d = await jsonFetch("/api/seeds");
  const un = $("#seeds-unavailable");
  if (!d.available) {
    un.hidden = false;
    un.textContent = "Seed store unavailable: " + d.reason;
    $("#seeds-stats").innerHTML = "";
    $("#seeds-genre").innerHTML = ""; $("#seeds-source").innerHTML = "";
    return;
  }
  un.hidden = true;
  $("#seeds-stats").innerHTML = `
    <div class="stat accent"><div class="v">${d.total}</div><div class="l">essays stored</div></div>
    <div class="stat ${d.unused < 10 ? "warn" : "ok"}"><div class="v">${d.unused}</div><div class="l">unused (available)</div></div>
    <div class="stat"><div class="v">${d.total - d.unused}</div><div class="l">already used</div></div>`;
  const rows = (obj) => Object.entries(obj)
    .sort((a, b) => b[1].unused - a[1].unused)
    .map(([k, v]) => {
      const pct = v.total ? Math.round((v.unused / v.total) * 100) : 0;
      return `<tr><td>${esc(k)}</td>
        <td class="num">${v.unused} / ${v.total}</td>
        <td><span class="bar-bg"><span class="bar-fg" style="width:${pct}%"></span></span></td>
      </tr>`;
    }).join("");
  const head = `<thead><tr><th>Name</th><th class="num">Unused / total</th><th>Availability</th></tr></thead>`;
  $("#seeds-genre").innerHTML = head + `<tbody>${rows(d.by_genre)}</tbody>`;
  $("#seeds-source").innerHTML = head + `<tbody>${rows(d.by_source)}</tbody>`;
}

function runRagSync() { startJob("rag-sync", "/api/jobs/rag-sync"); }

/* ============================= tracker ============================ */

async function loadTracker() {
  const d = await jsonFetch("/api/tracker");
  $("#tracker-info").innerHTML = d.exists
    ? `Last built: <b>${new Date(d.mtime * 1000).toLocaleString()}</b><br>
       <span class="small mono">${esc(d.path)}</span>`
    : "RC_Tracker.xlsx does not exist yet — rebuild to create it.";
}

async function runTracker() {
  const btn = $("#tracker-btn");
  btn.disabled = true; btn.textContent = "Rebuilding…";
  try {
    const res = await jsonFetch("/api/tracker/rebuild", { method: "POST" });
    const out = $("#tracker-out");
    out.hidden = false; out.textContent = res.output.trim();
    toast(res.returncode === 0 ? "Tracker rebuilt" : "Tracker rebuild failed",
          res.returncode === 0 ? "ok" : "bad");
    loadTracker();
  } catch (e) { toast(e.message, "bad"); }
  finally { btn.disabled = false; btn.textContent = "▦ Rebuild tracker"; }
}

/* ============================ settings ============================ */

async function loadSettings() {
  settingsCache = null;
  const st = await getSettings();
  $("#set-providers").innerHTML =
    `<thead><tr><th>Provider</th><th>Big</th><th>Mid</th><th>Small</th>
      <th>Env key(s)</th><th>Key</th></tr></thead><tbody>` +
    st.providers.map((p) => `
      <tr><td><b>${esc(p.name)}</b></td>
        <td class="mono">${esc(p.models.big)}</td>
        <td class="mono">${esc(p.models.mid)}</td>
        <td class="mono">${esc(p.models.small)}</td>
        <td class="mono muted">${esc(p.env_keys.join(" or "))}</td>
        <td>${p.key_present
            ? `<span class="pill done">present</span>`
            : `<span class="pill failed">missing</span>`}</td>
      </tr>`).join("") + "</tbody>";
  $("#set-rates").innerHTML =
    `<thead><tr><th>Model</th><th class="num">Input</th><th class="num">Output</th></tr></thead><tbody>` +
    Object.entries(st.model_rates).map(([m, r]) => `
      <tr><td class="mono">${esc(m)}</td>
        <td class="num">$${r.input.toFixed(2)}</td>
        <td class="num">$${r.output.toFixed(2)}</td></tr>`).join("") + "</tbody>";
  $("#set-budgets").innerHTML =
    `<thead><tr><th>Tier</th><th class="num">Cap / RC</th></tr></thead><tbody>` +
    Object.entries(st.tier_budgets).map(([t, b]) => `
      <tr><td>${esc(t)}</td><td class="num">$${b.toFixed(2)}</td></tr>`).join("") + "</tbody>";
  $("#set-paths").innerHTML = `
    <div><b>Database</b><span>${esc(st.db_path)}</span></div>
    <div><b>Backups</b><span>${esc(st.backup_dir)}</span></div>
    <div><b>Engine</b><span>${esc(st.engine_version)}</span></div>`;
}

function runBackfill() { startJob("backfill", "/api/jobs/backfill"); }

/* ============================== boot ============================== */

$("#job-pill").addEventListener("click", () => toggleDrawer());
syncJobState().then(route);
