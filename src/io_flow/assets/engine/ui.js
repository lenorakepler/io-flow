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
  // An edge legend row: a real stroke sample + label. Clickable to toggle every
  // edge of that type (wired below). `data-edge-type` is the toggle key.
  function edgeRow(type, label, off) {
    return (
      `<div class="legend__row legend__row--edge${off ? " legend__row--off" : ""}" role="listitem" tabindex="0"` +
      ` data-edge-type="${IOF.esc(type)}" aria-pressed="${off ? "true" : "false"}"` +
      ` title="Toggle ${IOF.esc(label || type)} edges">` +
      `<svg class="legend__edge" width="42" height="12" aria-hidden="true">` +
      `<path class="edge edge--${IOF.esc(type)}" d="M1,6 H34" marker-end="url(#arrow)"></path>` +
      `</svg><span class="legend__text">${IOF.esc(label || type)}</span></div>`
    );
  }

  // Clicking (or Enter/Space on) an edge row hides/shows that edge type.
  function wireEdgeToggles(state, legend) {
    const toggle = (row) => {
      const type = row.getAttribute("data-edge-type");
      if (!type) return;
      const off = row.getAttribute("aria-pressed") !== "true"; // becoming hidden
      row.setAttribute("aria-pressed", off ? "true" : "false");
      row.classList.toggle("legend__row--off", off);
      IOF.edges.setEdgeTypeHidden(state, type, off);
    };
    legend.addEventListener("click", (ev) => {
      const row = ev.target.closest(".legend__row--edge");
      if (row) toggle(row);
    });
    legend.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      const row = ev.target.closest(".legend__row--edge");
      if (row) {
        ev.preventDefault();
        toggle(row);
      }
    });
  }

  function buildLegend(state, legend) {
    legend.setAttribute("role", "list");
    const declared = state.graph.legend;
    if (declared && ((declared.nodes || []).length || (declared.edges || []).length)) {
      legend.setAttribute("aria-label", declared.title || "Legend");
      const rows = [];
      if (declared.title) rows.push(`<div class="legend__title">${IOF.esc(declared.title)}</div>`);
      // Node samples arrive prerendered (jinja_templates.prerender) -- the same
      // markup a real node of that type gets, so they follow every type
      // declaration and CSS rule automatically.
      (declared.nodes || []).forEach((n) => {
        rows.push(`<div class="legend__row" role="listitem">${n.html}</div>`);
      });
      const off = state.hiddenEdgeTypes || new Set();
      (declared.edges || []).forEach((e) => rows.push(edgeRow(e.type, e.label, off.has(e.type))));
      legend.innerHTML = rows.join("");
      wireEdgeToggles(state, legend);
      return;
    }
    // No `legend:` block: node types as chips, then a clickable row per edge
    // type present so whole edge sets can be toggled off.
    const types = [];
    const seen = new Set();
    state.graph.nodes.forEach((n) => {
      if (!seen.has(n.type)) {
        seen.add(n.type);
        types.push(n.type);
      }
    });
    const edgeTypes = [];
    const seenE = new Set();
    (state.graph.edges || []).forEach((e) => {
      const t = e.type || "edge";
      if (!seenE.has(t)) {
        seenE.add(t);
        edgeTypes.push(t);
      }
    });
    legend.setAttribute("aria-label", "Legend");
    legend.innerHTML =
      types
        .map(
          (t) =>
            `<div class="node node--${IOF.esc(t)}" role="listitem"><span class="node__title">${IOF.esc(t)}</span></div>`
        )
        .join("") +
      edgeTypes.map((t) => edgeRow(t, t, (state.hiddenEdgeTypes || new Set()).has(t))).join("");
    wireEdgeToggles(state, legend);
  }

  IOF.ui = { init };
})(window.IOFlow);
