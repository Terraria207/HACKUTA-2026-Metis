"use strict";
const $ = (id) => document.getElementById(id),
  esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
const state = {
  journey: null,
  run: null,
  runs: [],
  papers: [],
  graph: null,
  status: null,
  tab: "run",
  token: sessionStorage.getItem("metisToken") || "",
  stream: null,
  poll: null,
};
async function api(path, options = {}) {
  const headers = {
    ...(options.body instanceof FormData
      ? {}
      : { "Content-Type": "application/json" }),
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
  setTimeout(() => ($("error").hidden = true), 12000);
}
function on(id, event, fn) {
  $(id).addEventListener(event, (e) => Promise.resolve(fn(e)).catch(error));
}
function date(t) {
  return new Date(t * 1000).toLocaleString();
}
function pill(s) {
  return `<span class="pill">${esc(s)}</span>`;
}
function showTab(tab) {
  state.tab = tab;
  document
    .querySelectorAll(".tab")
    .forEach((el) => (el.hidden = el.id !== tab + "Tab"));
  document
    .querySelectorAll("[data-tab]")
    .forEach((el) => el.classList.toggle("active", el.dataset.tab === tab));
  if (tab === "graph") loadGraph().catch(error);
  if (tab === "report") loadReport().catch(error);
  if (tab === "history") loadHistory().catch(error);
}
function goHome() {
  if (state.stream) state.stream.abort();
  clearInterval(state.poll);
  state.journey = null;
  $("workspace").hidden = true;
  $("home").hidden = false;
  location.hash = "home";
  home().catch(error);
}
async function openCatalog(adding) {
  const c = await api("/catalog");
  state.addingFields = adding;
  $("catalogTitle").textContent = adding ? "Add fields / modules" : "New journey";
  state.catalogModules = [...new Map(c.fields.flatMap(f => f.modules).map(m => [m.id, m])).values()];
  const pinned = new Set(adding ? state.journey.modules : []);
  $("fieldCatalog").innerHTML = '<legend>Available fields and explicit module versions</legend><p class="hint">Cross-field modules appear once under their first field. Select their exact prerequisites too.</p>' + c.fields.map(f =>
    `<section><h3>${esc(f.name)} — ${f.ready ? "ready" : "unavailable: import a reviewed module first"}</h3>${f.modules.filter(m => m.islands[0] === f.id).map(m =>
      `<label class="check"><input type="checkbox" name="module" value="${esc(m.id)}" ${!m.available || pinned.has(m.id) ? "disabled" : ""}>${esc(m.id)} ${pinned.has(m.id) ? "(pinned)" : ""} · ${m.fixture ? "FIXTURE" : "SOURCED"} · ${m.counts.concepts} nodes / ${m.counts.edges} relations</label><p class="hint">${esc(m.coverage)} · requires: ${esc((m.requires || []).join(", ") || "none")}</p><details><summary>Source metadata and coverage gaps</summary><pre>${esc(JSON.stringify({source: m.source, remaining_gaps: m.remaining_gaps || "Curated scope only; no exhaustive coverage claim"}, null, 2))}</pre></details>`).join("")}</section>`).join("");
  $("journeyForm").elements.name.required = !adding;
  $("journeyForm").elements.name.closest("label").hidden = adding;
  $("journeyForm").querySelector('button[type="submit"]').textContent = adding ? "Add selected modules (preserve existing pins)" : "Create journey";
  $("newDialog").showModal();
}
async function home() {
  const journeys = await api("/journeys");
  $("journeyCount").textContent = journeys.length + " explorations";
  $("journeyList").innerHTML = journeys.length
    ? journeys
        .map(
          (j) =>
            `<button class="card" data-journey="${esc(j.id)}"><div class="eyebrow">${esc(j.islands.join(" · "))}</div><h3>${esc(j.name)}</h3><div class="muted">${j.paper_count} papers · ${j.run_count} runs · ${esc(j.modules.length)} pinned modules</div><div class="cardFoot">${pill(j.status)}<span>Open journey ↗</span></div></button>`,
        )
        .join("")
    : '<div class="empty">Your first connection starts with a journey. Choose mathematical islands and add a paper to explore.</div>';
  const discoveries = await api("/discoveries");
  $("discoveries").innerHTML = discoveries.length
    ? discoveries
        .map(
          (d) =>
            `<div class="finding"><h3>${esc(d.edge.argument)}</h3>${pill(d.edge.tier)} <button data-journey="${esc(d.journey_id)}">${esc(d.journey_name)} ↗</button></div>`,
        )
        .join("")
    : '<div class="empty">No potentially new findings yet. Fixture mode never represents scripted associations as discoveries.</div>';
}
async function openJourney(id) {
  if (state.stream) state.stream.abort();
  clearInterval(state.poll);
  state.run = null;
  state.journey = await api("/journeys/" + id);
  $("home").hidden = true;
  $("workspace").hidden = false;
  location.hash = id;
  $("journeyTitle").textContent = state.journey.name;
  $("islandsLabel").textContent = state.journey.islands.join(" / ");
  $("journeyMeta").textContent = state.journey.modules.join(" · ");
  const g = await api(`/journeys/${id}/graph`);
  state.graph = g;
  $("paperGroup").innerHTML = g.groups
    .filter((g) => g.depth === 3)
    .map(
      (g) =>
        `<option value="${esc(g.id)}">${esc(g.msc)} — ${esc(g.name)}</option>`,
    )
    .join("");
  $("graphIsland").innerHTML =
    '<option value="">All islands</option>' +
    state.journey.islands.map((i) => `<option>${esc(i)}</option>`).join("");
  await refresh();
  showTab("run");
  connectEvents(id);
  state.poll = setInterval(() => refresh().catch(error), 3000);
}
async function refresh() {
  if (!state.journey) return;
  const id = state.journey.id;
  [state.runs, state.papers] = await Promise.all([
    api(`/journeys/${id}/runs`),
    api(`/journeys/${id}/papers`),
  ]);
  const selected = $("paperSelect").value;
  $("paperSelect").innerHTML = state.papers
    .map(
      (p) =>
        `<option value="${esc(p.id)}">${esc(p.title)} [${esc(p.msc)}]</option>`,
    )
    .join("");
  if (state.papers.some((p) => p.id === selected))
    $("paperSelect").value = selected;
  const old = state.run;
  state.run = state.run
    ? state.runs.find((r) => r.id === state.run.id) || state.runs[0]
    : state.runs[0];
  const run = state.run;
  $("addFields").disabled = state.runs.some(r => ["queued", "running", "paused"].includes(r.status));
  $("addFields").title = $("addFields").disabled ? "Finish or cancel the active run before changing modules" : "Preserve existing pins and add explicit compatible modules";
  $("runStatus").textContent = run ? run.status : "Ready";
  $("startRun").disabled =
    !state.papers.length ||
    state.runs.some((r) => ["queued", "running", "paused"].includes(r.status));
  document.querySelectorAll("[data-control]").forEach((b) => {
    const a = b.dataset.control;
    b.disabled =
      !run ||
      (["pause"].includes(a)
        ? !["queued", "running"].includes(run.status)
        : ["retry", "resume"].includes(a)
          ? !["failed", "paused"].includes(run.status)
          : ["complete", "cancelled"].includes(run.status));
  });
  $("stageList").innerHTML = state.status.stages
    .map(
      (s, i) =>
        `<div class="stage ${run && i < run.checkpoint ? "done" : run && i === run.checkpoint ? "current" : ""}"><i></i>${i + 1}. ${esc(s)}</div>`,
    )
    .join("");
  if (run && run.error) $("runStatus").title = run.error;
  const rsel = $("graphRun").value;
  $("graphRun").innerHTML =
    '<option value="">All runs</option>' +
    state.runs
      .map(
        (r) =>
          `<option value="${esc(r.id)}">${esc(date(r.created))} · ${esc(r.status)}</option>`,
      )
      .join("");
  $("graphRun").value = rsel;
  await loadTrace();
  if (run && run.status === "complete" && old?.status !== "complete") {
    if ("Notification" in window && Notification.permission === "granted")
      new Notification("Metis exploration complete", {
        body: state.journey.name,
      });
    if (state.tab === "report") await loadReport();
  }
  if (state.tab === "history") await loadHistory();
}
async function connectEvents(id) {
  const controller = new AbortController();
  state.stream = controller;
  try {
    const res = await fetch(
      `/api/journeys/${id}/events?after=${Date.now() / 1000}`,
      {
        headers: state.token ? { Authorization: "Bearer " + state.token } : {},
        signal: controller.signal,
      },
    );
    if (!res.ok) return;
    const reader = res.body.getReader();
    let text = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      text += new TextDecoder().decode(value);
      let p;
      while ((p = text.indexOf("\n\n")) >= 0) {
        const chunk = text.slice(0, p);
        text = text.slice(p + 2);
        if (chunk.includes("event: update")) await refresh();
      }
    }
  } catch (e) {
    if (e.name !== "AbortError")
      console.info(
        "Live stream unavailable; polling durable state remains active",
      );
  }
}
async function loadTrace() {
  if (!state.journey) return;
  const params = new URLSearchParams();
  if (state.run) params.set("run_id", state.run.id);
  if ($("traceAgent").value) params.set("agent", $("traceAgent").value);
  if ($("traceStep").value) params.set("step", $("traceStep").value);
  const entries = await api(`/journeys/${state.journey.id}/trace?${params}`);
  $("traceList").innerHTML = entries.length
    ? entries
        .map(
          (t) =>
            `<details class="traceItem"><summary><span class="time">${esc(new Date(t.time * 1000).toLocaleTimeString())}</span><strong>${esc(t.agent)}</strong><span>${esc(t.summary)}</span></summary><pre>${esc(JSON.stringify(t.data, null, 2))}</pre></details>`,
        )
        .join("")
    : '<div class="empty">Run activity will appear here. Summaries, arguments and evidence are public; hidden model reasoning is never requested.</div>';
}
async function loadReport() {
  if (!state.run || state.run.checkpoint < 7) {
    $("reportContent").innerHTML =
      '<div class="empty">A ranked report appears after all seven stages finish. Reopen any completed run in History.</div>';
    return;
  }
  const r = await api(
    `/journeys/${state.journey.id}/runs/${state.run.id}/report`,
  );
  $("reportContent").innerHTML =
    `<div class="panel"><div class="eyebrow">${r.fixture ? "FIXTURE SIMULATION — NOT DISCOVERY" : "AUDITABLE EXPLORATION"}</div><p>${esc(r.summary)}</p></div>` +
    [
      ["potentially_new", "Potentially new"],
      ["rediscoveries", "Rediscoveries"],
      ["unchecked", "Unchecked connections"],
    ]
      .map(
        ([key, title]) =>
          `<h2>${title} <span class="muted">${r[key].length}</span></h2>${r[key].length ? r[key].map((e, i) => finding(e, i)).join("") : '<div class="empty">No connections in this category.</div>'}`,
      )
      .join("") +
    `<div class="panel"><h3>Proposed concepts & new groups</h3><p>${r.proposed_concepts.length} proposed concepts · ${r.new_groups.length} groups</p><p class="hint">Odysseus proposals are kept separate and never self-ranked.</p><pre>${esc(JSON.stringify({ concepts: r.proposed_concepts, groups: r.new_groups }, null, 2))}</pre></div>`;
}
function finding(e, i) {
  const value = e.bridge_score?.value;
  return `<article class="finding"><div class="sectionTitle"><div>${pill(e.tier)} ${pill(e.existing)} ${e.fixture ? pill("fixture") : ""}</div><span class="muted">Bridge ${value == null ? "unavailable" : value.toFixed(3)}</span></div><h3>${i + 1}. ${esc(e.argument)}</h3><div class="meta"><span>${esc(e.type)}</span><span>${e.premises.length} premise(s)</span><span>${e.support_count} support(s)</span><span>${e.tier === "verified" ? "Machine verified exact statement" : e.tier === "cited" ? "Literature supported" : "Conjectural / descriptive"}</span></div><div class="actions"><button data-detail="${esc(e.id)}" data-kind="edge">Evidence & provenance ↗</button><button data-feedback="${esc(e.id)}" data-mark="interesting">☆ Interesting</button><button data-feedback="${esc(e.id)}" data-mark="wrong">Flag wrong → re-review</button></div></article>`;
}
async function loadHistory() {
  const papers = Object.fromEntries(state.papers.map((p) => [p.id, p]));
  $("historyList").innerHTML = state.runs.length
    ? state.runs
        .map(
          (r) =>
            `<div class="historyRow"><div><h3>${esc(papers[r.paper_id]?.title || r.paper_id)}</h3><span class="muted">${esc(date(r.created))} · ${r.checkpoint}/7 checkpoints ${r.error ? "· " + esc(r.error) : ""}</span></div><div class="actions">${pill(r.status)}<button data-open-run="${esc(r.id)}">Open ${r.status === "complete" ? "report" : "trace"} ↗</button></div></div>`,
        )
        .join("")
    : '<div class="empty">No runs yet.</div>';
  const suggestions = await api(`/journeys/${state.journey.id}/suggestions`);
  $("suggestionList").innerHTML = suggestions.length
    ? suggestions
        .map(
          (p) =>
            `<p><button data-pick-paper="${esc(p.id)}">${esc(p.title)} →</button> <span class="muted">${esc(p.suggestion_reason)}</span></p>`,
        )
        .join("")
    : '<p class="muted">Import more papers to see suggestions near reviewed bridges.</p>';
  const queue = await api(`/journeys/${state.journey.id}/rechecks`);
  $("recheckList").innerHTML = queue.length
    ? queue
        .map(
          (q) =>
            `<p>${esc(q.edge_id.slice(0, 14))} · ${esc(q.status)} ${["queued", "failed"].includes(q.status) ? `<button data-recheck="${esc(q.id)}">Retry re-review with run budget cap</button>` : esc(q.result?.reason)} ${esc(q.error || "")}</p>`,
        )
        .join("")
    : '<p class="muted">No pending feedback.</p>';
}
async function loadGraph() {
  const params = new URLSearchParams();
  [
    ["layer", "graphLayer"],
    ["tier", "graphTier"],
    ["existing", "graphExisting"],
    ["island", "graphIsland"],
    ["run_id", "graphRun"],
    ["q", "graphSearch"],
  ].forEach(([k, id]) => {
    if ($(id).value) params.set(k, $(id).value);
  });
  if ($("graphRejected").checked) params.set("include_rejected", "true");
  if ($("graphProposed").checked) params.set("include_proposed", "true");
  if ($("graphNew").checked) params.set("new_only", "true");
  if ($("graphBefore").checked) params.set("before", "true");
  let g = await api(`/journeys/${state.journey.id}/graph?${params}`);
  if ($("graphSemantic").checked && $("graphSearch").value) {
    const result = await api(`/journeys/${state.journey.id}/search/semantic`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        query: $("graphSearch").value,
        budget_usd: Number($("runBudget").value),
      }),
    });
    const ids = new Set(result.results.map((n) => n.id));
    params.delete("q");
    g = await api(`/journeys/${state.journey.id}/graph?${params}`);
    g.concepts = g.concepts.filter((n) => ids.has(n.id));
    g.edges = g.edges.filter((e) =>
      e.premises.concat(e.conclusion).every((n) => ids.has(n)),
    );
  }
  state.graph = g;
  drawGraph(g);
  $("proofStart").innerHTML = g.concepts
    .map((n) => `<option value="${esc(n.id)}">${esc(n.name)}</option>`)
    .join("");
}
function drawGraph(g) {
  const islands = state.journey.islands;
  const pos = {};
  let svg =
    '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#8b999d"/></marker></defs>';
  const maxRows = Math.max(1, ...islands.map(i => Math.ceil(g.concepts.filter(n => n.island === i).length/3)));
  const clusterHeight = Math.max(290, maxRows * 55 + 85);
  const height = islands.length < 3 ? clusterHeight + 60 : 2 * clusterHeight + 90;
  $("graphSvg").setAttribute("viewBox", `0 0 1000 ${height}`);
  const centers = islands.map((_, i) => islands.length === 1 ? [500, height/2] :
    islands.length === 2 ? [260 + i * 480, height/2] : [250 + (i % 2) * 500, 30 + clusterHeight/2 + Math.floor(i / 2) * (clusterHeight + 30)]);
  islands.forEach((island, i) => {
    const [cx, cy] = centers[i];
    svg += `<ellipse class="cluster" cx="${cx}" cy="${cy}" rx="215" ry="${(clusterHeight-15)/2}"/><text class="clusterTitle" x="${cx}" y="${cy - clusterHeight/2 + 25}" text-anchor="middle">${esc(island.toUpperCase())}</text>`;
    const ns = g.concepts.filter((n) => n.island === island);
    ns.forEach((n, j) => {
      const cols = Math.min(3, ns.length);
      const rows = Math.ceil(ns.length / cols);
      pos[n.id] = [cx + (j % cols - (cols-1)/2) * 138, cy + (Math.floor(j/cols) - (rows-1)/2) * 55];
    });
  });
  g.edges.forEach((e) => {
    const end = pos[e.conclusion];
    if (!end) return;
    const ps = e.premises.map((p) => pos[p]).filter(Boolean);
    if (ps.length !== e.premises.length) return;
    // Stop arrows outside the node circle so arrowheads remain visible.
    const trim = (from, to) => { const d = Math.hypot(to[0]-from[0], to[1]-from[1]) || 1;
      return [to[0] - 15*(to[0]-from[0])/d, to[1] - 15*(to[1]-from[1])/d]; };
    const nonEvidence = e.review_status !== "passed" || e.invalidated;
    const edgeClass = `${e.tier} ${nonEvidence ? "nonEvidence" : ""}`;
    let junction = trim(ps[0], end);
    if (ps.length > 1) {
      junction = [
        (ps.reduce((s, p) => s + p[0], 0) / ps.length + end[0]) / 2,
        (ps.reduce((s, p) => s + p[1], 0) / ps.length + end[1]) / 2,
      ];
      svg += `<circle class="graphNode" data-detail="${esc(e.id)}" data-kind="edge" cx="${junction[0]}" cy="${junction[1]}" r="5" fill="#577c77"/><path class="graphEdge ${esc(edgeClass)}" data-detail="${esc(e.id)}" data-kind="edge" d="M ${junction} L ${trim(junction, end)}" marker-end="url(#arrow)"/>`;
    }
    ps.forEach((p) => {
      svg += `<path class="graphEdge ${esc(edgeClass)}" data-detail="${esc(e.id)}" data-kind="edge" d="M ${p} L ${junction}" ${ps.length === 1 && e.directed ? 'marker-end="url(#arrow)"' : ""}/>`;
    });
  });
  g.concepts.forEach((n) => {
    const p = pos[n.id];
    if (!p) return;
    const color = ["#397c70", "#647ba5", "#ac8552", "#9865a5"][islands.indexOf(n.island)];
    svg += `<g class="graphNode ${n.integrated ? "" : "unintegrated"} ${n.status === "Proposed" ? "proposed" : ""}" data-detail="${esc(n.id)}" data-kind="concept" tabindex="0" role="button" aria-label="${esc(n.name)}">${n.layer.startsWith("journey:") ? `<rect x="${p[0]-11}" y="${p[1]-11}" width="22" height="22" fill="${color}"/>` : `<circle cx="${p[0]}" cy="${p[1]}" r="11" fill="${color}"/>`}<text x="${p[0]}" y="${p[1] + 27}" text-anchor="middle">${esc(n.name.length > 19 ? n.name.slice(0, 17) + "…" : n.name)}</text></g>`;
  });
  $("graphSvg").innerHTML = svg;
  const inv = g.inventory || {};
  $("graphEmpty").textContent =
    `Inventory: ${inv.base_nodes ?? "?"} base nodes / ${inv.base_edges ?? "?"} base relations; ${inv.journey_nodes ?? "?"} journey nodes / ${inv.journey_edges ?? "?"} journey relations. ${inv.accepted === 0 ? "No accepted relations: pinned modules may contain no edges and generated candidates may have failed review. Inspect rejected relations for reasons. " : (!g.edges.length ? "No relations match the current filters. " : "")}Visible: ${g.concepts.length} concepts · ${g.edges.length} relations. Circles: base nodes. Squares: journey nodes. Red dotted edges are NON-EVIDENCE; arrows show relation direction, junctions require all premises. Only implies/equivalent relations are proof steps. Base endpoints remain visible as context when filtering journey edges. Dotted outlines indicate unintegrated nodes. Click nodes or edges to inspect.`;
}
async function showDetail(kind, id) {
  const result = await api(
    `/journeys/${state.journey.id}/details/${kind}/${encodeURIComponent(id)}`,
  );
  const d = result.item;
  const html = `<h3>${esc(d.name || d.type)}</h3><p>${esc(d.statement || d.argument)}</p>${pill(d.status || d.tier)} ${d.existing ? pill(d.existing) : ""}${d.review_status && d.review_status !== "passed" || d.invalidated ? pill("NON-EVIDENCE — excluded from proofs and scores") : ""}<p>Layer: ${esc(d.layer)}</p><h3>Reviewer reasons</h3>${(result.reviews || []).map(r => `<p>${esc(r.verdict)}: ${esc(r.reason)}</p>`).join("") || "<p>No reviewer record; inspect source evidence below.</p>"}<h3>Evidence, provenance & history</h3><pre>${esc(JSON.stringify(result, null, 2))}</pre>`;
  if (state.tab === "graph") $("graphDetails").innerHTML = html;
  else {
    $("detailContent").innerHTML = html;
    $("detailDialog").showModal();
  }
}
async function openSettings(journeySettings = false) {
  $("settingsTitle").textContent = journeySettings
    ? "Journey settings"
    : "Settings & costs";
  if (journeySettings) {
    const s = { formalize_definitions: false, ...state.journey.settings };
    $("settingsContent").innerHTML =
      `<form id="editSettings"><div class="settingsGrid">${Object.entries(s)
        .map(
          ([k, v]) =>
            `<label>${esc(k.replaceAll("_", " "))}${typeof v === "boolean"
              ? `<input type="checkbox" name="${esc(k)}" ${v ? "checked" : ""}>`
              : `<input type="number" name="${esc(k)}" value="${v}" min="0" step="${["tree_weight", "group_ratio", "budget_usd"].includes(k) ? "0.01" : "1"}" required>`}</label>`,
        )
        .join(
          "",
        )}</div><p class="hint">Graph weight is 1 − tree weight. Budget defaults to zero. Caps apply before every live provider request.</p><button class="primary">Save settings</button></form>`;
    on("editSettings", "submit", async (e) => {
      e.preventDefault();
      const values = Object.fromEntries(
        [...new FormData(e.target)].map(([k, v]) => [k, Number(v)]),
      );
      values.formalize_definitions = e.target.elements.formalize_definitions.checked;
      state.journey = await api(`/journeys/${state.journey.id}/settings`, {
        method: "PUT",
        body: JSON.stringify(values),
      });
      $("settingsDialog").close();
    });
  } else {
    const [s, c] = await Promise.all([
      api("/settings"),
      api("/costs" + (state.journey ? "?journey_id=" + state.journey.id : "")),
    ]);
    $("settingsContent").innerHTML =
      `<div class="settingsGrid"><div class="panel"><span class="muted">Conservative charges</span><div class="metric">$${c.total_usd.toFixed(4)}</div></div><div class="panel"><span class="muted">Server budget cap</span><div class="metric">$${s.global_budget_usd.toFixed(2)}</div></div></div><p class="hint">${esc(c.accounting)} ${esc(s.credentials)} Live enabled: ${s.live_enabled}. The database allowance is not a model budget.</p><h3>Role configuration</h3><p class="hint">Configure provider, model, server key environment variable and maximum call charge. Actual key values stay on the server. Save requires METIS_PROVIDERS_FILE.</p><form id="providersForm"><textarea name="roles" rows="12" aria-label="Provider roles JSON">${esc(JSON.stringify(s.roles, null, 2))}</textarea><button>Save provider configuration</button></form><h3>Usage ledger</h3><pre>${esc(JSON.stringify(c, null, 2))}</pre>`;
    on("providersForm", "submit", async (e) => {
      e.preventDefault();
      await api("/settings/providers", {
        method: "PUT",
        body: JSON.stringify(Object.fromEntries(Object.entries(
          JSON.parse(new FormData(e.target).get("roles"))
        ).filter(([, spec]) => Object.keys(spec).length))),
      });
      $("settingsDialog").close();
    });
  }
  $("settingsDialog").showModal();
}
async function download(fmt) {
  if (!state.run) throw Error("Select a completed run first");
  const res = await fetch(
    `/api/journeys/${state.journey.id}/runs/${state.run.id}/export/${fmt}`,
    { headers: state.token ? { Authorization: "Bearer " + state.token } : {} },
  );
  if (!res.ok) throw Error("Export unavailable until report is complete");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `metis-${state.run.id}.${fmt}`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
document.addEventListener("click", (e) => {
  const el = e.target.closest("button,[data-detail]");
  if (!el) return;
  Promise.resolve(
    (async () => {
      if (el.dataset.close) $(el.dataset.close).close();
      if (el.dataset.journey) await openJourney(el.dataset.journey);
      if (el.dataset.tab) showTab(el.dataset.tab);
      if (el.dataset.control) {
        if (!state.run) return;
        state.run = await api(
          `/journeys/${state.journey.id}/runs/${state.run.id}/${el.dataset.control}`,
          {
            method: "POST",
            body: JSON.stringify({ budget_usd: Number($("runBudget").value) }),
          },
        );
        await refresh();
      }
      if (el.dataset.export) await download(el.dataset.export);
      if (el.dataset.detail)
        await showDetail(el.dataset.kind, el.dataset.detail);
      if (el.dataset.feedback) {
        await api(`/journeys/${state.journey.id}/feedback`, {
          method: "POST",
          body: JSON.stringify({
            target_id: el.dataset.feedback,
            mark: el.dataset.mark,
          }),
        });
        el.textContent =
          el.dataset.mark === "wrong"
            ? "Queued for re-review"
            : "Marked interesting";
        el.disabled = true;
      }
      if (el.dataset.pickPaper) {
        $("paperSelect").value = el.dataset.pickPaper;
        showTab("run");
      }
      if (el.dataset.openRun) {
        state.run = state.runs.find((r) => r.id === el.dataset.openRun);
        showTab(state.run.status === "complete" ? "report" : "run");
        await loadTrace();
      }
      if (el.dataset.recheck) {
        await api(
          `/journeys/${state.journey.id}/rechecks/${el.dataset.recheck}`,
          { method: "POST", body: JSON.stringify({ budget_usd: Number($("runBudget").value) }) },
        );
        await loadHistory();
      }
    })(),
  ).catch(error);
});
on("homeButton", "click", goHome);
on("newButton", "click", () => openCatalog(false));
on("addFields", "click", () => openCatalog(true));
on("settingsButton", "click", () => openSettings());
on("journeySettings", "click", () => openSettings(true));
on("authButton", "click", () => {
  const token = prompt(
    "API bearer token for this browser session (leave empty for local development)",
    state.token,
  );
  if (token !== null) {
    state.token = token;
    sessionStorage.setItem("metisToken", token);
    location.reload();
  }
});
on("journeyForm", "submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const modules = f.getAll("module");
  if (!modules.length) throw Error("Select at least one ready module version");
  const islands = [...new Set(modules.flatMap(mid => state.catalogModules.find(m => m.id === mid).islands))];
  const j = await api(state.addingFields ? `/journeys/${state.journey.id}/modules` : "/journeys", {
    method: "POST",
    body: JSON.stringify({ name: f.get("name"), islands, modules }),
  });
  $("newDialog").close();
  await openJourney(j.id);
});
on("sourceKind", "change", () => {
  const kind = $("sourceKind").value;
  $("pdfLabel").hidden = kind !== "pdf";
  $("paperValueLabel").hidden = ["pdf", "fixture"].includes(kind);
});
on("paperForm", "submit", async (e) => {
  e.preventDefault();
  if (!state.journey) return;
  const f = new FormData(e.target);
  let p;
  if (f.get("kind") === "pdf") {
    f.delete("kind");
    f.delete("value");
    p = await api(`/journeys/${state.journey.id}/papers/pdf`, {
      method: "POST",
      body: f,
    });
  } else
    p = await api(`/journeys/${state.journey.id}/papers`, {
      method: "POST",
      body: JSON.stringify({
        title: f.get("title"),
        kind: f.get("kind"),
        value: f.get("value"),
        home_group: f.get("home_group"),
      }),
    });
  await refresh();
  $("paperSelect").value = p.id;
});
on("bulkForm", "submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const ids = form.get("ids")
    .split(/[\s,]+/)
    .filter(Boolean);
  const results = await api(`/journeys/${state.journey.id}/papers/bulk`, {
    method: "POST",
    body: JSON.stringify(form.get("mode") === "msc"
      ? { msc_category: form.get("ids").trim(), limit: 20 }
      : { arxiv_ids: ids, home_group: $("paperGroup").value }),
  });
  await refresh();
  $("bulkResult").textContent = `${results.filter(r => r.paper).length} imported. ${results.filter(r => r.error).length} failed. MSC mode searches stored corpus only.`;
  if (results.some((r) => r.error)) throw Error(JSON.stringify(results));
});
on("correctPlacement", "click", async () => {
  if (!$("paperSelect").value) throw Error("Select a paper first");
  await api(`/journeys/${state.journey.id}/papers/${$("paperSelect").value}/placement`, {
    method: "PUT", body: JSON.stringify({ home_group: $("paperGroup").value })
  });
  await refresh();
});
on("startRun", "click", async () => {
  if ("Notification" in window && Notification.permission === "default")
    Notification.requestPermission();
  state.run = await api(`/journeys/${state.journey.id}/runs`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({
      paper_id: $("paperSelect").value,
      budget_usd: Number($("runBudget").value),
    }),
  });
  await refresh();
});
on("extractOnly", "click", async () => {
  state.run = await api(`/journeys/${state.journey.id}/runs`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({
      paper_id: $("paperSelect").value,
      budget_usd: Number($("runBudget").value),
      ingest_only: true,
    }),
  });
  await refresh();
});
on("traceAgent", "change", loadTrace);
on("traceStep", "change", loadTrace);
on("applyGraph", "click", loadGraph);
on("proofButton", "click", async () => {
  $("proofResult").textContent = JSON.stringify(
    await api(`/journeys/${state.journey.id}/proof`, {
      method: "POST",
      body: JSON.stringify({
        starts: [...$("proofStart").selectedOptions].map((o) => o.value),
      }),
    }),
    null,
    2,
  );
});
async function init() {
  try {
    state.status = await api("/status");
    $("mode").textContent = state.status.fixture
      ? "FIXTURE · LOCAL"
      : "LIVE · MONGODB";
    $("notice").textContent = state.status.notice;
    $("sourceKind").querySelector('[value="fixture"]').disabled =
      !state.status.fixture;
    if (!state.status.fixture) $("sourceKind").value = "text";
    $("paperValueLabel").hidden = state.status.fixture;
    const agents = [
      "system",
      "decomposer",
      "Eurylochus",
      "Elpenor",
      "Polites",
      "Perimedes",
      "Penelope",
      "Hephaestus",
      "Tiresias",
      "Odysseus",
    ];
    $("traceAgent").innerHTML =
      '<option value="">All agents</option>' +
      agents.map((a) => `<option>${a}</option>`).join("");
    $("traceStep").innerHTML =
      '<option value="">All stages</option>' +
      state.status.stages
        .map((s, i) => `<option value="${i}">${i + 1}. ${esc(s)}</option>`)
        .join("");
    const hash = location.hash.slice(1);
    if (hash && hash !== "home") await openJourney(hash);
    else await home();
  } catch (e) {
    error(e);
  }
}
init();
document.addEventListener("keydown", (e) => {
  if (
    (e.key === "Enter" || e.key === " ") &&
    e.target.matches('[data-detail][role="button"]')
  ) {
    e.preventDefault();
    showDetail(e.target.dataset.kind, e.target.dataset.detail).catch(error);
  }
});
