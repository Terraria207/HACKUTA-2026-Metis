# Vendored browser libraries

- `cytoscape.min.js` — Cytoscape.js 3.35.0, MIT License (Copyright (c) 2016-2026, The Cytoscape
  Consortium; license text at the top of the file). Fetched from the npm package `cytoscape@3.35.0`
  (`dist/cytoscape.min.js`), SHA-256 `71fa9ebec21a7ca2c40cff6aacc30d1f6464e363662ad4b2c197e1adc770cd94`.
  Served same-origin under `/static/vendor/` so the strict Content-Security-Policy (`script-src 'self'`)
  holds; no CDN, no build step.

The overview's implementation notes call for a graph library such as Sigma.js or Cytoscape.js so
a few thousand nodes render smoothly; the Graph tab uses Cytoscape's canvas renderer with island
compound nodes, hyperedge junction nodes and a keyboard-accessible list beside the canvas.
