/* engine/ui.js — search filter + type legend. INFRASTRUCTURE.
 *
 * Search: typing dims every node whose id/label doesn't contain the query
 * (ancestors of matches stay lit so containers remain readable); Enter
 * selects the first match and centers it; Escape clears.
 *
 * Legend: one mini node chip per node type present in the graph, rendered
 * with the real `.node node--<type>` classes so it follows any user CSS
 * automatically (see the #legend overrides in viewer.css).
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  function init(state) {
    const input = document.getElementById("search");
    if (input) initSearch(state, input);
    const legend = document.getElementById("legend");
    if (legend) buildLegend(state, legend);
  }

  // ---- Search ----------------------------------------------------------------
  function initSearch(state, input) {
    input.addEventListener("input", () => filter(state, input.value));
    input.addEventListener("keydown", (e) => {
      e.stopPropagation(); // keep Escape-in-field from bubbling to dim.js
      if (e.key === "Escape") {
        input.value = "";
        filter(state, "");
        input.blur();
      } else if (e.key === "Enter") {
        const hit = matches(state, input.value)[0];
        if (hit) {
          IOF.dim.select(state, hit);
          center(state, hit);
        }
      }
    });
    // Don't let a click in the field bubble to the background-click clear.
    input.addEventListener("click", (e) => e.stopPropagation());
  }

  function matches(state, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return [];
    return state.graph.nodes
      .filter(
        (n) =>
          n.id.toLowerCase().includes(q) ||
          String(n.label || "").toLowerCase().includes(q)
      )
      .map((n) => n.id);
  }

  function filter(state, query) {
    const q = String(query || "").trim();
    if (!q) {
      IOF.dim.clear(state);
      return;
    }
    const hits = new Set(matches(state, q));
    const lit = new Set(hits);
    hits.forEach((id) => {
      state.dim.ancestors(id).forEach((a) => lit.add(a));
    });
    state.graph.nodes.forEach((n) => {
      state.nodeEls[n.id].classList.toggle("dimmed", !lit.has(n.id));
    });
    state.edgeEls.forEach(({ el, edge }) => {
      const on = hits.has(edge.source) || hits.has(edge.target);
      el.classList.toggle("dimmed", !on);
    });
  }

  function center(state, id) {
    if (!state.pz) return;
    const a = IOF.absPos(state, id);
    const s = state.getScale();
    const vp = state.viewport.getBoundingClientRect();
    state.pz.moveTo(
      vp.width / 2 - (a.x + a.w / 2) * s,
      vp.height / 2 - (a.y + a.h / 2) * s
    );
  }

  // ---- Legend ----------------------------------------------------------------
  function buildLegend(state, legend) {
    const types = [];
    const seen = new Set();
    state.graph.nodes.forEach((n) => {
      if (!seen.has(n.type)) {
        seen.add(n.type);
        types.push(n.type);
      }
    });
    legend.setAttribute("role", "list");
    legend.setAttribute("aria-label", "Node types");
    legend.innerHTML = types
      .map(
        (t) =>
          `<div class="node node--${IOF.esc(t)}" role="listitem"><span class="node__title">${IOF.esc(t)}</span></div>`
      )
      .join("");
  }

  IOF.ui = { init };
})(window.IOFlow);
