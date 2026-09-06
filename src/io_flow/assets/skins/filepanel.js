/* filepanel skin — an always-open side panel that shows a node's embedded file.
 *
 * Opt-in: enable with `style: skin: [..., filepanel]`. Nodes get file text by
 * declaring `src: path/to/file` (the parser embeds it into graph.fileContents).
 * Clicking a node with embedded content shows it here; the panel stays open.
 *
 * Markdown (lang === "markdown") is rendered to HTML by a small built-in
 * renderer; everything else shows as plain monospace. Code `lang` is exposed as
 * a `language-<lang>` class, ready for a syntax highlighter later.
 */
(function () {
  "use strict";

  // ---- tiny markdown -> HTML -------------------------------------------------
  function esc(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }
  function inline(s) {
    // escape first; every replacement below emits our own trusted tags.
    s = esc(s);
    const codes = [];
    s = s.replace(/`([^`]+)`/g, (_m, c) => {
      codes.push(c);
      return "\u0000" + (codes.length - 1) + "\u0000"; // protect from other rules
    });
    s = s
      .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img alt="$1" src="$2">')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_]+)__/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/(^|[\s(])_([^_]+)_/g, "$1<em>$2</em>");
    s = s.replace(/\u0000(\d+)\u0000/g, (_m, i) => "<code>" + codes[+i] + "</code>");
    return s;
  }
  const BLOCK = /^(#{1,6}\s|```|>\s?|\s*[-*+]\s|\s*\d+\.\s|(-{3,}|\*{3,}|_{3,})\s*$)/;
  function md2html(src) {
    const lines = src.replace(/\r\n?/g, "\n").split("\n");
    let html = "";
    let list = null;
    const closeList = () => {
      if (list) {
        html += "</" + list + ">";
        list = null;
      }
    };
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^```/.test(line)) {
        closeList();
        i++;
        const buf = [];
        while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
        i++;
        html += '<pre class="fp__code"><code>' + esc(buf.join("\n")) + "</code></pre>";
        continue;
      }
      if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        closeList();
        html += "<hr>";
        i++;
        continue;
      }
      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        closeList();
        const lvl = h[1].length;
        html += "<h" + lvl + ">" + inline(h[2]) + "</h" + lvl + ">";
        i++;
        continue;
      }
      if (/^>\s?/.test(line)) {
        closeList();
        const buf = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
        html += "<blockquote>" + md2html(buf.join("\n")) + "</blockquote>";
        continue;
      }
      const ul = line.match(/^\s*[-*+]\s+(.*)$/);
      const ol = line.match(/^\s*\d+\.\s+(.*)$/);
      if (ul || ol) {
        const tag = ul ? "ul" : "ol";
        if (list !== tag) {
          closeList();
          html += "<" + tag + ">";
          list = tag;
        }
        html += "<li>" + inline((ul || ol)[1]) + "</li>";
        i++;
        continue;
      }
      if (/^\s*$/.test(line)) {
        closeList();
        i++;
        continue;
      }
      closeList();
      const buf = [line];
      i++;
      while (i < lines.length && !/^\s*$/.test(lines[i]) && !BLOCK.test(lines[i])) buf.push(lines[i++]);
      html += "<p>" + inline(buf.join(" ")) + "</p>";
    }
    closeList();
    return html;
  }

  // ---- panel -----------------------------------------------------------------
  function ensurePanel() {
    let el = document.getElementById("filepanel");
    if (!el) {
      el = document.createElement("aside");
      el.id = "filepanel";
      el.setAttribute("aria-label", "File contents");
      el.innerHTML =
        '<div class="fp__head"><span class="fp__name"></span>' +
        '<span class="fp__lang"></span></div>' +
        '<div class="fp__body"></div>';
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
    el.querySelector(".fp__body").replaceChildren();
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
    const body = el.querySelector(".fp__body");
    if (fc.lang === "markdown") {
      const md = document.createElement("div");
      md.className = "fp__md";
      md.innerHTML = md2html(fc.text); // renderer escapes all source text
      body.replaceChildren(md);
    } else {
      const pre = document.createElement("pre");
      pre.className = "fp__pre";
      const code = document.createElement("code");
      code.className = "language-" + (fc.lang || "text");
      code.textContent = fc.text; // textContent = no injection
      pre.appendChild(code);
      body.replaceChildren(pre);
    }
    body.scrollTop = 0;
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
