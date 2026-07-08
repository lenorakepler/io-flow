/* engine/resize.js — manual resize of compound nodes. INFRASTRUCTURE.
 *
 * Injects a bottom-right drag handle into every compound (any node whose
 * template has a `.node__children` mount). Resizing updates `state.pos[id]`
 * live — drag clamping and edge routing read from there, so children stay
 * contained and edges re-route for free. The size is marked dirty and saved
 * as `[x, y, w, h]` in the layout block (see save.js / layout_store.py);
 * restore keeps it, growing only if children need more room.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  const PAD = 6; // matches drag.js clamp inset
  const MIN_W = 80;

  function init(state) {
    state.graph.nodes.forEach((n) => {
      if (!state.childMount[n.id]) return; // leaves have no resize handle
      const el = state.nodeEls[n.id];
      const handle = document.createElement("div");
      handle.className = "node__resize";
      handle.setAttribute("aria-hidden", "true");
      handle.addEventListener("pointerdown", (e) => onDown(state, n.id, el, handle, e));
      // The click that follows pointerup must not select the node (dim.js).
      handle.addEventListener("click", (e) => e.stopPropagation());
      el.appendChild(handle);
    });
  }

  // Smallest box that still contains the children (plus the drag inset).
  function minSize(state, id) {
    let mx = 0;
    let my = 0;
    state.graph.nodes.forEach((n) => {
      if (n.parent !== id) return;
      const p = state.pos[n.id];
      if (!p) return;
      mx = Math.max(mx, p.x + p.w);
      my = Math.max(my, p.y + p.h);
    });
    return { w: Math.max(mx + PAD, MIN_W), h: Math.max(my + PAD, IOF.headerH() + PAD) };
  }

  function onDown(state, id, el, handle, e) {
    if (e.button !== 0) return;
    e.stopPropagation(); // not a node drag, not a pan
    e.preventDefault();

    const startX = e.clientX;
    const startY = e.clientY;
    const orig = { w: state.pos[id].w, h: state.pos[id].h };
    const scale = () => (state.getScale ? state.getScale() : 1);
    const min = minSize(state, id);
    let moved = false;

    try {
      handle.setPointerCapture(e.pointerId);
    } catch (_) {
      /* ignore */
    }

    function move(ev) {
      moved = true;
      let nw = orig.w + (ev.clientX - startX) / scale();
      let nh = orig.h + (ev.clientY - startY) / scale();
      nw = Math.max(min.w, nw);
      nh = Math.max(min.h, nh);

      // Growing must not overflow this compound's own parent.
      const pid = state.parentOf[id];
      if (pid != null && state.pos[pid]) {
        const pp = state.pos[pid];
        const p = state.pos[id];
        nw = Math.min(nw, pp.w - p.x - PAD);
        nh = Math.min(nh, pp.h - p.y - PAD);
      }

      state.pos[id].w = nw;
      state.pos[id].h = nh;
      el.style.width = nw + "px";
      el.style.height = nh + "px";
      IOF.edges.updateFor(state, id);
    }

    function up() {
      try {
        handle.releasePointerCapture(e.pointerId);
      } catch (_) {
        /* ignore */
      }
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      if (moved) {
        IOF.edges.resize(state);
        if (IOF.save && IOF.save.markDirty) IOF.save.markDirty(state);
      }
    }

    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  }

  IOF.resize = { init };
})(window.IOFlow);
