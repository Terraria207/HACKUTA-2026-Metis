"use strict";
/* Metis interface (UI spec): title screen -> New Journey / Load Journey -> scroll transition ->
   sea map, with the paper input, Odyssey discussion, route finder, report, history, trace,
   details, costs and settings around the map. */
const $ = (id) => document.getElementById(id),
  esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const state = {
  status: null, settings: null, catalog: null, journeys: [], journeyId: null, journey: null, data: null,
  runs: [], papers: [], run: null, mapSig: "", view: "sea", match: null, selection: null, pick: null,
  route: { start: null, end: null, result: null }, before: null, stream: null, poll: null,
  token: sessionStorage.getItem("metisToken") || "",
  disc: { runId: null, queue: [], log: [], seen: new Set(), cursor: 0, muted: false, timer: null, current: null },
};
const DEFAULTS = { tree_weight: 0.5, d_max: 8, group_ratio: 0.5, k: 50, p: 5, integration_depth: 2, new_node_threshold: 3, blind_support: 2, proof_attempts: 3, formalize_definitions: false, narration: true, budget_usd: 0 };
const SETTING_FIELDS = [
  ["tree_weight", "Bridge-score weight w_t (w_g = 1 − w_t)", { min: 0, max: 1, step: 0.05 }],
  ["d_max", "D_max, graph-distance cap (not set in the design doc; this build starts at 8)", { min: 1, max: 50, step: 1 }],
  ["group_ratio", "Group-or-paper target ratio (share of groups)", { min: 0, max: 1, step: 0.05 }],
  ["k", "K, concepts per target", { min: 1, max: 200, step: 1 }],
  ["p", "P, proposals per comparison", { min: 1, max: 10, step: 1 }],
  ["integration_depth", "Integration depth (levels)", { min: 0, max: 4, step: 1 }],
  ["new_node_threshold", "New-node trigger (intuitive edges from different papers or runs)", { min: 3, max: 20, step: 1 }],
  ["blind_support", "Blind-test bar for new nodes (different crew mates)", { min: 2, max: 4, step: 1 }],
  ["proof_attempts", "Hephaestus's budget per run, in proof attempts (not set in the design doc; starts at 3)", { min: 0, max: 20, step: 1 }],
  ["budget_usd", "Budget cap in USD (pauses a run before it is exceeded)", { min: 0, step: 0.01 }],
];
let cy = null, seaMap = null;

async function api(path, options = {}) {
  const headers = {
    ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    ...(state.token ? { Authorization: "Bearer " + state.token } : {}),
    ...options.headers,
  };
  const res = await fetch("/api" + path, { ...options, headers });
  if (!res.ok) {
    const body = await res.text();
    let msg = body;
    try { msg = JSON.parse(body).detail || body; } catch { /* plain HTTP error */ }
    throw Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.status === 204 ? null : res.json();
}
function error(e) {
  $("error").textContent = e.message || String(e);
  $("error").hidden = false;
  clearTimeout(error.timer);
  error.timer = setTimeout(() => ($("error").hidden = true), 12000);
}
function on(id, event, fn) {
  $(id).addEventListener(event, (e) => Promise.resolve(fn(e)).catch(error));
}
const date = (t) => new Date(t * 1000).toLocaleString(); // the user's own time zone
const pill = (s, cls = "") => `<span class="pill ${cls}">${esc(s)}</span>`;
const journeyName = (j) => j.name || "Journey of " + date(j.created);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const typing = (e) => /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
function paint(canvas, sprite) {
  const ctx = canvas.getContext("2d");
  canvas.width = sprite.width; canvas.height = sprite.height;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(sprite, 0, 0);
}

/* =========================== Title screen and menu scrolls =========================== */
async function showTitle() {
  leaveJourney();
  $("mapScreen").hidden = true;
  $("titleScreen").hidden = false;
  TitleScene.run(true);
  if (location.hash !== "#home") history.replaceState(null, "", "#home");
  await Promise.all([loadJourneys(), loadDiscoveries(), loadHarbour()]);
}
async function loadJourneys() {
  state.journeys = await api("/journeys");
  $("journeyList").innerHTML = state.journeys.length
    ? '<p class="scrollTitle">Past journeys</p>' + state.journeys.map((j) =>
        `<button class="journeyRow" data-row="${esc(j.id)}"><strong>${esc(journeyName(j))}</strong>` +
        `<span class="meta">${esc(j.islands.join(" · "))}</span>` +
        `<span class="meta">${j.papers_run} paper(s) run · ${j.new_connections} new connection(s) · last activity ${esc(date(j.last_activity))}</span>` +
        `${pill(j.status, j.status === "running" ? "gold" : "")}${j.active_run && j.active_run.status !== "running" && j.active_run.status !== "queued" ? " " + pill("run " + j.active_run.status + " — resume available", "bad") : ""}</button>` +
        `<div class="rowChoices" id="choices-${esc(j.id)}" hidden><button class="pixelButton small primary" data-open-journey="${esc(j.id)}">Open journey</button>` +
        `<button class="pixelButton small" data-open-review="${esc(j.id)}">Open review document${j.review_documents ? " (" + j.review_documents + ")" : ""}</button></div>`).join("")
    : '<p class="scrollTitle">No journeys yet</p><p>There is nothing to load. Your first voyage starts with <button class="pixelButton small" data-open-setup="1">New Journey</button>.</p>';
}
async function loadDiscoveries() {
  const found = await api("/discoveries");
  $("discoveries").innerHTML = '<p class="scrollTitle">Across all journeys</p>' + (found.length
    ? found.map((d) => `<div class="finding"><div>${pill(d.kind, "gold")} ${d.fixture ? pill("fixture") : ""}</div><p>${esc(d.edge ? d.edge.argument : d.concept.name + ": " + d.concept.statement)}</p>` +
        `<button class="pixelButton small" data-open-journey="${esc(d.journey_id)}" data-focus-kind="${d.edge ? "edge" : "concept"}" data-focus-id="${esc(d.edge ? d.edge.id : d.concept.id)}">${esc(d.journey_name || "Unnamed journey")} — where it was found ↗</button></div>`).join("")
    : '<p>Nothing yet. Machine-verified and potentially new connections, Proven concepts and accepted conjectures appear here, each linking to where it was found.</p><p class="hint">Fixture mode never presents scripted associations as discoveries.</p>');
}
const scrolls = () => [...document.querySelectorAll(".scroll")];
function openScroll(el, sticky) {
  scrolls().forEach((s) => { if (s !== el && !s.classList.contains("busy")) closeScroll(s); });
  el.classList.add("open");
  el.setAttribute("aria-expanded", "true");
  if (sticky) el.dataset.sticky = "1";
}
function closeScroll(el) {
  el.classList.remove("open", "busy");
  el.setAttribute("aria-expanded", "false");
  delete el.dataset.sticky;
  el.querySelectorAll(".rowChoices").forEach((c) => (c.hidden = true));
  el.querySelectorAll(".journeyRow.chosen").forEach((c) => c.classList.remove("chosen"));
}
function wireScrolls() {
  scrolls().forEach((el) => {
    el.addEventListener("mouseenter", () => openScroll(el));
    // Mouse leaves: the scroll rolls back up, unless a choice is in progress.
    el.addEventListener("mouseleave", () => { if (!el.classList.contains("busy") && !el.dataset.sticky) closeScroll(el); });
    el.addEventListener("pointerdown", (e) => {
      // Touch has no hover: the first tap unrolls the scroll.
      if (e.pointerType !== "mouse" && !el.classList.contains("open")) { openScroll(el, true); el.dataset.justOpened = "1"; }
    });
    el.addEventListener("click", (e) => {
      if (el.dataset.justOpened) { delete el.dataset.justOpened; return; }
      if (el.dataset.scroll === "new" && !e.target.closest("button")) openSetup().catch(error);
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { closeScroll(el); el.focus(); e.stopPropagation(); return; }
      if (e.target !== el) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (!el.classList.contains("open")) openScroll(el, true);
        else if (el.dataset.scroll === "new") openSetup().catch(error);
        else { const first = el.querySelector(".parchment button"); if (first) first.focus(); }
      }
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const all = scrolls(), next = all[(all.indexOf(el) + (e.key === "ArrowRight" ? 1 : all.length - 1)) % all.length];
        next.focus();
      }
    });
  });
  document.addEventListener("keydown", (e) => {
    if ($("titleScreen").hidden || !$("setup").hidden || !$("transition").hidden || typing(e)) return;
    if ((e.key === "ArrowRight" || e.key === "ArrowLeft") && !e.target.closest(".scroll")) { e.preventDefault(); scrolls()[0].focus(); }
  });
}

/* =========================== New Journey setup =========================== */
function settingsGrid(values) {
  return SETTING_FIELDS.map(([key, label, attrs]) =>
    `<label>${esc(label)}<input name="${key}" type="number" value="${esc(values[key])}" ${Object.entries(attrs).map(([k, v]) => `${k}="${v}"`).join(" ")} required></label>`).join("") +
    `<label class="inline"><input name="narration" type="checkbox" ${values.narration ? "checked" : ""}> Odyssey discussion narrated by the narrator model (live runs)</label>` +
    `<label class="inline"><input name="formalize_definitions" type="checkbox" ${values.formalize_definitions ? "checked" : ""}> Type-check proposed definitions in Lean</label>`;
}
function readSettings(form) {
  const f = new FormData(form), out = {};
  SETTING_FIELDS.forEach(([key]) => (out[key] = Number(f.get(key))));
  out.narration = f.get("narration") === "on";
  out.formalize_definitions = f.get("formalize_definitions") === "on";
  return out;
}
function rolesSummary(s) {
  if (!s.keys_required) {
    return '<p class="ok">✓ Fixture mode: the agents are scripted, no model is called and no key is needed.</p>' +
      '<p class="hint">In live mode each role below needs a working key: ' + esc(Object.values(s.roster).filter((r) => !r.extra).map((r) => r.label + " — " + r.default_model_name).join("; ")) + ".</p>";
  }
  return Object.values(s.roster).map((r) =>
    `<div class="roleRow"><span class="mark ${r.ready ? "ok" : "warn"}">${r.ready ? "✓" : "⚠"}</span><span>${esc(r.label)}</span><span>${esc(r.model || "no model chosen — default " + r.default_model_name)}</span>` +
    `<span class="hint">${r.ready ? esc(r.key_label) + " key" : !r.configured ? "choose a model" : !r.key.set ? "missing " + esc(r.key_label) + " key" : "key test failed"}</span></div>`).join("");
}
const BUILD_NEW = "__build__";
async function openSetup() {
  [state.catalog, state.settings] = await Promise.all([api("/catalog"), api("/settings")]);
  const short = (v) => (v ? "mathlib " + String(v).slice(0, 8) : "no mathlib tag");
  const ex = state.catalog.export;
  $("catalogNote").textContent = ex
    ? `${state.catalog.fields.length} basis groups: every MSC 2020 field that holds declarations in the mathlib export (${ex.declarations.toLocaleString()} declarations at ${ex.mathlib.slice(0, 8)}). Placement is by script, not gods-curated.`
    : `${state.catalog.fields.length} saved basis groups. No mathlib export is configured, so no further group can be built here.`;
  $("fieldCatalog").innerHTML = state.catalog.fields.map((f) => {
    const roots = f.modules.filter((m) => m.available && m.islands.length === 1 && !m.additive);
    const usable = f.state === "ready" || f.buildable;
    const size = f.declarations ? ` · ${f.declarations.toLocaleString()} declarations in the export` : "";
    return `<div class="fieldRow" data-field="${esc((f.name + " " + f.id + " " + (f.msc || "")).toLowerCase())}"><input type="checkbox" name="island" value="${esc(f.id)}" id="isl-${esc(f.id)}" ${usable ? "" : "disabled"} aria-label="${esc(f.name)}">` +
      `<label class="name inline" for="isl-${esc(f.id)}">${esc(f.name)}${f.msc ? ` <span class="hint">MSC ${esc(f.msc)}</span>` : ""}</label>${f.state === "ready" ? pill("Ready", "good") : f.buildable ? pill("Needs building", "gold") : pill("No data", "bad")}` +
      `<span class="sub">${f.state === "ready"
        ? `<select name="module-${esc(f.id)}" aria-label="Saved version of ${esc(f.name)}">${roots.map((m) => `<option value="${esc(m.id)}" ${m.id === f.recommended ? "selected" : ""}>${esc(m.id)} · ${m.counts.concepts} nodes · ${esc(short(m.mathlib_version))}${m.fixture ? " · fixture" : ""}</option>`).join("")}` +
          `${f.can_build_new ? `<option value="${BUILD_NEW}">Build a new version from the full export${esc(size)}</option>` : ""}</select>`
        : esc(f.build_note) + esc(size)}</span></div>`;
  }).join("");
  $("fieldFilter").value = "";
  $("catalogInstall").hidden = !!ex || state.catalog.fields.every((f) => f.state === "ready");
  $("setupRoles").innerHTML = rolesSummary(state.settings);
  $("setupSettingsGrid").innerHTML = settingsGrid(DEFAULTS) +
    (state.catalog.fields.some((f) => f.buildable) && state.settings.keys_required
      ? '<label>Budget for building missing groups (USD)<input name="build_budget" type="number" min="0" step="0.01" value="0"></label>' : "");
  $("journeyForm").elements.name.value = "";
  validateSetup();
  $("setup").hidden = false;
  $("journeyForm").elements.name.focus();
}
function filterFields() {
  const q = $("fieldFilter").value.trim().toLowerCase();
  document.querySelectorAll("#fieldCatalog .fieldRow").forEach((row) => {
    row.hidden = !!q && !row.dataset.field.includes(q) && !row.querySelector('input[name="island"]').checked;
  });
}
function validateSetup() {
  const chosen = [...$("journeyForm").querySelectorAll('input[name="island"]:checked')];
  const problem = !chosen.length ? "Pick at least one basis group."
    : chosen.length > 12 ? "Pick at most twelve basis groups for one journey."
    : !state.settings.ready ? "Every role needs a working key before sailing: open Settings."
    : "";
  $("setupProblem").textContent = problem;
  $("chosenCount").textContent = chosen.length ? `${chosen.length} chosen` : "";
  $("setSail").disabled = !!problem; // Start is disabled until every role the journey uses has a working key.
}
async function setSail(e) {
  e.preventDefault();
  const form = $("journeyForm"), f = new FormData(form);
  const islands = f.getAll("island");
  const fields = Object.fromEntries(state.catalog.fields.map((x) => [x.id, x]));
  const settings = readSettings(form);
  const mustBuild = (i) => fields[i].state !== "ready" || f.get("module-" + i) === BUILD_NEW;
  const building = islands.filter(mustBuild);
  const modules = islands.filter((i) => !mustBuild(i)).map((i) => f.get("module-" + i));
  $("setup").hidden = true;
  let created = null;
  await transition({
    from: $("scrollNew"),
    hold: building.length ? async (el) => { modules.push(...(await buildHold(el, building.map((i) => fields[i]), Number(f.get("build_budget") || 0)))); } : null,
    load: async () => {
      // Bridge modules between any two selected islands are included automatically; a pair that
      // has none yet gets one from the same export.
      const { bridges } = await api("/modules/bridges", { method: "POST", body: JSON.stringify({ modules }) });
      created = await api("/journeys", { method: "POST", body: JSON.stringify({ name: f.get("name").trim(), islands, modules: modules.concat(bridges), settings }) });
      await openJourney(created.id);
    },
    fail: () => { $("setup").hidden = false; },
  });
}
async function buildHold(el, fields, budget) {
  el.innerHTML = '<h2>The gods are building</h2><p class="hint">A basis group is built once and saved; later journeys link it at once.</p>' +
    '<div class="buildRow"><canvas id="buildPortrait" width="16" height="16"></canvas><div><p id="buildStage"></p><div class="progressBar"><i id="buildBar"></i></div></div><canvas id="buildIsland" width="48" height="32"></canvas></div><div id="buildDone"></div>';
  paint($("buildPortrait"), Pixel.portraits.gods);
  const ink = $("buildIsland").getContext("2d"), rand = Pixel.rng(11), dots = [];
  for (let y = 0; y < 32; y++) for (let x = 0; x < 48; x++) { const d = Math.hypot((x - 24) / 21, (y - 16) / 12); if (d < 0.86 + rand() * 0.16) dots.push([x, y, d]); }
  dots.sort((a, b) => b[2] - a[2]);
  const modules = [];
  for (const field of fields) {
    let job = await api("/modules/build", { method: "POST", body: JSON.stringify({ island: field.id, budget_usd: budget }) });
    ink.clearRect(0, 0, 48, 32);
    let inked = 0;
    while (job.status === "queued" || job.status === "building") {
      $("buildStage").textContent = field.name + ": " + job.stage;
      $("buildBar").style.width = job.percent + "%";
      const upto = Math.floor((dots.length * job.percent) / 100);
      ink.fillStyle = "#5a3d2b";
      for (; inked < upto; inked++) ink.fillRect(dots[inked][0], dots[inked][1], 1, 1);
      await wait(350);
      job = await api("/modules/builds/" + job.id);
    }
    if (job.status !== "ready") throw Error("The build of " + field.name + " stopped: " + (job.error || "unknown error"));
    ink.fillStyle = "#3f8a4a";
    dots.forEach(([x, y, d]) => { if (d < 0.7) ink.fillRect(x, y, 1, 1); });
    $("buildBar").style.width = "100%";
    $("buildStage").textContent = field.name + ": ready";
    $("buildDone").insertAdjacentHTML("beforeend", `<p class="ok">✓ ${esc(field.name)} is ready — ${esc(job.module_id)} (${esc(job.method || "saved earlier")}).</p>`);
    modules.push(job.module_id);
  }
  await wait(500);
  return modules;
}

/* =========================== Scroll transition =========================== */
let skipTransition = null;
function skippable(ms) {
  return new Promise((resolve) => {
    const timer = setTimeout(done, ms);
    function done() { clearTimeout(timer); skipTransition = null; resolve(); }
    skipTransition = done; // a click or Esc skips the animation; returning users see it every time
  });
}
async function transition({ from, hold, load, fail }) {
  const t = $("transition"), fly = $("flyScroll");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  $("holdContent").innerHTML = "";
  $("skipHint").hidden = false;
  const r = from ? from.getBoundingClientRect() : { left: innerWidth / 2, top: innerHeight / 2, width: 0, height: 0 };
  fly.style.transformOrigin = `${r.left + r.width / 2}px ${r.top + r.height / 2}px`;
  t.className = "fly";
  t.hidden = false;
  try {
    // The scroll flies toward the viewer and grows until it covers the whole screen.
    await skippable(reduced ? 0 : 760);
    t.className = "";
    $("skipHint").hidden = true;
    if (hold) await hold($("holdContent")); // builds and review documents hold at full screen
    await load();
    // ...then it fades into the top-down ocean.
    $("skipHint").hidden = false;
    t.className = "fade";
    await skippable(reduced ? 0 : 620);
  } catch (e) {
    if (fail) fail();
    if (e && e.message !== "cancelled") error(e);
  } finally {
    t.hidden = true;
    t.className = "";
    skipTransition = null;
  }
}
async function reviewHold(el, j) {
  // A review document opens on the same full-screen scroll, with a button that finishes the
  // transition into that journey.
  const [runs, papers] = await Promise.all([api(`/journeys/${j.id}/runs`), api(`/journeys/${j.id}/papers`)]);
  const title = Object.fromEntries(papers.map((p) => [p.id, p.title]));
  const done = runs.filter((r) => r.checkpoint >= 7); // newest first, as the API returns them
  return new Promise((resolve, reject) => {
    el.innerHTML = `<h2>Review documents — ${esc(journeyName(j))}</h2><div class="actions"><button id="sailToMap" class="pixelButton primary">Sail to the map</button><button id="backBeach" class="pixelButton quiet">Back to the beach</button></div>` +
      (done.length ? '<p class="hint">Run reports, newest first. Pick one to open its ranked report.</p>' + done.map((r) => `<div class="historyRow"><div><h3>${esc(title[r.paper_id] || r.paper_id)}</h3><span class="hint">${esc(date(r.created))} · ${esc(r.status)}</span></div><button class="pixelButton small" data-review-run="${esc(r.id)}">Open ranked report</button></div>`).join("")
        : '<div class="empty">This journey has no finished run yet, so there is no review document. Sail to the map to run a paper.</div>') +
      '<div id="reviewDoc"></div>';
    el.onclick = (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.id === "sailToMap") { el.onclick = null; resolve(null); }
      if (b.id === "backBeach") { el.onclick = null; reject(Error("cancelled")); }
      if (b.dataset.reviewRun) api(`/journeys/${j.id}/runs/${b.dataset.reviewRun}/report`).then((rep) => {
        $("reviewDoc").innerHTML = `<div class="actions">Export: ${["pdf", "md", "json"].map((x) => `<button class="pixelButton small" data-review-export="${x}" data-run="${esc(b.dataset.reviewRun)}">${x.toUpperCase()}</button>`).join("")}</div>` + reportHtml(rep, false);
        $("reviewDoc").scrollIntoView({ block: "start" });
      }).catch(error);
      if (b.dataset.reviewExport) download(j.id, b.dataset.run, b.dataset.reviewExport).catch(error);
      if (b.dataset.show) { el.onclick = null; resolve({ kind: b.dataset.kind, id: b.dataset.show }); }
    };
  });
}

/* =========================== Sea map: opening a journey =========================== */
function leaveJourney() {
  if (state.stream) state.stream.abort();
  clearInterval(state.poll);
  clearTimeout(state.disc.timer);
  state.journeyId = null; state.journey = null; state.run = null; state.before = null; state.mapSig = "";
  state.disc = { runId: null, queue: [], log: [], seen: new Set(), cursor: 0, muted: state.disc.muted, timer: null, current: null };
  $("discussion").hidden = true;
  document.querySelectorAll("dialog[open]").forEach((d) => d.close());
  if (seaMap) seaMap.run(false);
}
async function openJourney(id, focus) {
  leaveJourney();
  state.journeyId = id;
  state.match = null; state.selection = null; state.pick = null;
  state.route = { start: null, end: null, result: null };
  $("titleScreen").hidden = true;
  $("mapScreen").hidden = false;
  TitleScene.run(false);
  ["bottle", "routePanel", "details", "beforeBar", "resumeBanner"].forEach((p) => ($(p).hidden = true));
  setView("sea");
  seaMap.run(true);
  await loadMap(false);
  if (location.hash !== "#" + id) history.replaceState(null, "", "#" + id);
  $("journeyTitle").textContent = journeyName(state.journey);
  const names = state.journey.island_names || {};
  $("journeyMeta").textContent = state.journey.islands.map((i) => names[i] || i).join(" · ") + " · " + state.journey.modules.length + " module(s)";
  $("graphIsland").innerHTML = '<option value="">All islands</option>' + state.journey.islands.map((i) => `<option value="${esc(i)}">${esc(names[i] || i)}</option>`).join("");
  $("groupFilter").value = "";
  fillPaperGroups();
  renderRouteEnds();
  await refresh();
  connectEvents(id);
  state.poll = setInterval(() => refresh().catch(error), 3000);
  const waiting = state.runs.find((r) => ["paused", "failed"].includes(r.status));
  if (waiting) {
    // A paused or interrupted run offers Resume.
    state.run = waiting;
    $("resumeLabel").textContent = `The run on “${(state.papers.find((p) => p.id === waiting.paper_id) || {}).title || "a paper"}” is ${waiting.status}${waiting.error ? ": " + waiting.error : ""}.`;
    $("resumeButton").textContent = waiting.status === "failed" ? "Retry" : "Resume";
    $("resumeBanner").hidden = false;
  }
  if (focus) select(focus, true);
}
function fillPaperGroups() {
  // Every MSC subtopic of the journey's basis groups, grouped by island and subfield.
  const q = $("groupFilter").value.trim().toLowerCase(), names = state.journey.island_names || {};
  const byId = Object.fromEntries(state.data.groups.map((g) => [g.id, g]));
  const keep = $("paperGroup").value, sections = new Map();
  state.data.groups.filter((g) => g.depth === 3 && (!q || (g.msc + " " + g.name).toLowerCase().includes(q))).forEach((g) => {
    const parent = byId[g.parent] || {};
    const label = `${names[g.island] || g.island} — ${parent.msc || ""} ${parent.name || ""}`.trim();
    if (!sections.has(label)) sections.set(label, []);
    sections.get(label).push(g);
  });
  $("paperGroup").innerHTML = [...sections].map(([label, groups]) => `<optgroup label="${esc(label)}">${groups.map((g) => `<option value="${esc(g.id)}">${esc(g.msc)} — ${esc(g.name)}</option>`).join("")}</optgroup>`).join("");
  if ([...$("paperGroup").options].some((o) => o.value === keep)) $("paperGroup").value = keep;
}
async function loadMap(keepCamera) {
  const b = state.before;
  const data = await api(`/journeys/${state.journeyId}/map${b && b.showing === "before" ? `?run_id=${encodeURIComponent(b.runId)}&before=true` : ""}`);
  state.data = data;
  state.journey = data.journey;
  state.byId = Object.fromEntries(data.concepts.map((n) => [n.id, n]));
  seaMap.setData(data, keepCamera);
  if (state.view === "simple") drawSimple();
  applyFilters();
}
function currentFilters() {
  return { tier: $("graphTier").value, existing: $("graphExisting").value, island: $("graphIsland").value, run: $("graphRun").value,
    newOnly: $("graphNew").checked, rejected: $("graphRejected").checked, proposed: $("graphProposed").checked, match: state.match };
}
function applyFilters() {
  const f = currentFilters();
  seaMap.setFilters(f);
  if (state.view === "simple") filterSimple(f);
}
function edgeVisible(e, f) {
  const rejected = e.review_status === "rejected" || e.invalidated;
  if (rejected && !f.rejected) return false;
  if (!rejected && e.review_status !== "passed" && !f.proposed) return false;
  if (f.tier && e.tier !== f.tier) return false;
  if (f.existing && e.existing !== f.existing) return false;
  if (f.run && e.run_id !== f.run) return false;
  if (f.newOnly && (e.run_id !== state.data.latest_run || e.kind === "integration")) return false;
  const ends = e.premises.concat(e.conclusion);
  if (f.island && !ends.some((n) => state.byId[n] && state.byId[n].island === f.island)) return false;
  if (f.match && !ends.some((n) => f.match.has(n))) return false;
  return true;
}
async function search() {
  const q = $("graphSearch").value.trim();
  if (!q) { state.match = null; $("searchResult").textContent = ""; applyFilters(); return; }
  let ids;
  if ($("graphSemantic").checked) {
    const result = await api(`/journeys/${state.journeyId}/search/semantic`, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ query: q, budget_usd: Number($("runBudget").value) }) });
    ids = result.results.map((n) => n.id);
    $("searchResult").textContent = `${ids.length} match(es) by meaning${result.fixture ? " (fixture mode searches the text, not vectors)" : ""}`;
  } else {
    ids = state.data.concepts.filter((n) => n.name.toLowerCase().includes(q.toLowerCase())).map((n) => n.id);
    $("searchResult").textContent = `${ids.length} match(es) by name`;
  }
  state.match = new Set(ids);
  applyFilters();
  if (ids.length) select({ kind: "concept", id: ids[0] }, true);
}

/* =========================== Two views, one camera =========================== */
const STATUS_COLOR = { Established: "#397c70", Accepted: "#b07a2a", Proven: "#2e7d4f", Proposed: "#ffffff" };
const SIMPLE_STYLE = [
  { selector: "node.island", style: { shape: "round-rectangle", "background-color": "#dfe9d5", "background-opacity": 0.55, "border-color": "#9db38c", "border-width": 1, label: "data(label)", "text-valign": "top", "text-halign": "center", color: "#4a6a4a", "font-size": 13, "font-family": "monospace", "font-weight": "bold", padding: "10px", "text-margin-y": -3 } },
  { selector: "node.group", style: { shape: "rectangle", "background-color": "data(color)", "background-opacity": 0.45, "border-color": "#6e8a5a", "border-width": 0.4, label: "data(label)", "text-valign": "top", "text-halign": "center", color: "#3a4a3a", "font-size": 4, "min-zoomed-font-size": 7, "font-family": "monospace", padding: "2px", "text-margin-y": 3, "text-wrap": "ellipsis", "text-max-width": "60px" } },
  { selector: "node[kind = 'concept']", style: { "background-color": "data(color)", width: 4.5, height: 4.5, "border-width": 0.7, "border-color": "#ffffff", label: "data(label)", "font-size": 1.25, "min-zoomed-font-size": 9, "font-family": "monospace", color: "#1b2a2a", "text-valign": "bottom", "text-margin-y": 0.4, "text-wrap": "ellipsis", "text-max-width": "7.4px" } },
  { selector: "node.journey", style: { shape: "rectangle", width: 6, height: 6, "font-size": 2.2, "min-zoomed-font-size": 8, "text-max-width": "16px", "font-weight": "bold" } },
  { selector: "node.unintegrated", style: { "border-color": "#f5a623", "border-style": "dashed", "border-width": 1.2 } },
  { selector: "node.proposed", style: { "background-color": "#ffffff", "border-color": "#397c70", opacity: 0.55 } },
  { selector: "node.fresh", style: { "border-color": "#ffb000", "border-width": 1.6 } },
  { selector: "node.junction", style: { width: 3, height: 3, "background-color": "#577c77", "border-width": 0, label: "" } },
  { selector: "edge", style: { width: 0.4, "line-color": "#8b999d", "curve-style": "straight", "target-arrow-shape": "none", "arrow-scale": 0.3, opacity: 0.5 } },
  { selector: "edge.arrow", style: { "target-arrow-shape": "triangle", "target-arrow-color": "#8b999d" } },
  { selector: "edge.cited", style: { "line-style": "dashed", "line-dash-pattern": [3, 2] } },
  { selector: "edge.intuitive", style: { "line-style": "dotted" } },
  { selector: "edge.fresh", style: { "line-color": "#ffb000", "target-arrow-color": "#ffb000", width: 1.3, opacity: 1 } },
  { selector: "edge.nonEvidence", style: { "line-color": "#bc3e45", "target-arrow-color": "#bc3e45", "line-style": "dotted" } },
  { selector: "edge.route", style: { "line-color": "#e08a00", "target-arrow-color": "#e08a00", width: 2.2, opacity: 1, "z-index": 9 } },
  { selector: ".filtered", style: { display: "none" } },
  { selector: "node.dim", style: { opacity: 0.12 } },
  { selector: "node:selected", style: { "border-color": "#101c30", "border-width": 1.8 } },
  { selector: "edge:selected", style: { width: 2, "line-color": "#101c30" } },
];
function drawSimple() {
  if (typeof cytoscape !== "function") { error(Error("Graph library unavailable")); return; }
  const world = seaMap.world(), d = state.data, elements = [];
  const leaf = {}, color = {};
  world.islands.forEach((isl) => {
    elements.push({ data: { id: "island:" + isl.id, label: isl.name.toUpperCase(), kind: "island" }, classes: "island", selectable: false, grabbable: false });
    isl.leafRects.forEach((l) => { leaf[l.group.id] = isl.id; color[l.group.id] = l.color; });
  });
  const parents = new Set();
  const parentOf = (n) => (leaf[n.home_group] === n.island ? n.home_group : n.island + ":misc");
  d.concepts.forEach((n) => { if (world.pos[n.id]) parents.add(parentOf(n) + "|" + n.island); });
  const groupById = Object.fromEntries(d.groups.map((g) => [g.id, g]));
  parents.forEach((key) => {
    const [gid, island] = key.split("|"), g = groupById[gid];
    elements.push({ data: { id: "group:" + gid, parent: "island:" + island, label: g ? (g.msc ? g.msc + " " : "") + g.name : "Other", kind: "group", gid, color: color[gid] || "#b9cfa3" }, classes: "group", selectable: false, grabbable: false });
  });
  d.concepts.forEach((n) => {
    const p = world.pos[n.id];
    if (!p) return;
    elements.push({ data: { id: n.id, label: n.name, kind: "concept", parent: "group:" + parentOf(n), color: STATUS_COLOR[n.status] || STATUS_COLOR.Established }, position: { x: p.x, y: p.y }, grabbable: false,
      classes: [n.layer.startsWith("journey:") ? "journey" : "base", n.integrated ? "" : "unintegrated", n.status === "Proposed" ? "proposed" : "", n.run_id && n.run_id === d.latest_run ? "fresh" : ""].join(" ").trim() });
  });
  d.edges.forEach((e) => {
    const c = world.pos[e.conclusion];
    if (!c || !e.premises.every((p) => world.pos[p])) return;
    const none = e.review_status !== "passed" || e.invalidated;
    const cls = `${e.tier} ${none ? "nonEvidence" : ""} ${e.run_id && e.run_id === d.latest_run ? "fresh" : ""}`.trim();
    if (e.premises.length > 1) {
      // Lines converge on a junction dot before the conclusion: all premises together.
      const m = e.premises.reduce((s, p) => ({ x: s.x + world.pos[p].x / e.premises.length, y: s.y + world.pos[p].y / e.premises.length }), { x: 0, y: 0 });
      const jid = "junction:" + e.id;
      elements.push({ data: { id: jid, kind: "edge", edge: e.id }, position: { x: (m.x + c.x) / 2, y: (m.y + c.y) / 2 }, classes: "junction", grabbable: false });
      e.premises.forEach((p, k) => elements.push({ data: { id: `${e.id}:p${k}`, source: p, target: jid, kind: "edge", edge: e.id }, classes: cls }));
      elements.push({ data: { id: `${e.id}:c`, source: jid, target: e.conclusion, kind: "edge", edge: e.id }, classes: cls + " arrow" });
    } else elements.push({ data: { id: `${e.id}:e`, source: e.premises[0], target: e.conclusion, kind: "edge", edge: e.id }, classes: cls + (e.directed ? " arrow" : "") });
  });
  if (cy) cy.destroy();
  const large = d.concepts.length > 1200;
  cy = cytoscape({ container: $("graphCanvas"), elements, layout: { name: "preset" }, style: SIMPLE_STYLE, minZoom: 0.2, maxZoom: 24, boxSelectionEnabled: false, textureOnViewport: large, hideEdgesOnViewport: large });
  cy.on("tap", "node[kind = 'concept'], node.junction, edge, node.group", (evt) => {
    const data = evt.target.data();
    mapClick(data.kind === "concept" ? { kind: "concept", id: data.id, name: data.label } : data.kind === "group" ? { kind: "group", id: data.gid, name: data.label } : { kind: "edge", id: data.edge });
  });
  filterSimple(currentFilters());
  markRoute();
}
function filterSimple(f) {
  if (!cy) return;
  const visible = new Set(state.data.edges.filter((e) => edgeVisible(e, f)).map((e) => e.id));
  cy.batch(() => {
    cy.elements("[kind = 'edge']").forEach((el) => el.toggleClass("filtered", !visible.has(el.data("edge"))));
    cy.nodes("[kind = 'concept']").forEach((el) => {
      const n = state.byId[el.id()];
      el.toggleClass("filtered", !!((f.island && n.island !== f.island) || (n.invalidated && !f.rejected)));
      el.toggleClass("dim", !!(f.match && !f.match.has(n.id)));
    });
  });
}
function markRoute() {
  if (!cy) return;
  const ids = new Set(state.route.result && state.route.result.found ? state.route.result.path_edges : []);
  cy.batch(() => cy.elements("[kind = 'edge']").forEach((el) => el.toggleClass("route", ids.has(el.data("edge")))));
}
function setView(view) {
  const box = $("seaCanvas").getBoundingClientRect(), w = box.width || innerWidth, h = box.height || innerHeight;
  if (view === "simple" && state.view !== "simple") {
    // The camera carries over: zoom, pan and the current selection stay put.
    const cam = seaMap.camera();
    state.view = "simple";
    $("graphCanvas").hidden = false; $("seaCanvas").hidden = true; $("minimap").hidden = true;
    seaMap.run(false);
    drawSimple();
    cy.viewport({ zoom: cam.zoom, pan: { x: w / 2 - cam.x * cam.zoom, y: h / 2 - cam.y * cam.zoom } });
    markSelection();
  } else if (view === "sea") {
    const from = state.view === "simple" && cy ? { zoom: cy.zoom(), x: (w / 2 - cy.pan().x) / cy.zoom(), y: (h / 2 - cy.pan().y) / cy.zoom() } : null;
    state.view = "sea";
    $("graphCanvas").hidden = true; $("seaCanvas").hidden = false;
    seaMap.run(true);
    if (from) seaMap.setCamera(from);
    seaMap.setSelection(state.selection);
  }
  $("viewToggle").textContent = state.view === "sea" ? "Simplified view (G)" : "Sea map (G)";
  $("viewToggle").setAttribute("aria-pressed", state.view === "simple");
  updateZoomLabel();
}
function updateZoomLabel() {
  const z = state.view === "sea" ? seaMap.camera().zoom : cy ? cy.zoom() : 1;
  $("zoomLabel").textContent = (z === 0.5 ? "½" : z === 0.25 ? "¼" : Number.isInteger(z) ? z : z.toFixed(1)) + "×";
}
function markSelection() {
  if (state.view === "sea") { seaMap.setSelection(state.selection); return; }
  if (!cy) return;
  cy.elements().unselect();
  const s = state.selection;
  if (!s) return;
  if (s.kind === "concept") cy.$id(s.id).select();
  if (s.kind === "edge") cy.elements(`[edge = "${s.id}"]`).select();
}
function select(info, pan) {
  state.selection = info && ["concept", "edge", "group", "paper", "island"].includes(info.kind) ? { kind: info.kind, id: info.id } : null;
  markSelection();
  if (pan && state.selection) centreOn(seaMap.anchor(state.selection));
  if (info) showDetail(info).catch(error);
}
function centreOn(p) {
  if (!p) return;
  if (state.view === "sea") { seaMap.panTo(p, 3); return; }
  if (!cy) return;
  const z = Math.max(cy.zoom(), 3);
  cy.viewport({ zoom: z, pan: { x: cy.width() / 2 - p.x * z, y: cy.height() / 2 - p.y * z } });
  updateZoomLabel();
}
function mapClick(info) {
  if (!info) { state.selection = null; markSelection(); return; }
  if (state.pick && info.kind === "concept") { setRouteEnd(state.pick, info.id); return; }
  select(info, false);
}

/* =========================== Details side panel =========================== */
const nameOf = (id) => (state.byId[id] ? state.byId[id].name : id);
function conceptButtons(ids, limit = 400) {
  return `<ul class="conceptList">${ids.slice(0, limit).map((id) => `<li><button data-show="${esc(id)}" data-kind="concept">${esc(nameOf(id))}</button></li>`).join("")}</ul>` + (ids.length > limit ? `<p class="hint">${ids.length - limit} more not listed; use search.</p>` : "");
}
function edgeLine(e) {
  return `<li><button data-show="${esc(e.id)}" data-kind="edge">${esc(e.premises.map(nameOf).join(" + "))} → ${esc(nameOf(e.conclusion))} <span class="hint">(${esc(e.type)}, ${esc(e.tier)})</span></button></li>`;
}
function proofTree(id, depth, seen) {
  // The proof tree that reaches a concept: accepted inference edges into it, premises expanded.
  const into = state.data.edges.filter((e) => e.conclusion === id && e.review_status === "passed" && !e.invalidated && ["implies", "equivalent"].includes(e.type) && e.tier !== "intuitive");
  if (!into.length || depth > 3 || seen.has(id)) return "";
  const next = new Set(seen).add(id);
  return `<ul class="conceptList">${into.slice(0, 6).map((e) => `<li><button data-show="${esc(e.id)}" data-kind="edge">${esc(e.type)} · ${esc(e.tier)} from ${esc(e.premises.map(nameOf).join(" + "))}</button>${e.premises.map((p) => proofTree(p, depth + 1, next)).join("")}</li>`).join("")}</ul>`;
}
async function showDetail(info) {
  const box = $("detailContent");
  let html = "";
  if (info.kind === "concept" || info.kind === "edge") {
    const result = await api(`/journeys/${state.journeyId}/details/${info.kind}/${encodeURIComponent(info.id)}`);
    const d = result.item, none = (d.review_status && d.review_status !== "passed") || d.invalidated;
    if (info.kind === "concept") {
      const sprite = d.layer.startsWith("journey:") ? Pixel.itemFor(d.id).name : null;
      const out = state.data.edges.filter((e) => e.premises.includes(d.id)), into = state.data.edges.filter((e) => e.conclusion === d.id);
      const tree = proofTree(d.id, 0, new Set());
      html = `<h2>${esc(d.name)}</h2><div>${pill(d.status, d.status === "Proven" ? "good" : "")} ${pill(d.kind || "concept")} ${d.integrated === false ? pill("unintegrated", "gold") : ""} ${d.invalidated ? pill("invalidated", "bad") : ""}</div>` +
        `<p>${esc(d.statement)}</p>${sprite ? `<p class="hint">On the map: ${esc(sprite.toLowerCase())}.</p>` : '<p class="hint">A basis concept: laid out on its island but not drawn on the sea map. The simplified view (G) shows it.</p>'}` +
        `<div class="actions"><button class="pixelButton small" data-route-set="start" data-id="${esc(d.id)}">Route from here</button><button class="pixelButton small" data-route-set="end" data-id="${esc(d.id)}">Route to here</button></div>` +
        `<h3>Provenance</h3><p>${esc(sourceText(d.source))}</p><p class="hint">Home group: ${esc((state.data.groups.find((g) => g.id === d.home_group) || {}).name || d.home_group)} · layer ${esc(d.layer)}</p>` +
        `<h3>Proof tree that reaches it</h3>${tree || '<p class="hint">No verified or cited inference edge reaches this concept yet.</p>'}` +
        `<h3>Connections</h3><ul class="conceptList">${into.concat(out).slice(0, 40).map(edgeLine).join("") || "<li>None.</li>"}</ul>`;
    } else {
      html = `<h2>${esc(d.premises.map(nameOf).join(" + "))} → ${esc(nameOf(d.conclusion))}</h2><div>${pill(d.type)} ${pill(d.tier, d.tier === "verified" ? "good" : "")} ${d.existing ? pill(d.existing) : ""} ${none ? pill("non-evidence — excluded from proofs and scores", "bad") : ""}</div>` +
        `<p>${esc(d.argument)}</p>` +
        `<div class="actions"><button class="pixelButton small" data-feedback="${esc(d.id)}" data-mark="interesting">☆ Interesting</button><button class="pixelButton small" data-feedback="${esc(d.id)}" data-mark="wrong">Flag wrong → back to Penelope</button></div>` +
        `<h3>Provenance</h3><p>${esc(d.provenance ? [d.provenance.agent, d.provenance.perspective && d.provenance.perspective + " perspective", d.provenance.band && d.provenance.band + " band", d.provenance.kind].filter(Boolean).join(" · ") : "Base graph")}</p>` +
        (d.bridge_score && d.bridge_score.value != null ? `<p>Bridge score ${d.bridge_score.value.toFixed(3)}</p>` : "") +
        `<h3>Evidence</h3>${(d.evidence || []).map((v) => `<p class="hint">${esc([v.source, v.location].filter(Boolean).join(" — "))}${v.excerpt ? ": “" + esc(v.excerpt) + "”" : ""}</p>`).join("") || '<p class="hint">The argument alone.</p>'}` +
        `<h3>Tier history</h3>${(d.tier_history || []).map((h) => `<p class="hint">${esc(h.tier)}${h.action ? " · " + esc(h.action) : ""}${h.reason ? " — " + esc(h.reason) : ""}</p>`).join("") || '<p class="hint">No changes recorded.</p>'}` +
        `<h3>Reviewer reasons</h3>${(result.reviews || []).map((r) => `<p class="hint">${esc(r.verdict)}: ${esc(r.reason)}</p>`).join("") || '<p class="hint">No reviewer record.</p>'}` +
        `<h3>Proof tree that reaches it</h3><ul class="conceptList">${d.premises.map((p) => `<li><button data-show="${esc(p)}" data-kind="concept">${esc(nameOf(p))}</button>${proofTree(p, 1, new Set([d.conclusion]))}</li>`).join("")}</ul>`;
    }
    html += `<details><summary>Full record</summary><pre>${esc(JSON.stringify(result, null, 2))}</pre></details>`;
  } else if (info.kind === "group") {
    const g = state.data.groups.find((x) => x.id === info.id) || { name: info.name || "Group", msc: "" };
    const members = state.data.concepts.filter((n) => n.home_group === info.id).map((n) => n.id);
    html = `<h2>${esc((g.msc ? g.msc + " " : "") + g.name)}</h2><div>${pill("subgroup")} ${pill(g.island || "")}</div><p>${esc(g.description || "")}</p><h3>${members.length} concept(s) filed here</h3>${conceptButtons(members)}`;
  } else if (info.kind === "paper") {
    const p = state.data.papers.find((x) => x.id === info.id);
    const g = state.data.groups.find((x) => x.id === p.home_group) || {};
    html = `<h2>${esc(p.title)}</h2><div>${pill("paper")} ${pill("MSC " + (p.msc || "?"))}</div><p class="hint">Placed in ${esc(g.name || p.home_group)}. Added ${esc(date(p.created))}.</p><h3>${(p.concept_ids || []).length} concept(s)</h3>${conceptButtons(p.concept_ids || [])}`;
  } else if (info.kind === "fleet") {
    const names = state.journey.island_names || {}, byId = Object.fromEntries(state.data.edges.map((e) => [e.id, e]));
    const edges = info.edges.map((id) => byId[id]).filter(Boolean);
    html = `<h2>${esc(names[info.from] || info.from)} → ${esc(names[info.to] || info.to)}</h2><div>${pill("fleet")} ${pill(edges.length + " base links")}</div>` +
      `<p class="hint">Links between two basis groups in the base graph are drawn as one small fleet, not one boat each. They are mathlib dependency metadata or cited base links; each link a paper or the crew adds gets a boat of its own. The simplified view (G) draws every one.</p>` +
      `<ul class="conceptList">${edges.slice(0, 200).map(edgeLine).join("")}</ul>${edges.length > 200 ? `<p class="hint">${edges.length - 200} more not listed.</p>` : ""}`;
  } else if (info.kind === "island") {
    const isl = seaMap.world().islands.find((i) => i.id === info.id);
    html = `<h2>${esc(isl.name)}</h2><div>${pill("basis group")} ${pill(isl.count + " concepts")}</div><p>${esc(isl.field)}</p><p class="hint">An island's area scales with its node count. Its basis nodes are laid out slightly apart but not drawn.</p><h3>Subgroups</h3><ul class="conceptList">${isl.leafRects.map((l) => `<li><button data-show="${esc(l.group.id)}" data-kind="group">${esc((l.group.msc ? l.group.msc + " " : "") + l.group.name)} <span class="hint">(${l.count})</span></button></li>`).join("")}</ul>`;
  }
  box.innerHTML = html;
  $("details").hidden = false;
}
function sourceText(source) {
  if (!source || typeof source !== "object") return "The gods (base graph)";
  return [source.agent, source.declaration && "mathlib " + source.declaration, source.url, source.paper_id && "paper " + ((state.data.papers.find((p) => p.id === source.paper_id) || {}).title || source.paper_id), source.kind].filter(Boolean).join(" · ") || "The gods (base graph)";
}

/* =========================== Odyssey discussion =========================== */
async function pollDiscussion() {
  const d = state.disc, run = state.run;
  if (!run || !state.journeyId) return;
  if (d.runId !== run.id) {
    clearTimeout(d.timer);
    Object.assign(d, { runId: run.id, queue: [], log: [], seen: new Set(), cursor: 0, current: null, timer: null });
    $("discussion").hidden = true;
  }
  const first = d.cursor === 0;
  const lines = await api(`/journeys/${state.journeyId}/discussion?run_id=${encodeURIComponent(run.id)}&after=${d.cursor}`);
  if (d.runId !== run.id) return;
  const live = ["queued", "running"].includes(run.status) || !first;
  lines.forEach((l) => {
    if (d.seen.has(l.id)) return;
    d.seen.add(l.id); d.log.push(l); d.cursor = Math.max(d.cursor, l.time);
    if (live) d.queue.push(l); // lines from a run that finished before the journey was opened stay in the log
  });
  if (!d.current && d.queue.length && !d.muted) nextLine();
  if ($("logDialog").open) renderLog();
}
function factChips(facts) {
  const label = { tier: "tier", existing: "existing tag", edge_type: "type", conclusion: "conclusion", status: "status", concept: "concept", perspective: "perspective", band: "band", reason: "reason", formal_status: "Lean" };
  const chips = Object.entries(label).filter(([k]) => facts[k] != null).map(([k, v]) => `<span class="fact"><b>${v}</b> ${esc(facts[k])}</span>`);
  if (facts.premises) chips.splice(2, 0, `<span class="fact"><b>premises</b> ${esc(facts.premises.join(" + "))}</span>`);
  (facts.citations || []).forEach((c) => chips.push(`<span class="fact"><b>citation</b> ${esc(c)}</span>`));
  (facts.proposals || []).forEach((c) => chips.push(`<span class="fact"><b>proposal</b> ${esc(c)}</span>`));
  return chips.join("");
}
function nextLine() {
  const d = state.disc;
  clearTimeout(d.timer);
  const line = d.queue.shift();
  d.current = line || null;
  if (!line || d.muted) { $("discussion").hidden = true; d.current = null; return; }
  paint($("portrait"), Pixel.portraits[line.portrait] || Pixel.portraits.decomposer);
  $("speaker").textContent = line.speaker;
  $("speechMeta").textContent = `${state.status.stages[line.step] || "step " + line.step} · ${line.source === "narrator" ? "narrated" : line.fixture ? "fixture template" : "template"}${d.queue.length ? " · " + d.queue.length + " more" : ""}`;
  $("speechLine").textContent = line.line;
  $("speechFacts").innerHTML = factChips(line.facts || {});
  $("speechPan").hidden = !line.target;
  $("discussion").hidden = false;
  // A line about a specific node or edge highlights its walker, boat or patch.
  if (line.target) { state.selection = line.target; markSelection(); }
  d.timer = setTimeout(nextLine, Number($("speechSpeed").value));
}
function renderLog() {
  const log = state.disc.log;
  $("logList").innerHTML = log.length ? log.map((l, i) =>
    `<div class="logItem"><canvas width="16" height="16" data-portrait="${esc(l.portrait)}"></canvas><div><strong>${esc(l.speaker)}</strong> <span class="hint">${esc(new Date(l.time * 1000).toLocaleTimeString())} · ${esc(state.status.stages[l.step] || "")} · ${l.source === "narrator" ? "narrated" : "template"}</span><p>${esc(l.line)}</p><div class="facts">${factChips(l.facts || {})}</div>` +
    `<div class="actions"><button class="pixelButton small quiet" data-trace-entry="${esc(l.trace_ids[0])}">Trace entry ↗</button>${l.target ? `<button class="pixelButton small quiet" data-show="${esc(l.target.id)}" data-kind="${esc(l.target.kind)}">Show on map</button>` : ""}</div></div></div>`).join("")
    : '<div class="empty">No discussion yet. It appears while a run is going.</div>';
  $("logList").querySelectorAll("canvas").forEach((c) => paint(c, Pixel.portraits[c.dataset.portrait] || Pixel.portraits.decomposer));
}

/* =========================== Route finder =========================== */
function renderRouteEnds() {
  const r = state.route;
  $("routeStartName").textContent = r.start ? nameOf(r.start) : "No start chosen";
  $("routeEndName").textContent = r.end ? nameOf(r.end) : "No end chosen";
  $("routeFind").disabled = !(r.start && r.end);
  $("seaCanvas").classList.toggle("picking", !!state.pick);
  document.querySelectorAll("[data-pick]").forEach((b) => b.setAttribute("aria-pressed", state.pick === b.dataset.pick));
}
function setRouteEnd(which, id) {
  state.route[which] = id;
  state.pick = null;
  $("routePanel").hidden = false; $("bottle").hidden = true;
  renderRouteEnds();
}
async function routeSearch() {
  const q = $("routeSearch").value.trim();
  if (q.length < 2) { $("routeResults").innerHTML = ""; return; }
  let ids;
  if ($("routeSemantic").checked) ids = (await api(`/journeys/${state.journeyId}/search/semantic`, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ query: q, budget_usd: Number($("runBudget").value) }) })).results.map((n) => n.id);
  else ids = state.data.concepts.filter((n) => n.name.toLowerCase().includes(q.toLowerCase())).map((n) => n.id);
  $("routeResults").innerHTML = ids.slice(0, 40).map((id) => `<li><span title="${esc(nameOf(id))}">${esc(nameOf(id))}</span><button class="pixelButton small" data-route-set="start" data-id="${esc(id)}">Start</button><button class="pixelButton small" data-route-set="end" data-id="${esc(id)}">End</button></li>`).join("") || "<li>No concept matches.</li>";
}
async function findRoute() {
  const kind = document.querySelector('input[name="routeKind"]:checked').value;
  const r = await api(`/journeys/${state.journeyId}/route`, { method: "POST", body: JSON.stringify({ start: state.route.start, end: state.route.end, kind }) });
  state.route.result = r;
  $("routePlay").disabled = !(r.found && r.path_nodes.length > 1);
  $("routeExport").hidden = !r.found;
  if (!r.found) {
    // If no route exists under the chosen type, the finder says so.
    $("routeResult").innerHTML = `<div class="empty">${esc(r.message)}</div>`;
    seaMap.setRoute(null);
  } else {
    $("routeResult").innerHTML = `<h3>${esc(r.label)}: formal view</h3>` + (r.steps.length ? r.steps.map((s) =>
      `<div class="routeStep ${s.main ? "" : "side"}"><span class="n">${s.n}.</span> ${s.premises.map((p) => `<button class="pixelButton small quiet" data-show="${esc(p.id)}" data-kind="concept">${esc(p.name)}</button>${p.from === "assumed" ? " " + pill("assumed", "bad") : p.from === "start" ? "" : ` <span class="hint">[step ${p.from}]</span>`}`).join(" + ")}` +
      ` <strong>— ${esc(s.type)}${s.reversed ? ", against its direction" : ""} →</strong> <button class="pixelButton small quiet" data-show="${esc(s.conclusion.id)}" data-kind="concept">${esc(s.conclusion.name)}</button>` +
      `<div>${pill(s.tier, s.tier === "verified" ? "good" : "")} <button class="pixelButton small quiet" data-show="${esc(s.edge_id)}" data-kind="edge">evidence ↗</button> <span class="hint">${esc((s.evidence.find((v) => v && v.source) || {}).source || "argument only")}</span></div></div>`).join("")
      : '<p class="hint">The start and the end are the same concept.</p>') +
      (r.assumptions.length ? `<p class="warn">Additional premises assumed, not derived from the start: ${esc(r.assumptions.map((a) => a.name).join("; "))}</p>` : "") +
      `<p><strong>Length ${r.length} step(s)${r.total_steps > r.length ? ` (${r.total_steps} with side premises)` : ""} · overall tier ${esc(r.tier || "n/a")}</strong> — the lowest tier of any step.</p><p>${esc(r.result)}</p>`;
    seaMap.setRoute(r.path_nodes);
    centreOn(seaMap.anchor({ kind: "concept", id: r.path_nodes[0] }));
  }
  markRoute();
}

/* =========================== Report, history, trace =========================== */
function finding(e, i, onMap) {
  const value = e.bridge_score && e.bridge_score.value;
  const source = (e.evidence || []).find((v) => v && v.source);
  return `<article class="finding"><div class="sectionTitle"><div>${pill(e.tier, e.tier === "verified" ? "good" : "")} ${pill(e.existing)} ${e.fixture ? pill("fixture") : ""}</div><span class="hint">Bridge score ${value == null ? "unavailable" : value.toFixed(3)}</span></div>` +
    `<h3>${i + 1}. ${esc(e.argument)}</h3><div class="meta"><span>${esc(e.type)}</span><span>${e.premises.length} premise(s)</span><span>${e.support_count} crew mate(s) agreed</span><span>${e.tier === "verified" ? "machine verified exact statement" : e.tier === "cited" ? "literature supported" : "conjectural"}</span>${source ? `<span>evidence: ${esc(source.source)}${source.location ? " — " + esc(source.location) : ""}</span>` : ""}</div>` +
    `<div class="actions"><button class="pixelButton small" data-show="${esc(e.id)}" data-kind="edge">${onMap ? "Show on the map ↗" : "Sail to it on the map ↗"}</button>` +
    (onMap ? `<button class="pixelButton small" data-feedback="${esc(e.id)}" data-mark="interesting">☆ Interesting</button><button class="pixelButton small" data-feedback="${esc(e.id)}" data-mark="wrong">Flag wrong → back to Penelope</button>` : "") + `</div></article>`;
}
function reportHtml(r, onMap) {
  return `<div class="finding">${pill(r.fixture ? "fixture simulation — not discovery" : "auditable exploration", r.fixture ? "gold" : "good")}<p>${esc(r.summary)}</p></div>` +
    [["potentially_new", "Top new connections (tagged Not found: potentially new)"], ["rediscoveries", "Rediscoveries"], ["unchecked", "Unchecked connections"]].map(([key, title]) =>
      `<h3>${title} · ${r[key].length}</h3>${r[key].length ? r[key].map((e, i) => finding(e, i, onMap)).join("") : '<div class="empty">None in this run.</div>'}`).join("") +
    `<h3>Proposed concepts and new groups</h3><p class="hint">Odysseus's own proposals are kept apart from his ranking.</p>` +
    (r.proposed_concepts.length ? r.proposed_concepts.map((c) => {
      const id = typeof c === "string" ? c : c.id, n = (state.byId && state.byId[id]) || {};
      return `<div class="finding"><strong>${esc(n.name || id)}</strong> ${n.status ? pill(n.status, n.status === "Proven" ? "good" : "") : ""} <button class="pixelButton small" data-show="${esc(id)}" data-kind="concept">${onMap ? "Show on the map ↗" : "Sail to it ↗"}</button></div>`;
    }).join("") : '<div class="empty">No proposed concepts.</div>') +
    (r.new_groups.length ? `<p>New groups added by Odysseus: ${esc(r.new_groups.map((g) => { const id = typeof g === "string" ? g : g.id; return ((state.data && state.data.groups.find((x) => x.id === id)) || {}).name || id; }).join("; "))}</p>` : "");
}
async function openReport(runId) {
  const done = state.runs.filter((r) => r.checkpoint >= 7);
  const title = Object.fromEntries(state.papers.map((p) => [p.id, p.title]));
  $("reportRun").innerHTML = done.map((r) => `<option value="${esc(r.id)}">${esc(title[r.paper_id] || "paper")} · ${esc(date(r.created))}</option>`).join("");
  const id = runId || (state.run && state.run.checkpoint >= 7 ? state.run.id : done[0] && done[0].id);
  if (id) $("reportRun").value = id;
  $("reportContent").innerHTML = id ? reportHtml(await api(`/journeys/${state.journeyId}/runs/${id}/report`), true)
    : '<div class="empty">A ranked report appears after all seven steps of a run finish.</div>';
  if (!$("reportDialog").open) $("reportDialog").showModal();
}
async function openHistory() {
  const title = Object.fromEntries(state.papers.map((p) => [p.id, p.title]));
  $("historyList").innerHTML = state.runs.length ? state.runs.map((r) =>
    `<div class="historyRow"><div><h3>${esc(title[r.paper_id] || r.paper_id)}</h3><span class="hint">${esc(date(r.created))} · ${r.checkpoint}/7 steps${r.ingest_only ? " · extraction only" : ""}${r.error ? " · " + esc(r.error) : ""}</span></div>` +
    `<div class="actions">${pill(r.status, r.status === "complete" ? "good" : r.status === "failed" ? "bad" : "")}<button class="pixelButton small" data-open-trace="${esc(r.id)}">Trace</button>` +
    `${r.checkpoint >= 7 ? `<button class="pixelButton small" data-open-report="${esc(r.id)}">Report</button>` : ""}<button class="pixelButton small" data-before="${esc(r.id)}">Before and after</button></div></div>`).join("")
    : '<div class="empty">No runs yet. Use the message in a bottle to bring a paper in.</div>';
  if (!$("historyDialog").open) $("historyDialog").showModal();
  const [suggestions, queue] = await Promise.all([api(`/journeys/${state.journeyId}/suggestions`), api(`/journeys/${state.journeyId}/rechecks`)]);
  $("suggestionList").innerHTML = suggestions.length ? suggestions.map((p) => `<p><button class="pixelButton small" data-pick-paper="${esc(p.id)}">${esc(p.title)} →</button> <span class="hint">${esc(p.suggestion_reason)}</span></p>`).join("") : '<div class="empty">No suggestions yet: add more papers to the corpus.</div>';
  $("recheckList").innerHTML = queue.length ? queue.map((q) => `<p>${esc(q.edge_id.slice(0, 14))} · ${esc(q.status)} ${["queued", "failed"].includes(q.status) ? `<button class="pixelButton small" data-recheck="${esc(q.id)}">Retry the re-review within the run budget cap</button>` : esc((q.result || {}).reason || "")} ${esc(q.error || "")}</p>`).join("") : '<p class="hint">No pending feedback.</p>';
}
async function loadTrace(flash) {
  if (!state.journeyId) return;
  const params = new URLSearchParams();
  if (state.run) params.set("run_id", state.run.id);
  if ($("traceAgent").value) params.set("agent", $("traceAgent").value);
  if ($("traceStep").value) params.set("step", $("traceStep").value);
  const entries = await api(`/journeys/${state.journeyId}/trace?${params}`);
  const open = new Set([...$("traceList").querySelectorAll("details[open]")].map((el) => el.id));
  // Grouped by pipeline step; each entry expands to its full text and evidence.
  let last = -1;
  $("traceList").innerHTML = entries.length ? entries.map((t) => {
    const head = t.step !== last ? `<h3>${t.step + 1}. ${esc(state.status.stages[t.step] || "")}</h3>` : "";
    last = t.step;
    return head + `<details class="traceItem" id="trace-${esc(t.id)}" ${open.has("trace-" + t.id) ? "open" : ""}><summary><span class="time">${esc(new Date(t.time * 1000).toLocaleTimeString())}</span><strong>${esc(t.agent)}</strong><span>${esc(t.summary)}</span></summary><pre>${esc(JSON.stringify(t.data, null, 2))}</pre></details>`;
  }).join("") : '<div class="empty">Run activity appears here.</div>';
  if (flash) {
    const el = $("trace-" + flash);
    if (el) { el.open = true; el.classList.add("flash"); el.scrollIntoView({ block: "center" }); setTimeout(() => el.classList.remove("flash"), 1600); }
  }
}
async function openTrace(flash) {
  if (flash) { $("traceAgent").value = ""; $("traceStep").value = ""; }
  if (!$("traceDialog").open) $("traceDialog").showModal();
  await loadTrace(flash);
}
async function download(jid, rid, fmt) {
  const res = await fetch(`/api/journeys/${jid}/runs/${rid}/export/${fmt}`, { headers: state.token ? { Authorization: "Bearer " + state.token } : {} });
  if (!res.ok) throw Error("Export unavailable until the report is complete");
  saveBlob(await res.blob(), `metis-${rid}.${fmt}`);
}
function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob), a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* =========================== Settings, keys, costs =========================== */
const TABS = { mode: "Mode", groups: "Basis groups", keys: "API keys", models: "Models", costs: "Costs" };
const src = (entry, env) => entry.source === "env" ? `<span class="srcNote">set by the server environment (${esc(env)}); change it there</span>` : "";
async function openSettings(journeySettings, tab) {
  $("settingsTabs").hidden = !!journeySettings;
  if (journeySettings) {
    $("settingsTitle").textContent = "Journey settings";
    $("settingsContent").innerHTML = `<form id="journeySettingsForm"><div class="settingsGrid">${settingsGrid({ ...DEFAULTS, ...state.journey_settings })}</div><div class="actions"><button class="pixelButton primary">Save journey settings</button></div></form>`;
    on("journeySettingsForm", "submit", async (e) => {
      e.preventDefault();
      const saved = await api(`/journeys/${state.journeyId}/settings`, { method: "PUT", body: JSON.stringify(readSettings(e.target)) });
      state.journey_settings = saved.settings;
      $("settingsDialog").close();
    });
  } else {
    state.settingsTab = tab || state.settingsTab || "mode";
    $("settingsTitle").textContent = "Settings · " + TABS[state.settingsTab];
    document.querySelectorAll("#settingsTabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.stab === state.settingsTab));
    await ({ mode: renderMode, groups: renderGroups, keys: renderKeys, models: renderModels, costs: renderCosts })[state.settingsTab]();
  }
  if (!$("settingsDialog").open) $("settingsDialog").showModal();
  if (!$("setup").hidden && state.settings) { $("setupRoles").innerHTML = rolesSummary(state.settings); validateSetup(); }
}
const settingsBox = () => $("settingsContent");

/* ---- Mode: fixture or live, MongoDB, budget, restart ---- */
async function renderMode() {
  const [sv, s] = await Promise.all([api("/server"), api("/settings")]);
  state.settings = s;
  const saved = sv.saved, running = sv.running;
  const live = saved.mode.value === "live";
  const pinned = (k) => saved[k].source === "env";
  const rolesReady = Object.values(s.roster).filter((r) => r.ready).length, rolesTotal = Object.values(s.roster).length;
  const checks = [
    [saved.mongo_uri.value, "A MongoDB connection string is saved", "Enter a MongoDB connection string below (Atlas free tier works)"],
    [rolesReady === rolesTotal, `All ${rolesTotal} model roles have a key and a model`, `${rolesTotal - rolesReady} of ${rolesTotal} roles still need a key or a model (API keys and Models tabs)`],
    [saved.live_budget.value > 0, `Spending cap set: $${Number(saved.live_budget.value).toFixed(2)}`, "Set a spending cap above 0: live runs cost money"],
    [saved.allow_live.value, "Live calls are allowed", "Allow live calls below"],
  ];
  settingsBox().innerHTML =
    (sv.startup_error ? `<p class="warn">The saved settings could not start last time, so the server is in fixture mode: ${esc(sv.startup_error)}</p>` : "") +
    `<p class="hint">Running now: <strong>${esc(running.mode.value)}</strong> mode${running.mode.source === "fallback" ? " (fallback)" : ""}, storage ${esc(sv.store)}. Changes are saved to the server and take effect after a restart.</p>` +
    `<form id="modeForm"><div class="cards">` +
    `<label class="card modeChoice ${!live ? "selected" : ""}"><input type="radio" name="mode" value="fixture" ${!live ? "checked" : ""} ${pinned("mode") ? "disabled" : ""}><span><h3>Fixture mode</h3><p>Scripted agents, no keys, no cost. Everything works, but nothing it reports is a real discovery. Good for learning the map.</p></span></label>` +
    `<label class="card modeChoice ${live ? "selected" : ""}"><input type="radio" name="mode" value="live" ${live ? "checked" : ""} ${pinned("mode") ? "disabled" : ""}><span><h3>Live mode</h3><p>Real models explore real papers, with results stored in MongoDB. Every call is charged against the caps you set.</p></span></label></div>` +
    src(saved.mode, "METIS_MODE") +
    `<fieldset><legend>MongoDB</legend><label>Connection string ${saved.mongo_uri.value ? '<span class="ok">✓ saved</span>' : '<span class="warn">⚠ none saved</span>'}<input type="password" name="mongo_uri" autocomplete="off" placeholder="${saved.mongo_uri.value ? "Leave blank to keep the saved one" : "mongodb+srv://user:password@cluster.example.net/"}" ${pinned("mongo_uri") ? "disabled" : ""}></label>${src(saved.mongo_uri, "MONGODB_URI")}` +
    `<label>Database name<input name="mongo_db" value="${esc(saved.mongo_db.value)}" ${pinned("mongo_db") ? "disabled" : ""}></label>${src(saved.mongo_db, "MONGODB_DATABASE")}` +
    `<div class="actions"><button type="button" id="testMongo" class="pixelButton small">Test connection</button><span id="mongoResult" class="hint" role="status"></span>${saved.mongo_uri.value && !pinned("mongo_uri") ? '<button type="button" id="forgetMongo" class="pixelButton small quiet">Forget the saved string</button>' : ""}</div>` +
    `<p class="hint">A free Atlas cluster is enough to start. Add your computer's IP to the cluster's network access list, and copy the connection string from Atlas › Connect › Drivers. It is stored in a private server file and never shown again.</p></fieldset>` +
    `<fieldset><legend>Spending</legend><label>Spending cap for this server, in USD<input name="live_budget" type="number" min="0" max="100000" step="0.5" value="${esc(saved.live_budget.value)}" ${pinned("live_budget") ? "disabled" : ""}></label>${src(saved.live_budget, "METIS_LIVE_BUDGET_USD")}` +
    `<label class="check"><input type="checkbox" name="allow_live" ${saved.allow_live.value ? "checked" : ""} ${pinned("allow_live") ? "disabled" : ""}> Allow live calls to model providers</label>${src(saved.allow_live, "METIS_ALLOW_LIVE")}` +
    `<p class="hint">Every call reserves its maximum charge against this cap, the journey's cap and the run's cap before it is made; a cap that would be exceeded pauses the run. This is the app's own accounting, not a provider-side limit.</p></fieldset>` +
    `<h3>Ready for live mode?</h3><ul class="stepList">${checks.map(([ok, yes, no]) => `<li><span class="mark ${ok ? "ok" : "warn"}">${ok ? "✓" : "⚠"}</span><span>${esc(ok ? yes : no)}</span></li>`).join("")}</ul>` +
    `<div class="actions"><button class="pixelButton primary">Save</button><span id="modeSaved" class="hint" role="status"></span></div></form>` +
    `<div id="restartBox">${restartHtml(sv)}</div>`;
  settingsBox().querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", () => settingsBox().querySelectorAll(".modeChoice").forEach((c) => c.classList.toggle("selected", c.querySelector("input").checked))));
  on("modeForm", "submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target), body = {};
    if (!pinned("mode")) body.mode = f.get("mode");
    if (!pinned("mongo_db")) body.mongo_db = f.get("mongo_db");
    if (!pinned("live_budget")) body.live_budget = Number(f.get("live_budget"));
    if (!pinned("allow_live")) body.allow_live = f.get("allow_live") === "on";
    if (f.get("mongo_uri")) body.mongo_uri = f.get("mongo_uri");
    const result = await api("/server", { method: "PUT", body: JSON.stringify(body) });
    await renderMode();
    $("modeSaved").textContent = result.restart_required.length ? "Saved. Restart to apply." : "Saved; nothing to restart.";
  });
  on("testMongo", "click", async () => {
    $("mongoResult").textContent = "testing…";
    const uri = settingsBox().querySelector('input[name="mongo_uri"]').value;
    const r = await api("/server/test-mongo", { method: "POST", body: JSON.stringify(uri ? { mongo_uri: uri } : {}) });
    $("mongoResult").textContent = (r.ok ? "✓ " : "⚠ ") + r.detail;
    $("mongoResult").className = r.ok ? "ok" : "warn";
  });
  if ($("forgetMongo")) on("forgetMongo", "click", async () => { await api("/server", { method: "PUT", body: JSON.stringify({ mongo_uri: null, mode: "fixture" }) }); await renderMode(); });
  if ($("restartNow")) on("restartNow", "click", restartServer);
}
function restartHtml(sv) {
  if (!sv.restart_required.length) return "";
  return `<div class="card"><h3>Restart to apply</h3><p>Changed: ${esc(sv.restart_required.join(", "))}. The new settings take effect when the server restarts.</p>` +
    (sv.supervised ? '<div class="actions"><button id="restartNow" class="pixelButton primary">Restart now</button><span class="hint">Takes a few seconds; the page reloads by itself.</span></div>'
      : '<p class="warn">This server was started without its supervisor, so it cannot restart itself. Stop it (Ctrl+C in its window) and start it again with run.bat / run.sh or <code>python -m metis</code>; the saved settings apply then.</p>') + "</div>";
}
async function restartServer() {
  const r = await api("/server/restart", { method: "POST" });
  if (!r.restarting) { $("restartBox").innerHTML = `<p class="warn">${esc(r.detail)}</p>`; return; }
  document.querySelectorAll("dialog[open]").forEach((d) => d.close());
  $("restartOverlay").hidden = false;
  const started = Date.now();
  await wait(1500);
  while (Date.now() - started < 60000) {
    try {
      const st = await api("/status");
      $("restartText").textContent = st.startup_error ? "The saved settings could not start: " + st.startup_error + " — running in fixture mode." : "Back up in " + st.mode + " mode.";
      await wait(st.startup_error ? 4000 : 600);
      location.reload();
      return;
    } catch { await wait(700); }
  }
  $("restartText").textContent = "The server has not come back yet. Check its window, then reload this page.";
}

/* ---- Basis groups: install from mathlib inside the app ---- */
function installHtml(st) {
  const job = st.job, running = st.running;
  const tool = (key) => { const t = st.tools[key]; return `<li><span class="mark ${t.found ? "ok" : "warn"}">${t.found ? "✓" : "⚠"}</span><span><strong>${esc(t.label)}</strong> ${t.found ? `<span class="hint">${esc(t.path)}${t.managed ? " (installed by Metis)" : ""}</span>` : `<span class="warn">not found.</span> <span class="hint">${esc(t.hint)}</span>${t.auto && !running ? ` <button class="pixelButton small" data-install-tool="${key}">Install here</button>` : ""}`}</span></li>`; };
  const steps = st.steps;
  const total = st.groups.total, ready = st.groups.ready;
  const stepIcon = (x) => ({ done: "✓", skipped: "✓", running: "…", failed: "✗", cancelled: "–" })[x.status] || "·";
  return `<div class="cards"><div class="card"><h3>Tools</h3><ul class="stepList">${tool("git")}${tool("lake")}</ul><p class="hint">Both run only on this computer; nothing is installed outside the project folder.</p></div>` +
    `<div class="card"><h3>On this computer</h3><ul class="stepList">` +
    `<li><span class="mark ${steps.mathlib ? "ok" : ""}">${steps.mathlib ? "✓" : "·"}</span><span>Pinned mathlib ${esc(st.mathlib.slice(0, 8))} with its compiled cache</span></li>` +
    `<li><span class="mark ${steps.export ? "ok" : ""}">${steps.export ? "✓" : "·"}</span><span>Declaration export${steps.export ? ` (${Number(steps.export_declarations).toLocaleString()} declarations)` : ""}</span></li>` +
    `<li><span class="mark ${steps.msc ? "ok" : ""}">${steps.msc ? "✓" : "·"}</span><span>MSC 2020 table</span></li>` +
    `<li><span class="mark ${steps.index ? "ok" : ""}">${steps.index ? "✓" : "·"}</span><span>Basis-group index${steps.index ? ` (${steps.index_groups} groups)` : ""}</span></li>` +
    `<li><span class="mark ${total && ready === total ? "ok" : ""}">${total && ready === total ? "✓" : "·"}</span><span>Groups ready: ${total ? `${ready} of ${total}${st.groups.built < ready ? ` (${st.groups.built} built from mathlib, the rest from the reviewed corpus)` : ""}` : "none from mathlib yet"}</span></li></ul>` +
    `<p class="hint">${st.disk_free_gb} GB free on this drive. Needs about ${st.estimate.disk_gb} GB of disk and ${st.estimate.memory_gb} GB of memory; downloads about ${st.estimate.download_gb} GB the first time; ${esc(st.estimate.minutes)}.</p></div></div>` +
    (running ? `<div class="card"><h3>Installing… ${job.percent}%</h3><div class="progressBar"><i id="installBar"></i></div><ul class="stepList">${job.steps.map((x) => `<li><span class="mark">${stepIcon(x)}</span><span>${esc(x.name)} <span class="detail">${esc(x.detail || "")}</span></span></li>`).join("")}</ul><div class="logBox" id="installLog">${esc(job.log.map((l) => l.text).join("\n"))}</div><div class="actions"><button class="pixelButton small quiet" id="installCancel">Cancel</button><span class="hint">You can close this window; the installation continues on the server.</span></div></div>`
      : `<div class="actions"><button class="pixelButton primary" id="installAll" ${st.tools.git.found && st.tools.lake.found ? "" : "disabled"}>${total && ready === total ? "Check again and rebuild what is missing" : "Install all basis groups"}</button><label class="check"><input type="checkbox" id="installPrebuild" checked> build every group now (otherwise each is built the first time a journey uses it)</label></div>` +
        `<div class="card" id="installConfirm" hidden><h3>Ready to install?</h3><p>${steps.mathlib ? "mathlib is already on this computer, so this only runs the steps still missing above" : `This downloads about ${st.estimate.download_gb} GB (mathlib and its compiled cache) into the project's <code>.lean</code> folder and takes ${esc(st.estimate.minutes)}`}. It uses no model and no key, and you can cancel at any point; finished steps are kept.</p><div class="actions"><button class="pixelButton primary" id="installGo">Start installing</button><button class="pixelButton small quiet" id="installNo">Not now</button></div></div>` +
        (!(st.tools.git.found && st.tools.lake.found) ? '<p class="hint">Install the missing tools above first; the button enables itself when both are found.</p>' : "") +
        (job && job.status !== "running" ? `<details ${job.status === "failed" ? "open" : ""}><summary>Last installation: ${esc(job.status)}${job.error ? " — " + esc(job.error) : ""}</summary><ul class="stepList">${job.steps.map((x) => `<li><span class="mark">${stepIcon(x)}</span><span>${esc(x.name)} <span class="detail">${esc(x.detail || "")}</span></span></li>`).join("")}</ul><div class="logBox">${esc((job.log || []).map((l) => l.text).join("\n"))}</div></details>` : ""));
}
async function renderGroups(force) {
  const st = await api("/install");
  const sig = JSON.stringify(st);
  const open = () => $("settingsDialog").open && state.settingsTab === "groups";
  clearTimeout(state.installTimer);
  if (!force && !st.running && sig === state.installSig && $("installAll")) {
    // Nothing changed: leave the confirm card and focus alone, just look again later.
    if (open()) state.installTimer = setTimeout(() => renderGroups().catch(error), 5000);
    return;
  }
  state.installSig = sig;
  settingsBox().innerHTML = `<p class="hint">Basis groups are the islands a journey can sail between: one per MSC 2020 field that holds mathlib declarations, 42 at the pinned mathlib. This downloads mathlib and builds them here; no model or key is involved.</p>` + installHtml(st);
  if ($("installBar")) { $("installBar").style.width = st.job.percent + "%"; $("installLog").scrollTop = $("installLog").scrollHeight; }
  if ($("installAll")) {
    on("installAll", "click", () => { $("installConfirm").hidden = false; $("installGo").focus(); });
    on("installNo", "click", () => { $("installConfirm").hidden = true; });
    on("installGo", "click", async () => {
      await api("/install", { method: "POST", body: JSON.stringify({ prebuild: $("installPrebuild").checked }) });
      await renderGroups(true);
    });
  }
  if ($("installCancel")) on("installCancel", "click", async () => { await api("/install/cancel", { method: "POST" }); await renderGroups(true); });
  settingsBox().querySelectorAll("[data-install-tool]").forEach((b) => b.addEventListener("click", () => api("/install/tools", { method: "POST", body: JSON.stringify({ tool: b.dataset.installTool }) }).then(() => renderGroups(true)).catch(error)));
  if (open()) state.installTimer = setTimeout(() => renderGroups().catch(error), st.running ? 2000 : 5000);
  if (!st.running && state.installWasRunning) { state.installWasRunning = false; if (!$("titleScreen").hidden) loadHarbour().catch(() => {}); }
  state.installWasRunning = st.running;
}

/* ---- Keys, models, costs ---- */
async function renderKeys() {
  const s = await api("/settings");
  state.settings = s;
  settingsBox().innerHTML = `<p class="hint">${esc(s.credentials)}. ${s.keys_required ? "" : "Fixture mode needs no keys; what you enter here is used once the server runs in live mode."} Entered once and reused by every journey. Roles that share a provider share one key.</p>` +
    Object.entries(s.keys).map(([env, k]) => `<form class="keyRow" data-key-form="${esc(env)}"><strong>${esc(k.label)}</strong>` +
      `<span>${k.set ? `<span class="ok">✓ •••••••••••• (${k.source === "environment" ? "from the server environment" : "stored"})</span>` : '<span class="warn">⚠ missing</span>'}${k.test ? ` <span class="hint">last test ${k.test.ok ? "passed" : "failed: " + esc(k.test.detail)}</span>` : ""}` +
      `<input type="password" name="value" autocomplete="off" placeholder="${k.set ? "Replace key" : "Paste key"}" aria-label="${esc(k.label)} API key"></span>` +
      `<span class="actions"><button class="pixelButton small">Save</button>${k.source === "stored" ? `<button type="button" class="pixelButton small quiet" data-remove-key="${esc(env)}">Remove</button>` : ""}</span></form>`).join("");
  settingsBox().querySelectorAll("[data-key-form]").forEach((form) => form.addEventListener("submit", (e) => {
    e.preventDefault();
    const value = new FormData(form).get("value");
    if (!value) return;
    api("/settings/keys", { method: "PUT", body: JSON.stringify({ [form.dataset.keyForm]: value }) }).then(renderKeys).catch(error);
  }));
}
async function renderModels() {
  const s = await api("/settings");
  state.settings = s;
  settingsBox().innerHTML = `<p class="hint">Defaults come from the design doc's model roster. An ID marked unverified was not confirmed against the provider's documentation: check it with Test (live mode only).</p>` +
    `<form id="rolesForm">${Object.entries(s.roster).map(([role, r]) => `<div class="roleRow"><span class="mark ${r.ready ? "ok" : "warn"}">${r.ready ? "✓" : "⚠"}</span><span>${esc(r.label)}</span>` +
      `<input name="${esc(role)}" value="${esc(r.model || r.default_model || "")}" placeholder="${esc(r.default_model_name)} — enter its API model ID" aria-label="Model for ${esc(r.label)}" list="models-${esc(r.provider)}">` +
      `<span><button type="button" class="pixelButton small" data-test-role="${esc(role)}">Test</button> <span class="hint" id="test-${esc(role)}">${esc(r.key_label)}${r.model ? "" : r.default_model ? (r.default_verified ? " · default" : " · default, unverified") : " · no known ID"}</span></span></div>`).join("")}` +
    [...new Set(Object.values(s.roster).map((r) => r.provider))].map((p) => `<datalist id="models-${esc(p)}">${[...new Set(Object.values(s.roster).filter((r) => r.provider === p && r.default_model).map((r) => r.default_model))].map((m) => `<option value="${esc(m)}">`).join("")}</datalist>`).join("") +
    `<div class="actions"><button class="pixelButton primary">Save models</button></div></form>` +
    `<details><summary>Advanced: prices and limits per role (JSON)</summary><p class="hint">Live calls need a positive max_cost_usd and known input and output prices per role.</p><form id="providersForm"><textarea name="roles" rows="12" aria-label="Role configuration JSON">${esc(JSON.stringify(s.roles, null, 2))}</textarea><button class="pixelButton small">Save role configuration</button></form></details>`;
  on("rolesForm", "submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target), roles = {};
    Object.entries(s.roster).forEach(([role, r]) => {
      const model = String(f.get(role) || "").trim();
      if (model) roles[role] = { provider: r.provider, key_env: r.key_env, max_cost_usd: 0, max_output_tokens: 4096, ...(s.roles[role] || {}), model };
    });
    await api("/settings/providers", { method: "PUT", body: JSON.stringify(roles) });
    await renderModels();
  });
  on("providersForm", "submit", async (e) => {
    e.preventDefault();
    await api("/settings/providers", { method: "PUT", body: JSON.stringify(JSON.parse(new FormData(e.target).get("roles"))) });
    await renderModels();
  });
}
async function renderCosts() {
  const [s, c] = await Promise.all([api("/settings"), api("/costs" + (state.journeyId ? "?journey_id=" + state.journeyId : ""))]);
  const perRun = {};
  c.calls.forEach((x) => (perRun[x.run_id] = (perRun[x.run_id] || 0) + x.max_cost_usd));
  settingsBox().innerHTML = `<div class="settingsGrid"><div><span class="hint">${state.journeyId ? "This journey" : "All journeys"}, conservative charges</span><div class="metric">$${c.total_usd.toFixed(4)}</div></div><div><span class="hint">Server spending cap</span><div class="metric">$${s.global_budget_usd.toFixed(2)}</div></div></div>` +
    `<p class="hint">${esc(c.accounting)} Live calls enabled: ${s.live_enabled}. The journey's budget cap pauses a run before it is exceeded.</p>` +
    (Object.keys(perRun).length ? `<h3>Per run</h3>${Object.entries(perRun).map(([rid, v]) => `<p class="hint">${esc(rid)} — $${v.toFixed(4)}</p>`).join("")}` : '<div class="empty">No charges yet.</div>') +
    `<details><summary>Usage ledger</summary><pre>${esc(JSON.stringify(c, null, 2))}</pre></details>`;
}

/* ---- Harbour board on the title screen ---- */
async function loadHarbour() {
  const o = await api("/overview");
  const board = (cls, text, button, tab) => `<div class="board ${cls}"><span>${text}</span>${button ? `<button class="pixelButton small" data-open-settings="${tab}">${esc(button)}</button>` : ""}</div>`;
  $("harbour").innerHTML =
    (o.startup_error ? board("warnBoard", `<strong>Fixture mode (fallback)</strong> — the saved live settings could not start`, "See why", "mode") : "") +
    board("", `<strong>Basis groups</strong> ${o.groups_ready} of ${o.groups_total} ready${o.install_running ? " · installing…" : ""}`, o.install_running ? "Watch progress" : o.export_present ? "Manage" : "Install all 42", "groups") +
    board("", `<strong>Mode</strong> ${o.mode === "live" ? "live — real models" : "fixture — scripted, free"}`, o.mode === "live" ? "Settings" : "Switch to live", "mode") +
    board("", `<strong>API keys</strong> ${o.keys_set} of ${o.keys_total}`, o.keys_set < o.keys_total ? "Enter keys" : "Manage", "keys");
}
async function updateCosts() {
  const c = await api("/costs?journey_id=" + state.journeyId);
  const run = state.run ? c.calls.filter((x) => x.run_id === state.run.id).reduce((s, x) => s + x.max_cost_usd, 0) : 0;
  $("costCounter").textContent = `$${run.toFixed(4)} run · $${c.total_usd.toFixed(4)} journey`;
}

/* =========================== Runs: refresh, controls, live events =========================== */
async function refresh() {
  if (!state.journeyId) return;
  const id = state.journeyId;
  const [runs, papers, j] = await Promise.all([api(`/journeys/${id}/runs`), api(`/journeys/${id}/papers`), api(`/journeys/${id}`)]);
  if (state.journeyId !== id) return;
  state.runs = runs; state.papers = papers; state.journey_settings = j.settings;
  const selected = $("paperSelect").value;
  $("paperSelect").innerHTML = papers.map((p) => `<option value="${esc(p.id)}">${esc(p.title)} [MSC ${esc(p.msc)}]</option>`).join("");
  if (papers.some((p) => p.id === selected)) $("paperSelect").value = selected;
  const old = state.run;
  state.run = state.run ? runs.find((r) => r.id === state.run.id) || runs[0] : runs[0];
  const run = state.run;
  // New paper characters appear and new boats set sail as each step of the run finishes.
  const sig = runs.map((r) => r.id + r.status + r.checkpoint).join("|") + "#" + papers.length;
  if (sig !== state.mapSig) { const first = !state.mapSig; state.mapSig = sig; if (!first && !state.before) await loadMap(true); }
  const active = runs.some((r) => ["queued", "running", "paused"].includes(r.status));
  $("guide").hidden = !!(runs.length || localStorage.getItem("metisGuideDismissed")) || !$("details").hidden;
  $("runStatus").textContent = run ? run.status + (run.status === "running" || run.status === "queued" ? ` · step ${Math.min(7, run.checkpoint + 1)}/7` : "") : "No run yet";
  $("runStatus").className = "pill " + (run && run.status === "complete" ? "good" : run && run.status === "failed" ? "bad" : run && ["running", "queued"].includes(run.status) ? "gold" : "");
  $("runStatus").title = (run && run.error) || "";
  $("startRun").disabled = $("extractOnly").disabled = !papers.length || active;
  document.querySelectorAll("[data-control]").forEach((b) => {
    const a = b.dataset.control;
    b.disabled = !run || (a === "pause" ? !["queued", "running"].includes(run.status) : ["retry", "resume"].includes(a) ? !["failed", "paused"].includes(run.status) : ["complete", "cancelled"].includes(run.status));
  });
  $("stageList").innerHTML = state.status.stages.map((s, i) => `<div class="stage ${run && i < run.checkpoint ? "done" : run && i === run.checkpoint && run.status !== "complete" ? "current" : ""}">${i + 1}. ${esc(s)}</div>`).join("");
  const rsel = $("graphRun").value, title = Object.fromEntries(papers.map((p) => [p.id, p.title]));
  $("graphRun").innerHTML = '<option value="">All runs</option>' + runs.map((r) => `<option value="${esc(r.id)}">${esc(title[r.paper_id] || "paper")} · ${esc(date(r.created))}</option>`).join("");
  $("graphRun").value = rsel;
  if (run && run.status === "complete" && old && old.id === run.id && old.status !== "complete") {
    // A notification when a long run finishes.
    if ("Notification" in window && Notification.permission === "granted") new Notification("Metis: the run has finished", { body: journeyName(state.journey) });
    $("resumeBanner").hidden = true;
  }
  if (!runs.some((r) => ["paused", "failed"].includes(r.status))) $("resumeBanner").hidden = true;
  await Promise.all([pollDiscussion(), updateCosts()]);
  if ($("traceDialog").open) await loadTrace();
}
async function connectEvents(id) {
  const controller = new AbortController();
  state.stream = controller;
  try {
    const res = await fetch(`/api/journeys/${id}/events?after=${Date.now() / 1000}`, { headers: state.token ? { Authorization: "Bearer " + state.token } : {}, signal: controller.signal });
    if (!res.ok) return;
    const reader = res.body.getReader();
    let text = "", pending = null;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      text += new TextDecoder().decode(value);
      let p;
      while ((p = text.indexOf("\n\n")) >= 0) {
        const chunk = text.slice(0, p);
        text = text.slice(p + 2);
        if (chunk.includes("event: update") && !pending) pending = setTimeout(() => { pending = null; refresh().catch(error); }, 200);
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") console.info("Live stream unavailable; polling durable state remains active");
  }
}
async function startRun(ingestOnly) {
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
  state.run = await api(`/journeys/${state.journeyId}/runs`, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ paper_id: $("paperSelect").value, budget_usd: Number($("runBudget").value), ingest_only: !!ingestOnly }) });
  $("resumeBanner").hidden = true;
  await refresh();
}
async function control(action) {
  if (!state.run) return;
  state.run = await api(`/journeys/${state.journeyId}/runs/${state.run.id}/${action}`, { method: "POST", body: JSON.stringify({ budget_usd: Number($("runBudget").value) }) });
  await refresh();
}
async function compare(runId, showing) {
  state.before = runId ? { runId, showing } : null;
  $("beforeBar").hidden = !runId;
  if (runId) {
    const r = state.runs.find((x) => x.id === runId), title = (state.papers.find((p) => p.id === (r || {}).paper_id) || {}).title || "the run";
    $("beforeLabel").textContent = `Showing the map ${showing} the run on “${title}” (${r ? date(r.created) : ""}).`;
    $("beforeToggle").textContent = showing === "before" ? "Show after" : "Show before";
    $("graphRun").value = showing === "after" ? runId : "";
  }
  await loadMap(true);
}

/* =========================== Legend =========================== */
function buildLegend() {
  const row = (canvas, text) => { const d = document.createElement("div"); d.className = "legendRow"; if (canvas) d.appendChild(canvas); d.insertAdjacentHTML("beforeend", `<span>${text}</span>`); return d; };
  const scaled = (sprite, k = 2) => { const c = document.createElement("canvas"); paint(c, sprite); c.style.width = sprite.width * k + "px"; c.style.height = sprite.height * k + "px"; return c; };
  const swatch = (color, cls = "swatch") => { const s = document.createElement("span"); s.className = cls; if (color) s.style.background = color; return s; };
  const body = $("legendBody");
  body.append(
    row(swatch("#6fae4a"), "Island = a basis group; its area scales with its node count. Basis nodes are not drawn."),
    row(swatch("#3f9470"), "Grass colours = subgroups (subfields, subtopics)"),
    row(swatch("#c6dc7a"), "Flowered meadow with a dotted border = a paper's own patch"),
    row(scaled(Pixel.ITEMS[0].canvas), "Odyssey items and creatures = paper concepts (dashed amber outline: unintegrated; faded: proposed, quarantined)"),
    row(scaled(Pixel.walkers.verified[0], 3), "Walkers = a link on one island, walking premise → conclusion. Tunic: white verified, blue cited, brown intuitive"),
    row(scaled(Pixel.FIRE[0], 3), "Campfire = a hyperedge: every premise's walker meets here, then one walks on"),
    row(scaled(Pixel.boats.verified.fresh.right), "Trireme = verified link between islands"),
    row(scaled(Pixel.boats.cited.fresh.right), "Merchant ship = cited link"),
    row(scaled(Pixel.boats.intuitive.fresh.right), "Raft = intuitive link"),
    row(scaled(Pixel.boats.cited.old.right), "Bright sail = added in the latest run; weathered, patched sail = earlier run or base graph"),
    row(scaled(Pixel.boats.intuitive.old.right), "A small fleet on one lane = all the base-graph links between two islands (hover for the count, click to list them); each paper or crew link has its own boat"),
    row(swatch("#ffe27a"), "Gold sparkles and gold paths = new in the latest run"),
  );
  body.insertAdjacentHTML("beforeend", "<h3>Simplified view (G)</h3>");
  body.append(
    row(swatch("#397c70", "dotSample"), "Established"), row(swatch("#b07a2a", "dotSample"), "Accepted"), row(swatch("#2e7d4f", "dotSample"), "Proven (machine verified)"), row(swatch("#ffffff", "dotSample"), "Proposed (quarantined)"),
    row(swatch("", "lineSample"), "Solid line = verified"), row(swatch("", "lineSample cited"), "Dashed = cited"), row(swatch("", "lineSample intuitive"), "Dotted = intuitive"),
    row(null, "Lines converging on a junction dot = a hyperedge. Squares are paper concepts, dashed amber outline is unintegrated, gold is new in the latest run."),
  );
}

/* =========================== Wiring =========================== */
document.addEventListener("click", (e) => {
  if (skipTransition && e.target.closest("#transition")) { skipTransition(); return; }
  const el = e.target.closest("button,[data-show]");
  if (!el) return;
  const d = el.dataset;
  Promise.resolve((async () => {
    if (d.close) $(d.close).close();
    if (d.hide) $(d.hide).hidden = true;
    if (d.stab) await openSettings(false, d.stab);
    if (d.openSettings) await openSettings(false, d.openSettings);
    if (d.openSetup) await openSetup();
    if (d.row) {
      // Click a journey, then choose Open journey or Open review document.
      const scroll = el.closest(".scroll"), choices = $("choices-" + d.row), opening = choices.hidden;
      scroll.querySelectorAll(".rowChoices").forEach((c) => (c.hidden = true));
      scroll.querySelectorAll(".journeyRow.chosen").forEach((c) => c.classList.remove("chosen"));
      choices.hidden = !opening;
      el.classList.toggle("chosen", opening);
      scroll.classList.toggle("busy", opening);
      if (opening) choices.querySelector("button").focus();
    }
    if (d.openJourney) {
      const focus = d.focusId ? { kind: d.focusKind, id: d.focusId } : null;
      await transition({ from: el.closest(".scroll"), load: () => openJourney(d.openJourney, focus) });
    }
    if (d.openReview) {
      const j = state.journeys.find((x) => x.id === d.openReview);
      let focus = null;
      await transition({ from: el.closest(".scroll"), hold: async (box) => { focus = await reviewHold(box, j); }, load: () => openJourney(j.id, focus) });
    }
    if (d.panel) {
      if (d.panel === "bottle") { $("bottle").hidden = !$("bottle").hidden; $("routePanel").hidden = true; }
      if (d.panel === "route") { $("routePanel").hidden = !$("routePanel").hidden; $("bottle").hidden = true; }
      if (d.panel === "report") await openReport();
      if (d.panel === "history") await openHistory();
      if (d.panel === "trace") await openTrace();
      if (d.panel === "log") { renderLog(); $("logDialog").showModal(); }
    }
    if (d.show && !el.closest("#holdContent")) {
      document.querySelectorAll("dialog[open]").forEach((x) => x.close());
      select({ kind: d.kind, id: d.show }, true);
    }
    if (d.control) await control(d.control);
    if (d.export) await download(state.journeyId, $("reportRun").value, d.export);
    if (d.feedback) {
      await api(`/journeys/${state.journeyId}/feedback`, { method: "POST", body: JSON.stringify({ target_id: d.feedback, mark: d.mark }) });
      el.textContent = d.mark === "wrong" ? "Sent back to Penelope" : "Marked interesting";
      el.disabled = true;
    }
    if (d.openTrace) { state.run = state.runs.find((r) => r.id === d.openTrace); $("historyDialog").close(); await refresh(); await openTrace(); }
    if (d.openReport) { $("historyDialog").close(); await openReport(d.openReport); }
    if (d.before) { $("historyDialog").close(); await compare(d.before, "before"); }
    if (d.pickPaper) { $("historyDialog").close(); $("bottle").hidden = false; $("routePanel").hidden = true; $("paperSelect").value = d.pickPaper; }
    if (d.recheck) { await api(`/journeys/${state.journeyId}/rechecks/${d.recheck}`, { method: "POST", body: JSON.stringify({ budget_usd: Number($("runBudget").value) }) }); await openHistory(); }
    if (d.pick) { state.pick = state.pick === d.pick ? null : d.pick; renderRouteEnds(); }
    if (d.routeSet) setRouteEnd(d.routeSet, d.id);
    if (d.traceEntry) { $("logDialog").close(); await openTrace(d.traceEntry); }
    if (d.removeKey) { await api("/settings/keys", { method: "PUT", body: JSON.stringify({ [d.removeKey]: null }) }); await openSettings(false); }
    if (d.testRole) {
      $("test-" + d.testRole).textContent = "testing…";
      const r = await api("/settings/keys/test", { method: "POST", body: JSON.stringify({ role: d.testRole }) });
      $("test-" + d.testRole).textContent = (r.ok ? "✓ " : "⚠ ") + r.detail;
      $("test-" + d.testRole).className = r.ok ? "ok" : "warn";
    }
  })()).catch(error);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (skipTransition) { skipTransition(); return; }
    if (!$("setup").hidden) { $("setup").hidden = true; $("scrollNew").focus(); return; }
    if (state.pick) { state.pick = null; renderRouteEnds(); return; }
  }
  if ($("mapScreen").hidden || typing(e) || document.querySelector("dialog[open]") || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "g" || e.key === "G") setView(state.view === "sea" ? "simple" : "sea");
  if (e.key === "+" || e.key === "=") $("zoomIn").click();
  if (e.key === "-") $("zoomOut").click();
  if (e.key === "0") $("fitAll").click();
  const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
  if (step && state.view === "sea") { e.preventDefault(); const c = seaMap.camera(); seaMap.setCamera({ zoom: c.zoom, x: c.x + (step[0] * 80) / c.zoom, y: c.y + (step[1] * 80) / c.zoom }); }
});
function wire() {
  wireScrolls();
  on("journeyForm", "submit", setSail);
  $("journeyForm").addEventListener("change", validateSetup);
  $("fieldFilter").addEventListener("input", filterFields);
  $("groupFilter").addEventListener("input", fillPaperGroups);
  on("setupBack", "click", () => { $("setup").hidden = true; });
  on("setupSettings", "click", () => openSettings(false));
  on("titleSettings", "click", () => openSettings(false));
  on("settingsButton", "click", () => openSettings(false));
  on("costCounter", "click", () => openSettings(false, "costs"));
  on("guideClose", "click", () => { localStorage.setItem("metisGuideDismissed", "1"); $("guide").hidden = true; });
  $("error").addEventListener("click", () => ($("error").hidden = true));
  $("settingsDialog").addEventListener("close", () => clearTimeout(state.installTimer));
  on("journeySettings", "click", () => openSettings(true));
  on("returnTitle", "click", showTitle); // everything is already saved on the server
  on("authButton", "click", () => {
    const token = prompt("API bearer token for this browser session (leave empty for local development)", state.token);
    if (token !== null) { state.token = token; sessionStorage.setItem("metisToken", token); location.reload(); }
  });
  on("viewToggle", "click", () => setView(state.view === "sea" ? "simple" : "sea"));
  on("zoomIn", "click", () => { if (state.view === "sea") seaMap.zoomIn(); else if (cy) { cy.zoom({ level: cy.zoom() * 1.5, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }); updateZoomLabel(); } });
  on("zoomOut", "click", () => { if (state.view === "sea") seaMap.zoomOut(); else if (cy) { cy.zoom({ level: cy.zoom() / 1.5, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }); updateZoomLabel(); } });
  on("fitAll", "click", () => { if (state.view === "sea") seaMap.fit(); else if (cy) { cy.fit(undefined, 30); updateZoomLabel(); } });
  ["graphTier", "graphExisting", "graphIsland", "graphRun", "graphNew", "graphRejected", "graphProposed"].forEach((id) => on(id, "change", applyFilters));
  on("applySearch", "click", search);
  $("graphSearch").addEventListener("keydown", (e) => { if (e.key === "Enter") search().catch(error); });
  on("beforeToggle", "click", () => compare(state.before.runId, state.before.showing === "before" ? "after" : "before"));
  on("beforeClose", "click", () => compare(null));
  on("resumeButton", "click", async () => { await control(state.run.status === "failed" ? "retry" : "resume"); $("resumeBanner").hidden = true; });
  on("resumeDismiss", "click", () => { $("resumeBanner").hidden = true; });
  on("startRun", "click", () => startRun(false));
  on("extractOnly", "click", () => startRun(true));
  on("traceAgent", "change", () => loadTrace());
  on("traceStep", "change", () => loadTrace());
  on("reportRun", "change", () => openReport($("reportRun").value));
  on("routeFind", "click", findRoute);
  on("routeClear", "click", () => { state.route = { start: null, end: null, result: null }; state.pick = null; $("routeResult").innerHTML = ""; $("routeExport").hidden = true; $("routePlay").disabled = true; seaMap.setRoute(null); markRoute(); renderRouteEnds(); });
  on("routePlay", "click", () => { if (state.view !== "sea") setView("sea"); seaMap.play(); });
  on("routeCopy", "click", async () => { await navigator.clipboard.writeText(state.route.result.text); $("routeCopy").textContent = "Copied"; setTimeout(() => ($("routeCopy").textContent = "Copy as text"), 1500); });
  on("routeSave", "click", () => saveBlob(new Blob([state.route.result.text], { type: "text/plain" }), "metis-route.txt"));
  let searchTimer = null;
  $("routeSearch").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => routeSearch().catch(error), 250); });
  on("speechNext", "click", nextLine);
  on("speechSkip", "click", () => { state.disc.queue = []; nextLine(); });
  on("speechMute", "click", () => { const d = state.disc; d.muted = !d.muted; $("speechMute").setAttribute("aria-pressed", d.muted); if (d.muted) { clearTimeout(d.timer); d.current = null; d.queue = []; $("discussion").hidden = true; } });
  on("speechTrace", "click", () => state.disc.current && openTrace(state.disc.current.trace_ids[0]));
  on("speechPan", "click", () => state.disc.current && state.disc.current.target && select(state.disc.current.target, true));
  $("discussion").addEventListener("click", (e) => { if (!e.target.closest("button,select,label")) nextLine(); }); // a click advances
  on("sourceKind", "change", () => {
    const kind = $("sourceKind").value;
    $("pdfLabel").hidden = kind !== "pdf";
    $("paperValueLabel").hidden = ["pdf", "fixture"].includes(kind);
  });
  on("paperForm", "submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.target), jid = state.journeyId;
    if (form.get("kind") === "pdf") {
      const upload = new FormData();
      ["title", "home_group"].forEach((k) => upload.append(k, form.get(k)));
      upload.append("file", form.get("file"));
      await api(`/journeys/${jid}/papers/pdf`, { method: "POST", body: upload });
    } else {
      await api(`/journeys/${jid}/papers`, { method: "POST", body: JSON.stringify({ title: form.get("title"), kind: form.get("kind"), value: form.get("value") || "", home_group: form.get("home_group") }) });
    }
    e.target.reset();
    $("sourceKind").value = state.status.fixture ? "fixture" : "pdf";
    $("sourceKind").dispatchEvent(new Event("change"));
    await refresh();
  });
  on("bulkForm", "submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const ids = form.get("ids").split(/[\s,]+/).filter(Boolean);
    const results = await api(`/journeys/${state.journeyId}/papers/bulk`, { method: "POST", body: JSON.stringify(form.get("mode") === "msc" ? { msc_category: form.get("ids").trim(), limit: 20 } : { arxiv_ids: ids, home_group: $("paperGroup").value }) });
    await refresh();
    $("bulkResult").textContent = `${results.filter((r) => r.paper).length} imported, ${results.filter((r) => r.error).length} failed. MSC mode searches the stored corpus only.`;
    if (results.some((r) => r.error)) throw Error(results.filter((r) => r.error).map((r) => r.error).join("; "));
  });
  on("correctPlacement", "click", async () => {
    if (!$("paperSelect").value) throw Error("Select a paper first");
    await api(`/journeys/${state.journeyId}/papers/${$("paperSelect").value}/placement`, { method: "PUT", body: JSON.stringify({ home_group: $("paperGroup").value }) });
    await refresh();
  });
  window.addEventListener("resize", () => { if (!$("mapScreen").hidden) { seaMap.resize(); if (cy) cy.resize(); } });
  window.addEventListener("hashchange", () => {
    const hash = location.hash.slice(1);
    if (!hash || hash === "home") { if (state.journeyId) showTitle().catch(error); }
    else if (hash !== state.journeyId) openJourney(hash).catch(error);
  });
}
async function init() {
  try {
    TitleScene.init($("titleCanvas"));
    const tip = $("tooltip");
    seaMap = SeaMap.create($("seaCanvas"), $("minimap"), {
      onHover(info, x, y) {
        tip.hidden = !info;
        if (info) { tip.textContent = (state.pick && info.kind === "concept" ? "Click to set the route " + state.pick + ": " : "") + info.name; tip.style.left = Math.min(x + 14, innerWidth - 330) + "px"; tip.style.top = y + 16 + "px"; }
      },
      onClick: mapClick,
      onCamera(cam, all) { $("minimap").hidden = all || state.view !== "sea"; updateZoomLabel(); }, // a small minimap while zoomed in
    });
    wire();
    buildLegend();
    state.status = await api("/status");
    $("mode").textContent = state.status.fixture ? "FIXTURE · LOCAL" : "LIVE · MONGODB";
    $("notice").textContent = state.status.notice;
    $("sourceKind").querySelector('[value="fixture"]').disabled = !state.status.fixture;
    $("sourceKind").value = state.status.fixture ? "fixture" : "pdf";
    $("sourceKind").dispatchEvent(new Event("change"));
    $("traceAgent").innerHTML = '<option value="">All agents</option>' + ["system", "decomposer", "Eurylochus", "Elpenor", "Polites", "Perimedes", "Penelope", "Hephaestus", "Tiresias", "Odysseus"].map((a) => `<option>${a}</option>`).join("");
    $("traceStep").innerHTML = '<option value="">All steps</option>' + state.status.stages.map((s, i) => `<option value="${i}">${i + 1}. ${esc(s)}</option>`).join("");
    const hash = location.hash.slice(1);
    if (hash && hash !== "home") await openJourney(hash);
    else await showTitle();
  } catch (e) {
    error(e);
    if ($("mapScreen").hidden) showTitle().catch(() => {});
  }
}
init();
