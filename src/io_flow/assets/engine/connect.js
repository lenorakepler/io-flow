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
  let handleLayer = null; // canvas-level layer for the face handles
  let sourceFace = null; // chosen source face (right|bottom|left|top) or null=auto
  let targetFace = null; // chosen target face for the click that completes
  let hoverTarget = null; // node currently showing target handles

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

    handleLayer = document.createElement("div");
    handleLayer.className = "connect-handle-layer";
    state.canvas.appendChild(handleLayer);

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
        // A face-handle click is handled by the handle's own listener; don't
        // let it read as a node or background click here (handles live in a
        // canvas-level layer, so closest("[data-node-id]") would be null).
        if (ev.target.closest && ev.target.closest(".connect-handle")) return;
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

    // Hybrid handles: once a source is chosen, hovering a candidate target
    // reveals its face handles so the target end can be pinned too. Handles
    // vanish on leave, so the whole canvas is never dotted at once.
    state.viewport.addEventListener("mouseover", (ev) => {
      if (!active || source == null) return;
      // Moving onto a handle must not clear the handles under the pointer.
      if (ev.target.closest && ev.target.closest(".connect-handle")) return;
      const el = ev.target.closest && ev.target.closest("[data-node-id]");
      const id = el && el.getAttribute("data-node-id");
      if (!id || id === source) {
        if (hoverTarget) clearTargetHandles();
        return;
      }
      if (id !== hoverTarget) renderTargetHandles(id);
    });

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
  // uses this to route Enter/Space here before falling back to select). A node
  // *body* click completes with automatic anchors; a face handle completes via
  // complete() with a pinned face.
  function pick(s, id) {
    if (!active) return false;
    if (source == null) {
      setSource(id);
    } else if (source === id) {
      setSource(null); // picking the source again cancels it (no self-edges)
    } else {
      complete(id, null);
    }
    return true;
  }

  // Finish the edge source -> to, pinning either end's face when one was
  // chosen (null = automatic). Shared by node-body clicks (via pick) and target
  // face-handle clicks.
  function complete(to, tFace) {
    if (source == null || to === source) return;
    addEdge(source, to, { from: sourceFace, to: tFace });
    setSource(null);
  }

  function setSource(id) {
    if (source != null && state.nodeEls[source]) {
      state.nodeEls[source].classList.remove("connect-source");
    }
    clearHandles();
    sourceFace = null;
    source = id;
    if (id != null) {
      state.nodeEls[id].classList.add("connect-source");
      renderSourceHandles(id);
      setHint(`Source: ${id}. Click a target node, or a face to pin this end.`);
      announce(`Source ${id}. Choose a target node.`);
    } else {
      setHint("Click a source node.");
    }
  }

  // --- face handles -------------------------------------------------------- #
  function clearHandles() {
    if (handleLayer) handleLayer.textContent = "";
    hoverTarget = null;
    targetFace = null;
  }

  function clearTargetHandles() {
    if (!handleLayer) return;
    handleLayer
      .querySelectorAll(".connect-handle--target")
      .forEach((h) => h.remove());
    hoverTarget = null;
  }

  function makeHandle(pt, cls, onPick) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "connect-handle " + cls;
    b.style.left = pt.x + "px";
    b.style.top = pt.y + "px";
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      onPick(pt.face, b);
    });
    return b;
  }

  function renderSourceHandles(id) {
    if (!handleLayer || !IOF.edges.facePoints) return;
    const pts = IOF.edges.facePoints(state, id);
    Object.values(pts).forEach((pt) => {
      const b = makeHandle(pt, "connect-handle--source", (face) => {
        sourceFace = sourceFace === face ? null : face; // click again = auto
        handleLayer
          .querySelectorAll(".connect-handle--source")
          .forEach((h) => h.classList.remove("connect-handle--picked"));
        if (sourceFace) b.classList.add("connect-handle--picked");
        setHint(
          sourceFace
            ? `Source face: ${sourceFace}. Click a target node or its face.`
            : `Source: ${source}. Click a target node, or a face to pin this end.`
        );
      });
      if (pt.face === sourceFace) b.classList.add("connect-handle--picked");
      b.title = `Pin source to ${pt.face} face`;
      b.setAttribute("aria-label", b.title);
      handleLayer.appendChild(b);
    });
  }

  function renderTargetHandles(id) {
    clearTargetHandles();
    if (!handleLayer || !IOF.edges.facePoints) return;
    hoverTarget = id;
    const pts = IOF.edges.facePoints(state, id);
    Object.values(pts).forEach((pt) => {
      const b = makeHandle(pt, "connect-handle--target", (face) =>
        complete(id, face)
      );
      b.title = `Connect to ${id} at its ${pt.face} face`;
      b.setAttribute("aria-label", b.title);
      handleLayer.appendChild(b);
    });
  }

  function addEdge(from, to, faces) {
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
      return null;
    }
    const edge = { source: from, target: to };
    if (type) edge.type = type;
    if (label) edge.label = label;
    state.graph.edges.push(edge);
    state.pendingEdges.push(edge);
    // Pin chosen faces before the first render so the edge routes out/into
    // them immediately; anchors.js owns the override map + persistence.
    if (faces && (faces.from || faces.to) && IOF.anchors && IOF.anchors.setEndFaces) {
      IOF.anchors.setEndFaces(state, edge, faces);
    }
    // dim.js builds its incidence map once at boot; keep it in step so
    // selecting either endpoint lights the new edge without a reload.
    if (state.dim && state.dim.incident) {
      state.dim.incident[from].push(edge);
      state.dim.incident[to].push(edge);
    }
    IOF.edges.renderAll(state);
    if (IOF.save) IOF.save.markDirty(state);
    const pinned =
      faces && (faces.from || faces.to)
        ? ` (${faces.from || "auto"}→${faces.to || "auto"})`
        : "";
    setHint(`Added ${from} → ${to}${pinned}. Click a source node.`);
    announce(`Connected ${from} to ${to}. Choose a source node.`);
    return edge;
  }

  function setHint(text) {
    if (hint) hint.textContent = text;
  }

  function announce(text) {
    if (IOF.a11y && IOF.a11y.announce) IOF.a11y.announce(text);
  }

  IOF.connect = { init, pick };
})(window.IOFlow);
