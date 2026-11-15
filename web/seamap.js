"use strict";
/* Sea map (UI spec): each basis group is an island sized by its node count; subgroups are patches
   of different-coloured grass; papers get patches of their own; paper nodes are Odyssey items and
   creatures; edges on one island are walkers (meeting at a campfire for a hyperedge); edges
   between islands are boats whose hull shows the tier and whose sail shows new or old.
   Basis nodes are laid out but not drawn. The same world coordinates feed the simplified view,
   so the camera and the selection carry over between the two. */
const SeaMap = (() => {
  const T = 8; // one tile, in world pixels
  const PAD = 4; // beach ring, in tiles
  const GAP = 11; // water between islands, in tiles
  const ZOOMS = [0.25, 0.5, 1, 2, 3, 4, 6, 8];
  const GRASS = ["#6fae4a", "#4f9d57", "#8bb84a", "#3f9470", "#a3b64a", "#5c9f3c", "#79a85e", "#4c8f4c", "#93ad52", "#58a06a"];
  const MEADOW = ["#c6dc7a", "#d9d27c", "#bfe0a0", "#dccf90", "#cfe38c"];
  const FLOWERS = ["#e88bb0", "#fdfdf5", "#ffe27a", "#b08ad6"];
  const TIER_COLOR = { verified: "#fdfdf5", cited: "#9cc3ff", intuitive: "#e0a070" };

  function squarify(items, x, y, w, h) {
    const total = items.reduce((s, i) => s + i.area, 0) || 1;
    const scale = (w * h) / total;
    const list = items.map((i) => ({ key: i.key, area: i.area * scale })).sort((a, b) => b.area - a.area);
    const out = [];
    let rx = x, ry = y, rw = w, rh = h, row = [];
    const worst = (r, side) => {
      const s = r.reduce((a, b) => a + b.area, 0);
      const max = Math.max(...r.map((v) => v.area)), min = Math.min(...r.map((v) => v.area));
      return Math.max((side * side * max) / (s * s), (s * s) / (side * side * min));
    };
    const place = (r) => {
      const s = r.reduce((a, b) => a + b.area, 0);
      if (rw >= rh) {
        const sw = s / rh;
        let cy = ry;
        r.forEach((v) => { const hh = v.area / sw; out.push({ key: v.key, x: rx, y: cy, w: sw, h: hh }); cy += hh; });
        rx += sw; rw -= sw;
      } else {
        const sh = s / rw;
        let cx = rx;
        r.forEach((v) => { const ww = v.area / sh; out.push({ key: v.key, x: cx, y: ry, w: ww, h: sh }); cx += ww; });
        ry += sh; rh -= sh;
      }
    };
    for (const item of list) {
      const side = Math.max(0.0001, Math.min(rw, rh));
      if (!row.length || worst(row.concat(item), side) <= worst(row, side)) row.push(item);
      else { place(row); row = [item]; }
    }
    if (row.length) place(row);
    return out;
  }
  function spread(nodes, x, y, w, h, pos, island) {
    const n = nodes.length;
    if (!n) return;
    const cols = Math.max(1, Math.round(Math.sqrt((n * Math.max(w, 0.5)) / Math.max(h, 0.5))));
    const rows = Math.ceil(n / cols);
    nodes.forEach((node, i) => {
      pos[node.id] = { x: (x + ((i % cols) + 0.5) * (w / cols)) * T, y: (y + (Math.floor(i / cols) + 0.5) * (h / rows)) * T, island };
    });
  }

  /* ---- World layout: islands, grass patches, paper patches, a position for every node ---- */
  function layout(data) {
    const groupById = Object.fromEntries(data.groups.map((g) => [g.id, g]));
    const paperById = Object.fromEntries(data.papers.map((p) => [p.id, p]));
    const runPaper = Object.fromEntries(data.runs.map((r) => [r.id, r.paper_id]));
    const hasChild = new Set(data.groups.map((g) => g.parent).filter(Boolean));
    const pos = {};
    const islands = data.journey.islands.map((id) => {
      const leaves = data.groups.filter((g) => g.island === id && !hasChild.has(g.id) && g.depth >= 2);
      const leafIds = new Set(leaves.map((g) => g.id));
      const misc = { id: id + ":misc", name: "Other", msc: "", depth: 3, parent: null, island: id };
      const nodes = data.concepts.filter((n) => n.island === id);
      const base = {}, patches = {};
      const leafOf = (gid) => (leafIds.has(gid) ? gid : misc.id);
      nodes.forEach((n) => {
        if (!n.layer.startsWith("journey:")) { (base[leafOf(n.home_group)] ||= []).push(n); return; }
        const paper = paperById[n.paper_id] || paperById[runPaper[n.run_id]];
        const home = paper && groupById[paper.home_group] && groupById[paper.home_group].island === id;
        const group = leafOf(home ? paper.home_group : n.home_group);
        const key = (paper ? paper.id : "crew") + "@" + group;
        (patches[key] ||= { key, paper: paper || null, group, nodes: [] }).nodes.push(n);
      });
      if (base[misc.id] || Object.values(patches).some((p) => p.group === misc.id)) leaves.push(misc);
      // A basis group carries its whole MSC subtree; only subgroups that hold concepts or papers
      // become grass, so the island's area keeps reflecting its node count.
      const populated = leaves.filter((g) => (base[g.id] || []).length || Object.values(patches).some((p) => p.group === g.id));
      leaves.splice(0, leaves.length, ...(populated.length ? populated : leaves.slice(0, 1)));
      const patchArea = (p) => Math.max(12, p.nodes.length * 6);
      const area = {};
      leaves.forEach((g) => {
        const own = Object.values(patches).filter((p) => p.group === g.id);
        area[g.id] = Math.max(4, (base[g.id] || []).length + own.reduce((s, p) => s + patchArea(p), 0));
      });
      const total = leaves.reduce((s, g) => s + area[g.id], 0) || 12;
      const W = Math.max(12, Math.ceil(Math.sqrt(total * 1.45)));
      const H = Math.max(9, Math.ceil(total / W));
      const regions = {};
      leaves.forEach((g) => (regions[g.depth >= 3 && g.parent ? g.parent : g.id] ||= []).push(g));
      const regionKeys = Object.keys(regions);
      const outer = squarify(regionKeys.map((k) => ({ key: k, area: regions[k].reduce((s, g) => s + area[g.id], 0) })), 0, 0, W, H);
      const leafRects = [];
      outer.forEach((r) => {
        const hue = GRASS[regionKeys.indexOf(r.key) % GRASS.length];
        squarify(regions[r.key].map((g) => ({ key: g.id, area: area[g.id] })), r.x, r.y, r.w, r.h).forEach((q, j) => {
          const g = groupById[q.key] || misc;
          leafRects.push({ group: g, region: groupById[r.key] || null, fx: q.x, fy: q.y, fw: q.w, fh: q.h,
            x0: Math.round(q.x), y0: Math.round(q.y), x1: Math.round(q.x + q.w), y1: Math.round(q.y + q.h),
            color: Pixel.shade(hue, ((j % 5) - 2) * 0.03), count: (base[g.id] || []).length });
        });
      });
      return { id, name: (data.journey.island_names || {})[id] || id.replace(/-/g, " "), field: (data.groups.find((g) => g.island === id && g.depth === 1) || {}).name || "", W, H, leafRects, base, patches: Object.values(patches), count: nodes.length };
    });
    // Place the islands on the sea: one row for one or two, otherwise two per row.
    const perRow = islands.length <= 2 ? Math.max(1, islands.length) : Math.ceil(Math.sqrt(islands.length));
    let x = GAP, y = GAP, rowH = 0;
    islands.forEach((isl, i) => {
      if (i && i % perRow === 0) { x = GAP; y += rowH + GAP; rowH = 0; }
      isl.tx = x; isl.ty = y; // tile origin of the island canvas (beach ring included)
      x += isl.W + 2 * PAD + GAP;
      rowH = Math.max(rowH, isl.H + 2 * PAD);
    });
    const world = { w: 0, h: 0 };
    islands.forEach((isl) => {
      const ox = isl.tx + PAD, oy = isl.ty + PAD; // interior origin, tiles
      isl.rect = { x: isl.tx * T, y: isl.ty * T, w: (isl.W + 2 * PAD) * T, h: (isl.H + 2 * PAD) * T };
      isl.leafRects.forEach((leaf) => {
        const own = isl.patches.filter((p) => p.group === leaf.group.id);
        let used = 0;
        const room = Math.max(1, leaf.fh);
        own.forEach((p) => {
          const want = Math.max(2, Math.ceil(Math.max(12, p.nodes.length * 6) / Math.max(1, leaf.fw)));
          const rows = Math.min(want, Math.max(1.5, room * (leaf.count ? 0.7 : 1) / own.length));
          used += rows;
          p.t = { x: leaf.fx, y: leaf.fy + leaf.fh - used, w: leaf.fw, h: rows };
          p.rect = { x: (ox + Math.round(p.t.x)) * T, y: (oy + Math.round(p.t.y)) * T, w: Math.max(1, Math.round(p.t.x + p.t.w) - Math.round(p.t.x)) * T, h: Math.max(1, Math.round(p.t.y + p.t.h) - Math.round(p.t.y)) * T };
          p.island = isl.id;
          spread(p.nodes, ox + p.t.x, oy + p.t.y, p.t.w, p.t.h, pos, isl.id);
        });
        spread(isl.base[leaf.group.id] || [], ox + leaf.fx, oy + leaf.fy, leaf.fw, Math.max(0.5, leaf.fh - used), pos, isl.id);
        leaf.rect = { x: (ox + leaf.x0) * T, y: (oy + leaf.y0) * T, w: (leaf.x1 - leaf.x0) * T, h: (leaf.y1 - leaf.y0) * T };
      });
      isl.canvas = paintIsland(isl);
      world.w = Math.max(world.w, isl.rect.x + isl.rect.w + GAP * T);
      world.h = Math.max(world.h, isl.rect.y + isl.rect.h + GAP * T);
    });
    return { islands, pos, world, groupById, paperById };
  }

  function paintIsland(isl) {
    const cols = isl.W + 2 * PAD, rows = isl.H + 2 * PAD;
    const [canvas, ctx] = Pixel.make(cols * T, rows * T);
    const rand = Pixel.rng(Pixel.hash(isl.id));
    const seedA = (Pixel.hash(isl.id) % 628) / 100, seedB = (Pixel.hash(isl.id + "b") % 628) / 100;
    const land = Array.from({ length: rows }, () => new Uint8Array(cols));
    const leafAt = Array.from({ length: rows }, () => new Int16Array(cols).fill(-1));
    isl.leafRects.forEach((leaf, i) => {
      for (let y = leaf.y0; y < leaf.y1; y++) for (let x = leaf.x0; x < leaf.x1; x++) leafAt[y + PAD][x + PAD] = i;
    });
    for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
      const dx = Math.max(PAD - x, 0, x - (PAD + isl.W - 1)), dy = Math.max(PAD - y, 0, y - (PAD + isl.H - 1));
      const d = Math.hypot(dx, dy);
      // A gently undulating coast: low-frequency waves around the shore, not per-tile noise.
      const swell = (Math.sin(x * 0.83 + seedA) + Math.sin(y * 1.07 + seedB) + Math.sin((x + y) * 0.47 + seedA * 2)) / 3;
      land[y][x] = d === 0 ? 2 : d <= 2.1 + 1.25 * swell ? 1 : 0;
    }
    const fill = (color, x, y, w = 1, h = 1) => { ctx.fillStyle = color; ctx.fillRect(x, y, w, h); };
    for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
      const px = x * T, py = y * T;
      if (!land[y][x]) continue;
      if (land[y][x] === 1 || leafAt[y][x] < 0) {
        fill("#f0d9a0", px, py, T, T);
        fill("#e3c784", px + Math.floor(rand() * 7), py + Math.floor(rand() * 7), 1, 1);
        fill("#f7e6b8", px + Math.floor(rand() * 7), py + Math.floor(rand() * 7), 1, 1);
        const water = (xx, yy) => yy < 0 || xx < 0 || yy >= rows || xx >= cols || !land[yy][xx];
        if (water(x, y - 1)) fill("#fdfdf5", px, py, T, 1);
        if (water(x, y + 1)) fill("#fdfdf5", px, py + T - 1, T, 1);
        if (water(x - 1, y)) fill("#fdfdf5", px, py, 1, T);
        if (water(x + 1, y)) fill("#fdfdf5", px + T - 1, py, 1, T);
        continue;
      }
      const leaf = isl.leafRects[leafAt[y][x]];
      fill(leaf.color, px, py, T, T);
      fill(Pixel.shade(leaf.color, -0.09), px + Math.floor(rand() * 7), py + Math.floor(rand() * 6), 1, 2);
      fill(Pixel.shade(leaf.color, -0.06), px + Math.floor(rand() * 7), py + Math.floor(rand() * 6), 1, 2);
      fill(Pixel.shade(leaf.color, 0.08), px + Math.floor(rand() * 7), py + Math.floor(rand() * 7), 1, 1);
      if (x - PAD === leaf.x1 - 1) fill(Pixel.shade(leaf.color, -0.13), px + T - 1, py, 1, T);
      if (y - PAD === leaf.y1 - 1) fill(Pixel.shade(leaf.color, -0.13), px, py + T - 1, T, 1);
    }
    // Paper patches: meadows of their own, flowered and ringed with a dotted border.
    isl.patches.forEach((p) => {
      const color = MEADOW[Pixel.hash(p.key) % MEADOW.length];
      const x0 = p.rect.x - isl.rect.x, y0 = p.rect.y - isl.rect.y;
      fill(color, x0, y0, p.rect.w, p.rect.h);
      const r = Pixel.rng(Pixel.hash(p.key));
      for (let i = 0; i < (p.rect.w * p.rect.h) / 40; i++) fill(FLOWERS[Math.floor(r() * FLOWERS.length)], x0 + 1 + Math.floor(r() * (p.rect.w - 2)), y0 + 1 + Math.floor(r() * (p.rect.h - 2)), 1, 1);
      for (let i = 0; i < p.rect.w; i += 2) { fill("#7a8f3a", x0 + i, y0, 1, 1); fill("#7a8f3a", x0 + i, y0 + p.rect.h - 1, 1, 1); }
      for (let i = 0; i < p.rect.h; i += 2) { fill("#7a8f3a", x0, y0 + i, 1, 1); fill("#7a8f3a", x0 + p.rect.w - 1, y0 + i, 1, 1); }
    });
    return canvas;
  }

  /* ---- The map instance ---- */
  function create(canvas, mini, hooks) {
    const ctx = canvas.getContext("2d");
    const mctx = mini.getContext("2d");
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let data = null, world = null, cam = { x: 0, y: 0, zoom: 1 }, filters = {}, selection = null, routePath = null, player = null;
    let movers = [], fires = [], trails = [], lanes = [], chars = [], hits = [], frame = 0, timer = null, started = performance.now();

    function setData(next, keepCamera) {
      data = next;
      world = layout(data);
      rebuild();
      if (!keepCamera) fit(); else draw();
      return world;
    }
    function visibleEdge(e) {
      const f = filters;
      const rejected = e.review_status === "rejected" || e.invalidated;
      if (rejected && !f.rejected) return false;
      if (!rejected && e.review_status !== "passed" && !f.proposed) return false;
      if (f.tier && e.tier !== f.tier) return false;
      if (f.existing && e.existing !== f.existing) return false;
      if (f.run && e.run_id !== f.run) return false;
      if (f.newOnly && (e.run_id !== data.latest_run || e.kind === "integration")) return false;
      const ends = e.premises.concat(e.conclusion);
      if (!ends.every((n) => world.pos[n])) return false;
      if (f.island && !ends.some((n) => world.pos[n].island === f.island)) return false;
      if (f.match && !ends.some((n) => f.match.has(n))) return false;
      return true;
    }
    function clip(a, b, rect, entering) {
      // Point where the segment a->b crosses the border of rect (leaving it, or entering it).
      let best = entering ? 1 : 0;
      const dx = b.x - a.x, dy = b.y - a.y;
      [[rect.x, 0], [rect.x + rect.w, 0], [rect.y, 1], [rect.y + rect.h, 1]].forEach(([v, axis]) => {
        const d = axis ? dy : dx;
        if (Math.abs(d) < 1e-6) return;
        const t = (v - (axis ? a.y : a.x)) / d;
        if (t <= 0 || t >= 1) return;
        const o = axis ? a.x + dx * t : a.y + dy * t;
        const lo = axis ? rect.x : rect.y, hi = lo + (axis ? rect.w : rect.h);
        if (o < lo - 0.5 || o > hi + 0.5) return;
        best = entering ? Math.min(best, t) : Math.max(best, t);
      });
      return { x: a.x + dx * best, y: a.y + dy * best };
    }
    function rebuild() {
      movers = []; fires = []; trails = []; lanes = []; chars = [];
      if (!data) return;
      const isJourney = Object.fromEntries(data.concepts.map((n) => [n.id, n.layer.startsWith("journey:")]));
      const fleets = {};
      const islandRect = Object.fromEntries(world.islands.map((i) => [i.id, i.rect]));
      data.concepts.forEach((n) => {
        if (!isJourney[n.id] || !world.pos[n.id]) return;
        if (n.invalidated && !filters.rejected) return;
        if (filters.island && n.island !== filters.island) return;
        chars.push({ node: n, pos: world.pos[n.id], item: Pixel.itemFor(n.id), fresh: n.run_id && n.run_id === data.latest_run,
          dim: n.status === "Proposed" || (filters.match && !filters.match.has(n.id)) });
      });
      data.edges.forEach((e) => {
        if (!visibleEdge(e)) return;
        const c = world.pos[e.conclusion];
        const fresh = !!e.run_id && e.run_id === data.latest_run;
        const none = e.review_status !== "passed" || e.invalidated;
        const tier = none ? "none" : e.tier;
        const seed = Pixel.hash(e.id) / 4294967296;
        const walk = (a, b, k) => {
          const len = Math.hypot(b.x - a.x, b.y - a.y);
          if (len < 2) return;
          trails.push({ a, b, tier, fresh, edge: e, none });
          movers.push({ type: "walker", edge: e, a, b, len, period: Math.max(2.5, len / 11), phase: (seed + k * 0.37) % 1, tier, fresh });
        };
        const sail = (a, b, fromIsland, k, twoWay) => {
          const start = clip(a, b, islandRect[fromIsland], false), end = clip(a, b, islandRect[c.island], true);
          const len = Math.hypot(end.x - start.x, end.y - start.y);
          lanes.push({ a: start, b: end, edge: e, fresh, none });
          movers.push({ type: "boat", edge: e, a: start, b: end, len, period: Math.max(6, len / 7), phase: (seed + k * 0.41) % 1, tier: none ? "intuitive" : e.tier, fresh, twoWay, none });
        };
        const local = e.premises.filter((p) => world.pos[p].island === c.island);
        const away = {};
        e.premises.filter((p) => world.pos[p].island !== c.island).forEach((p) => (away[world.pos[p].island] ||= []).push(world.pos[p]));
        const awayKeys = Object.keys(away);
        const centre = (list) => ({ x: list.reduce((s, p) => s + p.x, 0) / list.length, y: list.reduce((s, p) => s + p.y, 0) / list.length });
        // Walkers are shown for links that touch a paper node or came from the crew; the many
        // base links inside a basis group are left to the simplified view (spec, open question).
        const paperish = e.layer.startsWith("journey:") || isJourney[e.conclusion] || e.premises.some((p) => isJourney[p]);
        if (!awayKeys.length) {
          if (!paperish) return;
          if (e.premises.length === 1) {
            walk(world.pos[e.premises[0]], c, 0);
            if (!e.directed) walk(c, world.pos[e.premises[0]], 1);
          } else {
            const m = centre(local.map((p) => world.pos[p]));
            const fire = { x: (m.x + c.x) / 2, y: (m.y + c.y) / 2 };
            fires.push({ ...fire, edge: e });
            local.forEach((p, k) => walk(world.pos[p], fire, k));
            walk(fire, c, 9);
          }
          return;
        }
        // Base links between islands are far too many to draw one by one (hundreds per pair), so
        // they are gathered into a small fleet per pair of islands, below. Nothing on land.
        if (!paperish) { awayKeys.forEach((k) => (fleets[k + ">" + c.island] ||= { from: k, to: c.island, edges: [] }).edges.push(e)); return; }
        if (e.premises.length === 1) { sail(world.pos[e.premises[0]], c, awayKeys[0], 0, !e.directed); return; }
        // A hyperedge across islands: boats land by a campfire near the conclusion, local premises
        // walk to it, and one walker carries on to the conclusion.
        const toward = centre(awayKeys.map((k) => centre(away[k])));
        const d = Math.hypot(toward.x - c.x, toward.y - c.y) || 1;
        const fire = local.length
          ? { x: (centre(local.map((p) => world.pos[p])).x + c.x) / 2, y: (centre(local.map((p) => world.pos[p])).y + c.y) / 2 }
          : { x: c.x + ((toward.x - c.x) / d) * T * 2, y: c.y + ((toward.y - c.y) / d) * T * 2 };
        fires.push({ ...fire, edge: e });
        awayKeys.forEach((k, i) => sail(centre(away[k]), fire, k, i, false));
        local.forEach((p, k) => walk(world.pos[p], fire, k));
        walk(fire, c, 9);
      });
      // One fleet per ordered pair of islands: a few boats (more for more links) on parallel lanes.
      const names = Object.fromEntries(world.islands.map((i) => [i.id, i.name]));
      Object.values(fleets).forEach((fleet) => {
        const ra = islandRect[fleet.from], rb = islandRect[fleet.to];
        const a = { x: ra.x + ra.w / 2, y: ra.y + ra.h / 2 }, b = { x: rb.x + rb.w / 2, y: rb.y + rb.h / 2 };
        const start = clip(a, b, ra, false), end = clip(a, b, rb, true);
        const len = Math.hypot(end.x - start.x, end.y - start.y) || 1;
        const nx = -(end.y - start.y) / len, ny = (end.x - start.x) / len;
        const boatsInFleet = Math.min(7, Math.ceil(Math.log2(fleet.edges.length + 1)));
        const tiers = { verified: 0, cited: 0, intuitive: 0 };
        fleet.edges.forEach((e) => (tiers[e.tier] = (tiers[e.tier] || 0) + 1));
        const tier = Object.keys(tiers).sort((x, y) => tiers[y] - tiers[x])[0];
        const info = { kind: "fleet", id: fleet.from + ">" + fleet.to, from: fleet.from, to: fleet.to, edges: fleet.edges.map((e) => e.id),
          name: `Fleet: ${fleet.edges.length} base link(s) from ${names[fleet.from]} to ${names[fleet.to]} — click to list them` };
        for (let k = 0; k < boatsInFleet; k++) {
          // Lanes sit to one side of the line between the islands, so the return fleet has its own side.
          const off = 6 + k * 9;
          const s0 = { x: start.x + nx * off, y: start.y + ny * off }, s1 = { x: end.x + nx * off, y: end.y + ny * off };
          if (k === 0) lanes.push({ a: s0, b: s1, fresh: false, none: false });
          movers.push({ type: "boat", info, a: s0, b: s1, len, period: Math.max(8, len / 6), phase: (Pixel.hash(info.id) / 4294967296 + k / boatsInFleet) % 1, tier, fresh: false, twoWay: false, none: false });
        }
      });
    }

    /* ---- Camera ---- */
    const size = () => ({ w: canvas.clientWidth || 1, h: canvas.clientHeight || 1 });
    function resize() {
      const { w, h } = size();
      canvas.width = w; canvas.height = h;
      ctx.imageSmoothingEnabled = false;
      draw();
    }
    function fit() {
      if (!world) return;
      const { w, h } = size();
      const z = [...ZOOMS].reverse().find((v) => world.world.w * v <= w && world.world.h * v <= h) || ZOOMS[0];
      cam = { x: world.world.w / 2, y: world.world.h / 2, zoom: z };
      changed();
    }
    function zoomBy(dir, sx, sy) {
      const i = ZOOMS.indexOf(cam.zoom) < 0 ? 1 : ZOOMS.indexOf(cam.zoom);
      const z = ZOOMS[Math.max(0, Math.min(ZOOMS.length - 1, i + dir))];
      if (z === cam.zoom) return;
      const { w, h } = size();
      const px = sx === undefined ? w / 2 : sx, py = sy === undefined ? h / 2 : sy;
      const wx = cam.x + (px - w / 2) / cam.zoom, wy = cam.y + (py - h / 2) / cam.zoom;
      cam = { zoom: z, x: wx - (px - w / 2) / z, y: wy - (py - h / 2) / z };
      changed();
    }
    function changed() {
      if (world) {
        cam.x = Math.max(0, Math.min(world.world.w, cam.x));
        cam.y = Math.max(0, Math.min(world.world.h, cam.y));
      }
      draw();
      if (hooks.onCamera) hooks.onCamera(cam, allVisible());
    }
    function allVisible() {
      const { w, h } = size();
      return !world || (world.world.w * cam.zoom <= w + 1 && world.world.h * cam.zoom <= h + 1);
    }
    const toScreen = (p) => { const { w, h } = size(); return { x: Math.round((p.x - cam.x) * cam.zoom + w / 2), y: Math.round((p.y - cam.y) * cam.zoom + h / 2) }; };
    const toWorld = (sx, sy) => { const { w, h } = size(); return { x: cam.x + (sx - w / 2) / cam.zoom, y: cam.y + (sy - h / 2) / cam.zoom }; };
    function anchor(sel) {
      if (!sel || !world) return null;
      if (sel.kind === "concept") return world.pos[sel.id] || null;
      if (sel.kind === "edge") {
        const e = data.edges.find((x) => x.id === sel.id);
        if (!e || !world.pos[e.conclusion]) return null;
        const ps = e.premises.map((p) => world.pos[p]).filter(Boolean);
        if (!ps.length) return world.pos[e.conclusion];
        const c = world.pos[e.conclusion];
        return { x: (ps.reduce((s, p) => s + p.x, 0) / ps.length + c.x) / 2, y: (ps.reduce((s, p) => s + p.y, 0) / ps.length + c.y) / 2 };
      }
      if (sel.kind === "island") { const i = world.islands.find((x) => x.id === sel.id); return i && { x: i.rect.x + i.rect.w / 2, y: i.rect.y + i.rect.h / 2 }; }
      if (sel.kind === "group") { for (const i of world.islands) { const l = i.leafRects.find((x) => x.group.id === sel.id); if (l) return { x: l.rect.x + l.rect.w / 2, y: l.rect.y + l.rect.h / 2 }; } }
      if (sel.kind === "paper") { for (const i of world.islands) { const p = i.patches.find((x) => x.paper && x.paper.id === sel.id); if (p) return { x: p.rect.x + p.rect.w / 2, y: p.rect.y + p.rect.h / 2 }; } }
      return null;
    }
    function panTo(sel, minZoom) {
      const p = sel && sel.x !== undefined ? sel : anchor(sel);
      if (!p) return false;
      cam = { x: p.x, y: p.y, zoom: Math.max(cam.zoom, minZoom || cam.zoom) };
      changed();
      return true;
    }

    /* ---- Drawing ---- */
    function moverAt(m, t) {
      let u = (t / 1000 / m.period + m.phase) % 1, dir = 1;
      if (m.twoWay) { dir = u < 0.5 ? 1 : -1; u = u < 0.5 ? u * 2 : 2 - u * 2; }
      return { x: m.a.x + (m.b.x - m.a.x) * u, y: m.a.y + (m.b.y - m.a.y) * u, dir: (m.b.x - m.a.x) * dir >= 0 ? 1 : -1, u };
    }
    function line(a, b, color, dash, width) {
      const p = toScreen(a), q = toScreen(b);
      ctx.strokeStyle = color; ctx.lineWidth = width; ctx.setLineDash(dash);
      ctx.beginPath(); ctx.moveTo(p.x + 0.5, p.y + 0.5); ctx.lineTo(q.x + 0.5, q.y + 0.5); ctx.stroke();
      ctx.setLineDash([]);
    }
    function label(text, x, y, px, color) {
      ctx.font = `bold ${px}px ui-monospace, Menlo, Consolas, monospace`;
      ctx.textAlign = "center"; ctx.lineWidth = 3; ctx.strokeStyle = "rgba(16,28,48,0.85)"; ctx.fillStyle = color || "#fdfdf5";
      ctx.strokeText(text, x, y); ctx.fillText(text, x, y);
    }
    function sparkle(x, y, w, h, t, seed) {
      const on = Math.floor(t / 260 + seed * 7) % 4;
      ctx.fillStyle = "#ffe27a";
      [[-2, -2], [w + 1, 1], [w, h], [-1, h - 1]].forEach(([dx, dy], i) => { if (i === on || i === (on + 2) % 4) ctx.fillRect(x + dx * cam.zoom / 2, y + dy * cam.zoom / 2, Math.max(2, cam.zoom), Math.max(2, cam.zoom)); });
    }
    function draw() {
      if (!world) return;
      const { w, h } = size();
      const z = cam.zoom, t = still ? 0 : performance.now() - started;
      hits = [];
      ctx.imageSmoothingEnabled = false;
      ctx.fillStyle = "#2a85c6"; ctx.fillRect(0, 0, w, h);
      // Open water: small wave marks that shimmer in place.
      const cell = 32, tl = toWorld(0, 0), br = toWorld(w, h), shift = Math.floor(t / 700) % 2;
      for (let gy = Math.floor(tl.y / cell); gy <= br.y / cell; gy++) for (let gx = Math.floor(tl.x / cell); gx <= br.x / cell; gx++) {
        const k = Pixel.hash(gx + ":" + gy);
        const p = toScreen({ x: gx * cell + (k % 23) + shift * 2, y: gy * cell + ((k >> 5) % 27) });
        ctx.fillStyle = k % 3 ? "#3f9dd3" : "#63b7d8";
        ctx.fillRect(p.x, p.y, Math.max(2, 5 * z), Math.max(1, z));
        if (k % 5 === 0) ctx.fillRect(p.x + 3 * z, p.y + 2 * z, Math.max(2, 3 * z), Math.max(1, z));
      }
      // Sea lanes under the boats.
      lanes.forEach((l) => line(l.a, l.b, l.none ? "rgba(188,62,69,0.7)" : l.fresh ? "rgba(255,226,122,0.75)" : "rgba(214,241,251,0.38)", [2 * z, 4 * z], Math.max(1, z / 2)));
      world.islands.forEach((isl) => {
        const p = toScreen(isl.rect);
        if (p.x > w || p.y > h || p.x + isl.rect.w * z < 0 || p.y + isl.rect.h * z < 0) return;
        ctx.drawImage(isl.canvas, p.x, p.y, isl.rect.w * z, isl.rect.h * z);
        if (filters.island && filters.island !== isl.id) { ctx.fillStyle = "rgba(42,133,198,0.55)"; ctx.fillRect(p.x, p.y, isl.rect.w * z, isl.rect.h * z); }
      });
      const detail = z >= 2;
      if (detail) {
        // Footpaths: solid for verified, dashed for cited, dotted for intuitive.
        trails.forEach((tr) => line(tr.a, tr.b, tr.none ? "rgba(188,62,69,0.9)" : tr.fresh ? "#ffe27a" : "rgba(74,52,35,0.55)", tr.tier === "verified" ? [] : tr.tier === "cited" ? [3 * z, 2 * z] : [z, 2 * z], Math.max(1, z / 2)));
        fires.forEach((f) => {
          const img = Pixel.FIRE[Math.floor(t / 220) % 2], p = toScreen({ x: f.x - 3.5, y: f.y - 5 });
          ctx.drawImage(img, p.x, p.y, 7 * z, 7 * z);
          hits.push({ x: p.x, y: p.y, w: 7 * z, h: 7 * z, info: { kind: "edge", id: f.edge.id, name: "Campfire: all premises meet (" + f.edge.type + ", " + f.edge.tier + ")" } });
        });
        chars.forEach((c) => {
          const p = toScreen({ x: c.pos.x - 6, y: c.pos.y - 6 }), s = 12 * z;
          if (p.x > w || p.y > h || p.x + s < 0 || p.y + s < 0) return;
          ctx.globalAlpha = c.dim ? 0.4 : 1;
          ctx.drawImage(c.item.canvas, p.x, p.y, s, s);
          ctx.globalAlpha = 1;
          if (!c.node.integrated) { ctx.strokeStyle = "#f5a623"; ctx.lineWidth = Math.max(1, z / 2); ctx.setLineDash([2 * z, 2 * z]); ctx.strokeRect(p.x - z + 0.5, p.y - z + 0.5, s + 2 * z, s + 2 * z); ctx.setLineDash([]); }
          if (c.fresh) sparkle(p.x, p.y, 12 * z, 12 * z, t, c.pos.x);
          const room = z >= 6 ? 18 : z >= 4 ? 9 : 0; // names appear once neighbours are far enough apart
          if (room) label(c.node.name.length > room ? c.node.name.slice(0, room - 1) + "…" : c.node.name, p.x + s / 2, p.y + s + 11, 10);
          hits.push({ x: p.x, y: p.y, w: s, h: s, info: { kind: "concept", id: c.node.id, name: c.node.name + " — " + c.item.name.toLowerCase() + (c.node.status === "Proposed" ? " (proposed, quarantined)" : "") + (c.node.integrated ? "" : " (unintegrated)") } });
        });
        movers.filter((m) => m.type === "walker").forEach((m) => {
          const at = moverAt(m, t), img = Pixel.walkers[m.tier][Math.floor(t / 240 + m.phase * 4) % 2];
          const p = toScreen({ x: at.x - 2.5, y: at.y - 7 });
          ctx.drawImage(img, p.x, p.y, 5 * z, 7 * z);
          if (m.fresh) sparkle(p.x, p.y, 5 * z, 7 * z, t, m.phase);
          hits.push({ x: p.x - z, y: p.y - z, w: 7 * z, h: 9 * z, info: { kind: "edge", id: m.edge.id, name: "Walker: " + m.edge.type + ", " + m.edge.tier + (m.fresh ? ", new in the latest run" : "") } });
        });
      }
      movers.filter((m) => m.type === "boat").forEach((m) => {
        const at = moverAt(m, t), set = Pixel.boats[m.tier][m.fresh ? "fresh" : "old"], img = at.dir > 0 ? set.right : set.left;
        const bob = still ? 0 : Math.round(Math.sin(t / 500 + m.phase * 9));
        const p = toScreen({ x: at.x - img.width / 2, y: at.y - img.height + 2 + bob });
        ctx.globalAlpha = m.none ? 0.55 : 1;
        ctx.drawImage(img, p.x, p.y, img.width * z, img.height * z);
        ctx.globalAlpha = 1;
        if (m.fresh) sparkle(p.x, p.y, img.width * z, img.height * z, t, m.phase);
        hits.push({ x: p.x, y: p.y, w: img.width * z, h: img.height * z, info: m.info || { kind: "edge", id: m.edge.id, name: set.name + ": " + m.edge.type + ", " + m.edge.tier + (m.fresh ? ", new in the latest run" : ", from an earlier run or the base graph") } });
      });
      // Labels: islands always; paper patches and subtopic codes once there is room.
      world.islands.forEach((isl) => {
        const p = toScreen({ x: isl.rect.x + isl.rect.w / 2, y: isl.rect.y });
        label(isl.name.toUpperCase() + " · " + isl.count, p.x, p.y - 6, Math.max(11, Math.min(18, 7 * z)));
        if (z >= 2) isl.patches.forEach((pt) => { const q = toScreen({ x: pt.rect.x + pt.rect.w / 2, y: pt.rect.y }); label(pt.paper ? (pt.paper.title.length > 26 ? pt.paper.title.slice(0, 25) + "…" : pt.paper.title) : "Crew finds", q.x, q.y - 3, 10, "#fff3c4"); });
        if (z >= 3) isl.leafRects.forEach((l) => { if (l.rect.w * z > 70 && l.group.msc) { const q = toScreen({ x: l.rect.x + 2, y: l.rect.y + 2 }); ctx.font = "10px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.fillStyle = "rgba(16,28,48,0.6)"; ctx.fillText(l.group.msc, q.x + 3, q.y + 11); } });
      });
      if (routePath && routePath.length > 1) {
        for (let i = 1; i < routePath.length; i++) line(routePath[i - 1], routePath[i], "#ffd24a", [4 * z, 3 * z], Math.max(2, z));
        routePath.forEach((p, i) => { const q = toScreen(p); ctx.fillStyle = i === 0 ? "#6fd66f" : i === routePath.length - 1 ? "#ff7a5a" : "#ffd24a"; ctx.fillRect(q.x - 2 * z, q.y - 2 * z, 4 * z, 4 * z); });
      }
      if (player) {
        const total = player.lengths[player.lengths.length - 1];
        const dist = Math.min(total, ((performance.now() - player.start) / 1000) * 34);
        let i = 1; while (i < player.lengths.length - 1 && player.lengths[i] < dist) i++;
        const a = routePath[i - 1], b = routePath[i], seg = player.lengths[i] - player.lengths[i - 1] || 1, u = (dist - player.lengths[i - 1]) / seg;
        const at = { x: a.x + (b.x - a.x) * u, y: a.y + (b.y - a.y) * u };
        const sea = !world.islands.some((i) => at.x >= i.rect.x && at.x < i.rect.x + i.rect.w && at.y >= i.rect.y && at.y < i.rect.y + i.rect.h); // walk on land, sail on water
        const img = sea ? (b.x >= a.x ? Pixel.boats.intuitive.fresh.right : Pixel.boats.intuitive.fresh.left) : Pixel.walkers.verified[Math.floor(performance.now() / 200) % 2];
        cam.x = at.x; cam.y = at.y;
        const p = toScreen({ x: at.x - img.width / 2, y: at.y - img.height });
        ctx.drawImage(img, p.x, p.y, img.width * z, img.height * z);
        sparkle(p.x, p.y, img.width * z, img.height * z, performance.now(), 0.3);
        if (dist >= total) { player = null; if (hooks.onPlayEnd) hooks.onPlayEnd(); }
      }
      const sel = anchor(selection);
      if (sel) { const q = toScreen(sel), r = (10 + (Math.floor(t / 300) % 2)) * Math.max(1, z / 2); ctx.strokeStyle = "#ffffff"; ctx.lineWidth = Math.max(2, z / 2); ctx.strokeRect(q.x - r, q.y - r, 2 * r, 2 * r); ctx.strokeStyle = "#101c30"; ctx.lineWidth = 1; ctx.strokeRect(q.x - r - 2, q.y - r - 2, 2 * r + 4, 2 * r + 4); }
      drawMini();
    }
    function drawMini() {
      const mw = mini.width, mh = mini.height;
      const s = Math.min(mw / world.world.w, mh / world.world.h);
      mctx.imageSmoothingEnabled = false;
      mctx.fillStyle = "#2a85c6"; mctx.fillRect(0, 0, mw, mh);
      world.islands.forEach((i) => mctx.drawImage(i.canvas, i.rect.x * s, i.rect.y * s, i.rect.w * s, i.rect.h * s));
      const { w, h } = size();
      mctx.strokeStyle = "#fdfdf5"; mctx.lineWidth = 2;
      mctx.strokeRect((cam.x - w / 2 / cam.zoom) * s, (cam.y - h / 2 / cam.zoom) * s, (w / cam.zoom) * s, (h / cam.zoom) * s);
    }

    /* ---- Pointing, dragging, zooming ---- */
    function pick(sx, sy) {
      for (let i = hits.length - 1; i >= 0; i--) { const b = hits[i]; if (sx >= b.x && sx <= b.x + b.w && sy >= b.y && sy <= b.y + b.h) return b.info; }
      const p = toWorld(sx, sy);
      const inside = (r) => p.x >= r.x && p.x < r.x + r.w && p.y >= r.y && p.y < r.y + r.h;
      for (const isl of world.islands) {
        if (!inside(isl.rect)) continue;
        const patch = isl.patches.find((pt) => inside(pt.rect));
        if (patch) return patch.paper ? { kind: "paper", id: patch.paper.id, name: "Paper patch: " + patch.paper.title + " (" + patch.nodes.length + " concepts)" } : { kind: "group", id: patch.group, name: "Crew finds" };
        const leaf = isl.leafRects.find((l) => inside(l.rect));
        if (leaf) return { kind: "group", id: leaf.group.id, name: (leaf.group.msc ? leaf.group.msc + " " : "") + leaf.group.name + " — " + leaf.count + " basis concepts" };
        return { kind: "island", id: isl.id, name: isl.name + " — " + isl.count + " concepts" };
      }
      return null;
    }
    const pointers = new Map();
    let drag = null, pinch = null, wheel = 0;
    const local = (e) => { const r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    canvas.addEventListener("pointerdown", (e) => {
      canvas.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, local(e));
      if (pointers.size === 1) drag = { ...local(e), cx: cam.x, cy: cam.y, moved: false };
      else if (pointers.size === 2) { const [a, b] = [...pointers.values()]; pinch = Math.hypot(a.x - b.x, a.y - b.y); drag = null; }
    });
    canvas.addEventListener("pointermove", (e) => {
      const p = local(e);
      if (pointers.has(e.pointerId)) pointers.set(e.pointerId, p);
      if (pinch && pointers.size === 2) {
        const [a, b] = [...pointers.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
        if (d > pinch * 1.35) { zoomBy(1, (a.x + b.x) / 2, (a.y + b.y) / 2); pinch = d; }
        else if (d < pinch * 0.72) { zoomBy(-1, (a.x + b.x) / 2, (a.y + b.y) / 2); pinch = d; }
        return;
      }
      if (drag) {
        if (Math.hypot(p.x - drag.x, p.y - drag.y) > 4) drag.moved = true;
        if (drag.moved) { cam.x = drag.cx - (p.x - drag.x) / cam.zoom; cam.y = drag.cy - (p.y - drag.y) / cam.zoom; player = null; changed(); }
        return;
      }
      if (hooks.onHover) hooks.onHover(world ? pick(p.x, p.y) : null, e.clientX, e.clientY);
    });
    const release = (e) => {
      const p = local(e);
      if (drag && !drag.moved && pointers.size === 1 && hooks.onClick) hooks.onClick(pick(p.x, p.y));
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = null;
      if (!pointers.size) drag = null;
    };
    canvas.addEventListener("pointerup", release);
    canvas.addEventListener("pointercancel", (e) => { pointers.delete(e.pointerId); drag = null; pinch = null; });
    canvas.addEventListener("pointerleave", () => hooks.onHover && hooks.onHover(null));
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      wheel += e.deltaY;
      if (Math.abs(wheel) < 50) return;
      const p = local(e);
      zoomBy(wheel < 0 ? 1 : -1, p.x, p.y);
      wheel = 0;
    }, { passive: false });
    const miniMove = (e) => {
      if (!world || !(e.buttons & 1) && e.type !== "pointerdown") return;
      const r = mini.getBoundingClientRect(), s = Math.min(mini.width / world.world.w, mini.height / world.world.h);
      cam.x = ((e.clientX - r.left) * (mini.width / r.width)) / s; cam.y = ((e.clientY - r.top) * (mini.height / r.height)) / s;
      changed();
    };
    mini.addEventListener("pointerdown", miniMove);
    mini.addEventListener("pointermove", miniMove);

    function run(on) {
      clearInterval(timer);
      if (on) { resize(); if (!still) timer = setInterval(draw, 100); }
    }
    return {
      setData, resize, fit, run, draw,
      zoomIn: () => zoomBy(1), zoomOut: () => zoomBy(-1),
      setFilters(f) { filters = f || {}; rebuild(); draw(); },
      setSelection(sel) { selection = sel; draw(); },
      setRoute(ids) { routePath = ids ? ids.map((id) => world.pos[id]).filter(Boolean) : null; player = null; draw(); },
      play() {
        if (!routePath || routePath.length < 2) return false;
        const lengths = [0];
        for (let i = 1; i < routePath.length; i++) lengths.push(lengths[i - 1] + Math.hypot(routePath[i].x - routePath[i - 1].x, routePath[i].y - routePath[i - 1].y));
        cam.zoom = Math.max(cam.zoom, 3);
        player = { start: performance.now(), lengths };
        if (still) { player = null; panTo(routePath[routePath.length - 1]); }
        return true;
      },
      panTo, anchor,
      camera: () => ({ ...cam }),
      setCamera(c) { cam = { x: c.x, y: c.y, zoom: ZOOMS.reduce((best, v) => (Math.abs(v - c.zoom) < Math.abs(best - c.zoom) ? v : best), ZOOMS[0]) }; changed(); },
      world: () => world,
      counts: () => ({ walkers: movers.filter((m) => m.type === "walker").length, boats: movers.filter((m) => m.type === "boat").length, fleets: new Set(movers.filter((m) => m.info).map((m) => m.info.id)).size, fires: fires.length, characters: chars.length }),
    };
  }
  return { create, layout, ZOOMS, T };
})();
