/* engine/viewer.js — bootstrap orchestrator. INFRASTRUCTURE: rarely touched.
 *
 * Loads the inlined graph JSON, mounts node divs (nesting children under their
 * compound parents), waits for fonts, runs layout, applies positions, draws
 * edges, then hands the shared `state` to the optional interaction modules
 * (dim / drag / pan / save) if they are present.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  async function boot() {
    const graph = JSON.parse(document.getElementById("graph-data").textContent);
    const canvas = document.getElementById("canvas");

    const state = {
      graph,
      canvas,
      viewport: document.getElementById("viewport"),
      svg: document.getElementById("edges"),
      nodeEls: {}, // id -> node div
      childMount: {}, // id -> element to append children into
      parentOf: {}, // id -> parent id | null
      pos: {}, // id -> {x, y, w, h} parent-relative (live; drag mutates this)
      edgeEls: [],
    };
    graph.nodes.forEach((n) => {
      state.parentOf[n.id] = n.parent == null ? null : n.parent;
    });

    // 1. Build node elements (create all, then attach to parent/canvas).
    // Compound-ness is a state, not a type: any node may have children, so if
    // a parent's template provides no `.node__children` mount, create one.
    const parentIds = new Set(
      graph.nodes.map((n) => n.parent).filter((p) => p != null)
    );
    graph.nodes.forEach((n) => {
      const el = document.createElement("div");
      el.className = "node node--" + n.type;
      el.setAttribute("data-node-id", n.id);
      el.innerHTML = IOF.renderNode(n);
      state.nodeEls[n.id] = el;
      let mount = el.querySelector(".node__children");
      if (!mount && parentIds.has(n.id)) {
        mount = document.createElement("div");
        mount.className = "node__children";
        el.appendChild(mount);
      }
      if (mount) state.childMount[n.id] = mount;
    });
    graph.nodes.forEach((n) => {
      const parentMount = n.parent != null && state.childMount[n.parent];
      (parentMount || canvas).appendChild(state.nodeEls[n.id]);
    });
    // A compound with no members has nothing in normal flow (its header is an
    // absolute overlay), so it would measure 0x0. Mark it so the header can
    // join the flow and the node sizes to its text like a leaf (viewer.css).
    graph.nodes.forEach((n) => {
      const mount = state.childMount[n.id];
      if (mount && !mount.childElementCount) state.nodeEls[n.id].classList.add("node--empty");
    });

    // 2. Fonts must settle before measuring text-sized leaves.
    if (document.fonts && document.fonts.ready) {
      try {
        await document.fonts.ready;
      } catch (e) {
        /* ignore */
      }
    }

    // 3. Layout (restore saved positions or run ELK), then apply.
    const info = graph._layout || { mode: "elk", positions: {}, notice: null };
    if (info.notice) showNotice(info.notice);
    let laid;
    if (info.mode === "restore") {
      laid = restoreFromPositions(state, info.positions || {});
    } else {
      laid = await IOF.layout.run(graph, state.nodeEls, info.positions || {});
    }
    applyPositions(state, laid);

    // 4. Edges.
    IOF.edges.renderAll(state);

    // 5. Optional interaction modules.
    IOF.state = state;
    [IOF.pan, IOF.dim, IOF.drag, IOF.resize, IOF.save, IOF.live, IOF.collapse, IOF.ui, IOF.a11y].forEach((mod) => {
      if (mod && typeof mod.init === "function") mod.init(state);
    });

    document.body.classList.add("ready");
  }

  function applyPositions(state, laid) {
    state.graph.nodes.forEach((n) => {
      const p = laid[n.id];
      const el = state.nodeEls[n.id];
      if (!p) return;
      state.pos[n.id] = { x: p.x, y: p.y, w: p.w, h: p.h };
      el.style.left = p.x + "px";
      el.style.top = p.y + "px";
      el.style.width = p.w + "px";
      el.style.height = p.h + "px";
    });
  }

  IOF.applyPositions = applyPositions;

  // Restore saved positions without ELK. Sizes: leaves measured from the DOM,
  // compound nodes derived from their (already-sized) children, bottom-up.
  function restoreFromPositions(state, positions) {
    const depthOf = (id) => {
      let d = 0;
      let c = state.parentOf[id];
      while (c != null) {
        d += 1;
        c = state.parentOf[c];
      }
      return d;
    };
    const childrenOf = {};
    state.graph.nodes.forEach((n) => {
      if (n.parent != null) (childrenOf[n.parent] = childrenOf[n.parent] || []).push(n.id);
    });

    const laid = {};
    state.graph.nodes
      .slice()
      .sort((a, b) => depthOf(b.id) - depthOf(a.id)) // deepest first
      .forEach((n) => {
        const p = positions[n.id] || [0, 0];
        const kids = childrenOf[n.id];
        let w;
        let h;
        if (kids && kids.length) {
          let maxX = 0;
          let maxY = 0;
          kids.forEach((cid) => {
            const c = laid[cid];
            maxX = Math.max(maxX, c.x + c.w);
            maxY = Math.max(maxY, c.y + c.h);
          });
          // A manually resized compound saves [x, y, w, h]; honor the saved
          // size but never clip children out of it.
          w = Math.max(maxX + 16, p[2] || 0);
          h = Math.max(maxY + 16, p[3] || 0);
        } else {
          const r = state.nodeEls[n.id].getBoundingClientRect();
          // An empty compound may carry a manual size ([x, y, w, h]); never
          // shrink below the measured text.
          w = Math.max(Math.ceil(r.width), p[2] || 0);
          h = Math.max(Math.ceil(r.height), p[3] || 0);
        }
        laid[n.id] = { x: p[0], y: p[1], w, h };
      });
    return laid;
  }

  function showNotice(text) {
    const el = document.getElementById("notice");
    if (!el) return;
    el.textContent = text;
    el.hidden = false;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window.IOFlow);
