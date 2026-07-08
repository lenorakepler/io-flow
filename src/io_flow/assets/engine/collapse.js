/* engine/collapse.js — collapse/expand compound nodes. INFRASTRUCTURE.
 *
 * Injects a toggle button into each compound header. Collapsing shrinks the
 * node to header height and hides its children (CSS `.node--collapsed`);
 * edges.js re-anchors any edge touching a hidden descendant to the collapsed
 * container automatically (its absPos resolves through `state.collapsed`).
 * View-only state — never persisted, never affects saved positions.
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
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "node__collapse";
      btn.setAttribute("aria-label", "Collapse");
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

  function toggle(state, id, btn) {
    const el = state.nodeEls[id];
    const on = !state.collapsed.has(id);
    if (on) state.collapsed.add(id);
    else state.collapsed.delete(id);
    el.classList.toggle("node--collapsed", on);
    btn.textContent = on ? "▸" : "▾";
    btn.setAttribute("aria-label", on ? "Expand" : "Collapse");
    // Displayed height only; state.pos keeps the expanded size for restore.
    el.style.height = (on ? IOF.headerH() : state.pos[id].h) + "px";
    IOF.edges.renderAll(state);
  }

  IOF.collapse = { init, toggle };
})(window.IOFlow);
