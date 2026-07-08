/* engine/edges.js — SVG edge rendering. INFRASTRUCTURE: rarely touched.
 *
 * ONE geometry function (`route`) draws every edge in every state: initial
 * layout, mid-drag, restored layout, any layout direction. Anchor sides are
 * chosen from the two boxes' relative positions (dominant axis), so top-down
 * or right-to-left layouts — and nodes dragged "behind" their sources — route
 * sensibly with no direction assumption baked in.
 *
 * Anchor points are computed in canvas (untransformed) coordinates by walking
 * the parent chain, so zoom/pan never enters the math — the whole canvas is
 * transformed as a unit by panzoom. Nodes inside a collapsed ancestor resolve
 * to that ancestor's box, so edges re-anchor automatically on collapse.
 *
 * Each path carries `edge--<type>` (args/calls/returns/...) — style edge
 * kinds from viewer.css without touching this file.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  const SVGNS = "http://www.w3.org/2000/svg";

  // Path + label midpoint for one edge, given source/target boxes.
  // Dominant axis picks the anchor sides; control points extend along it.
  function route(s, t) {
    const scx = s.x + s.w / 2;
    const scy = s.y + s.h / 2;
    const tcx = t.x + t.w / 2;
    const tcy = t.y + t.h / 2;
    let sx, sy, tx, ty, c1x, c1y, c2x, c2y;
    if (Math.abs(tcx - scx) >= Math.abs(tcy - scy)) {
      const dir = tcx >= scx ? 1 : -1;
      sx = dir > 0 ? s.x + s.w : s.x;
      sy = scy;
      tx = dir > 0 ? t.x : t.x + t.w;
      ty = tcy;
      const d = Math.max(40, Math.abs(tx - sx) * 0.4) * dir;
      c1x = sx + d;
      c1y = sy;
      c2x = tx - d;
      c2y = ty;
    } else {
      const dir = tcy >= scy ? 1 : -1;
      sx = scx;
      sy = dir > 0 ? s.y + s.h : s.y;
      tx = tcx;
      ty = dir > 0 ? t.y : t.y + t.h;
      const d = Math.max(40, Math.abs(ty - sy) * 0.4) * dir;
      c1x = sx;
      c1y = sy + d;
      c2x = tx;
      c2y = ty - d;
    }
    return {
      d: `M ${sx} ${sy} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${tx} ${ty}`,
      // Cubic bezier at t = 0.5.
      mid: {
        x: 0.125 * sx + 0.375 * c1x + 0.375 * c2x + 0.125 * tx,
        y: 0.125 * sy + 0.375 * c1y + 0.375 * c2y + 0.125 * ty,
      },
    };
  }

  // Canvas-space box for `id` itself (no collapse indirection).
  function boxOf(state, id) {
    let x = 0;
    let y = 0;
    let cur = id;
    while (cur != null && state.pos[cur]) {
      x += state.pos[cur].x;
      y += state.pos[cur].y;
      cur = state.parentOf[cur];
    }
    const self = state.pos[id] || { w: 0, h: 0 };
    const collapsed = state.collapsed && state.collapsed.has(id);
    return { x, y, w: self.w, h: collapsed ? Math.min(self.h, IOF.headerH()) : self.h };
  }

  // Absolute (canvas-space) box a node renders at: itself, or — when hidden
  // inside a collapsed container — its highest collapsed ancestor.
  function absPos(state, id) {
    let vis = id;
    let cur = state.parentOf[id];
    while (cur != null) {
      if (state.collapsed && state.collapsed.has(cur)) vis = cur;
      cur = state.parentOf[cur];
    }
    return boxOf(state, vis);
  }
  IOF.absPos = absPos;

  function routeFor(state, edge) {
    return route(absPos(state, edge.source), absPos(state, edge.target));
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
    // Remove existing edge elements, keep <defs>.
    Array.from(svg.querySelectorAll("path.edge")).forEach((p) => p.remove());
    Array.from(svg.querySelectorAll("text.edge-label")).forEach((t) => t.remove());
    state.edgeEls = [];
    state.graph.edges.forEach((edge) => {
      const r = routeFor(state, edge);
      const p = document.createElementNS(SVGNS, "path");
      p.setAttribute("class", "edge" + (edge.type ? " edge--" + edge.type : ""));
      p.setAttribute("d", r.d);
      p.setAttribute("marker-end", "url(#arrow)");
      p.setAttribute("data-source", edge.source);
      p.setAttribute("data-target", edge.target);
      if (edge.type) p.setAttribute("data-type", edge.type);
      svg.appendChild(p);

      let label = null;
      if (edge.label) {
        label = document.createElementNS(SVGNS, "text");
        label.setAttribute("class", "edge-label");
        label.setAttribute("text-anchor", "middle");
        label.textContent = edge.label;
        label.setAttribute("x", r.mid.x);
        label.setAttribute("y", r.mid.y);
        svg.appendChild(label);
      }
      state.edgeEls.push({ el: p, edge, label });
    });
    resize(state);
  }

  // Re-route only the edges touching `nodeId` (or its descendants) -- called on
  // every drag move.
  function updateFor(state, nodeId) {
    (state.edgeEls || []).forEach(({ el, edge, label }) => {
      if (
        edge.source === nodeId ||
        edge.target === nodeId ||
        isAncestor(state, nodeId, edge.source) ||
        isAncestor(state, nodeId, edge.target)
      ) {
        const r = routeFor(state, edge);
        el.setAttribute("d", r.d);
        if (label) {
          label.setAttribute("x", r.mid.x);
          label.setAttribute("y", r.mid.y);
        }
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

  IOF.edges = { renderAll, updateFor, resize, isAncestor };
})(window.IOFlow);
