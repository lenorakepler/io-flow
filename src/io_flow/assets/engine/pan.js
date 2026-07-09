/* engine/pan.js — pan/zoom via vendored anvaka/panzoom. INFRASTRUCTURE.
 *
 * panzoom transforms the #canvas as a unit, so nodes and the SVG edge underlay
 * zoom/pan together and the edge geometry stays in untransformed canvas space.
 * Pressing on a node cancels panning so the node-drag handler owns that gesture.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  function init(state) {
    if (typeof panzoom !== "function") {
      state.getScale = () => 1;
      return;
    }
    const pz = panzoom(state.canvas, {
      maxZoom: 4,
      minZoom: 0.15,
      smoothScroll: false,
      zoomDoubleClickSpeed: 1, // effectively disable double-click zoom
      // Returning truthy cancels panzoom's own pan start -> lets node drag run.
      beforeMouseDown: (e) => e.target.closest(".node") != null,
      beforeTouchStart: (e) => e.target.closest(".node") != null,
    });
    state.pz = pz;
    state.getScale = () => pz.getTransform().scale;
    fitAndCenter(state, pz);
  }

  // Initial view: center the diagram in the viewport (zooming out to fit when
  // it's larger than the window) instead of starting in the top-left corner
  // under the search/legend chrome. Never zooms in past 1:1.
  function fitAndCenter(state, pz) {
    const vp = state.viewport.getBoundingClientRect();
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    state.graph.nodes.forEach((n) => {
      if (n.parent != null) return; // root nodes carry the full extent
      const p = state.pos[n.id];
      if (!p) return;
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x + (p.w || 0));
      maxY = Math.max(maxY, p.y + (p.h || 0));
    });
    if (!isFinite(minX) || !vp.width || !vp.height) return;
    const pad = 24;
    const w = maxX - minX;
    const h = maxY - minY;
    const scale = Math.max(
      Math.min(1, (vp.width - 2 * pad) / w, (vp.height - 2 * pad) / h),
      0.15 // keep within minZoom
    );
    pz.zoomAbs(0, 0, scale);
    pz.moveTo(
      (vp.width - w * scale) / 2 - minX * scale,
      (vp.height - h * scale) / 2 - minY * scale
    );
  }

  IOF.pan = { init };
})(window.IOFlow);
