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

  // Declared anchor faces: box face name -> {axis, sign}. "h" runs east/west
  // (sign +1 = right face), "v" runs north/south (sign +1 = bottom face) --
  // the same encoding the automatic dominant-axis rule produces, so declared
  // and automatic endpoints share stacks on a face. Edges carry
  // `anchor: {from, to}` (per-edge or stamped from a relation by the
  // parser); nodes may declare `anchors: {in, out}` as free data.
  const SIDES = {
    left: { axis: "h", sign: -1 },
    right: { axis: "h", sign: 1 },
    top: { axis: "v", sign: -1 },
    bottom: { axis: "v", sign: 1 },
  };

  // Sankey mode: `diagram: sankey:` declares that node populations and edge
  // weights are the same data unit and must render exactly proportionally --
  // node height = population * unit (applied by viewer.js), band width =
  // weight * unit, and bands tile node sides contiguously (no gap, no
  // inset), so when the data conserves, a node's incoming bands sum to
  // precisely its height. Returns the px-per-item unit, or null when the
  // diagram is not a sankey. `sankey: {unit: 12}` sets it explicitly;
  // otherwise it auto-scales so the largest population/weight is ~160px.
  function sankeyUnit(graph) {
    const cfg = graph.diagram && graph.diagram.sankey;
    if (cfg == null || cfg === false) return null;
    const explicit = typeof cfg === "object" ? +cfg.unit : NaN;
    if (explicit > 0) return explicit;
    let top = 0;
    graph.nodes.forEach((n) => {
      const p = n.data && n.data.population;
      if (typeof p === "number" && p > top) top = p;
    });
    graph.edges.forEach((e) => {
      if (typeof e.weight === "number" && e.weight > top) top = e.weight;
    });
    return top > 0 ? 160 / top : 12;
  }

  // Map numeric edge weights to stroke widths. In sankey mode widths are
  // purely linear (weight * unit, additive by construction). Otherwise
  // proportional to the diagram's heaviest flow, sqrt-damped so a 100x
  // volume isn't a 100x line, via diagram: edgeWidth: {min, max, scale}.
  // Returns null for unweighted edges (width stays a viewer.css concern).
  function weightScale(graph) {
    const unit = sankeyUnit(graph);
    if (unit != null) {
      return (edge) =>
        typeof edge.weight === "number" && edge.weight > 0 ? edge.weight * unit : null;
    }
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

  // The four face anchor points of a node's visible box, in canvas coords --
  // the same faces `anchor.from`/`anchor.to` name (SIDES). Used by connect.js
  // to place face handles on a node that has no edge touching it yet.
  function facePoints(state, id) {
    const b = absPos(state, id);
    return {
      right: { x: b.x + b.w, y: b.y + b.h / 2, face: "right" },
      left: { x: b.x, y: b.y + b.h / 2, face: "left" },
      top: { x: b.x + b.w / 2, y: b.y, face: "top" },
      bottom: { x: b.x + b.w / 2, y: b.y + b.h, face: "bottom" },
    };
  }

  // ---- Geometry pass ---------------------------------------------------------
  // One entry per edge, aligned with graph.edges order: resolved endpoint
  // boxes, the routing axis (dominant), stroke width, and — after the
  // stacking step — the exact source/target anchor points.
  function computeGeometry(state) {
    const widthOf = weightScale(state.graph);
    // Sankey bands tile their node side edge-to-edge; normal diagrams keep
    // breathing room between anchor bands.
    const sankey = sankeyUnit(state.graph) != null;
    const gap = sankey ? 0 : GAP;
    const pad = sankey ? 0 : PAD;
    // Sankey ribbons always run along the layout direction: a mostly-
    // vertical displacement between layer-mates would otherwise flip the
    // dominant axis and route the ribbon around the bars via their
    // top/bottom faces.
    const layoutDir = String(
      (state.graph.diagram || {}).direction || "RIGHT"
    ).toUpperCase();
    const sankeyHoriz = layoutDir !== "DOWN" && layoutDir !== "UP";
    // Node-level anchor defaults (`anchors: {in, out}`, free node data),
    // resolved against the *visible* node -- the box actually anchored.
    const nodeById = {};
    state.graph.nodes.forEach((n) => {
      nodeById[n.id] = n;
    });
    const nodeSide = (id, key) => {
      const n = nodeById[id];
      const a = n && n.data && n.data.anchors;
      return a ? SIDES[a[key]] : undefined;
    };
    // `diagram: sidebarOnlyEdgeTypes: [...]` — relations that are recorded in
    // the model (and listed in a node's sidebar) but never drawn or routed.
    const sbOnly = new Set((state.graph.diagram || {}).sidebarOnlyEdgeTypes || []);
    // Engine routes (layout.js collectRoutes, `diagram: edgeRouting:`), keyed
    // `edge_<index into graph.edges>`; an edge with one keeps its endpoints
    // and bends and stays out of the face stacks.
    const routes = state.routes || null;
    const routing = String((state.graph.diagram || {}).edgeRouting || "").toLowerCase();
    const eps = [];
    state.graph.edges.forEach((edge, i) => {
      if (sbOnly.has(edge.type)) return;
      const route = routes && routes["edge_" + i];
      const pts = Array.isArray(route) ? route : route && route.d ? pathPoints(route.d) : null;
      const sVis = visibleIdOf(state, edge.source);
      const tVis = visibleIdOf(state, edge.target);
      const s = boxOf(state, sVis);
      const t = boxOf(state, tVis);
      const horiz = sankey
        ? sankeyHoriz
        : Math.abs(t.x + t.w / 2 - (s.x + s.w / 2)) >=
          Math.abs(t.y + t.h / 2 - (s.y + s.h / 2));
      const dir = horiz
        ? t.x + t.w / 2 >= s.x + s.w / 2
          ? 1
          : -1
        : t.y + t.h / 2 >= s.y + s.h / 2
          ? 1
          : -1;
      // Each endpoint's face: declared per edge > node default > automatic
      // (dominant axis; source exits toward the target, target is entered
      // from the opposite face).
      const anchor = edge.anchor || {};
      const sFace =
        SIDES[anchor.from] || nodeSide(sVis, "out") || { axis: horiz ? "h" : "v", sign: dir };
      const tFace =
        SIDES[anchor.to] || nodeSide(tVis, "in") || { axis: horiz ? "h" : "v", sign: -dir };
      const width = widthOf(edge);
      // A routed edge is drawn only while both ends still sit where the
      // engine left them; collapse re-anchors an end, so the route goes.
      const routed = pts && pts.length >= 2 && sVis === edge.source && tVis === edge.target ? route : null;
      const rpts = routed ? pts : null;
      eps.push({
        edge,
        sVis,
        tVis,
        s,
        t,
        sFace,
        tFace,
        width,
        band: width != null ? width : BASE_BAND,
        route: routed,
        routing,
        // Both endpoints inside the same collapsed compound: the edge is
        // interior detail of a closed box -- don't draw it, and don't let
        // it occupy anchor slots that real edges need.
        hidden: sVis === tVis,
        sAnchor: rpts ? rpts[0] : { x: s.x + s.w / 2, y: s.y + s.h / 2 },
        tAnchor: rpts ? rpts[rpts.length - 1] : { x: t.x + t.w / 2, y: t.y + t.h / 2 },
      });
    });

    // Group endpoint usages by (visible node, face). Keys encode axis +
    // sign so "exits west" and "enters west" share one stack on that side.
    const groups = {};
    const faceKey = (face) => face.axis + (face.sign > 0 ? "+" : "-");
    eps.forEach((ep) => {
      if (ep.hidden || ep.route) return;
      const sKey = ep.sVis + "|" + faceKey(ep.sFace);
      const tKey = ep.tVis + "|" + faceKey(ep.tFace);
      (groups[sKey] = groups[sKey] || []).push({ ep, end: "s" });
      (groups[tKey] = groups[tKey] || []).push({ ep, end: "t" });
    });

    Object.values(groups).forEach((entries) => {
      entries.forEach((en) => {
        en.box = en.end === "s" ? en.ep.s : en.ep.t;
        en.face = en.end === "s" ? en.ep.sFace : en.ep.tFace;
        const other = en.end === "s" ? en.ep.t : en.ep.s;
        en.sort = en.face.axis === "h" ? other.y + other.h / 2 : other.x + other.w / 2;
      });
      entries.sort((a, b) => a.sort - b.sort);

      const box = entries[0].box;
      const horiz = entries[0].face.axis === "h"; // uniform per group (key includes axis)
      const side = (horiz ? box.h : box.w) - 2 * pad;
      const total =
        entries.reduce((acc, en) => acc + en.ep.band, 0) + gap * (entries.length - 1);
      const scale = side > 0 && total > side ? side / total : 1;
      // Sankey stacks anchor at the top (left, for vertical layouts) of the
      // side, so unconsumed population -- pending/ghosted items -- pools
      // visibly at the bottom; normal stacks stay centered on the side.
      let cursor = sankey
        ? (horiz ? box.y : box.x) + pad
        : (horiz ? box.y + box.h / 2 : box.x + box.w / 2) - (total * scale) / 2;

      entries.forEach((en) => {
        const mid = cursor + (en.ep.band * scale) / 2;
        cursor += (en.ep.band + gap) * scale;
        const plusFace = en.face.sign > 0;
        const p = horiz
          ? { x: plusFace ? en.box.x + en.box.w : en.box.x, y: mid }
          : { x: mid, y: plusFace ? en.box.y + en.box.h : en.box.y };
        if (en.end === "s") en.ep.sAnchor = p;
        else en.ep.tAnchor = p;
      });
    });

    return eps;
  }

  // Bezier path + label midpoint from the stacked anchors; each control
  // point extends along its own endpoint's outward face normal, so the two
  // ends may sit on unrelated faces (anchor: declarations). With automatic
  // (opposite-face) endpoints this is byte-identical to extending along the
  // shared routing axis.
  // The SVG path for an engine route. Orthogonal routes get a small rounded
  // corner at each bend; polylines are drawn as given; ELK's spline routes
  // carry cubic control points in threes (a trailing pair is quadratic). The
  // label sits halfway along the polyline through the points.
  const CORNER = 8;
  function pathFromRoute(pts, routing) {
    const seg = (a, b) => Math.hypot(b.x - a.x, b.y - a.y);
    let d = `M ${pts[0].x} ${pts[0].y}`;
    if (routing === "splines") {
      let i = 1;
      while (i < pts.length) {
        const rest = pts.length - i;
        if (rest >= 3) {
          d += ` C ${pts[i].x} ${pts[i].y}, ${pts[i + 1].x} ${pts[i + 1].y}, ${pts[i + 2].x} ${pts[i + 2].y}`;
          i += 3;
        } else if (rest === 2) {
          d += ` Q ${pts[i].x} ${pts[i].y}, ${pts[i + 1].x} ${pts[i + 1].y}`;
          i += 2;
        } else {
          d += ` L ${pts[i].x} ${pts[i].y}`;
          i += 1;
        }
      }
    } else {
      for (let i = 1; i < pts.length; i++) {
        const p = pts[i];
        const prev = pts[i - 1];
        const next = pts[i + 1];
        const r = routing === "orthogonal" && next ? Math.min(CORNER, seg(prev, p) / 2, seg(p, next) / 2) : 0;
        if (r > 0.5) {
          const a = { x: p.x + ((prev.x - p.x) / seg(prev, p)) * r, y: p.y + ((prev.y - p.y) / seg(prev, p)) * r };
          const b = { x: p.x + ((next.x - p.x) / seg(p, next)) * r, y: p.y + ((next.y - p.y) / seg(p, next)) * r };
          d += ` L ${a.x} ${a.y} Q ${p.x} ${p.y}, ${b.x} ${b.y}`;
        } else {
          d += ` L ${p.x} ${p.y}`;
        }
      }
    }
    let total = 0;
    for (let i = 1; i < pts.length; i++) total += seg(pts[i - 1], pts[i]);
    let left = total / 2;
    let mid = pts[0];
    for (let i = 1; i < pts.length; i++) {
      const l = seg(pts[i - 1], pts[i]);
      if (l >= left) {
        const f = l ? left / l : 0;
        mid = { x: pts[i - 1].x + (pts[i].x - pts[i - 1].x) * f, y: pts[i - 1].y + (pts[i].y - pts[i - 1].y) * f };
        break;
      }
      left -= l;
    }
    return { d, mid };
  }

  // The coordinate pairs of an SVG path (absolute M, L, C, Q, S, T, H, V, A; what D2 and we write).
  function pathPoints(d) {
    const pts = [];
    let cmd = null;
    let nums = [];
    let last = { x: 0, y: 0 };
    const flush = () => {
      if (!cmd) return;
      const v = nums.map(Number);
      if (cmd === "H") v.forEach((x) => pts.push((last = { x, y: last.y })));
      else if (cmd === "V") v.forEach((y) => pts.push((last = { x: last.x, y })));
      else if (cmd === "A") for (let j = 0; j + 6 < v.length; j += 7) pts.push((last = { x: v[j + 5], y: v[j + 6] }));
      else for (let j = 0; j + 1 < v.length; j += 2) pts.push((last = { x: v[j], y: v[j + 1] }));
    };
    (String(d).match(/[A-Za-z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g) || []).forEach((t) => {
      if (/[A-Za-z]/.test(t)) {
        flush();
        cmd = t.toUpperCase();
        nums = [];
        if (cmd === "Z") cmd = null;
      } else nums.push(t);
    });
    flush();
    return pts;
  }

  function routeOf(ep) {
    if (ep.route && ep.route.d) {
      // A saved path (io-flow layout with a D2 engine, or a browser Save): drawn as written, the label where it was placed.
      const pts = pathPoints(ep.route.d);
      return { d: ep.route.d, mid: ep.route.label || pts[Math.floor(pts.length / 2)] || ep.sAnchor };
    }
    if (ep.route) {
      const r = pathFromRoute(ep.route, ep.routing);
      if (ep.route.label) r.mid = ep.route.label; // the engine placed the label
      return r;
    }
    const sx = ep.sAnchor.x;
    const sy = ep.sAnchor.y;
    const tx = ep.tAnchor.x;
    const ty = ep.tAnchor.y;
    const ctrl = (x, y, face) => {
      const reach =
        Math.max(40, (face.axis === "h" ? Math.abs(tx - sx) : Math.abs(ty - sy)) * 0.4) *
        face.sign;
      return face.axis === "h" ? { x: x + reach, y } : { x, y: y + reach };
    };
    const c1 = ctrl(sx, sy, ep.sFace);
    const c2 = ctrl(tx, ty, ep.tFace);
    const c1x = c1.x,
      c1y = c1.y,
      c2x = c2.x,
      c2y = c2.y;
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
    state.edgeGeom = eps; // latest resolved geometry (anchors.js reads it)
    const offT = state.hiddenEdgeTypes;
    const offG = state.hiddenEdgeGroups;
    state.edgeEls.forEach((rec, i) => {
      const ep = eps[i];
      // An edge is hidden if an endpoint is collapsed away, or its type or its
      // group is toggled off in the legend.
      const hidden =
        ep.hidden ||
        (offT && offT.has(rec.edge.type)) ||
        groupHidden(offG, rec.edge.group);
      rec.el.style.display = hidden ? "none" : "";
      if (rec.label) rec.label.style.display = hidden ? "none" : "";
      // Skip geometry only when an endpoint is collapsed away (no route to
      // draw). A type-hidden edge still gets its `d` computed so click-to-focus
      // (dim.js) can reveal it instantly without a re-layout.
      if (ep.hidden) return;
      const r = routeOf(ep);
      rec.el.setAttribute("d", r.d);
      if (rec.label) {
        rec.label.setAttribute("x", r.mid.x);
        rec.label.setAttribute("y", r.mid.y);
      }
    });
    // Anchor-edit handles sit on the endpoints; keep them glued through
    // drags and re-routes.
    if (IOF.anchors && IOF.anchors.refresh) IOF.anchors.refresh(state);
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
    const sankey = sankeyUnit(state.graph) != null;
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
      // Sankey ribbons carry no arrowheads (direction is unambiguous and
      // the triangles read as clutter at band widths).
      if (!(sankey && width != null)) {
        p.setAttribute("marker-end", width != null ? "url(#arrow-flow)" : "url(#arrow)");
      }
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
    if (IOF.regions) IOF.regions.renderAll(state); // draw region backdrops behind nodes
  }

  // Re-route on drag/nudge. Anchor stacks depend on neighbors' relative
  // positions, so all edges are recomputed — a moved node can reorder or
  // re-side stacks on nodes it isn't connected to only via shared groups,
  // and at this tool's scale (low hundreds of edges) a full pass per move
  // is cheap. The nodeId argument is kept for API compatibility.
  function updateFor(state, nodeId) {
    // An engine route is only right for the positions the engine chose: once
    // a node moves, its edges go back to the face-to-face curve.
    if (state.routes && nodeId != null) {
      const touches = (end) => end === nodeId || isAncestor(state, nodeId, end);
      state.graph.edges.forEach((e, i) => {
        if (touches(e.source) || touches(e.target)) delete state.routes["edge_" + i];
      });
    }
    applyGeometry(state, computeGeometry(state));
    if (IOF.regions) IOF.regions.renderAll(state); // keep backdrops under dragged nodes
  }

  function resize(state) {
    let maxX = 0;
    let maxY = 0;
    state.graph.nodes.forEach((n) => {
      const a = absPos(state, n.id);
      maxX = Math.max(maxX, a.x + a.w);
      maxY = Math.max(maxY, a.y + a.h);
    });
    // Routed edges may swing outside the node extent (a wrap-back row).
    (state.edgeGeom || []).forEach((ep) => {
      const pts = Array.isArray(ep.route) ? ep.route : ep.route && ep.route.d ? pathPoints(ep.route.d) : [];
      pts.forEach((p) => {
        maxX = Math.max(maxX, p.x);
        maxY = Math.max(maxY, p.y);
      });
    });
    state.contentSize = { w: maxX, h: maxY };
    state.svg.setAttribute("width", maxX + 80);
    state.svg.setAttribute("height", maxY + 80);
  }

  // Show/hide every edge of a type (legend toggles). Reapplies the current
  // geometry so it survives later re-routes.
  // An edge's `group` may be a string or a list. It's group-hidden only when
  // it HAS a group and every one of its groups is toggled off (so any visible
  // group shows it). No group -> never group-hidden.
  function groupHidden(off, group) {
    if (!off || group == null) return false;
    if (Array.isArray(group)) return group.length > 0 && group.every((g) => off.has(g));
    return off.has(group);
  }
  IOF.edges = IOF.edges || {};
  IOF.groupHidden = groupHidden;

  function setEdgeTypeHidden(state, type, hidden) {
    const off = state.hiddenEdgeTypes || (state.hiddenEdgeTypes = new Set());
    if (hidden) off.add(type);
    else off.delete(type);
    if (state.edgeGeom) applyGeometry(state, state.edgeGeom);
  }

  // Same, but by `group` (edges declared inside a node inherit it as group).
  function setEdgeGroupHidden(state, group, hidden) {
    const off = state.hiddenEdgeGroups || (state.hiddenEdgeGroups = new Set());
    if (hidden) off.add(group);
    else off.delete(group);
    if (state.edgeGeom) applyGeometry(state, state.edgeGeom);
  }

  // Saved routes ({"src>tgt#k": [path d, label x, label y]}, the layout block's _routes) keyed by edge index, as {d, label}.
  // k counts the edges between one pair in graph order, which is how io-flow layout and D2 number them.
  function routesFromSaved(graph, saved) {
    const out = {};
    const seen = {};
    graph.edges.forEach((e, i) => {
      const pair = e.source + ">" + e.target;
      const k = seen[pair] || 0;
      seen[pair] = k + 1;
      const r = saved[pair + "#" + k];
      if (r && typeof r[0] === "string") {
        out["edge_" + i] = { d: r[0], label: r.length >= 3 ? { x: +r[1], y: +r[2] } : null };
      }
    });
    return out;
  }

  // The live routes in the saved form, for Save: engine point routes become M/L paths; a dragged edge has none.
  function routesForSave(state) {
    const out = {};
    if (!state.routes) return out;
    const seen = {};
    state.graph.edges.forEach((e, i) => {
      const pair = e.source + ">" + e.target;
      const k = seen[pair] || 0;
      seen[pair] = k + 1;
      const r = state.routes["edge_" + i];
      if (!r) return;
      let d;
      let label = null;
      if (Array.isArray(r)) {
        if (r.length < 2) return;
        d = "M " + r.map((p) => `${Math.round(p.x)} ${Math.round(p.y)}`).join(" L ");
        label = r.label || null;
      } else if (r.d) {
        d = r.d;
        label = r.label || null;
      } else return;
      out[pair + "#" + k] = label ? [d, Math.round(label.x), Math.round(label.y)] : [d];
    });
    return out;
  }

  IOF.edges = { renderAll, updateFor, resize, isAncestor, sankeyUnit, facePoints, setEdgeTypeHidden, setEdgeGroupHidden, routesFromSaved, routesForSave, pathPoints };
})(window.IOFlow);
