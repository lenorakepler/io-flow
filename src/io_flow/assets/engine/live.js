/* engine/live.js — live reload for `io-flow edit`. INFRASTRUCTURE.
 *
 * Polls the server's /version (newest mtime of the YAML + skin overrides)
 * once a second and reloads the page when it changes, so editing the source
 * YAML refreshes the browser by itself. Unsaved drag positions are lost on
 * reload — deliberate: the file is the source of truth.
 *
 * Inert from file:// or when no /version endpoint answers (static artifact).
 * save.js calls resync() after a successful save so the server writing the
 * YAML on our behalf doesn't count as an external change.
 */
window.IOFlow = window.IOFlow || {};
(function (IOF) {
  "use strict";

  let baseline = null;

  async function fetchVersion() {
    try {
      const r = await fetch("/version", { cache: "no-store" });
      if (!r.ok) return null;
      return (await r.json()).v;
    } catch (e) {
      return null;
    }
  }

  async function resync() {
    const v = await fetchVersion();
    if (v != null) baseline = v;
    return v != null;
  }

  function init() {
    if (location.protocol === "file:") return;
    resync().then((ok) => {
      if (!ok) return;
      setInterval(async () => {
        const v = await fetchVersion();
        if (v != null && v !== baseline) location.reload();
      }, 1000);
    });
  }

  IOF.live = { init, resync };
})(window.IOFlow);
