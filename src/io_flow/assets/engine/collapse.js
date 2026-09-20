/* engine/collapse.js — collapse/expand compound nodes. INFRASTRUCTURE.
 *
 * Injects a toggle button into each compound header. Collapsing hides the
 * node's children (CSS `.node--collapsed`) and re-runs ELK with that node
 * sized to its header (layout.js `collapsed` arg), so its siblings reflow to
 * fill the freed space instead of leaving a gap. The current positions seed
 * the re-layout (ELK interactive mode) so the diagram shifts incrementally
 * rather than jumping to a fresh arrangement. edges.js re-anchors any edge
 * touching a hidden descendant to the collapsed container automatically.
 *
 * When the layout is pinned (`_layout.mode === "restore"`: saved/manual
 * positions, no ELK), reflow would discard that hand-placement, so collapse
 * falls back to shrinking the node in place. View-only state either way —
 * never persisted, never affects saved positions.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  function init(state) {
    state.collapsed = new Set();
    state.graph.nodes.forEach((n) => {
      const mount = state.childMount[n.id];
      if (!mount || !mount.childElementCount) return; // leaves + empty compounds
      const header = state.nodeEls[n.id].querySelector(".node__header");
      if (!header) return;
      const name = n.label != null ? n.label : n.id;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "node__collapse";
      btn.setAttribute("aria-label", `Collapse ${name}`);
      btn.setAttribute("aria-expanded", "true");
      btn.dataset.nodeName = name;
      btn.textContent = "▾";
      // Own the gesture: no drag start, no select-click.
      btn.addEventListener("pointerdown", (e) => e.stopPropagation());
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        toggle(state, n.id, btn);
      });
      header.insertBefore(btn, header.firstChild);
    });
  }

  async function toggle(state, id, btn) {
    const el = state.nodeEls[id];
    const on = !state.collapsed.has(id);
    if (on) state.collapsed.add(id);
    else state.collapsed.delete(id);
    el.classList.toggle("node--collapsed", on);
    btn.textContent = on ? "▸" : "▾";
    btn.setAttribute("aria-label", `${on ? "Expand" : "Collapse"} ${btn.dataset.nodeName}`);
    btn.setAttribute("aria-expanded", String(!on));

    const pinned = state.layoutInfo && state.layoutInfo.mode === "restore";
    if (pinned || !IOF.layout || typeof IOF.layout.run !== "function") {
      // No ELK to reflow with (or reflowing would discard manual placement):
      // shrink in place. state.pos keeps the expanded size for restore.
      el.style.height = (on ? IOF.headerH() : state.pos[id].h) + "px";
      IOF.edges.renderAll(state);
      return;
    }

    // Reflow: re-run ELK with the collapsed set, seeded by the current
    // positions so the rest of the diagram moves as little as possible.
    const hints = {};
    state.graph.nodes.forEach((n) => {
      const p = state.pos[n.id];
      if (p) hints[n.id] = [p.x, p.y];
    });
    const laid = await IOF.layout.run(state.graph, state.nodeEls, hints, state.stacks, state.collapsed);
    IOF.applyPositions(state, laid);
    IOF.edges.renderAll(state);
  }

  IOF.collapse = { init, toggle };
})(window.IOFlow);
