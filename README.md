# io-flow

Turn a YAML description of a pipeline into an **interactive, portable, single
`.html` file** — no server needed to view it, zero network requests, works
offline from `file://`.

Nodes are plain HTML `<div>`s styled with plain CSS; layout is computed by
[elkjs](https://github.com/kieler/elkjs); edges are SVG. Click a node to dim
everything but its direct neighbors, drag nodes to rearrange, collapse groups,
filter by name, and (when editing) save the arranged layout straight back into
the source YAML with every comment preserved.

## Install

```bash
uv sync                  # dev: also `uv sync --extra dev` for pytest
uv tool install .        # or: install the `io-flow` command globally
```

## Use

```bash
# Compile once -> a single portable diagram.html
io-flow build example_input.yaml -o diagram.html

# Primary editing loop: build, serve on localhost, open browser.
# Drag nodes -> click "Save layout" -> Ctrl-C. The YAML gains a compact
# `layout:` block; the leftover diagram.html is the portable viewer.
# The browser live-reloads whenever the YAML (or a skin file) changes.
io-flow edit example_input.yaml

# Validate only; --strict exits nonzero on unresolved references (CI).
io-flow check example_input.yaml --strict

# No-server fallback: merge a {id: [x, y]} JSON into the YAML.
io-flow apply-layout example_input.yaml layout.json
```

Opened over `http://localhost` (via `edit`) the **Save** button appears and
writes back to the YAML. Opened from `file://` it is hidden and everything else
still works.

Once every node has a saved position (layout hash matches), `build` omits
elkjs entirely and the artifact drops from ~1.7 MB to tens of KB.

## Input format

See [`example_input.yaml`](example_input.yaml) for a worked example. Top-level
keys:

- **`title:`** — the HTML page title (defaults to the filename).
- **`nodes:`** — the node declarations (below).
- **`edges:`** — explicit edges: `- {from: a, to: b, type: calls, label: "..."}`.
  `type` is a free tag; every edge's type becomes an `edge--<type>` CSS class.
- **`relations:`** — register new relationship kinds (below).
- **`diagram:`** — per-diagram layout config (below).
- **`layout:`** — machine-owned block written by Save; don't edit by hand.

Under `nodes:`:

- **`input:`** — files / options / parameters. `type:` is free-form and maps
  straight to a template + `.node--<type>` CSS class.
- **`classes:`** — a compound node wrapping an `attributes:` node and each
  method. Class members get qualified ids (`Config.from_yaml`).
- **`functions:`** — processing nodes.
- **`groups:`** — compound containers nesting functions/classes/other groups
  ("steps", "workflows"). A group may carry `args`/`calls`/`returns` of its
  own, behaving like a function.

Any node takes `label:` (display name; the key stays the unique id) and free
data keys (`loc:`, `description:`, ...) shown in the sidebar.

**Edge derivation.** Edges come only from registered reference positions,
matched exactly against node ids — free text in `value:`/`cli:`/`description:`
never creates an edge. Built-ins:

| key        | direction              | reference position        |
|------------|------------------------|---------------------------|
| `args:`    | referenced node → owner | entry **values** (non-strings are literal defaults) |
| `calls:`   | owner → referenced node | entry **keys** (values are optional edge labels) |
| `returns:` | owner → referenced node | entry **keys** (values are optional edge labels) |

Duplicate ids are a hard error; an unresolved reference prints a loud warning
listing close candidates (`io-flow check --strict` turns those into a failing
exit code).

**Registering new relationship kinds.** `relations:` extends that table per
diagram, no code required:

```yaml
relations:
  emits: {direction: out}             # ref: key is the default
  reads: {direction: in, ref: value}

nodes:
  functions:
    a:
      emits: {log: "event"}           # a -> log, labeled, class edge--emits
```

**Layout config.** `diagram:` merges over the ELK defaults:

```yaml
diagram:
  direction: DOWN        # RIGHT (default) | DOWN | LEFT | UP
  algorithm: layered     # any elkjs algorithm (mrtree, force, ...)
  spacing: 40            # node-node spacing
  layerSpacing: 70       # between layers
  elk:                   # raw ELK options, highest precedence
    elk.aspectRatio: "2"
```

## Customizing appearance (the whole point)

Two files are the **entire modification surface** — change them without ever
touching engine code:

- **`viewer.css`** — all node + edge appearance. Recolor a type, style an edge
  kind (`.edge--calls`), restyle the sidebar, tweak the dim opacity. The
  compound-header height lives in one place (`--header-h`).
- **`templates.js`** — the `type → HTML` map for nodes, plus the optional
  `IOF.sidebars` map for per-type sidebar detail (types without an entry get a
  generic dump of their data keys). Adding a node type = one function here +
  one CSS rule.

Per-project skins without editing the installed package:

```bash
io-flow build pipeline.yaml --css my_skin.css --templates my_templates.js
```

Everything else lives behind a hard module boundary in
`src/io_flow/assets/engine/` (layout, edges, dim, drag, pan, save, live,
collapse, ui) and rarely needs editing.

## Viewer interactions

- **Click** a node: dim everything but its neighborhood + details sidebar.
- **Drag** nodes (children stay clamped inside their parent); **pan/zoom** the
  canvas.
- **Resize** groups and classes with the bottom-right corner handle for more
  interior room. Sizes persist with Save (compounds store `[x, y, w, h]` in
  the `layout:` block) and never shrink below their children.
- **Collapse/expand** groups and classes via the header toggle; edges to hidden
  children re-anchor to the container.
- **Filter box** (top-left): dims non-matches; Enter selects and centers the
  first match; Escape clears. A **legend** shows each node type present.
- **Save layout** (edit mode): writes positions into the YAML's `layout:` block.
- **Live reload** (edit mode): edit the YAML in your editor and the browser
  refreshes itself; a parse error shows in the browser and recovers on fix.
  Unsaved drag positions are lost on reload — the file is the source of truth.

## Accessibility

The picture itself can't carry a graph for a screen reader, so the viewer
generates a parallel text representation from the same graph model:

- A hidden **text alternative** (first in reading order): every node as a
  nested list mirroring containment, each entry naming its inputs and outputs
  with edge types and labels — the information the SVG edges encode visually.
- **Nodes are focusable** with accessible names ("do_run, function") and
  descriptions listing their connections. Enter/Space selects (dim + sidebar),
  Escape clears, and selections are announced via a live region.
- **Arrow keys nudge** the focused node by 8px (Shift for 1px), with the same
  parent clamping as mouse drag — layout editing works without a pointer.
- Collapse toggles carry `aria-expanded` and name their target; the search
  field, legend, notice, and save-state changes are labeled/announced.

Known gaps: pan/zoom and the resize handle are pointer-only (search-and-Enter
centers a node as the keyboard alternative to panning).

## Architecture

```
src/io_flow/
  cli.py            argparse: build / edit / check / apply-layout
  parser.py         two-pass YAML -> recursive graph model; EDGE_KEYS registry
  layout_store.py   layout: block read/merge (ruamel round-trip) + topology hash
  emit.py           inline JSON + CSS + JS into one self-contained HTML
  server.py         stdlib http.server: rebuild-on-GET, POST /save, /version
  assets/
    viewer.html     skeleton with style/graph/script slots
    viewer.css      <- user-editable: all node/edge styling
    templates.js    <- user-editable: node templates + sidebar templates
    engine/         layout edges dim drag pan save live collapse ui viewer
    vendor/         elk.bundled.js, panzoom.min.js
tests/              parser, layout_store, emit, server, cli
```

Layout persistence is gated by a **topology hash** (sorted node ids + edge
pairs). Hash matches the saved layout → positions are restored exactly and elkjs
is skipped (and omitted from the artifact). Hash differs → elkjs re-lays-out
(with the saved positions as hints) and the viewer shows a "topology changed"
notice. Positions are never silently mixed.

## Notes / limits

- Full output is ~1.7 MB (elkjs ships no minified build); pinned-layout output
  is tens of KB. Fine for the intended pipeline-diagram scale (low hundreds of
  nodes).
- Child nodes are clamped inside their parent; parents don't auto-grow while
  dragging, but can be resized manually via the corner handle.
- `data-node-id` attributes are used instead of `id`, because qualified ids
  contain dots that break `querySelector('#…')`.

## Tests

```bash
uv run --extra dev pytest
```
