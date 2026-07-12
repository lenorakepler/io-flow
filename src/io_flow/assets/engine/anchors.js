/* engine/anchors.js — in-browser edge anchor editing. INFRASTRUCTURE.
 *
 * Select a node and a small round handle appears at each incident edge
 * endpoint; clicking a handle cycles that endpoint's face override:
 * auto → right → bottom → left → top → auto. "Auto" means whatever the
 * YAML declared (`anchor:` per edge / relation, `anchors:` per node) or,
 * failing that, the dominant-axis rule — overrides layer on top exactly
 * like saved positions layer over ELK.
 *
 * Overrides live in `state.anchorOverrides`, keyed `src>tgt[:type]`
 * (layout_store.edge_key), ride the /save payload, and persist in the
 * machine-owned `layout:` block under `_anchors:`. At boot, apply() merges
 * saved overrides into edge.anchor — the same field the parser writes — so
 * edges.js needs no knowledge of this module. Parallel same-type edges
 * between one pair share a key (documented v1 limitation).
 *
 * Handles work without a server (like drag); unsaved cycles are lost on
 * reload, same as drags. Cycling marks Save dirty when save.js is live.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  const CYCLE = [null, "right", "bottom", "left", "top"];

  let state = null;
  let layer = null; // container div for handles, appended to #canvas
  let authored = []; // per edge index: the YAML-declared anchor (frozen copy)

  function keyOf(edge) {
    const k = edge.source + ">" + edge.target;
    return edge.type ? k + ":" + edge.type : k;
  }

  // Pre-render: merge saved overrides (graph._layout.anchors) into
  // edge.anchor and remember the authored values they layer over. Called by
  // viewer.js before the first edge render; init() runs later with state.
  function apply(graph) {
    authored = graph.edges.map((e) => Object.assign({}, e.anchor));
    const saved = (graph._layout && graph._layout.anchors) || {};
    graph.edges.forEach((e) => {
      const ovr = saved[keyOf(e)];
      if (ovr) e.anchor = Object.assign({}, e.anchor, ovr);
    });
    return saved;
  }

  function init(s) {
    state = s;
    // Seed the session's override map from what apply() found, so a save
    // that changes nothing else still re-persists last session's overrides
    // (merge_positions regenerates the whole layout block).
    state.anchorOverrides = {};
    const saved = (state.graph._layout && state.graph._layout.anchors) || {};
    Object.keys(saved).forEach((k) => {
      state.anchorOverrides[k] = Object.assign({}, saved[k]);
    });
    layer = document.createElement("div");
    layer.className = "anchor-layer";
    state.canvas.appendChild(layer);
  }

  // Re-sync handles with the current selection + geometry. Called by dim.js
  // on select/clear and by edges.js applyGeometry (so handles track drags).
  function refresh(s) {
    if (!layer) return;
    layer.textContent = "";
    const sel = s.selected;
    if (sel == null) return;
    const eps = s.edgeGeom || [];
    eps.forEach((ep, i) => {
      if (ep.hidden) return;
      // A handle for each endpoint sitting on the selected node -- directly,
      // or as the visible stand-in for something collapsed inside it.
      if (ep.edge.source === sel || ep.sVis === sel) addHandle(i, "from", ep.sAnchor);
      if (ep.edge.target === sel || ep.tVis === sel) addHandle(i, "to", ep.tAnchor);
    });
  }

  function addHandle(i, end, at) {
    const edge = state.graph.edges[i];
    const ovr = state.anchorOverrides[keyOf(edge)] || {};
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "anchor-handle" + (ovr[end] ? " anchor-handle--pinned" : "");
    btn.style.left = at.x + "px";
    btn.style.top = at.y + "px";
    const now = ovr[end] || "auto";
    btn.title = `${edge.source} → ${edge.target}${edge.type ? " (" + edge.type + ")" : ""}: ` +
      `${end} anchor ${now}. Click to cycle.`;
    btn.setAttribute("aria-label", btn.title);
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation(); // don't clear the selection underneath us
      cycle(i, end);
    });
    layer.appendChild(btn);
  }

  function cycle(i, end) {
    const edge = state.graph.edges[i];
    const key = keyOf(edge);
    const ovr = state.anchorOverrides[key] || {};
    const next = CYCLE[(CYCLE.indexOf(ovr[end] || null) + 1) % CYCLE.length];
    if (next) ovr[end] = next;
    else delete ovr[end];
    if (Object.keys(ovr).length) state.anchorOverrides[key] = ovr;
    else delete state.anchorOverrides[key];
    // Effective anchor = authored layer + override layer (either end may be
    // independently overridden or revert to its authored/automatic face).
    const eff = Object.assign({}, authored[i], ovr);
    if (Object.keys(eff).length) edge.anchor = eff;
    else delete edge.anchor;
    IOF.edges.updateFor(state, null); // re-route; applyGeometry re-refreshes us
    if (IOF.save && IOF.save.markDirty) IOF.save.markDirty(state);
    if (IOF.a11y && IOF.a11y.announce) {
      IOF.a11y.announce(
        `${end === "from" ? "Source" : "Target"} anchor of ${edge.source} to ` +
          `${edge.target}: ${next || "automatic"}.`
      );
    }
  }

  IOF.anchors = { init, apply, refresh };
})(window.IOFlow);
