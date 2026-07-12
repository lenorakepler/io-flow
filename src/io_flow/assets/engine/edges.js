/* engine/edges.js — SVG edge rendering. INFRASTRUCTURE: rarely touched.
 *
 * ONE geometry pass draws every edge in every state: initial layout,
 * mid-drag, restored layout, any layout direction. Anchor sides are chosen
 * from the two boxes' relative positions (dominant axis), so top-down or
 * right-to-left layouts — and nodes dragged "behind" their sources — route
 * sensibly with no direction assumption baked in.
 *
 * Anchors STACK: all edges using the same side of the same node get their
 * own band along that side — sorted by where their other endpoint sits (so
 * flows don't cross at the node), sized by stroke width, centered as a
 * stack, and squeezed to fit when a side is short. A side with one edge
 * anchors at its center, exactly as before; a fan-out of weighted edges
 * reads like a sankey, with widths stacking instead of piling on the
 * midpoint.
 *
 * Anchor points are computed in canvas (untransformed) coordinates by
 * walking the parent chain, so zoom/pan never enters the math — the whole
 * canvas is transformed as a unit by panzoom. Nodes inside a collapsed
 * ancestor resolve to that ancestor's box, so edges re-anchor (and their
 * stacks regroup) automatically on collapse.
 *
 * Each path carries `edge--<type>` (args/calls/returns/...) — style edge
 * kinds from viewer.css without touching this file.
 *
 * Edges with a numeric `weight` (flow volumes) additionally scale their
 * stroke width — sqrt-damped by default, tunable from the YAML
 * `diagram: edgeWidth:` block — carry `edge--weighted`, and use a
 * fixed-size arrowhead (the default marker scales with stroke width).
 * Unweighted edges are untouched: width stays a viewer.css concern.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  const SVGNS = "http://www.w3.org/2000/svg";

  const GAP = 3; // px between stacked anchor bands on one node side
  const PAD = 8; // stack inset from the side's corners
  const BASE_BAND = 2; // nominal band for unweighted edges (~CSS stroke width)

  // Map numeric edge weights to stroke widths. Proportional to the diagram's
  // heaviest flow, sqrt-damped so a 100x volume isn't a 100x line. Returns
  // null for unweighted edges (their width stays a viewer.css concern).
  // Config: diagram: edgeWidth: {min: 1.5, max: 12, scale: sqrt | linear}.
  function weightScale(graph) {
    const weights = graph.edges
      .map((e) => e.weight)
      .filter((w) => typeof w === "number" && w > 0);
    if (!weights.length) return () => null;
    const cfg = (graph.diagram && graph.diagram.edgeWidth) || {};
    const lo = cfg.min != null ? +cfg.min : 1.5;
    const hi = cfg.max != null ? +cfg.max : 12;
    const f = cfg.scale === "linear" ? (x) => x : Math.sqrt;
    const top = f(Math.max.apply(null, weights));
    return (edge) =>
      typeof edge.weight === "number" && edge.weight > 0
        ? lo + (hi - lo) * (f(edge.weight) / top)
        : null;
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

  // The node a hidden-inside-a-collapsed-container edge endpoint renders at:
  // itself, or its highest collapsed ancestor.
  function visibleIdOf(state, id) {
    let vis = id;
    let cur = state.parentOf[id];
    while (cur != null) {
      if (state.collapsed && state.collapsed.has(cur)) vis = cur;
      cur = state.parentOf[cur];
    }
    return vis;
  }

  function absPos(state, id) {
    return boxOf(state, visibleIdOf(state, id));
  }
  IOF.absPos = absPos;

  // ---- Geometry pass ---------------------------------------------------------
  // One entry per edge, aligned with graph.edges order: resolved endpoint
  // boxes, the routing axis (dominant), stroke width, and — after the
  // stacking step — the exact source/target anchor points.
  function computeGeometry(state) {
    const widthOf = weightScale(state.graph);
    const eps = state.graph.edges.map((edge) => {
      const sVis = visibleIdOf(state, edge.source);
      const tVis = visibleIdOf(state, edge.target);
      const s = boxOf(state, sVis);
      const t = boxOf(state, tVis);
      const horiz =
        Math.abs(t.x + t.w / 2 - (s.x + s.w / 2)) >= Math.abs(t.y + t.h / 2 - (s.y + s.h / 2));
      const dir = horiz
        ? t.x + t.w / 2 >= s.x + s.w / 2
          ? 1
          : -1
        : t.y + t.h / 2 >= s.y + s.h / 2
          ? 1
          : -1;
      const width = widthOf(edge);
      return {
        edge,
        sVis,
        tVis,
        s,
        t,
        horiz,
        dir,
        width,
        band: width != null ? width : BASE_BAND,
        // Both endpoints inside the same collapsed compound: the edge is
        // interior detail of a closed box -- don't draw it, and don't let
        // it occupy anchor slots that real edges need.
        hidden: sVis === tVis,
        sAnchor: { x: s.x + s.w / 2, y: s.y + s.h / 2 },
        tAnchor: { x: t.x + t.w / 2, y: t.y + t.h / 2 },
      };
    });

    // Group endpoint usages by (visible node, side). Key sides by axis +
    // sign so "exits west" and "enters west" share one stack on that side.
    const groups = {};
    eps.forEach((ep) => {
      if (ep.hidden) return;
      const axis = ep.horiz ? "h" : "v";
      const sKey = ep.sVis + "|" + axis + (ep.dir > 0 ? "+" : "-");
      const tKey = ep.tVis + "|" + axis + (ep.dir > 0 ? "-" : "+");
      (groups[sKey] = groups[sKey] || []).push({ ep, end: "s" });
      (groups[tKey] = groups[tKey] || []).push({ ep, end: "t" });
    });

    Object.values(groups).forEach((entries) => {
      entries.forEach((en) => {
        en.box = en.end === "s" ? en.ep.s : en.ep.t;
        const other = en.end === "s" ? en.ep.t : en.ep.s;
        en.sort = en.ep.horiz ? other.y + other.h / 2 : other.x + other.w / 2;
      });
      entries.sort((a, b) => a.sort - b.sort);

      const box = entries[0].box;
      const horiz = entries[0].ep.horiz; // uniform per group (key includes axis)
      const side = (horiz ? box.h : box.w) - 2 * PAD;
      const total =
        entries.reduce((acc, en) => acc + en.ep.band, 0) + GAP * (entries.length - 1);
      const scale = side > 0 && total > side ? side / total : 1;
      let cursor = (horiz ? box.y + box.h / 2 : box.x + box.w / 2) - (total * scale) / 2;

      entries.forEach((en) => {
        const mid = cursor + (en.ep.band * scale) / 2;
        cursor += (en.ep.band + GAP) * scale;
        // Which face of the box: the source exits toward dir, the target is
        // entered from the opposite face.
        const plusFace = en.end === "s" ? en.ep.dir > 0 : en.ep.dir < 0;
        const p = horiz
          ? { x: plusFace ? en.box.x + en.box.w : en.box.x, y: mid }
          : { x: mid, y: plusFace ? en.box.y + en.box.h : en.box.y };
        if (en.end === "s") en.ep.sAnchor = p;
        else en.ep.tAnchor = p;
      });
    });

    return eps;
  }

  // Bezier path + label midpoint from the stacked anchors; control points
  // extend along the routing axis.
  function routeOf(ep) {
    const sx = ep.sAnchor.x;
    const sy = ep.sAnchor.y;
    const tx = ep.tAnchor.x;
    const ty = ep.tAnchor.y;
    let c1x, c1y, c2x, c2y;
    if (ep.horiz) {
      const d = Math.max(40, Math.abs(tx - sx) * 0.4) * ep.dir;
      c1x = sx + d;
      c1y = sy;
      c2x = tx - d;
      c2y = ty;
    } else {
      const d = Math.max(40, Math.abs(ty - sy) * 0.4) * ep.dir;
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

  function applyGeometry(state, eps) {
    state.edgeEls.forEach((rec, i) => {
      const ep = eps[i];
      rec.el.style.display = ep.hidden ? "none" : "";
      if (rec.label) rec.label.style.display = ep.hidden ? "none" : "";
      if (ep.hidden) return;
      const r = routeOf(ep);
      rec.el.setAttribute("d", r.d);
      if (rec.label) {
        rec.label.setAttribute("x", r.mid.x);
        rec.label.setAttribute("y", r.mid.y);
      }
    });
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
    const eps = computeGeometry(state);
    eps.forEach(({ edge, width }) => {
      const p = document.createElementNS(SVGNS, "path");
      p.setAttribute(
        "class",
        "edge" +
          (edge.type ? " edge--" + edge.type : "") +
          (width != null ? " edge--weighted" : "")
      );
      if (width != null) p.style.strokeWidth = width.toFixed(1) + "px";
      p.setAttribute("marker-end", width != null ? "url(#arrow-flow)" : "url(#arrow)");
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
        svg.appendChild(label);
      }
      state.edgeEls.push({ el: p, edge, label });
    });
    applyGeometry(state, eps);
    resize(state);
  }

  // Re-route on drag/nudge. Anchor stacks depend on neighbors' relative
  // positions, so all edges are recomputed — a moved node can reorder or
  // re-side stacks on nodes it isn't connected to only via shared groups,
  // and at this tool's scale (low hundreds of edges) a full pass per move
  // is cheap. The nodeId argument is kept for API compatibility.
  function updateFor(state, _nodeId) {
    applyGeometry(state, computeGeometry(state));
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
