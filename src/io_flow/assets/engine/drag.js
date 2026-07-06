/* engine/drag.js — hand-rolled node dragging. INFRASTRUCTURE: rarely touched.
 *
 * Pointer deltas are divided by the current zoom scale so nodes track the
 * cursor at any zoom. A small movement threshold distinguishes a click (which
 * dim.js turns into a selection) from a drag. `stopPropagation` keeps a child
 * drag from also dragging its parent or starting a pan. Children are clamped
 * inside their parent's box; parents do not auto-resize (v1). Incident edges
 * re-route live through the single edge geometry function.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  const THRESHOLD = 4; // px of screen movement before it counts as a drag
  const PAD = 6; // clamp inset inside a parent
  const HEADER = 34; // keep children below the class header overlay

  function init(state) {
    state.graph.nodes.forEach((n) => {
      const el = state.nodeEls[n.id];
      el.addEventListener("pointerdown", (e) => onDown(state, n.id, el, e));
    });
  }

  function onDown(state, id, el, e) {
    if (e.button !== 0) return;
    e.stopPropagation(); // don't bubble to parent node or start a pan

    const startX = e.clientX;
    const startY = e.clientY;
    const orig = { x: state.pos[id].x, y: state.pos[id].y };
    const scale = () => (state.getScale ? state.getScale() : 1);
    let moved = false;
    el.__dragMoved = false;

    try {
      el.setPointerCapture(e.pointerId);
    } catch (_) {
      /* ignore */
    }

    function move(ev) {
      const totalPx = Math.hypot(ev.clientX - startX, ev.clientY - startY);
      if (!moved && totalPx < THRESHOLD) return;
      moved = true;
      el.__dragMoved = true;

      let nx = orig.x + (ev.clientX - startX) / scale();
      let ny = orig.y + (ev.clientY - startY) / scale();

      const pid = state.parentOf[id];
      if (pid != null && state.pos[pid]) {
        const pp = state.pos[pid];
        const cw = state.pos[id].w;
        const ch = state.pos[id].h;
        nx = Math.max(PAD, Math.min(nx, pp.w - cw - PAD));
        ny = Math.max(HEADER, Math.min(ny, pp.h - ch - PAD));
      }

      state.pos[id].x = nx;
      state.pos[id].y = ny;
      el.style.left = nx + "px";
      el.style.top = ny + "px";
      IOF.edges.updateFor(state, id);
    }

    function up() {
      try {
        el.releasePointerCapture(e.pointerId);
      } catch (_) {
        /* ignore */
      }
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      if (moved) {
        IOF.edges.resize(state);
        if (IOF.save && IOF.save.markDirty) IOF.save.markDirty(state);
      }
      // Let the click event fire first, then clear the drag flag.
      setTimeout(() => {
        el.__dragMoved = false;
      }, 0);
    }

    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  }

  IOF.drag = { init };
})(window.IOFlow);
