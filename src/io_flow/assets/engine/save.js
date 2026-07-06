/* engine/save.js — capability-detected save button. INFRASTRUCTURE.
 *
 * Visible only when served over http(s) AND a `/save` endpoint answers a ping
 * (i.e. `io-flow edit`). Opened from file:// it stays hidden and everything
 * else still works. Posts the live parent-relative positions (`state.pos`),
 * the same coordinate space layout_store restores from.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  let state = null;
  let btn = null;
  let dirty = false;

  function init(s) {
    state = s;
    btn = document.getElementById("save-btn");
    if (!btn) return;
    if (location.protocol === "file:") {
      btn.hidden = true;
      return;
    }
    ping().then((ok) => {
      if (!ok) {
        btn.hidden = true;
        return;
      }
      btn.hidden = false;
      btn.addEventListener("click", doSave);
      render();
    });
  }

  async function ping() {
    try {
      const r = await fetch("/save", { method: "OPTIONS" });
      return r.status === 204 || r.ok;
    } catch (e) {
      return false;
    }
  }

  function markDirty() {
    dirty = true;
    render();
  }

  function render() {
    if (!btn || btn.hidden) return;
    btn.disabled = !dirty;
    btn.textContent = dirty ? "Save layout" : "Saved";
  }

  async function doSave() {
    if (!state) return;
    const positions = {};
    state.graph.nodes.forEach((n) => {
      const p = state.pos[n.id];
      if (p) positions[n.id] = [Math.round(p.x), Math.round(p.y)];
    });
    btn.disabled = true;
    btn.textContent = "Saving…";
    try {
      const r = await fetch("/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ positions }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      dirty = false;
      btn.textContent = "Saved";
    } catch (e) {
      console.error("[io-flow] save failed:", e);
      btn.textContent = "Save failed";
      btn.disabled = false;
    }
  }

  IOF.save = { init, markDirty };
})(window.IOFlow);
