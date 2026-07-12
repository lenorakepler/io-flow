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

  function toElk(entry, domIndex, hints) {
    const { node, children } = entry;
    const out = { id: node.id };
    if (children.length) {
      out.layoutOptions = compoundOptions();
      out.children = children.map((c) => toElk(c, domIndex, hints));
    } else {
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

  async function run(graph, domIndex, hints) {
    const roots = buildForest(graph);
    const rootOptions = rootOptionsFor(graph);
    if (hints && Object.keys(hints).length) {
      rootOptions["elk.interactive"] = "true";
    }
    const elkGraph = {
      id: "root",
      layoutOptions: rootOptions,
      children: roots.map((r) => toElk(r, domIndex, hints)),
      edges: graph.edges.map((e, i) => ({
        id: "edge_" + i,
        sources: [e.source],
        targets: [e.target],
      })),
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
    return pos;
  }

  IOF.layout = { run };
})(window.IOFlow);
