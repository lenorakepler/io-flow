/* templates.js — USER-EDITABLE SURFACE (1 of 2).
 *
 * Maps a node `type` to a function returning the node's *inner* HTML. The
 * engine owns the wrapper element (`<div class="node node--TYPE"
 * data-node-id="...">`) and the structural invariants; everything you see
 * inside a node is defined here. Pair each type with a `.node--<type>` rule in
 * viewer.css. Adding a new node type = add a function here + a CSS rule. No
 * engine edits required.
 *
 * Contract:
 *  - Return an HTML string. Use `esc()` on any value that came from YAML.
 *  - A compound node (one that contains children, e.g. `class`) MUST include an
 *    element with class `node__children`; the engine mounts child nodes there.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  const esc = (s) =>
    String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  IOF.esc = esc;

  // Compound-header height. Single source of truth is the --header-h CSS
  // variable in viewer.css; layout padding, drag clamping, and collapse all
  // read it from here.
  let _headerH = null;
  IOF.headerH = () => {
    if (_headerH == null) {
      const v = getComputedStyle(document.documentElement).getPropertyValue("--header-h");
      _headerH = parseInt(v, 10) || 32;
    }
    return _headerH;
  };

  const badge = (t) => `<span class="node__badge">${esc(t)}</span>`;
  const meta = (t) => (t == null || t === "" ? "" : `<div class="node__meta">${esc(t)}</div>`);

  // Display name: `label` (set by the parser, defaults to the node id — methods
  // default to their short name). `id` stays the unique key used for wiring.
  const name = (n) => esc(n.label != null ? n.label : n.id);

  const templates = {
    file: (n) => `
      <div class="node__title">${name(n)} ${badge("file")}</div>
      ${n.data.cli ? `<div class="node__meta"><code>${esc(n.data.cli)}</code></div>` : ""}
      ${meta(n.data.value)}
    `,
    option: (n) => `
      <div class="node__title">${name(n)} ${badge("option")}</div>
      ${n.data.cli ? `<div class="node__meta"><code>${esc(n.data.cli)}</code></div>` : ""}
    `,
    parameter: (n) => `
      <div class="node__title">${name(n)} ${badge("param")}</div>
      ${n.data.value !== undefined ? `<div class="node__meta">= ${esc(n.data.value)}</div>` : ""}
    `,
    input: (n) => `<div class="node__title">${name(n)}</div>`,
    function: (n) => `
      <div class="node__title">${name(n)}()</div>
      ${meta(n.data.loc)}
    `,
    method: (n) => `
      <div class="node__title">${name(n)}()</div>
    `,
    attributes: (n) => {
      const keys = Object.keys(n.data || {});
      return `
        <div class="node__title">attributes</div>
        ${keys.length ? `<div class="node__meta">${keys.map(esc).join(", ")}</div>` : ""}
      `;
    },
    class: (n) => `
      <div class="node__header">
        <span class="node__title">${name(n)}</span>
        ${n.data.loc ? `<span class="node__meta">${esc(n.data.loc)}</span>` : ""}
      </div>
      <div class="node__children"></div>
    `,
    // Compound container grouping functions/classes/nested groups.
    group: (n) => `
      <div class="node__header">
        <span class="node__title">${name(n)}</span>
        ${n.data.loc ? `<span class="node__meta">${esc(n.data.loc)}</span>` : ""}
      </div>
      <div class="node__children"></div>
    `,
  };

  IOF.templates = templates;
  IOF.renderNode = (node) => (templates[node.type] || templates.input)(node);

  /* ---- Sidebar templates — USER-EDITABLE ----------------------------------
   *
   * Maps a node `type` to a function returning the sidebar's *detail* HTML
   * (the engine owns the chrome: close button, type tag, title). Types with
   * no entry fall back to a generic dump of every `data:` key, so new node
   * types get a working sidebar with zero code.
   */
  const row = (k, v) => `<dt>${esc(k)}</dt><dd>${v}</dd>`;
  const fmtMap = (obj) => {
    const rows = Object.entries(obj || {})
      .map(
        ([k, v]) =>
          `<div><code>${esc(k)}</code>: ${esc(
            v && typeof v === "object" ? JSON.stringify(v) : v
          )}</div>`
      )
      .join("");
    return rows || "<em>—</em>";
  };
  const CODE_KEYS = new Set(["cli", "loc"]);
  const fmtValue = (k, v) => {
    if (v && typeof v === "object") return fmtMap(v);
    if (CODE_KEYS.has(k)) return `<code>${esc(v)}</code>`;
    return esc(v);
  };

  const sidebars = {
    attributes: (n) => `<dl>${row("attributes", fmtMap(n.data))}</dl>`,
  };

  IOF.sidebars = sidebars;
  IOF.renderSidebar = (node) => {
    const fn = sidebars[node.type];
    if (fn) return fn(node);
    const rows = Object.entries(node.data || {})
      .filter(([, v]) => v != null && v !== "")
      .map(([k, v]) => row(k, fmtValue(k, v)))
      .join("");
    return `<dl>${rows || "<dt>—</dt><dd></dd>"}</dl>`;
  };
})(window.IOFlow);
