/* io-flow bundled skin: code-map (JS half).
 *
 * Overrides IOF.renderSidebar to render code-map node metadata: scalar fields
 * (module / kind / loc / ...) as a definition list, array fields (args /
 * returns / calls / modifies / attributes / bases) as labeled bullet lists, and
 * `source` (from `io-flow walk`) or `code` as a full-width <pre>.
 *
 * Additive: loaded AFTER templates.js, so it replaces only the sidebar renderer
 * and reuses IOF.esc / IOF.sidebars from the packaged templates.js. The engine
 * looks up IOF.renderSidebar at click time (dim.js), so this late override wins.
 *
 * Relation dicts (`calls`/`xcall`) are edge wiring shown via `callees`, so
 * they're skipped in the sidebar. Paired with codemap.css. */
(function (IOF) {
  "use strict";
  const esc = IOF.esc;
  const row = (k, v) => `<dt>${esc(k)}</dt><dd>${v}</dd>`;
  const scalar = (k, v) =>
    k === "loc" || k === "cli" ? `<code>${esc(v)}</code>` : esc(v);

  // walk emits display metadata under safe keys (args/calls/returns are reserved
  // relation keys in io-flow); relabel them for the sidebar.
  const LABELS = { arg_names: "args", return_exprs: "returns", callees: "calls" };
  const ORDER = ["module", "kind", "loc", "description", "cli", "bases",
    "attributes", "arg_names", "return_exprs", "callees", "modifies"];
  const SKIP = new Set(["code", "source", "calls", "xcall", "label"]);

  const listBlock = (label, arr) =>
    `<div class="sb-list"><div class="sb-list-h">${esc(label)}</div><ul>` +
    arr.map((v) => `<li>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</li>`).join("") +
    `</ul></div>`;
  const empty = (v) => v == null || v === "" || (Array.isArray(v) && !v.length);

  IOF.renderSidebar = (node) => {
    const data = node.data || {};
    const fn = (IOF.sidebars || {})[node.type];
    if (fn) return fn(node);

    const keys = [
      ...ORDER.filter((k) => k in data),
      ...Object.keys(data).filter((k) => !ORDER.includes(k) && !SKIP.has(k)),
    ];
    const dlRows = [], blocks = [];
    keys.forEach((k) => {
      const v = data[k];
      if (empty(v)) return;
      const label = LABELS[k] || k;
      if (Array.isArray(v)) {
        blocks.push(listBlock(label, v));
      } else if (typeof v === "object") {
        blocks.push(listBlock(label, Object.entries(v).map(([a, b]) => (b ? `${a}: ${b}` : a))));
      } else {
        dlRows.push(row(label, scalar(k, v)));
      }
    });
    const src = data.source || data.code;
    const dl = dlRows.length ? `<dl>${dlRows.join("")}</dl>` : "";
    const code = src ? `<pre class="sb-code"><code>${esc(src)}</code></pre>` : "";
    return (dl + blocks.join("") + code) || `<dl><dt>—</dt><dd></dd></dl>`;
  };
})(window.IOFlow);
