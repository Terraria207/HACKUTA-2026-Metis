"use strict";
/* Pixel art for Metis, drawn from palette-indexed grids so everything stays crisp at whole-number
   zoom. No external images except the METIS wordmark. */
const Pixel = (() => {
  function make(w, h) {
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    const ctx = c.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    return [c, ctx];
  }
  function grid(rows, palette) {
    const [c, ctx] = make(rows[0].length, rows.length);
    rows.forEach((row, y) => {
      for (let x = 0; x < row.length; x++) {
        const color = palette[row[x]];
        if (color) {
          ctx.fillStyle = color;
          ctx.fillRect(x, y, 1, 1);
        }
      }
    });
    return c;
  }
  function flip(src) {
    const [c, ctx] = make(src.width, src.height);
    ctx.translate(src.width, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(src, 0, 0);
    return c;
  }
  function hash(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619);
    return h >>> 0;
  }
  function rng(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function shade(hex, amount) {
    const n = parseInt(hex.slice(1), 16);
    const f = (v) => Math.max(0, Math.min(255, Math.round(v + 255 * amount)));
    return "#" + [f(n >> 16), f((n >> 8) & 255), f(n & 255)].map((v) => v.toString(16).padStart(2, "0")).join("");
  }

  /* ---- Paper nodes: Odyssey items and creatures (12x12). A node's sprite is chosen by a hash of
     its id, so the map looks the same on every visit. ---- */
  const ITEMS = [
    { name: "Cyclops", rows: ["...gggggg...", "..gggggggg..", ".gggggggggg.", ".gggwwwwggg.", ".ggwwkkwwgg.", ".ggwwkkwwgg.", ".gggwwwwggg.", ".gggggggggg.", "..ggkkkkgg..", "..gggggggg..", "...gg..gg...", "...gg..gg..."], pal: { g: "#8fa77a", w: "#f6f3e6", k: "#2b2a33" } },
    { name: "Amphora", rows: ["....dddd....", "....oooo....", ".....oo.....", "..d.oooo.d..", ".d.oooooo.d.", ".d.okkkko.d.", "..dooooood..", "...oooooo...", "...okkkko...", "....oooo....", ".....oo.....", "....dddd...."], pal: { o: "#c9703c", d: "#8a4526", k: "#2b2a33" } },
    { name: "Lyre", rows: [".yy......yy.", "..y......y..", "..y.s.ss.y..", "..y.s.ss.y..", "..y.s.ss.y..", "..y.s.ss.y..", "..yyyyyyyy..", "...bbbbbb...", "...bbbbbb...", "....bbbb....", "............", "............"], pal: { y: "#e3b341", s: "#f6f3e6", b: "#8a5a2b" } },
    { name: "Owl", rows: ["..b......b..", "..bbbbbbbb..", ".bbbbbbbbbb.", ".bwwbbbbwwb.", ".bwkwbbwkwb.", ".bwwbyybwwb.", ".bbbbyybbbb.", ".bbwbwbwbbb.", ".bbbwbwbwbb.", "..bbbbbbbb..", "...bb..bb...", "...yy..yy..."], pal: { b: "#8a6a45", w: "#f6f3e6", k: "#2b2a33", y: "#e3b341" } },
    { name: "Sheep", rows: ["............", "...wwwwww...", "..wwwwwwww..", ".wwwwwwwwkk.", ".wwwwwwwwkkk", ".wwwwwwwwkk.", ".wwwwwwwww..", "..wwwwwww...", "..k.k..k.k..", "..k.k..k.k..", "............", "............"], pal: { w: "#f6f3e6", k: "#3a3540" } },
    { name: "Pig", rows: ["............", "............", "..pp....pp..", ".pppppppppp.", ".ppppppppkpd", ".pppppppppdd", ".ppppppppppd", ".pppppppppp.", "..pp.pp.pp..", "..dd.dd.dd..", "............", "............"], pal: { p: "#f0a7b0", d: "#c9727e", k: "#2b2a33" } },
    { name: "Lotus", rows: ["............", ".....pp.....", "..p.pppp.p..", "..pppwwppp..", ".pppwyywppp.", ".ppwwyywwpp.", "..pppwwppp..", "...pppppp...", ".....gg.....", "..gg.gg.gg..", "...gggggg...", "....gggg...."], pal: { p: "#e88bb0", w: "#fbe9f0", y: "#e3b341", g: "#3f8a4a" } },
    { name: "Bow", rows: ["....bbb.....", "...b...s....", "..b.....s...", "..b.....s...", ".b......s...", ".baaaaaasahh", ".b......s...", "..b.....s...", "..b.....s...", "...b...s....", "....bbb.....", "............"], pal: { b: "#8a5a2b", s: "#f6f3e6", a: "#c9a66b", h: "#9aa3ad" } },
    { name: "Helmet", rows: ["....rrrr....", "...rrrrrr...", "..rrzzzzrr..", "..rzzzzzzr..", ".zzzzzzzzzz.", ".zzzzzzzzzz.", ".zzkkzzkkzz.", ".zzkkzzkkzz.", ".zzzzzzzzzz.", ".zzz.zz.zzz.", ".zz..zz..zz.", "............"], pal: { r: "#c93d3d", z: "#c9973c", k: "#2b2a33" } },
    { name: "Trident", rows: [".c...c...c..", ".c...c...c..", ".c...c...c..", ".cc..c..cc..", "..ccccccc...", ".....c......", ".....b......", ".....b......", ".....b......", ".....b......", ".....b......", ".....b......"], pal: { c: "#a9d6dc", b: "#8a5a2b" } },
    { name: "Wooden horse", rows: [".......bb...", "......bbbb..", "......bb.bd.", ".....bbb....", ".bbbbbbb....", "bbbbbbbbb...", "bbbbbbbbb...", ".bbbbbbb....", ".b.b..b.b...", ".b.b..b.b...", "dddddddddd..", ".w......w..."], pal: { b: "#b07a45", d: "#6e4a28", w: "#3a3540" } },
    { name: "Siren", rows: ["....ssss....", "....sksk....", "....ssss....", "..f.ffff.f..", ".fffffffffff", ".fffffffffff", "..fffffffff.", "...fffffff..", "....ff.ff...", "....y...y...", "...yy..yy...", "............"], pal: { s: "#f0c9a0", k: "#2b2a33", f: "#5b7fd1", y: "#e3b341" } },
    { name: "Whirlpool", rows: ["...wwwwww...", "..w......w..", ".w..wwww..w.", ".w.w....w.w.", "w.w..ww..w.w", "w.w.w..w.w.w", "w.w.w.ww.w.w", "w.w..w...w.w", ".w.w..www.w.", ".w..w.....w.", "..w..wwwww..", "...ww......."], pal: { w: "#e6f6fb" } },
    { name: "Olive branch", rows: ["..........g.", ".....gg..gg.", "....ggg.gg..", "..o..gggg...", ".ggg.gdg..o.", "..gggdggggg.", "...gdgg.ggg.", "..gdg..o....", ".gdgg.......", ".dgg........", "dg..........", "............"], pal: { g: "#6fae4a", d: "#3f7a34", o: "#5a3d6e" } },
  ].map((item) => ({ name: item.name, canvas: grid(item.rows, item.pal) }));
  const itemFor = (id) => ITEMS[hash(id) % ITEMS.length];

  /* ---- Walkers (tunic colour shows the edge's tier) and the hyperedge campfire ---- */
  const WALK = [
    [".hh..", ".ss..", "ttttt", ".ttt.", ".ttt.", ".l.l.", ".l.l."],
    [".hh..", ".ss..", "ttttt", ".ttt.", ".ttt.", "..l..", ".l.l."],
  ];
  const TUNIC = { verified: "#f6f3e6", cited: "#4f7fd6", intuitive: "#b5653a", none: "#8d8d8d" };
  const walkers = {};
  Object.entries(TUNIC).forEach(([tier, color]) => {
    walkers[tier] = WALK.map((rows) => grid(rows, { h: "#4a3423", s: "#f0c9a0", t: color, l: "#4a3423" }));
  });
  const FIRE = [
    ["...y...", "..yoy..", ".yoroy.", ".oryro.", "..rrr..", ".bb.bb.", "b.bbb.b"],
    ["..y....", "..oyy..", ".yoro..", ".oryro.", "..rrr..", ".bb.bb.", "b.bbb.b"],
  ].map((rows) => grid(rows, { y: "#ffe27a", o: "#f59b3a", r: "#d6452e", b: "#5a3d2b" }));

  /* ---- Boats: hull shows strength, sail shows age (UI spec, proposed mapping) ---- */
  const HULLS = {
    verified: { name: "Trireme", rows: ["........m...........", ".....SSSmSSS........", ".....SSSmSSS........", ".....sSSmSSs........", ".....SSpmSSS........", "........m...........", "h.......m.........r.", "hHHHHHHHHHHHHHHHHerr", ".hhhhhhhhhhhhhhhhhr.", "..o.o.o.o.o.o.o.o...", ".o.o.o.o.o.o.o.o...."] },
    cited: { name: "Merchant ship", rows: [".......m........", "..SSSSSmSSSSS...", "..SSSSSmSSSSS...", "..sSSSSmSSSSs...", "..SSSpSmSSSSS...", "..SSSSSmSSSSS...", ".......m........", "h......m......h.", "hH....HHH....Hh.", ".hHHHHHHHHHHHh..", "..hhhhhhhhhhh..."] },
    intuitive: { name: "Raft", rows: [".....m......", "...SSm......", "...SSm......", "...sSm......", ".....m......", "wWwWwWwWwWw.", "WwWwWwWwWwW."] },
  };
  const SAILS = {
    fresh: { S: "#fdfdf5", s: "#d94a3a", p: "#fdfdf5" },
    old: { S: "#b9a57a", s: "#9c8a62", p: "#6e5b3a" },
  };
  const boats = {};
  Object.entries(HULLS).forEach(([tier, hull]) => {
    boats[tier] = {};
    Object.entries(SAILS).forEach(([age, sail]) => {
      const right = grid(hull.rows, { h: "#5a3d2b", H: "#8a5a2b", m: "#3a2a1c", o: "#c9a66b", r: "#c9973c", e: "#fdfdf5", w: "#8a5a2b", W: "#a8743c", ...sail });
      boats[tier][age] = { right, left: flip(right), name: hull.name };
    });
  });

  /* ---- Portraits (16x16), built from features so each speaker is distinct ---- */
  function portrait(spec) {
    const [c, ctx] = make(16, 16);
    const px = (color, x, y, w = 1, h = 1) => {
      ctx.fillStyle = color;
      ctx.fillRect(x, y, w, h);
    };
    px(spec.bg, 0, 0, 16, 16);
    if (spec.icon === "temple") {
      px("#fff3c4", 6, 1, 4, 1); px("#ffe27a", 4, 2, 8, 1);
      px("#f3ead2", 7, 3, 2, 1); px("#f3ead2", 5, 4, 6, 1); px("#f3ead2", 3, 5, 10, 1); px("#cbbf9f", 2, 6, 12, 1);
      [3, 6, 9, 12].forEach((x) => { px("#f3ead2", x, 7, 1, 6); px("#cbbf9f", x + 1, 7, 1, 6); });
      px("#cbbf9f", 2, 13, 12, 1); px("#a89c7f", 1, 14, 14, 2);
      return c;
    }
    if (spec.icon === "scroll") {
      px("#8a5a2b", 2, 3, 12, 2); px("#f3e2b3", 3, 5, 10, 8); px("#8a5a2b", 2, 13, 12, 2);
      [6, 8, 10].forEach((y) => px("#7a6a4a", 5, y, 6, 1));
      px("#fdfdf5", 11, 1, 1, 6); px("#fdfdf5", 12, 0, 2, 3); px("#2b2a33", 11, 7, 1, 1);
      return c;
    }
    px(spec.tunic, 2, 13, 12, 3); px(spec.tunic, 4, 12, 8, 1);       // shoulders
    px(spec.skin, 6, 11, 4, 2);                                      // neck
    px(spec.skin, 4, 4, 8, 7); px(spec.skin, 5, 11, 6, 1);           // face
    px(shadeOf(spec.skin), 4, 10, 8, 1);
    if (spec.hair) {
      px(spec.hair, 4, 2, 8, 2); px(spec.hair, 3, 3, 1, 4); px(spec.hair, 12, 3, 1, 4);
      if (spec.long) { px(spec.hair, 3, 7, 1, 6); px(spec.hair, 12, 7, 1, 6); px(spec.hair, 2, 9, 1, 5); px(spec.hair, 13, 9, 1, 5); }
      if (spec.curly) [3, 5, 7, 9, 11].forEach((x) => px(spec.hair, x, 1, 1, 1));
    }
    if (spec.eyes === "closed") { px("#3a3540", 5, 7, 2, 1); px("#3a3540", 9, 7, 2, 1); }
    else if (spec.eyes === "band") px("#e9e2cf", 4, 6, 8, 2);
    else { px("#fdfdf5", 5, 6, 2, 2); px("#fdfdf5", 9, 6, 2, 2); px("#2b2a33", 6, 7, 1, 1); px("#2b2a33", 10, 7, 1, 1); }
    px(shadeOf(spec.skin), 7, 8, 2, 1);                              // nose
    if (spec.beard) {
      px(spec.beard, 4, 9, 8, 2); px(spec.beard, 5, 11, 6, 1); px(spec.skin, 7, 9, 2, 1);
      if (spec.beard_long) { px(spec.beard, 5, 12, 6, 2); px(spec.beard, 6, 14, 4, 1); }
    } else px("#b0584a", 7, 10, 2, 1);                               // mouth
    if (spec.hat === "helmet") { px("#c9973c", 3, 2, 10, 3); px("#c9973c", 3, 5, 1, 4); px("#c9973c", 12, 5, 1, 4); px("#c9973c", 7, 5, 2, 3); px("#c93d3d", 6, 0, 4, 2); px("#c93d3d", 7, 0, 2, 1); }
    if (spec.hat === "pilos") { px("#b9b2a3", 5, 0, 6, 1); px("#b9b2a3", 4, 1, 8, 2); px("#8f897c", 3, 3, 10, 1); }
    if (spec.hat === "veil") { px(spec.veil, 3, 1, 10, 2); px(spec.veil, 2, 3, 2, 10); px(spec.veil, 12, 3, 2, 10); px(spec.veil, 4, 3, 8, 1); }
    if (spec.hat === "band") px(spec.band, 4, 3, 8, 1);
    if (spec.hat === "cap") { px("#6e4a28", 4, 1, 8, 2); px("#6e4a28", 3, 3, 10, 1); }
    if (spec.soot) { px("#5b5560", 5, 9, 1, 1); px("#5b5560", 10, 5, 1, 1); }
    return c;
  }
  function shadeOf(hex) { return shade(hex, -0.12); }
  const PORTRAITS = {
    odysseus: { bg: "#27425e", tunic: "#3f6fb0", skin: "#e2b48a", hair: "#6e4a28", beard: "#6e4a28", hat: "pilos" },
    penelope: { bg: "#4a3560", tunic: "#8e5bb0", skin: "#f0c9a0", hair: "#3a2a1c", long: true, hat: "veil", veil: "#b08ad6" },
    hephaestus: { bg: "#7a3b1c", tunic: "#5a3d2b", skin: "#d9a273", hair: "#2b2a33", curly: true, beard: "#2b2a33", beard_long: true, hat: "cap", soot: true },
    tiresias: { bg: "#4b4f57", tunic: "#9aa3ad", skin: "#e2c4a4", hair: "#f6f3e6", long: true, beard: "#f6f3e6", beard_long: true, eyes: "closed" },
    eurylochus: { bg: "#5e2f2a", tunic: "#a8483c", skin: "#e2b48a", beard: "#4a3423", hat: "helmet" },
    elpenor: { bg: "#2f5e4a", tunic: "#6fae4a", skin: "#f0c9a0", hair: "#e3b341", hat: "band", band: "#fdfdf5" },
    polites: { bg: "#2f4f3a", tunic: "#3f8a4a", skin: "#d9a273", hair: "#8a5a2b", curly: true, beard: "#8a5a2b" },
    perimedes: { bg: "#3a3540", tunic: "#6b6f7a", skin: "#e2b48a", hair: "#2b2a33", hat: "band", band: "#c93d3d" },
    gods: { bg: "#3f6fb0", icon: "temple" },
    decomposer: { bg: "#5a4a3a", icon: "scroll" },
  };
  const portraits = {};
  Object.entries(PORTRAITS).forEach(([key, spec]) => (portraits[key] = portrait(spec)));

  return { make, grid, flip, hash, rng, shade, itemFor, ITEMS, walkers, FIRE, boats, portraits, TUNIC };
})();
