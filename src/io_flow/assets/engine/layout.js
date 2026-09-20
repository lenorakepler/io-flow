/* engine/layout.js — ELK layout. INFRASTRUCTURE: rarely touched.
 *
 * Converts the graph model (flat nodes + parent pointers) into ELK's nested
 * form, measures leaf nodes from the live DOM, runs ELK with INCLUDE_CHILDREN
 * so edges may cross the class/child hierarchy, and returns a flat map
 * { id: {x, y, w, h} } of *parent-relative* coordinates.
 *
 * Per-diagram configuration comes from the YAML `diagram:` block (passed
 * through as graph.diagram) and merges over the defaults:
 *
 *   diagram:
 *     direction: DOWN        # RIGHT (default) | DOWN | LEFT | UP
 *     algorithm: layered     # any elkjs algorithm name (mrtree, force, ...)
 *     spacing: 40            # node-node spacing
 *     layerSpacing: 70       # spacing between layers
 *     elk:                   # raw ELK options, highest precedence
 *       elk.layered.considerModelOrder.strategy: NODES_AND_EDGES
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  const ROOT_OPTIONS = {
    "elk.algorithm": "layered",
    "elk.direction": "RIGHT",
    "elk.hierarchyHandling": "INCLUDE_CHILDREN",
    "elk.layered.spacing.nodeNodeBetweenLayers": "70",
    "elk.spacing.nodeNode": "40",
    "elk.spacing.edgeNode": "24",
    "elk.padding": "[top=20,left=20,bottom=20,right=20]",
  };

  function rootOptionsFor(graph) {
    const o = Object.assign({}, ROOT_OPTIONS);
    const cfg = graph.diagram || {};
    if (cfg.direction) o["elk.direction"] = String(cfg.direction).toUpperCase();
    if (cfg.algorithm) o["elk.algorithm"] = String(cfg.algorithm);
    if (cfg.spacing != null) o["elk.spacing.nodeNode"] = String(cfg.spacing);
    if (cfg.layerSpacing != null)
      o["elk.layered.spacing.nodeNodeBetweenLayers"] = String(cfg.layerSpacing);
    // Nodes may declare a `tier:` (integer column, YAML data): every node
    // sharing a tier renders in the same layer -- an invisible grouping
    // tier, e.g. all sankey sources in one column. Activation is global.
    if (graph.nodes.some((n) => typeof (n.data || {}).tier === "number")) {
      o["elk.partitioning.activate"] = "true";
    }
    Object.assign(o, cfg.elk || {});
    return o;
  }

  // Room for the compound header (height owned by --header-h in viewer.css)
  // + inner padding around nested children.
  function compoundOptions() {
    return { "elk.padding": `[top=${IOF.headerH() + 8},left=16,bottom=16,right=16]` };
  }

  // What a compound's header bar needs to show its title. A compound is sized
  // by its children -- ELK from their extent + padding, restore from the same
  // -- and neither knows the header text, so a long title spills out of the
  // bar. The header is an absolute overlay stretched to the node's width, so
  // its scrollWidth is the content it would need. 0 for leaves, whose measured
  // box already includes the header in normal flow.
  function headerWidth(el) {
    const head = el && el.querySelector(":scope > .node__header");
    // Only the overlay kind: a header in normal flow (leaf, or an empty
    // compound sized like one) is already inside the measured box.
    if (!head || getComputedStyle(head).position !== "absolute") return 0;
    return Math.ceil(head.scrollWidth) + 12; // + the bar's own side padding
  }
  IOF.headerWidth = headerWidth;

  function buildForest(graph) {
    const byId = {};
    graph.nodes.forEach((n) => {
      byId[n.id] = { node: n, children: [] };
    });
    const roots = [];
    graph.nodes.forEach((n) => {
      const entry = byId[n.id];
      if (n.parent != null && byId[n.parent]) byId[n.parent].children.push(entry);
      else roots.push(entry);
    });
    return roots;
  }

  // Class-layout mode (diagram: classLayout:): compounds of the configured
  // types lay their members out as a UML-style stacked list (declaration
  // order, uniform width) and face ELK as fixed-size leaves. Strict no-op
  // when the key is absent. A bare `classLayout:` means {types: [class]};
  // `classLayout: {types: [...]}` widens it; `classLayout: false` opts out.
  function classLayoutTypes(graph) {
    const d = graph.diagram;
    if (!d || !("classLayout" in d) || d.classLayout === false) return null;
    const cfg = d.classLayout;
    const types = cfg && Array.isArray(cfg.types) ? cfg.types : ["class"];
    return new Set(types.map(String));
  }

  // Plan the member stacks. viewer.js calls this once, after fonts and
  // before layout, in BOTH sizing paths (sankey precedent: the inline sizes
  // set here are simply read back by leaf measurement, in toElk and in
  // restore). Geometry constants mirror compoundOptions() and
  // restoreFromPositions' +16 so a saved, untouched stack restores
  // pixel-identically. Returns null when the mode is off, else:
  //   pos:   {memberId: {x, y, w, h}} parent-relative stacked positions,
  //          merged into the laid map on the ELK path only (saved layouts win)
  //   roots: Set of topmost stacked compound ids (ELK leaves in toElk)
  function planStacks(graph, domIndex) {
    const types = classLayoutTypes(graph);
    if (!types) return null;
    const PAD = 16; // side/bottom inset; matches compoundOptions + restore's +16
    const GAP = 8; // row gap
    const childrenOf = {};
    const parentOf = {};
    graph.nodes.forEach((n) => {
      parentOf[n.id] = n.parent == null ? null : n.parent;
      if (n.parent != null) (childrenOf[n.parent] = childrenOf[n.parent] || []).push(n.id);
    });
    const wants = {};
    graph.nodes.forEach((n) => {
      wants[n.id] = types.has(n.type) && !!childrenOf[n.id];
    });
    // A stacked class may contain leaves and nested stacked classes only;
    // any other compound inside (a group, a method with children) makes the
    // whole class fall back to a normal ELK compound, loudly. Recursion
    // still reaches a stackable class nested inside the fallen-back one.
    const ok = {};
    const stackOk = (id) => {
      if (ok[id] == null) {
        ok[id] = (childrenOf[id] || []).every(
          (c) => !childrenOf[c] || (wants[c] && stackOk(c))
        );
      }
      return ok[id];
    };
    const cand = (id) => wants[id] && stackOk(id);
    graph.nodes.forEach((n) => {
      if (wants[n.id] && !stackOk(n.id)) {
        console.warn(
          `[io-flow] classLayout: "${n.id}" contains a non-stackable compound; falling back to ELK layout for it`
        );
      }
    });
    const roots = new Set();
    graph.nodes.forEach((n) => {
      if (!cand(n.id)) return;
      let p = parentOf[n.id];
      while (p != null && !cand(p)) p = parentOf[p];
      if (p == null) roots.add(n.id); // no stacked ancestor: topmost
    });

    const pos = {};
    function stackOne(id) {
      const kids = childrenOf[id];
      // Nested stacked classes size themselves before the parent measures them.
      kids.forEach((c) => {
        if (childrenOf[c]) stackOne(c);
      });
      // CSS hook goes on before measuring so row styling is reflected in
      // measured sizes (measure-then-freeze).
      domIndex[id].classList.add("node--stacked");
      let width = 0;
      const sizes = kids.map((c) => {
        const r = domIndex[c].getBoundingClientRect();
        const s = { w: Math.ceil(r.width), h: Math.ceil(r.height) };
        if (s.w > width) width = s.w;
        return s;
      });
      let y = IOF.headerH() + 8; // below the header; matches compoundOptions
      kids.forEach((c, i) => {
        domIndex[c].style.width = width + "px"; // uniform rows
        pos[c] = { x: PAD, y, w: width, h: sizes[i].h };
        y += sizes[i].h + GAP;
      });
      // The compound gets an explicit inline size so toElk's leaf
      // measurement (absolutely-positioned members contribute nothing to a
      // getBoundingClientRect otherwise) returns exactly this.
      domIndex[id].style.width = width + 2 * PAD + "px";
      domIndex[id].style.height = y - GAP + PAD + "px";
    }
    roots.forEach(stackOne);
    return { pos, roots };
  }

  function toElk(entry, domIndex, hints, stackRoots, collapsed) {
    const { node, children } = entry;
    const out = { id: node.id };
    // A collapsed compound faces ELK as a header-only leaf, so its siblings
    // reflow into the freed space instead of leaving a gap (collapse.js).
    const isCollapsed = collapsed && collapsed.has(node.id);
    if (children.length && !isCollapsed && !(stackRoots && stackRoots.has(node.id))) {
      out.layoutOptions = compoundOptions();
      // Lay out around a header-wide parent rather than widening it after the
      // fact, so siblings keep their spacing instead of being overlapped.
      const hw = headerWidth(domIndex[node.id]);
      if (hw) {
        out.layoutOptions["elk.nodeSize.constraints"] = "MINIMUM_SIZE";
        out.layoutOptions["elk.nodeSize.minimum"] = `(${hw},0)`;
      }
      out.children = children.map((c) => toElk(c, domIndex, hints, stackRoots, collapsed));
    } else if (isCollapsed) {
      // Header-only box: keep the measured width so the title still fits.
      const el = domIndex[node.id];
      out.width = Math.max(Math.ceil(el.getBoundingClientRect().width), headerWidth(el));
      out.height = IOF.headerH();
    } else {
      // Leaves -- and stacked compounds, whose inline size planStacks set.
      const el = domIndex[node.id];
      const r = el.getBoundingClientRect();
      // Round up to avoid sub-pixel clipping of measured content.
      out.width = Math.ceil(r.width);
      out.height = Math.ceil(r.height);
    }
    // tier: pins the node into that ELK partition (activated in
    // rootOptionsFor when any node declares one).
    const tier = (node.data || {}).tier;
    if (typeof tier === "number") {
      out.layoutOptions = Object.assign(out.layoutOptions || {}, {
        "elk.partitioning.partition": String(Math.round(tier)),
      });
    }
    // Feed a saved position as a placement hint (used with interactive mode on
    // a topology change; ignored gracefully otherwise).
    const h = hints && hints[node.id];
    if (h) {
      out.x = h[0];
      out.y = h[1];
    }
    return out;
  }

  // Stacked-compound members don't exist in the elk graph (their compound
  // is a leaf), and elkjs throws on unknown edge endpoints ("Referenced
  // shape does not exist"), so remap member endpoints to the topmost
  // stacked ancestor. This only shapes ELK's draft; rendered edge geometry
  // always comes from state.pos (edges.js). An edge entirely inside one
  // stack drops out of the elk graph but still renders.
  function elkEdges(graph, stackRoots) {
    // Opt-in (`diagram: layoutSkipsHiddenEdges: true`): drop default-hidden
    // edges from the layout so edges you can't see don't spread the nodes
    // apart. Off by default -- hidden edges still shape the layout, which keeps
    // structure when few edges are visible.
    const cfg = graph.diagram || {};
    const skipHidden = cfg.layoutSkipsHiddenEdges === true;
    const offT = new Set(skipHidden ? cfg.hiddenEdges || [] : []);
    const offG = new Set(skipHidden ? cfg.hiddenEdgeGroups || [] : []);
    // Opt-in (`diagram: layoutExcludeEdgeTypes: [...]`): keep these edge types
    // out of the layout entirely (they still render when visible). Use it to
    // stop noisy I/O edges from spreading nodes while the backbone shapes it.
    // Sidebar-only relations never route or lay out either.
    const exT = new Set([
      ...(cfg.layoutExcludeEdgeTypes || []),
      ...(cfg.sidebarOnlyEdgeTypes || []),
    ]);
    const parentOf = {};
    graph.nodes.forEach((n) => {
      parentOf[n.id] = n.parent == null ? null : n.parent;
    });
    const rep = (id) => {
      if (!stackRoots) return id;
      let r = id;
      for (let cur = id; cur != null; cur = parentOf[cur]) {
        if (stackRoots.has(cur)) r = cur; // topmost stacked ancestor wins
      }
      return r;
    };
    const out = [];
    graph.edges.forEach((e, i) => {
      if (offT.has(e.type) || offG.has(e.group) || exT.has(e.type)) return;
      const s = rep(e.source);
      const t = rep(e.target);
      // Drop self-loops created by stack-remapping (but keep genuine ones).
      if (stackRoots && s === t && e.source !== e.target) return;
      out.push({ id: "edge_" + i, sources: [s], targets: [t] });
    });
    return out;
  }

  // Push a set of sibling boxes apart until none overlap (with a gap), then
  // clamp them into their parent's content area. Used to make force/stress
  // layouts usable: those don't enforce non-overlap for sized compound boxes.
  function separate(kids, topPad, gap) {
    for (let iter = 0; iter < 200; iter++) {
      let moved = false;
      for (let i = 0; i < kids.length; i++) {
        for (let j = i + 1; j < kids.length; j++) {
          const a = kids[i];
          const b = kids[j];
          const ox = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
          const oy = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
          if (ox <= 0 || oy <= 0) continue; // no real overlap
          moved = true;
          const acx = a.x + a.width / 2;
          const bcx = b.x + b.width / 2;
          const acy = a.y + a.height / 2;
          const bcy = b.y + b.height / 2;
          if (ox < oy) {
            const push = (ox + gap) / 2;
            const dir = acx <= bcx ? 1 : -1;
            a.x -= dir * push;
            b.x += dir * push;
          } else {
            const push = (oy + gap) / 2;
            const dir = acy <= bcy ? 1 : -1;
            a.y -= dir * push;
            b.y += dir * push;
          }
        }
      }
      if (!moved) break;
    }
    let minX = Infinity;
    let minY = Infinity;
    kids.forEach((k) => {
      minX = Math.min(minX, k.x);
      minY = Math.min(minY, k.y);
    });
    const dx = minX < gap ? gap - minX : 0;
    const dy = minY < topPad ? topPad - minY : 0;
    if (dx || dy) kids.forEach((k) => { k.x += dx; k.y += dy; });
  }

  // Grow a compound to contain its (possibly moved) children.
  function fit(node, gap) {
    const kids = node.children || [];
    if (!kids.length) return;
    let maxX = 0;
    let maxY = 0;
    kids.forEach((k) => {
      maxX = Math.max(maxX, k.x + k.width);
      maxY = Math.max(maxY, k.y + k.height);
    });
    node.width = Math.max(node.width || 0, maxX + gap);
    node.height = Math.max(node.height || 0, maxY + gap);
  }

  // Bottom-up: de-overlap each compound's children (deepest first, so a parent
  // separates already-final child boxes), then grow the parent to fit.
  function declump(node, topPad, gap) {
    const kids = node.children || [];
    kids.forEach((k) => declump(k, IOF.headerH() + 8, gap));
    if (kids.length > 1) separate(kids, topPad, gap);
    fit(node, gap);
  }

  // Alternative backend (`diagram: engine: dagre`). Dagre is a pure-JS layered
  // DAG layout whose contract is exactly io-flow's: it returns node positions
  // and we draw our own edges. It's ~5x smaller than elkjs and often ranks a
  // plain DAG more tightly. Prototype-level: compound header room is reserved by
  // hand (dagre has no per-cluster header pad) and nested-compound growth isn't
  // re-fit bottom-up, so deep nesting can slightly overflow. Flat and
  // single-level-group diagrams (the common case) lay out cleanly.
  function runDagre(graph, domIndex, stacks, collapsed) {
    const stackRoots = stacks ? stacks.roots : null;
    const cfg = graph.diagram || {};
    const DIR = { DOWN: "TB", UP: "BT", RIGHT: "LR", LEFT: "RL" };
    const rankdir = DIR[String(cfg.direction || "RIGHT").toUpperCase()] || "LR";
    const HEADER = IOF.headerH() + 8;

    const parentOf = {};
    graph.nodes.forEach((n) => { parentOf[n.id] = n.parent == null ? null : n.parent; });
    const hidden = (id) => {
      for (let c = parentOf[id]; c != null; c = parentOf[c]) {
        if (collapsed && collapsed.has(c)) return true;
      }
      return false;
    };
    // A node is a compound only if it has a *visible* child (a collapsed node's
    // children are hidden, so it lays out as a header-only leaf).
    const isCompound = {};
    graph.nodes.forEach((n) => {
      if (n.parent != null && !hidden(n.id)) isCompound[n.parent] = true;
    });

    const g = new dagre.graphlib.Graph({ compound: true, multigraph: true });
    g.setGraph({
      rankdir,
      nodesep: Number(cfg.spacing) || 40,
      ranksep: Number(cfg.layerSpacing) || 70,
      marginx: 16,
      marginy: 16,
    });
    g.setDefaultEdgeLabel(() => ({}));

    graph.nodes.forEach((n) => {
      if (hidden(n.id)) return;
      if (isCompound[n.id]) {
        g.setNode(n.id, {}); // dagre sizes it from its children
      } else {
        const el = domIndex[n.id];
        const r = el.getBoundingClientRect();
        const h = collapsed && collapsed.has(n.id) ? IOF.headerH() : Math.ceil(r.height);
        g.setNode(n.id, { width: Math.ceil(r.width), height: h });
      }
    });
    graph.nodes.forEach((n) => {
      if (!hidden(n.id) && n.parent != null && g.hasNode(n.parent)) g.setParent(n.id, n.parent);
    });
    elkEdges(graph, stackRoots).forEach((e) => {
      const s = e.sources[0];
      const t = e.targets[0];
      if (g.hasNode(s) && g.hasNode(t)) g.setEdge(s, t, {}, e.id);
    });

    dagre.layout(g);

    // dagre gives absolute *center* coords; io-flow wants parent-relative
    // top-left (edges.js sums the parent chain). Convert, and normalise roots.
    const absTL = {};
    g.nodes().forEach((id) => {
      const nd = g.node(id);
      if (nd) absTL[id] = { x: nd.x - nd.width / 2, y: nd.y - nd.height / 2, w: nd.width, h: nd.height };
    });
    let minX = Infinity;
    let minY = Infinity;
    graph.nodes.forEach((n) => {
      if (parentOf[n.id] == null && absTL[n.id]) {
        minX = Math.min(minX, absTL[n.id].x);
        minY = Math.min(minY, absTL[n.id].y);
      }
    });
    const shiftX = isFinite(minX) ? 16 - minX : 0;
    const shiftY = isFinite(minY) ? 16 - minY : 0;

    const pos = {};
    graph.nodes.forEach((n) => {
      const a = absTL[n.id];
      if (!a) return;
      const p = parentOf[n.id];
      let x;
      let y;
      let h = a.h;
      if (p == null || !absTL[p]) {
        x = a.x + shiftX;
        y = a.y + shiftY;
      } else {
        x = a.x - absTL[p].x;
        y = a.y - absTL[p].y + HEADER; // clear the compound header overlay
      }
      if (isCompound[n.id]) h += HEADER; // grow the box to hold the shifted children
      pos[n.id] = { x, y, w: a.w, h };
    });
    if (stacks) Object.assign(pos, stacks.pos);
    return pos;
  }

  async function run(graph, domIndex, hints, stacks, collapsed) {
    if ((graph.diagram || {}).engine === "dagre") {
      return runDagre(graph, domIndex, stacks, collapsed);
    }
    const stackRoots = stacks ? stacks.roots : null;
    const roots = buildForest(graph);
    const rootOptions = rootOptionsFor(graph);
    if (hints && Object.keys(hints).length) {
      rootOptions["elk.interactive"] = "true";
    }
    const elkGraph = {
      id: "root",
      layoutOptions: rootOptions,
      children: roots.map((r) => toElk(r, domIndex, hints, stackRoots, collapsed)),
      edges: elkEdges(graph, stackRoots),
    };

    // Compounds default to ELK's `layered`; propagate the root algorithm so
    // nested nodes lay out the same way (e.g. a rectpacking diagram packs
    // *inside* each compound too, instead of falling back to a layered row).
    const rootAlgo = rootOptions["elk.algorithm"];
    if (rootAlgo && rootAlgo !== "layered") {
      const carry = { "elk.algorithm": rootAlgo };
      if (rootOptions["elk.aspectRatio"]) carry["elk.aspectRatio"] = rootOptions["elk.aspectRatio"];
      (function propagate(node) {
        (node.children || []).forEach((c) => {
          if (c.children && c.children.length) {
            c.layoutOptions = Object.assign({}, c.layoutOptions, carry);
            propagate(c);
          }
        });
      })(elkGraph);
    }

    const elk = new ELK();
    const laid = await elk.layout(elkGraph);

    // `diagram: deoverlap: true` — separate any overlapping boxes after layout.
    // Makes force/stress usable (they don't keep compound boxes apart).
    if ((graph.diagram || {}).deoverlap) {
      const gap = Number((graph.diagram || {}).spacing) || 16;
      declump(laid, 16, gap);
    }

    const pos = {};
    (function walk(nodes) {
      (nodes || []).forEach((n) => {
        pos[n.id] = { x: n.x || 0, y: n.y || 0, w: n.width || 0, h: n.height || 0 };
        walk(n.children);
      });
    })(laid.children);
    // Stacked members never went through ELK; their planned positions join
    // the laid map here so state.pos (edges, drag, save) covers them too.
    if (stacks) Object.assign(pos, stacks.pos);
    return pos;
  }

  IOF.layout = { run, planStacks };
})(window.IOFlow);
