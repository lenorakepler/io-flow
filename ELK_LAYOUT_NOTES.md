# ELK Layout — Notes & Plan

Notes on how elkjs is used in io-flow today, what was learned wiring it up, and
a recommended plan for evolving it. Scope is the layout engine only
(`src/io_flow/assets/engine/layout.js` + the restore path in `viewer.js` and the
hash policy in `layout_store.py`).

## How it works today

**Pipeline** (`viewer.js` → `layout.js`):

1. Mount every node as an absolutely-positioned `<div>`, nesting a class's
   children inside its `.node__children` box.
2. `await document.fonts.ready` — text-sized nodes measure wrong before fonts
   settle.
3. Measure **leaf** nodes with `getBoundingClientRect()` (rounded up to avoid
   sub-pixel clipping). Compound (class) nodes are **not** measured — ELK sizes
   them from their children + padding.
4. Convert the flat `{nodes, edges}` model into ELK's nested form and run
   `elk.layout()`.
5. Apply the returned coordinates: `left/top` for every node, plus explicit
   `width/height` for compounds.

**Options that matter** (`ROOT_OPTIONS` / `COMPOUND_OPTIONS`):

- `elk.algorithm: layered`, `elk.direction: RIGHT` — left-to-right dataflow.
- `elk.hierarchyHandling: INCLUDE_CHILDREN` — **the load-bearing option.** It
  lets edges declared at the root cross into nodes nested inside a compound
  (e.g. `configfile → Config.from_yaml`). Without it, cross-hierarchy edges are
  silently dropped or rerouted to the compound boundary.
- `elk.padding: [top=40,left=16,bottom=16,right=16]` on compounds — reserves the
  top strip for the class-header overlay so children never sit under it.
- Layer/node spacing tuned for legibility, not correctness.

**Coordinate contract (the subtle part).** ELK returns child coordinates
*relative to the parent node's top-left*. That only maps cleanly to the DOM if
the child-mount box shares the parent's origin — so `.node--class .node__children`
is `position:absolute; inset:0` and the header is an absolute overlay in the
reserved top padding. Getting this wrong produces a ~header-height vertical
drift that stacks with nesting depth. **One coordinate space, top-left origins,
everywhere** — the edge geometry (`edges.js` `absPos`) and the drag clamp both
assume it.

**Edges are decoupled from ELK.** ELK is used for **node positions only**. Every
edge — initial, mid-drag, restored — is drawn by a single bezier function
between node-side anchors computed in untransformed canvas space. This is
deliberate: no bend-point routing means no stale-routing / two-renderer mess
when a node is dragged.

**Persistence gate** (`layout_store.py`). A topology hash (sorted node ids +
edge pairs) decides at build time:
- hash matches saved layout → **restore** (skip ELK entirely; sizes re-derived
  in the browser, compounds bottom-up from children),
- hash differs → **ELK** re-layout + a visible "topology changed" notice,
- no saved layout → plain ELK.
Positions are never silently mixed.

## What was learned / gotchas

- **INCLUDE_CHILDREN just works** for the cross-hierarchy edge — this was the #1
  de-risk in the plan and needed no option fiddling. Validate it first on any
  new nesting level (e.g. workflow/step grouping) before trusting it.
  The flip side: it ignores per-compound `elk.algorithm`/`elk.direction`, which
  killed per-subgraph layout *config*. The sanctioned bypass is
  `diagram: classLayout:` (layout.js `planStacks`): stack class interiors
  outside ELK and present each class to ELK as a fixed-size leaf, remapping
  member edge endpoints in the elk graph (elkjs throws on unknown ids).
- **Measure after `fonts.ready`**, and round leaf sizes up. Fractional widths
  caused occasional single-line labels to wrap.
- **Don't measure compounds** — let ELK size them; otherwise you fight the DOM's
  pre-layout size against ELK's computed size.
- **The interactive-hint path is the soft spot.** On a topology change we pass
  saved positions as `x/y` with `elk.interactive: true`, but ELK layered does
  **not** honor free-form pinned positions the way the plan's prose implies —
  it uses them only as ordering hints, and the result is essentially a clean
  re-layout. That satisfies the acceptance criteria (no 0,0 pileup, clear
  notice) but "saved positions as hints" is weaker than it sounds. This is the
  main thing worth revisiting.
- **Performance ceiling** is low hundreds of nodes: DOM node count + synchronous
  ELK + ~100–300 ms to parse/eval the 1.6 MB GWT bundle on load. Fine for
  pipeline diagrams; don't engineer around it.

## Recommended plan

Ordered by value-for-effort. None of these are blocking; the current layout is
correct and shippable.

1. **Honest topology-change behavior (highest value).** Stop implying pinned
   hints work. Pick one:
   - *Preserve-what-you-can:* keep the subgraph whose positions are known fixed
     (render those from saved coords) and run ELK only on the new/changed
     component, anchored to its neighbors. Needs ELK per-connected-component or a
     manual placement pass for new nodes near their references. More faithful to
     the "approximated" promise.
   - *Or* drop the hint pretense entirely: on mismatch, do a clean re-layout and
     let the notice own the UX. Simpler, already 90% there. Recommend this
     unless users complain about losing arrangement on small edits.
   Either way, update the notice copy to match reality.

2. **Slim-artifact build.** When every node has a saved position (pure restore),
   emit **without** elkjs — the browser never calls ELK in restore mode. That
   drops output from ~1.7 MB to a few KB. Gate in `emit.py` on
   `_layout.mode == "restore"`; keep the full build otherwise. High value, low
   risk, already anticipated in PLAN.md.

3. **Layout options as data, not code.** Promote `ROOT_OPTIONS` /
   `COMPOUND_OPTIONS` to a small config (YAML `layout.options:` or a JSON block)
   so direction, spacing, and algorithm are tunable without touching engine JS.
   Keeps the "modification surface" promise honest for layout, not just styling.

4. **Deeper nesting (workflow/step grouping).** The model is already recursive
   and INCLUDE_CHILDREN is hierarchy-agnostic, so this is mostly parser +
   template work. **Before building it**, validate a 2-level cross-hierarchy
   edge (top-level → node inside a step inside a workflow) — that's the one place
   ELK options might need attention, per the same de-risk logic as M2.

5. **Edge-routing upgrade (only if asked).** Current single-bezier routing can
   overlap nodes on dense graphs. If that becomes a real complaint, the cheap
   win is orthogonal/segmented routing computed in the same anchor space — *not*
   adopting ELK's bend points (which reintroduces the stale-routing problem the
   architecture deliberately avoids). Treat as a v2 decision.

6. **Guardrails.** Add a browser-level smoke test (headless) that asserts: no
   two top-level nodes overlap, the cross-hierarchy edge's endpoints resolve,
   and restore reproduces saved coords exactly. The Python side is covered;
   layout regressions currently need a human eye.
