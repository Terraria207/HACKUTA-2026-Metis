"use strict";
/* Title screen scene: an ocean view from an island beach under a bright blue sky, with light
   animation (waves rolling in, drifting clouds, a ship on the horizon). Drawn at low resolution
   and scaled by a whole number so the pixels stay sharp. */
const TitleScene = (() => {
  let canvas, ctx, W, H, S, timer, start, still;
  const noise = Pixel.rng(7);
  const speckles = Array.from({ length: 260 }, () => [noise(), noise(), noise()]);
  const clouds = Array.from({ length: 6 }, (_, i) => ({ x: noise(), y: 0.05 + noise() * 0.24, w: 22 + noise() * 30, speed: 0.6 + noise() * 0.9, seed: i }));
  const ship = Pixel.boats.cited.fresh.right;

  function resize() {
    S = Math.max(2, Math.round(window.innerHeight / 210));
    W = Math.ceil(window.innerWidth / S);
    H = Math.ceil(window.innerHeight / S);
    canvas.width = W;
    canvas.height = H;
    canvas.style.width = W * S + "px";
    canvas.style.height = H * S + "px";
    ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    draw(still ? 0 : performance.now() - start);
  }
  const px = (color, x, y, w = 1, h = 1) => {
    ctx.fillStyle = color;
    ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  };

  function cloud(c, t) {
    const x = ((c.x * (W + 120) + (t / 1000) * c.speed) % (W + 120)) - 60;
    const y = c.y * H;
    const w = c.w;
    px("#ffffff", x + 4, y, w - 8, 3);
    px("#ffffff", x, y + 3, w, 4);
    px("#ffffff", x + w * 0.25, y - 3, w * 0.3, 3);
    px("#ffffff", x + w * 0.5, y - 2, w * 0.22, 2);
    px("#dcefff", x + 2, y + 7, w - 4, 2);
  }

  function palm(x, base) {
    for (let i = 0; i < 34; i++) px(i % 4 ? "#8a5a2b" : "#6e4a28", x + Math.round(Math.sin(i / 9) * 4), base - i, 4, 1);
    const top = base - 34;
    const tx = x + Math.round(Math.sin(34 / 9) * 4) + 1;
    [[-1, -0.35], [-1, 0.25], [1, -0.35], [1, 0.25], [-1, -0.9], [1, -0.9]].forEach(([dir, slope], k) => {
      for (let i = 0; i < 20; i++) {
        const y = top + slope * i + (i * i) / 34;
        px(k % 2 ? "#2f7a3a" : "#3f9a4a", tx + dir * i, y, 2, 2);
        if (i % 3 === 0) px("#256a30", tx + dir * i, y + 2, 1, 2);
      }
    });
    px("#6e4a28", tx - 1, top + 1, 3, 3);
  }

  function draw(t) {
    const horizon = Math.round(H * 0.44);
    const shore = Math.round(H * 0.74);
    // Sky: stepped bands, brightest at the horizon.
    const sky = ["#2f8fe6", "#3f9bea", "#52a8ee", "#68b6f2", "#80c4f5", "#9bd2f8", "#b7e0fa", "#d0ebfc"];
    sky.forEach((color, i) => px(color, 0, Math.floor((horizon * i) / sky.length), W, Math.ceil(horizon / sky.length) + 1));
    // Sun.
    const sx = Math.round(W * 0.8), sy = Math.round(H * 0.14);
    px("#fff3c4", sx - 9, sy - 5, 18, 10); px("#fff3c4", sx - 5, sy - 9, 10, 18); px("#fff3c4", sx - 8, sy - 8, 16, 16);
    px("#ffe27a", sx - 6, sy - 6, 12, 12); px("#ffd24a", sx - 4, sy - 4, 8, 8);
    clouds.forEach((c) => cloud(c, t));
    // A far island on the horizon.
    const ix = Math.round(W * 0.16);
    px("#5f8f7a", ix, horizon - 5, 46, 5); px("#5f8f7a", ix + 8, horizon - 9, 26, 4); px("#5f8f7a", ix + 15, horizon - 12, 10, 3);
    px("#e9e2cf", ix + 18, horizon - 15, 6, 3); px("#cbbf9f", ix + 17, horizon - 16, 8, 1);
    // Sea: darker out deep, lighter by the shore.
    const sea = ["#1f6fb5", "#2379bd", "#2a85c6", "#3391ce", "#3f9dd3", "#4faad6", "#63b7d8", "#7cc5da"];
    sea.forEach((color, i) => px(color, 0, horizon + Math.floor(((shore - horizon) * i) / sea.length), W, Math.ceil((shore - horizon) / sea.length) + 1));
    // The ship crossing the horizon.
    const shipX = ((t / 1000) * 2.2 + W * 0.45) % (W + 60) - 30;
    ctx.drawImage(ship, Math.round(shipX), horizon - 8 + Math.round(Math.sin(t / 900)));
    // Sparkles.
    speckles.slice(0, 90).forEach(([a, b, c], i) => {
      if (Math.sin(t / 420 + i * 1.7) > 0.55) px("#e6f6fb", a * W, horizon + 3 + b * (shore - horizon - 10), 2 + c * 3, 1);
    });
    // Waves rolling in: each crest travels from mid-sea to the shore, then starts again.
    for (let k = 0; k < 4; k++) {
      const phase = ((t / 5200 + k / 4) % 1);
      const y = horizon + 14 + phase * (shore - horizon - 16);
      const strength = Math.sin(phase * Math.PI);
      if (strength < 0.15) continue;
      for (let x = 0; x < W; x += 2) {
        const wobble = Math.round(Math.sin(x / 13 + k * 2 + t / 1400) * 2);
        if (Math.sin(x / 7 + k * 5) > -0.55) px(phase > 0.75 ? "#ffffff" : "#d8f1fb", x, y + wobble, 2, phase > 0.6 ? 2 : 1);
      }
    }
    // Sand, wet sand and the swash line breathing up and down the beach.
    px("#f0d9a0", 0, shore, W, H - shore);
    const swash = Math.round(3 + Math.sin(t / 1700) * 3);
    px("#d9bd7c", 0, shore, W, swash + 5);
    for (let x = 0; x < W; x += 1) {
      const edge = shore + swash + Math.round(Math.sin(x / 11 + t / 2300) * 1.5);
      px("#7cc5da", x, shore - 1, 1, edge - shore + 1);
      px("#ffffff", x, edge, 1, 2);
    }
    speckles.forEach(([a, b, c]) => {
      const y = shore + 12 + b * (H - shore - 12);
      px(c > 0.5 ? "#e3c784" : "#f7e6b8", a * W, y, 1 + (c > 0.8 ? 1 : 0), 1);
    });
    // Foreground: rocks, a shell, a starfish, and a palm leaning over the beach.
    const rx = Math.round(W * 0.84), ry = H - 26;
    px("#7c7f86", rx, ry, 26, 14); px("#9a9da4", rx + 3, ry - 5, 18, 6); px("#63666d", rx, ry + 10, 26, 4); px("#b4b7bd", rx + 5, ry - 3, 6, 2);
    px("#8f9299", rx - 14, ry + 6, 12, 8); px("#a9acb3", rx - 12, ry + 4, 7, 3);
    const stx = Math.round(W * 0.63), sty = H - 16;
    px("#e8694a", stx, sty, 7, 1); px("#e8694a", stx + 3, sty - 3, 1, 7); px("#e8694a", stx + 1, sty - 1, 5, 3); px("#f59b7a", stx + 3, sty, 1, 1);
    const shx = Math.round(W * 0.38), shy = H - 11;
    px("#fbe9f0", shx, shy, 6, 3); px("#e8b7c8", shx + 1, shy + 3, 4, 1); px("#e8b7c8", shx + 2, shy, 1, 3); px("#e8b7c8", shx + 4, shy, 1, 3);
    palm(Math.round(W * 0.07), H - 4);
    px("#3f9a4a", 0, H - 6, Math.round(W * 0.16), 6); px("#2f7a3a", 0, H - 3, Math.round(W * 0.19), 3);
  }

  function init(el) {
    canvas = el;
    still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    start = performance.now();
    resize();
    window.addEventListener("resize", resize);
  }
  function run(on) {
    clearInterval(timer);
    if (on && !still) timer = setInterval(() => draw(performance.now() - start), 110);
    else if (on) draw(0);
  }
  return { init, run };
})();
