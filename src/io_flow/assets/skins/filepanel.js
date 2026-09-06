/* filepanel skin — an always-open side panel that shows a node's embedded file.
 *
 * Opt-in: enable with `style: skin: [..., filepanel]`. Nodes get file text by
 * declaring `src: path/to/file` (the parser embeds it into graph.fileContents).
 * Clicking a node with embedded content shows it here; the panel stays open.
 *
 * No syntax highlighting yet — plain monospace. `lang` is exposed as a
 * `language-<lang>` class on the <code>, ready for a highlighter later.
 */
(function () {
  "use strict";

  function ensurePanel() {
    let el = document.getElementById("filepanel");
    if (!el) {
      el = document.createElement("aside");
      el.id = "filepanel";
      el.setAttribute("aria-label", "File contents");
      el.innerHTML =
        '<div class="fp__head"><span class="fp__name"></span>' +
        '<span class="fp__lang"></span></div>' +
        '<pre class="fp__body"><code></code></pre>';
      document.body.appendChild(el);
      document.body.classList.add("has-filepanel");
    }
    return el;
  }

  function graph() {
    return (window.IOFlow && IOFlow.state && IOFlow.state.graph) || null;
  }

  function placeholder(msg) {
    const el = ensurePanel();
    el.querySelector(".fp__name").textContent = msg;
    el.querySelector(".fp__lang").textContent = "";
    el.querySelector(".fp__body code").textContent = "";
    el.classList.add("fp--empty");
  }

  function show(id) {
    const g = graph();
    if (!g) return;
    const fc = (g.fileContents || {})[id];
    if (!fc) {
      placeholder("No file for this node");
      return;
    }
    const el = ensurePanel();
    el.classList.remove("fp--empty");
    el.querySelector(".fp__name").textContent = fc.name || id;
    el.querySelector(".fp__lang").textContent =
      (fc.lang || "") + (fc.truncated ? " · truncated" : "");
    const code = el.querySelector(".fp__body code");
    code.className = "language-" + (fc.lang || "text");
    code.textContent = fc.text;
    el.querySelector(".fp__body").scrollTop = 0;
  }

  function init() {
    placeholder("Click a file node");
  }

  document.addEventListener("ioflow:select", (e) => show(e.detail.id));
  document.addEventListener("ioflow:clear", () => placeholder("Click a file node"));

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
