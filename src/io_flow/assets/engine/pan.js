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
  }

  IOF.pan = { init };
})(window.IOFlow);
