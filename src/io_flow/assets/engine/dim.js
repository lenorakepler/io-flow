/* engine/dim.js — click-to-dim + sidebar. INFRASTRUCTURE: rarely touched.
 *
 * Clicking a node dims everything except its direct in/out neighborhood.
 * Compound rules (PLAN.md §3.2):
 *   - selecting a node also focuses its descendants (a parent lights the union
 *     of its children's neighborhoods),
 *   - ancestors of anything lit stay undimmed (a selected child keeps its
 *     containing class visible),
 *   - an edge is lit iff it touches the selected node or one of its descendants.
 * Escape or a background click clears. Appearance is pure CSS (`.dimmed`).
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  function init(state) {
    const { graph } = state;

    const childrenOf = {};
    graph.nodes.forEach((n) => (childrenOf[n.id] = []));
    graph.nodes.forEach((n) => {
      if (n.parent != null && childrenOf[n.parent]) childrenOf[n.parent].push(n.id);
    });
    const incident = {};
    graph.nodes.forEach((n) => (incident[n.id] = []));
    graph.edges.forEach((e) => {
      incident[e.source].push(e);
      incident[e.target].push(e);
    });

    const descendants = (id) => {
      const out = [];
      (function rec(i) {
        (childrenOf[i] || []).forEach((c) => {
          out.push(c);
          rec(c);
        });
      })(id);
      return out;
    };
    const ancestors = (id) => {
      const out = [];
      let c = state.parentOf[id];
      while (c != null) {
        out.push(c);
        c = state.parentOf[c];
      }
      return out;
    };

    state.dim = { childrenOf, incident, descendants, ancestors };

    graph.nodes.forEach((n) => {
      const el = state.nodeEls[n.id];
      el.addEventListener("click", (ev) => {
        if (el.__dragMoved) return; // a drag just happened; not a select-click
        ev.stopPropagation();
        select(state, n.id);
      });
    });

    state.viewport.addEventListener("click", () => clear(state));
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") clear(state);
    });
  }

  function select(state, id) {
    state.selected = id;
    const D = state.dim;

    const focus = new Set([id, ...D.descendants(id)]);
    const lit = new Set(focus);
    D.ancestors(id).forEach((a) => lit.add(a));

    focus.forEach((f) => {
      (D.incident[f] || []).forEach((e) => {
        [e.source, e.target].forEach((end) => {
          lit.add(end);
          D.ancestors(end).forEach((a) => lit.add(a));
        });
      });
    });

    state.graph.nodes.forEach((n) => {
      state.nodeEls[n.id].classList.toggle("dimmed", !lit.has(n.id));
    });
    state.edgeEls.forEach(({ el, edge }) => {
      const on = focus.has(edge.source) || focus.has(edge.target);
      el.classList.toggle("dimmed", !on);
    });

    showSidebar(state, id);
    if (IOF.a11y) IOF.a11y.onSelect(state, id);
  }

  function clear(state) {
    const hadSelection = state.selected != null;
    state.selected = null;
    state.graph.nodes.forEach((n) => state.nodeEls[n.id].classList.remove("dimmed"));
    state.edgeEls.forEach(({ el }) => el.classList.remove("dimmed"));
    hideSidebar();
    if (hadSelection && IOF.a11y) IOF.a11y.onClear();
  }

  // ---- Sidebar ---------------------------------------------------------------
  // Detail markup comes from the user-editable surface (IOF.renderSidebar /
  // IOF.sidebars in templates.js); this engine owns only the chrome.
  function showSidebar(state, id) {
    const node = state.graph.nodes.find((n) => n.id === id);
    if (!node) return;
    const sb = document.getElementById("sidebar");
    sb.innerHTML =
      `<button class="sb-close" type="button" aria-label="Close">&times;</button>` +
      `<div class="sb-type">${IOF.esc(node.type)}</div>` +
      `<h2>${IOF.esc(node.id)}</h2>` +
      IOF.renderSidebar(node);
    sb.hidden = false;
    sb.querySelector(".sb-close").addEventListener("click", () => clear(state));
  }

  function hideSidebar() {
    const sb = document.getElementById("sidebar");
    sb.hidden = true;
    sb.innerHTML = "";
  }

  IOF.dim = { init, select, clear };
})(window.IOFlow);
