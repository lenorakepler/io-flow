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

  const badge = (t) => `<span class="node__badge">${esc(t)}</span>`;
  const meta = (t) => (t == null || t === "" ? "" : `<div class="node__meta">${esc(t)}</div>`);

  const templates = {
    file: (n) => `
      <div class="node__title">${esc(n.id)} ${badge("file")}</div>
      ${n.data.cli ? `<div class="node__meta"><code>${esc(n.data.cli)}</code></div>` : ""}
      ${meta(n.data.value)}
    `,
    option: (n) => `
      <div class="node__title">${esc(n.id)} ${badge("option")}</div>
      ${n.data.cli ? `<div class="node__meta"><code>${esc(n.data.cli)}</code></div>` : ""}
    `,
    parameter: (n) => `
      <div class="node__title">${esc(n.id)} ${badge("param")}</div>
      ${n.data.value !== undefined ? `<div class="node__meta">= ${esc(n.data.value)}</div>` : ""}
    `,
    input: (n) => `<div class="node__title">${esc(n.id)}</div>`,
    function: (n) => `
      <div class="node__title">${esc(n.id)}()</div>
      ${meta(n.data.loc)}
    `,
    method: (n) => `
      <div class="node__title">${esc(n.id.split(".").pop())}()</div>
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
        <span class="node__title">${esc(n.id)}</span>
        ${n.data.loc ? `<span class="node__meta">${esc(n.data.loc)}</span>` : ""}
      </div>
      <div class="node__children"></div>
    `,
  };

  IOF.templates = templates;
  IOF.renderNode = (node) => (templates[node.type] || templates.input)(node);
})(window.IOFlow);
