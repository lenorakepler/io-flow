/* engine/connect.js — create-connection mode. INFRASTRUCTURE (edit mode only).
 *
 * Append-only by design: the browser can ADD explicit edges, never delete or
 * rewrite existing ones. Derived edges (args/calls/returns) are woven into
 * hand-authored node mappings, so removing one is a YAML edit — which the
 * live-reload loop already makes fast.
 *
 * Click-click, not drag: the "Connect" button toggles a mode, then one click
 * picks the source and the next picks the target. This avoids any contention
 * with drag.js (which owns pointer-drag) and pan. While the mode is active, a
 * capture-phase click listener on the viewport intercepts clicks before
 * dim.js can turn them into selections; a11y.js routes Enter/Space on a
 * focused node through pick() first, so the mode works without a pointer.
 *
 * A new edge goes live immediately (pushed into state.graph.edges + full edge
 * re-render) and queues in state.pendingEdges until save.js POSTs it; the
 * server appends `- {from: $a, to: $b, ...}` entries to the YAML's top-level
 * `edges:` list. Unsaved connections are lost on reload, same as drags.
 *
 * Visible under the same capability gate as Save: http(s) + /save answering.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  let state = null;
  let btn = null;
  let bar = null;
  let hint = null;
  let typeInput = null;
  let labelInput = null;
  let active = false;
  let source = null;

  function init(s) {
    state = s;
    state.pendingEdges = [];
    btn = document.getElementById("connect-btn");
    bar = document.getElementById("connect-bar");
    hint = document.getElementById("connect-hint");
    typeInput = document.getElementById("connect-type");
    labelInput = document.getElementById("connect-label");
    if (!btn || !bar) return;
    if (location.protocol === "file:") return; // stays hidden, like Save

    ping().then((ok) => {
      if (!ok) return;
      btn.hidden = false;
      btn.addEventListener("click", () => setActive(!active));
      fillTypeSuggestions();
    });

    // Capture phase: runs before dim.js's node/background click handlers, so
    // connect-mode clicks never select or clear-select underneath us.
    state.viewport.addEventListener(
      "click",
      (ev) => {
        if (!active) return;
        ev.stopPropagation();
        ev.preventDefault();
        const el = ev.target.closest && ev.target.closest("[data-node-id]");
        if (!el) {
          setSource(null); // background click: drop the pending source
          return;
        }
        if (el.__dragMoved) return; // same click-vs-drag contract as dim.js
        pick(state, el.getAttribute("data-node-id"));
      },
      true
    );

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || !active) return;
      if (source != null) setSource(null);
      else setActive(false);
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

  // Suggest types already in use plus the built-in relations; the field stays
  // free text, matching the parser (any type: tag is legal and stylable).
  function fillTypeSuggestions() {
    const list = document.getElementById("connect-types");
    if (!list) return;
    const types = new Set(["args", "calls", "returns"]);
    state.graph.edges.forEach((e) => {
      if (e.type) types.add(e.type);
    });
    list.innerHTML = Array.from(types)
      .sort()
      .map((t) => `<option value="${IOF.esc(t)}"></option>`)
      .join("");
  }

  function setActive(on) {
    active = on;
    setSource(null);
    document.body.classList.toggle("connecting", on);
    btn.setAttribute("aria-pressed", String(on));
    btn.textContent = on ? "Done connecting" : "Connect";
    bar.hidden = !on;
    if (on && IOF.dim) IOF.dim.clear(state); // start from an undimmed canvas
    setHint("Click a source node.");
    announce(on ? "Connect mode on. Choose a source node." : "Connect mode off.");
  }

  // One selection step. Returns true when the mode consumed the pick (a11y.js
  // uses this to route Enter/Space here before falling back to select).
  function pick(s, id) {
    if (!active) return false;
    if (source == null) {
      setSource(id);
    } else if (source === id) {
      setSource(null); // picking the source again cancels it (no self-edges)
    } else {
      addEdge(source, id);
      setSource(null);
    }
    return true;
  }

  function setSource(id) {
    if (source != null && state.nodeEls[source]) {
      state.nodeEls[source].classList.remove("connect-source");
    }
    source = id;
    if (id != null) {
      state.nodeEls[id].classList.add("connect-source");
      setHint(`Source: ${id}. Click a target node (source again cancels).`);
      announce(`Source ${id}. Choose a target node.`);
    } else {
      setHint("Click a source node.");
    }
  }

  function addEdge(from, to) {
    const type = typeInput ? typeInput.value.trim() : "";
    const label = labelInput ? labelInput.value.trim() : "";
    const dup = state.graph.edges.some(
      (e) =>
        e.source === from &&
        e.target === to &&
        (e.type || "") === type &&
        (e.label || "") === label
    );
    if (dup) {
      setHint(`${from} → ${to} already exists. Click a source node.`);
      announce("Those nodes are already connected.");
      return;
    }
    const edge = { source: from, target: to };
    if (type) edge.type = type;
    if (label) edge.label = label;
    state.graph.edges.push(edge);
    state.pendingEdges.push(edge);
    // dim.js builds its incidence map once at boot; keep it in step so
    // selecting either endpoint lights the new edge without a reload.
    if (state.dim && state.dim.incident) {
      state.dim.incident[from].push(edge);
      state.dim.incident[to].push(edge);
    }
    IOF.edges.renderAll(state);
    if (IOF.save) IOF.save.markDirty(state);
    setHint(`Added ${from} → ${to}. Click a source node.`);
    announce(`Connected ${from} to ${to}. Choose a source node.`);
  }

  function setHint(text) {
    if (hint) hint.textContent = text;
  }

  function announce(text) {
    if (IOF.a11y && IOF.a11y.announce) IOF.a11y.announce(text);
  }

  IOF.connect = { init, pick };
})(window.IOFlow);
