/* engine/a11y.js — screen-reader & keyboard support. INFRASTRUCTURE.
 *
 * Diagrams can't be made accessible by decorating the picture, so this module
 * follows the standard pattern instead: generate a parallel text
 * representation from the same graph model.
 *
 *  1. A visually-hidden overview (`<nav class="sr-only">`): every node as a
 *     nested list mirroring the containment hierarchy, with its inputs and
 *     outputs derived from the edge list — the relationships the SVG paths
 *     can't convey.
 *  2. Per-node semantics: nodes are focusable; leaves are buttons, compounds
 *     are groups; each carries an accessible name ("do_run, function") and an
 *     aria-describedby description listing its connections.
 *  3. Keyboard operation: Enter/Space selects (dim + sidebar, same as click);
 *     arrow keys nudge the focused node by 8px (Shift = 1px) with the same
 *     parent clamping as drag; Escape clears (dim.js). Selections are
 *     announced through a polite live region.
 *
 * The SVG edge layer is marked decorative — the text layers above carry it.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  const PAD = 6; // matches drag.js clamp inset
  const STEP = 8;
  const FINE = 1;

  let statusEl = null;

  function init(state) {
    const adj = buildAdjacency(state.graph);
    state.svg.setAttribute("aria-hidden", "true");
    buildOverview(state, adj);
    annotateNodes(state, adj);
    statusEl = document.createElement("div");
    statusEl.id = "a11y-status";
    statusEl.className = "sr-only";
    statusEl.setAttribute("role", "status");
    document.getElementById("app").appendChild(statusEl);
    state.a11yAdj = adj;
  }

  function buildAdjacency(graph) {
    const inputs = {};
    const outputs = {};
    graph.nodes.forEach((n) => {
      inputs[n.id] = [];
      outputs[n.id] = [];
    });
    graph.edges.forEach((e) => {
      outputs[e.source].push(e);
      inputs[e.target].push(e);
    });
    return { inputs, outputs };
  }

  const nameOf = (state, id) => {
    const n = state.graph.nodes.find((x) => x.id === id);
    return n ? (n.label != null ? n.label : n.id) : id;
  };

  // "Config.from_yaml (calls: load config)" — the endpoint plus how/why.
  function endpointText(state, id, edge) {
    let tag = edge.type || "";
    if (edge.label) tag += (tag ? ": " : "") + edge.label;
    return nameOf(state, id) + (tag ? ` (${tag})` : "");
  }

  function connectionText(state, adj, id) {
    const parts = [];
    const ins = adj.inputs[id] || [];
    const outs = adj.outputs[id] || [];
    if (ins.length) {
      parts.push("Inputs: " + ins.map((e) => endpointText(state, e.source, e)).join(", ") + ".");
    }
    if (outs.length) {
      parts.push("Outputs: " + outs.map((e) => endpointText(state, e.target, e)).join(", ") + ".");
    }
    return parts.join(" ");
  }

  // ---- 1. Hidden overview ----------------------------------------------------
  function buildOverview(state, adj) {
    const { graph } = state;
    const childrenOf = {};
    const roots = [];
    graph.nodes.forEach((n) => {
      childrenOf[n.id] = [];
    });
    graph.nodes.forEach((n) => {
      if (n.parent != null && childrenOf[n.parent]) childrenOf[n.parent].push(n);
      else roots.push(n);
    });

    const item = (n) => {
      let text = `${IOF.esc(nameOf(state, n.id))}, ${IOF.esc(n.type)}.`;
      const conn = connectionText(state, adj, n.id);
      if (conn) text += " " + IOF.esc(conn);
      const kids = childrenOf[n.id];
      const sub = kids.length ? `<ul>${kids.map(item).join("")}</ul>` : "";
      return `<li>${text}${sub}</li>`;
    };

    const nav = document.createElement("nav");
    nav.className = "sr-only";
    nav.setAttribute("aria-label", "Diagram text alternative");
    nav.innerHTML =
      `<h1>${IOF.esc(graph.title || "io-flow diagram")}</h1>` +
      `<p>${graph.nodes.length} nodes, ${graph.edges.length} connections. ` +
      `The list below mirrors the diagram; each entry names its inputs and outputs.</p>` +
      `<ul>${roots.map(item).join("")}</ul>`;
    const app = document.getElementById("app");
    app.insertBefore(nav, app.firstChild);
  }

  // ---- 2 + 3. Node semantics and keyboard ------------------------------------
  function annotateNodes(state, adj) {
    // aria-describedby still resolves content inside aria-hidden, and hiding
    // the host keeps browse mode from hitting the descriptions twice.
    const descHost = document.createElement("div");
    descHost.className = "sr-only";
    descHost.setAttribute("aria-hidden", "true");
    document.getElementById("app").appendChild(descHost);

    state.graph.nodes.forEach((n, i) => {
      const el = state.nodeEls[n.id];
      el.tabIndex = 0;
      // A button may not contain interactive children, so compounds (which
      // hold collapse buttons and nested nodes) are groups instead.
      el.setAttribute("role", state.childMount[n.id] ? "group" : "button");
      el.setAttribute("aria-label", `${nameOf(state, n.id)}, ${n.type}`);

      const conn = connectionText(state, adj, n.id);
      if (conn) {
        const d = document.createElement("div");
        d.id = "iof-desc-" + i;
        d.textContent = conn;
        descHost.appendChild(d);
        el.setAttribute("aria-describedby", d.id);
      }

      el.addEventListener("keydown", (ev) => {
        if (ev.target !== el) return; // let child buttons handle their own keys
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          ev.stopPropagation();
          IOF.dim.select(state, n.id);
        } else if (ev.key.startsWith("Arrow")) {
          ev.preventDefault();
          ev.stopPropagation();
          nudge(state, n.id, el, ev);
        }
      });
    });
  }

  function nudge(state, id, el, ev) {
    const step = ev.shiftKey ? FINE : STEP;
    const p = state.pos[id];
    let nx = p.x + (ev.key === "ArrowRight" ? step : ev.key === "ArrowLeft" ? -step : 0);
    let ny = p.y + (ev.key === "ArrowDown" ? step : ev.key === "ArrowUp" ? -step : 0);

    const pid = state.parentOf[id];
    if (pid != null && state.pos[pid]) {
      const pp = state.pos[pid];
      nx = Math.max(PAD, Math.min(nx, pp.w - p.w - PAD));
      ny = Math.max(IOF.headerH() + 2, Math.min(ny, pp.h - p.h - PAD));
    }

    p.x = nx;
    p.y = ny;
    el.style.left = nx + "px";
    el.style.top = ny + "px";
    IOF.edges.updateFor(state, id);
    IOF.edges.resize(state);
    if (IOF.save && IOF.save.markDirty) IOF.save.markDirty(state);
  }

  // ---- Announcements (called by dim.js) --------------------------------------
  function announce(text) {
    if (!statusEl) return;
    // A trailing NBSP forces re-announcement of an identical message without
    // relying on rAF/timers (which are throttled in background tabs).
    if (statusEl.textContent === text) text += " ";
    statusEl.textContent = text;
  }

  function onSelect(state, id) {
    const adj = state.a11yAdj;
    if (!adj) return;
    const ins = (adj.inputs[id] || []).length;
    const outs = (adj.outputs[id] || []).length;
    announce(
      `${nameOf(state, id)} selected. ${ins} input${ins === 1 ? "" : "s"}, ` +
        `${outs} output${outs === 1 ? "" : "s"}. Details shown in sidebar.`
    );
  }

  function onClear() {
    announce("Selection cleared.");
  }

  IOF.a11y = { init, announce, onSelect, onClear };
})(window.IOFlow);
