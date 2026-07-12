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

  function toElk(entry, domIndex, hints, stackRoots) {
    const { node, children } = entry;
    const out = { id: node.id };
    if (children.length && !(stackRoots && stackRoots.has(node.id))) {
      out.layoutOptions = compoundOptions();
      out.children = children.map((c) => toElk(c, domIndex, hints, stackRoots));
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
    const all = graph.edges.map((e, i) => ({
      id: "edge_" + i,
      sources: [e.source],
      targets: [e.target],
    }));
    if (!stackRoots) return all;
    const parentOf = {};
    graph.nodes.forEach((n) => {
      parentOf[n.id] = n.parent == null ? null : n.parent;
    });
    const rep = (id) => {
      let r = id;
      for (let cur = id; cur != null; cur = parentOf[cur]) {
        if (stackRoots.has(cur)) r = cur; // topmost stacked ancestor wins
      }
      return r;
    };
    return all
      .map((e) => ({ id: e.id, sources: [rep(e.sources[0])], targets: [rep(e.targets[0])] }))
      .filter((e, i) => e.sources[0] !== e.targets[0] || graph.edges[i].source === graph.edges[i].target);
  }

  async function run(graph, domIndex, hints, stacks) {
    const stackRoots = stacks ? stacks.roots : null;
    const roots = buildForest(graph);
    const rootOptions = rootOptionsFor(graph);
    if (hints && Object.keys(hints).length) {
      rootOptions["elk.interactive"] = "true";
    }
    const elkGraph = {
      id: "root",
      layoutOptions: rootOptions,
      children: roots.map((r) => toElk(r, domIndex, hints, stackRoots)),
      edges: elkEdges(graph, stackRoots),
    };

    const elk = new ELK();
    const laid = await elk.layout(elkGraph);

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
