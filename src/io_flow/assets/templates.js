/* templates.js — the viewer's last-resort renderers.
 *
 * Node appearance is NOT defined here any more. A node's inner HTML is rendered
 * at build time in Python, from `assets/templates/types.yaml` (the built-in
 * types), a project's `templates/types.yaml`, a diagram's own `types:` block,
 * or a `templates/<type>.html.j2` file — see io_flow/jinja_templates.py and the
 * "Adding a node type" section of the README. The result arrives on the node as
 * `html`, and this file just hands it over.
 *
 * Every node arrives with `html` — a type nobody declared still renders, via
 * the `_node` / `_group` base its children (or lack of them) call for — so
 * what is left here is a defensive guard, the generic sidebar dump for types
 * with no `sidebar:` of their own, and the two helpers skins reuse (`IOF.esc`,
 * `IOF.headerH`). A skin's JS may still reassign `IOF.renderNode` /
 * `IOF.renderSidebar` wholesale — it loads after this file.
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

  // Display name: `label` (set by the parser, defaults to the node id — methods
  // default to their short name). `id` stays the unique key used for wiring.
  const name = (n) => esc(n.label != null ? n.label : n.id);

  // A node with children still gets a mount even here: the engine appends a
  // `.node__children` div when the rendered body provides none.
  IOF.renderNode = (node) =>
    node.html != null ? node.html : `<div class="node__title">${name(node)}</div>`;

  /* ---- Sidebar ------------------------------------------------------------
   *
   * Per-type detail comes from a `sidebar:` declaration or a
   * `templates/<type>.sidebar.html.j2` file, prerendered onto the node. This
   * map is the JS escape hatch for anything that must be computed in the
   * browser; types with neither get the generic dump below.
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

  const sidebars = {};

  IOF.sidebars = sidebars;
  IOF.renderSidebar = (node) => {
    if (node.sidebar != null) return node.sidebar;
    const fn = sidebars[node.type];
    if (fn) return fn(node);
    const rows = Object.entries(node.data || {})
      .filter(([, v]) => v != null && v !== "")
      .map(([k, v]) => row(k, fmtValue(k, v)))
      .join("");
    return `<dl>${rows || "<dt>—</dt><dd></dd>"}</dl>`;
  };
})(window.IOFlow);
