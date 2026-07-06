# io-flow — Implementation Plan

YAML → interactive, single-file HTML diagrams. This document is the approved plan and is intended to be handed to an orchestrating agent for implementation. It is self-contained: requirements, architecture, settled decisions, milestones with acceptance criteria, and verification steps.

## 1. Context and requirements

The repo is a fresh uv Python project (empty stub `main.py`, no dependencies yet). The goal, per `context.md`, is a tool that builds mermaid-like dependency/dataflow diagrams that are:

- **Defined purely in YAML** — see `example_input.yaml` for the spec contract: input nodes (files / options / parameters), functions, classes wrapping attributes + methods, and (future) "workflow"/"step" grouping. The comments in that file document the expected edges and are the parser's acceptance spec.
- **Emitted as a single portable `.html` file** — interactive, viewable offline from `file://`, no server required to view, zero network requests.
- **"Mostly HTML"** — node types map to HTML templates styled by plain CSS. This is an explicit, load-bearing user requirement and the deciding constraint behind the library choices.
- **Auto-laid-out** by an existing layout package, but nodes are **draggable in-browser** with the adjusted layout **saved back into the source YAML**.
- **Interactive**: clicking a node dims everything except its direct in/out neighbors; an optional sidebar shows node details.

**Top priority: ease of modification.** Prefer simple existing packages; no build tooling, no npm, no bundlers.

### Design principle (agreed with the user — enforce throughout)

JS is unavoidable for layout/drag/adjacency, so split it hard into an **engine** (written once, rarely touched) and an **editable surface**. Every routine change — node appearance, colors, dim styling, sidebar layout, adding a node type's markup — must be an HTML-template or CSS edit, never an engine edit. Concretely: `viewer.css` + the `type → template` map in `templates.js` are the entire modification surface; everything else is infrastructure behind a hard module boundary. Interaction scope is **frozen for v1** (pan/zoom, drag, dim, sidebar — nothing more); multi-select, edge editing, minimap etc. are deliberate future decisions, possibly a library switch.

## 2. Settled decisions — do not re-litigate

This plan was produced by an ideas agent, adversarially reviewed by a second agent (which fact-checked library claims via web search), and refined with the user. The following are decided:

| Decision | Rationale |
|---|---|
| **elkjs** for layout; plain HTML divs for nodes; SVG paths for edges; vanilla JS | Only approach that fully satisfies "mostly HTML + plain CSS". ELK natively lays out compound/nested graphs incl. cross-hierarchy edges. |
| Cytoscape.js **rejected** | Canvas rendering; styling via JSON stylesheet not CSS; its `node-html-label` extension has confirmed open bugs (labels don't hide with nodes) incompatible with the dim feature. |
| React Flow **rejected** | Needs a bundler to make a single offline file; framework tax. Also checked and rejected: vis-network, AntV X6/G6, JointJS, dagre, GoJS, raw D3, d3-dag, sigma, drawflow, litegraph, jsPlumb (archived), maxGraph. |
| ELK is used for **node positions only** — no bend-point edge rendering | One bezier geometry function for all states (initial layout, post-drag, restored layout) avoids a stale-routing / two-renderer mess. |
| Layout persistence uses a **topology hash** | ELK layered cannot mix pinned and free nodes (verified). Hash matches → restore positions exactly, skip ELK. Hash differs → ELK interactive mode with saved positions as hints + visible notice. Never silently mix. |
| `io-flow edit` (localhost serve + POST-save) is the **primary editing loop** | Browser sandbox can't write files; download-then-merge is too clunky as primary UX. The emitted artifact is still a static single file. |
| Vendor **anvaka/panzoom** (~10 KB, MIT) for pan/zoom; hand-roll node drag only | Wheel/pinch/transform math is not worth owning. |
| Child drags are **clamped inside their parent; parents do not auto-resize** (v1) | Bounds the interaction-layer complexity. |
| elkjs is **1.63 MB with no official min build** → output files are ~1.7 MB | Accepted for v1. Optional later: when every node has a saved position, emit without elkjs for a slim artifact. |
| `data-node-id` attributes, never `id` | Qualified ids contain dots (`Config.from_yaml`), which break `querySelector('#…')`. |
| Python deps: **`ruamel.yaml` only** (+ optionally `jinja2`; plain string substitution is acceptable) | ruamel round-trip mode is required to preserve the comment-heavy YAML on save-back. |

## 3. Architecture

### 3.1 Python CLI (`io-flow`)

- **`parser.py`** — YAML → normalized recursive graph model `{nodes: [{id, type, parent, data}], edges: [{source, target}]}`. Hardened edge derivation:
  - **Two-pass**: collect all node ids first, then resolve references (handles forward references).
  - References are looked for **only in a whitelist of positions** — class `attributes:` values and method/function `args:` values. Never scan `value:`, `cli:`, `description:`. Exact match only.
  - Class children get **qualified ids** (`Config.attributes`, `Config.from_yaml`); the class itself becomes a compound/parent node. The model is recursive from day one so future workflow grouping is just another parenting level.
  - **Duplicate ids are a hard error.** Unresolved or ambiguous references produce a **loud warning listing candidates** — wrong diagrams that look plausible destroy trust.
  - Escape hatches (design in now, implement when needed): explicit `edges:` section and/or `!ref` tag to disambiguate literals from references.
  - Expected edges for `example_input.yaml`: `limitparam → Config.attributes`, `configfile → Config.from_yaml`, `Config → do_run`, `skippreflight → do_run`.
- **`layout_store.py`** — reads/merges the `layout:` block. Compact flow-style entries (`nodeid: [x, y]`) at the bottom of the file, plus a **topology hash** (hash of sorted node ids + edge pairs). All merging goes through ruamel.yaml round-trip mode so comments survive. One merge code path shared by the server and the CLI fallback.
- **`server.py`** — stdlib `http.server`, ~60 lines, zero dependencies. Serves the built HTML; `POST /save` receives `{nodeId: [x, y]}` positions, merges into the source YAML via `layout_store`, re-emits `diagram.html`.
- **`emit.py`** — inlines the graph JSON (`<script type="application/json">`), viewer JS/CSS, and vendored `elk.bundled.js` + `panzoom.min.js` into `viewer.html` → self-contained `diagram.html`. No CDN references in output.
- **`cli.py`** — argparse subcommands:
  - `build input.yaml [-o diagram.html]` — compile once. Applies the topology-hash policy: hash matches saved layout → positions baked in, browser skips ELK; differs → browser runs ELK interactive with hints and shows a "topology changed; layout approximated (N nodes added/removed)" notice.
  - `edit input.yaml` — build, serve on localhost, open browser. **Primary workflow**: drag → Save (POSTs to server, YAML updated in place, comments preserved, HTML re-emitted) → Ctrl-C → the leftover `diagram.html` is the portable viewer.
  - `apply-layout input.yaml layout.json` — optional fallback for the no-server case (same merge path).

### 3.2 Browser viewer (vanilla JS, no framework, no build step)

- **Layout**: elkjs — `elk.algorithm: layered`, direction RIGHT, `hierarchyHandling: INCLUDE_CHILDREN` (compound graphs with cross-hierarchy edges). Pipeline: render node divs → wait for `document.fonts.ready` → measure at scale 1 with `getBoundingClientRect()` → feed real sizes to ELK with `elk.padding` and label placement options (class header must not overlap children) → apply positions. ELK child coordinates are parent-relative, matching nested `position: absolute`.
- **Nodes**: absolutely-positioned `<div>`s. `templates.js` holds the `type → template function` map (`file`, `option`, `parameter`, `function`, `class`, `attributes`, `method`). All appearance lives in `viewer.css` (`.node--file`, `.node--class`, …). Class nodes contain their children's divs.
- **Edges**: one SVG underlay; a `<path>` per edge; arrowheads via SVG `<marker>`. **A single geometry function** (smooth bezier between node-side anchor points) renders every edge in every state. Anchors for nested nodes computed by cumulative offset up the ancestor chain.
- **Pan/zoom**: vendored panzoom on the canvas container.
- **Drag**: hand-rolled pointer events on nodes only. Deltas divided by current zoom scale; `stopPropagation` so dragging a child doesn't drag the parent; a movement threshold distinguishes click (dim) from drag; children clamp inside parent bounds. Incident edges re-render through the single geometry function on every move.
- **Click-to-dim**: adjacency map precomputed at load. Compound rules (decided): child edges aggregate to ancestors; selecting a parent highlights the union of its children's neighborhoods; selecting a child keeps its ancestors undimmed. Toggle a `.dimmed` class — appearance (opacity, transition) is pure CSS. Background click or Escape clears.
- **Sidebar**: plain `<aside>`, populated from the selected node's data (cli flag, value, description, loc, args). Hidden until a node is selected.
- **Save button**: capability-detected. Served from `http://localhost` (+ successful ping of the save endpoint) → visible, POSTs positions. Opened from `file://` → hidden; everything else still works.

**Budget** (post-adversarial-review, realistic): ~1,000–1,400 lines JS total (the editable `templates.js` + `viewer.css` surface stays small and isolated), ~200 lines CSS, ~300 lines Python.

## 4. File layout (all new)

```
src/io_flow/
  cli.py            # argparse: build / edit (serve + POST /save) / apply-layout
  parser.py         # two-pass YAML → recursive graph model; hardened edge derivation
  layout_store.py   # layout: block read/merge (ruamel round-trip), topology hash
  emit.py           # inline JSON + assets into template
  server.py         # stdlib http.server + /save endpoint
  assets/
    viewer.html     # skeleton: canvas container, SVG underlay, sidebar, slots
    viewer.css      # ALL node-type styling  ← user-editable surface
    templates.js    # type → HTML template map ← user-editable surface
    engine/         # rarely touched: layout.js, drag.js, dim.js, edges.js, save.js
    vendor/
      elk.bundled.js
      panzoom.min.js
tests/
  test_parser.py
  test_layout_store.py
```

`pyproject.toml`: add `ruamel.yaml`; add `[project.scripts] io-flow = "io_flow.cli:main"`; adopt src layout (retire the stub `main.py`). Vendor files fetched once via curl from npm/jsDelivr and committed.

## 5. Milestones, ordering, and acceptance criteria

Each milestone is independently testable; 1–3 give a viewable, clickable diagram; 4–5 add editing.

**M1 — Parser** (`parser.py`, tests)
Parse `example_input.yaml` into the graph model.
✅ Tests pass asserting the exact expected edge list (see §3.1); no phantom edges from `value:`/`cli:`/`description:` content; duplicate ids raise; unresolved references warn with candidates.

**M2 — Static viewer** (`templates.js`, `viewer.css`, `engine/layout.js`, `engine/edges.js`, `viewer.html`)
Templates → mount → fonts.ready → measure → ELK → position → SVG edges.
⚠️ **De-risk first**: validate the cross-hierarchy edge (`configfile → Config.from_yaml`, an edge from a top-level node to a node inside a compound) with `INCLUDE_CHILDREN` before building anything else — this is the one ELK feature that may need option fiddling.
✅ Diagram renders with `Config` visually wrapping `attributes` and `from_yaml`; all four edges drawn with arrowheads; no overlaps.

**M3 — Dim + sidebar** (`engine/dim.js`, sidebar markup/CSS)
✅ Clicking any node dims all non-neighbors (compound rules per §3.2); sidebar shows the node's data; Escape/background-click clears.

**M4 — Pan/zoom + drag** (`engine/drag.js`, vendored panzoom)
✅ Pan/zoom works (wheel + pinch); nodes drag correctly at any zoom level; child drags stay inside parents and don't move the parent; click-vs-drag threshold works; incident edges follow live.

**M5 — Save-back** (`layout_store.py`, `server.py`, `engine/save.js`, hash policy in build)
✅ `io-flow edit example_input.yaml` → drag → Save → the YAML gains a compact flow-style `layout:` block **with every original comment preserved**; reload reproduces positions exactly (ELK skipped). Adding a node to the YAML and rebuilding shows the "topology changed" notice with no 0,0 pileup. Save button hidden on `file://`.

**M6 — Emit + CLI wiring** (`emit.py`, `cli.py`, pyproject)
✅ `uv run io-flow build example_input.yaml` produces a single `diagram.html` that works offline (zero network requests) with all interactivity except save.

Parallelization notes for the orchestrator: M1 and M2 can proceed in parallel (M2 can start from a hand-written JSON fixture matching the model schema, which then doubles as a parser test fixture). M3 and M4 both depend on M2 but not on each other. M5 depends on M1 + M4. M6 is mostly independent glue and can be drafted early.

## 6. Verification (end-to-end)

1. `uv run pytest` — parser and layout-store suites green.
2. `uv run io-flow edit example_input.yaml`; in the browser: layout sane; nesting correct; cross-hierarchy edge renders; click-dim + sidebar work; drag a node; Save; confirm the YAML diff is only a compact `layout:` block appended (comments intact); reload reproduces positions exactly.
3. Edit the YAML (add a node), rebuild → visible "topology changed" notice, new node placed sensibly.
4. Stop the server; open `diagram.html` via `file://` — fully interactive, save button hidden, network tab shows zero requests.
5. Ease-of-modification smoke test (the top priority, so test it explicitly): change `.node--file`'s color in `viewer.css` and add a trivial new node type to `templates.js` — both must require **zero** engine edits.

## 7. Known risks

- **ELK cross-hierarchy layout** may need option fiddling — that's why it is validated first in M2.
- **Interaction-layer complexity** (nested drag + zoom transforms) is the budget's soft spot; the panzoom vendor and the clamp-don't-resize decision exist to contain it. If it still balloons, the agreed fallback is AntV X6 — but only after M2–M4 genuinely fail, not preemptively.
- **ruamel round-trip quirks**: always verify comment preservation in tests, not by eye.
- Performance ceiling is low hundreds of nodes (DOM + synchronous ELK, ~100–300 ms parse/eval of the GWT bundle on load) — fine for the intended pipeline-diagram scale; document, don't engineer around.
