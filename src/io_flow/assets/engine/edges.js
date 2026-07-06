/* engine/edges.js — SVG edge rendering. INFRASTRUCTURE: rarely touched.
 *
 * ONE geometry function (`bezier`) draws every edge in every state: initial
 * layout, mid-drag, and restored layout. Anchor points are computed in canvas
 * (untransformed) coordinates by walking the parent chain, so zoom/pan never
 * enters the math -- the whole canvas is transformed as a unit by panzoom.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  const SVGNS = "http://www.w3.org/2000/svg";

  function bezier(sx, sy, tx, ty) {
    const dx = Math.max(40, Math.abs(tx - sx) * 0.4);
    return `M ${sx} ${sy} C ${sx + dx} ${sy}, ${tx - dx} ${ty}, ${tx} ${ty}`;
  }

  // Absolute (canvas-space) box for a node: sum parent-relative offsets up the
  // ancestor chain.
  function absPos(state, id) {
    let x = 0;
    let y = 0;
    let cur = id;
    while (cur != null && state.pos[cur]) {
      x += state.pos[cur].x;
      y += state.pos[cur].y;
      cur = state.parentOf[cur];
    }
    const self = state.pos[id] || { w: 0, h: 0 };
    return { x, y, w: self.w, h: self.h };
  }
  IOF.absPos = absPos;

  function pathFor(state, edge) {
    const s = absPos(state, edge.source);
    const t = absPos(state, edge.target);
    return bezier(s.x + s.w, s.y + s.h / 2, t.x, t.y + t.h / 2);
  }

  function isAncestor(state, ancestor, id) {
    let cur = state.parentOf[id];
    while (cur != null) {
      if (cur === ancestor) return true;
      cur = state.parentOf[cur];
    }
    return false;
  }

  function renderAll(state) {
    const svg = state.svg;
    // Remove existing <path> elements, keep <defs>.
    Array.from(svg.querySelectorAll("path.edge")).forEach((p) => p.remove());
    state.edgeEls = [];
    state.graph.edges.forEach((edge) => {
      const p = document.createElementNS(SVGNS, "path");
      p.setAttribute("class", "edge");
      p.setAttribute("d", pathFor(state, edge));
      p.setAttribute("marker-end", "url(#arrow)");
      p.setAttribute("data-source", edge.source);
      p.setAttribute("data-target", edge.target);
      svg.appendChild(p);
      state.edgeEls.push({ el: p, edge });
    });
    resize(state);
  }

  // Re-route only the edges touching `nodeId` (or its descendants) -- called on
  // every drag move.
  function updateFor(state, nodeId) {
    (state.edgeEls || []).forEach(({ el, edge }) => {
      if (
        edge.source === nodeId ||
        edge.target === nodeId ||
        isAncestor(state, nodeId, edge.source) ||
        isAncestor(state, nodeId, edge.target)
      ) {
        el.setAttribute("d", pathFor(state, edge));
      }
    });
  }

  function resize(state) {
    let maxX = 0;
    let maxY = 0;
    state.graph.nodes.forEach((n) => {
      const a = absPos(state, n.id);
      maxX = Math.max(maxX, a.x + a.w);
      maxY = Math.max(maxY, a.y + a.h);
    });
    state.contentSize = { w: maxX, h: maxY };
    state.svg.setAttribute("width", maxX + 80);
    state.svg.setAttribute("height", maxY + 80);
  }

  IOF.edges = { renderAll, updateFor, resize, pathFor, isAncestor };
})(window.IOFlow);
