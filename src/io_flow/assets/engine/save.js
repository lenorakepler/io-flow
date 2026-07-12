/* engine/save.js — capability-detected save button. INFRASTRUCTURE.
 *
 * Visible only when served over http(s) AND a `/save` endpoint answers a ping
 * (i.e. `io-flow edit`). Opened from file:// it stays hidden and everything
 * else still works. Posts the live parent-relative positions (`state.pos`),
 * the same coordinate space layout_store restores from, plus any connections
 * created in-browser (`state.pendingEdges`, queued by connect.js) for the
 * server to append to the YAML's `edges:` list.
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
      if (!p) return;
      // Compounds persist their (possibly hand-resized) size too.
      positions[n.id] = state.childMount[n.id]
        ? [Math.round(p.x), Math.round(p.y), Math.round(p.w), Math.round(p.h)]
        : [Math.round(p.x), Math.round(p.y)];
    });
    // Connections created in-browser ride along; the server appends them to
    // the YAML's `edges:` list ($-marking happens server-side).
    const newEdges = (state.pendingEdges || []).map((e) => {
      const spec = { from: e.source, to: e.target };
      if (e.type) spec.type = e.type;
      if (e.label) spec.label = e.label;
      return spec;
    });
    btn.disabled = true;
    btn.textContent = "Saving…";
    try {
      const r = await fetch("/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          newEdges.length ? { positions, new_edges: newEdges } : { positions }
        ),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      if (state.pendingEdges) state.pendingEdges.length = 0;
      dirty = false;
      btn.textContent = "Saved";
      // Our own write just changed the YAML's mtime; rebase the live-reload
      // watcher so it doesn't count as an external edit.
      if (IOF.live) IOF.live.resync();
    } catch (e) {
      console.error("[io-flow] save failed:", e);
      btn.textContent = "Save failed";
      btn.disabled = false;
    }
  }

  IOF.save = { init, markDirty };
})(window.IOFlow);
