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
# Drag nodes, create connections (Connect button), click "Save layout",
# Ctrl-C. The YAML gains a compact `layout:` block and new `edges:` entries;
# the leftover diagram.html is the portable viewer. The browser live-reloads
# whenever the YAML (or a skin file) changes.
io-flow edit example_input.yaml

# Validate only; --strict exits nonzero on unresolved references (CI).
io-flow check example_input.yaml --strict

# No-server fallback: merge a {id: [x, y]} JSON into the YAML.
io-flow apply-layout example_input.yaml layout.json

# Tidy a hand-arranged layout: left/top edges within --tolerance px of each
# other (siblings only -- positions are parent-relative) snap to exact
# columns/rows. Run it while `edit` is serving and watch the live reload.
io-flow align example_input.yaml            # default tolerance: 8px
io-flow align example_input.yaml --dry-run  # print what would move
```

Opened over `http://localhost` (via `edit`) the **Save** button appears and
writes back to the YAML. Opened from `file://` it is hidden and everything else
still works.

Once every node has a saved position (layout hash matches), `build` omits
elkjs entirely and the artifact drops from ~1.7 MB to tens of KB.

## Input format

**`$name` means node, everywhere.** A key starting with `$` declares a node;
a `$`-marked key or string value inside a relation block references one. One
rule covers declaration, nesting, and reference. See
[`example_input.yaml`](example_input.yaml) for a worked example.

```yaml
defaults:
  class: method              # untyped children of a class are methods
nodes:
  $configfile: {type: file, cli: --config}
  $Config:
    type: class
    loc: src/config.py       # not reserved, not $-marked: free sidebar data
    $from_yaml:              # child node; id "from_yaml"
      args: {path: $configfile}
```

Top-level keys:

- **`title:`** — the HTML page title (defaults to the filename).
- **`nodes:`** — the node declarations (every key must be a `$name`).
- **`edges:`** — explicit edges: `- {from: $a, to: $b, type: calls, label: "...", weight: 42}`.
  `type` is a free tag; every edge's type becomes an `edge--<type>` CSS class.
  `weight` is an optional flow volume drawn as stroke width (below).
  An `edges:` list may also live inside any node (below).
- **`relations:`** — register new relationship kinds (below).
- **`defaults:`** — default types for untyped nodes (below).
- **`diagram:`** — per-diagram layout config (below).
- **`layout:`** — machine-owned block written by Save; don't edit by hand.

Inside a node's mapping:

- **`$name:`** — a child node. Compound-ness is a state, not a type: any node
  with `$`-children is a container. Names are globally unique and are the
  ids; nesting only sets the parent, so regrouping a node never changes its
  name — references and saved layouts survive reorganization. Labels default
  to the name.
- **`type:`** — free-form; maps straight to a template + `.node--<type>` CSS
  class, no registration anywhere.
- **`label:`** — display-name override (the name stays the unique key). When
  two things naturally share a name, pick unique names — dots carry no
  meaning, so `$Config.run` and `$Runner.run` are just two names — and label
  them for display.
- **`tier:`** — optional integer column constraint (ordinary data, read by
  the layout): all nodes sharing a tier render in the same layer — an
  invisible grouping tier, e.g. every sankey source in one column. Lower
  tiers sit earlier in the layout direction. Only shapes the ELK draft;
  saved layouts still win.
- **relation names** (`args`/`calls`/`returns`/registered) — edge blocks.
- **`edges:`** — a locally-declared explicit-edge list, handy for keeping a
  group's internal wiring inside the group. An omitted `from`/`to` defaults
  to the declaring node. Placement is organization only: references are
  always global names, so moving the list never changes its meaning.
- **anything else** — free data (`loc:`, `cli:`, `description:`, ...) shown in
  the sidebar and available to templates.

**Edge derivation.** References are self-marking: inside a relation block,
whichever side of an entry wears the `$` is the reference; the unmarked side
is a literal (arg name, edge-label text, or default value). Unmarked strings
can never create an edge, so free text in `value:`/`cli:`/`description:` is
always safe. Built-ins:

| key        | direction               | example |
|------------|-------------------------|---------|
| `args:`    | referenced node → owner | `args: {path: $configfile, retries: 3}` |
| `calls:`   | owner → referenced node | `calls: {$from_yaml: "load config"}` |
| `returns:` | owner → referenced node | `returns: {$report: ""}` |

An unresolved `$ref` prints a loud warning listing close candidates; an
unmarked string that exactly matches a node id warns that a `$` may be missing
(`io-flow check --strict` turns warnings into a failing exit code).

**Weighted edges (flow volumes).** The unmarked side of a `$`-keyed relation
entry annotates the edge *by type*: a string is a label, a number is a
weight. Explicit edges take a numeric `weight:` alongside `type`/`label`.
Weighted edges scale their stroke width — proportional to the diagram's
heaviest flow, sqrt-damped so a 100× volume isn't a 100× line — carry an
`edge--weighted` class, and use a fixed-size arrowhead. Unweighted edges are
untouched, so structural wiring and flow volumes mix freely in one diagram
(see [`examples/weighted_flow.yaml`](examples/weighted_flow.yaml)):

```yaml
nodes:
  $parse: {calls: {$validate: 118000}}   # number = weight
  $validate: {calls: {$dedupe: "check"}} # string = label, as before
edges:
  - {from: $validate, to: $quarantine, type: passes, weight: 22000}
diagram:
  edgeWidth: {min: 1.5, max: 12, scale: sqrt}  # defaults; scale: sqrt | linear
```

**Sankey mode.** For flow diagrams where quantities are the point, declare
`diagram: sankey:` and give every node a `population:` — its size *as data*,
in the same unit as the edge weights:

```yaml
diagram:
  sankey: {unit: 12}        # px per item; omit unit to auto-scale (~160px max)
nodes:
  $applied:   {population: 7}
  $interview: {population: 3}
edges:
  - {from: $applied, to: $interview, weight: 3}
```

Rendering then works differently: node height is exactly `population × unit`
(not measured from content — the box *is* the bar, so style labels outside
via CSS), band widths are exactly `weight × unit` (`edgeWidth:` is ignored),
bands tile node sides contiguously so incoming flows sum to precisely the
node's height when the data conserves, and arrowheads are dropped. A node
without a numeric population keeps its measured size and logs a console
warning. `examples/csv_to_sankey.py` generates all of this — populations,
weights, strata colors, bar styling — from a CSV of items progressing
through boolean stages.

**Class layout mode.** ELK ignores per-compound layout options under the
hierarchy handling this project depends on (see `ELK_LAYOUT_NOTES.md`), so
per-subgraph layout is a mode instead: declare `diagram: classLayout:` and
every `class` compound renders as a UML-style stacked member list — members
in declaration order, uniform width — while ELK still arranges everything
outside the classes (each stacked class faces ELK as a fixed-size box, and
edges into members keep working):

```yaml
diagram:
  classLayout:              # bare = {types: [class]}; {types: [class, group]} widens
```

The engine owns the stack geometry only; row appearance is CSS via the
`.node--stacked` class it adds (defaults in `viewer.css`, edit freely). A
stacked class may contain leaves and nested stacked classes; any other
compound inside makes that class fall back to normal ELK layout with a
console warning. Drag, resize, collapse, and Save work as usual — members
drag like any node, and a dragged-out member saves and restores where you
left it. Saved layouts win as always: toggling the mode on in a file that
already has a `layout:` block restores the saved positions (only row widths
normalize); delete the block to get freshly stacked classes. Non-goal:
`sankey:` and `classLayout:` together is untested. See
[`examples/class_layout.yaml`](examples/class_layout.yaml).

**Registering new relationship kinds.** `relations:` extends that table per
diagram, no code required. Because references self-mark, a relation declares
only its direction:

```yaml
relations:
  emits: {direction: out}
  reads: {direction: in}

nodes:
  $log: {type: file}
  $a: {emits: {$log: "event"}}        # a -> log, labeled, class edge--emits
```

**Default types.** Untyped nodes get `type: node`. The `defaults:` block maps
a parent type to its children's default (`_root` covers top-level nodes), so
terse declarations stay correct:

```yaml
defaults:
  class: method
  group: function
  _root: input
```

**Layout config.** `diagram:` merges over the ELK defaults:

```yaml
diagram:
  direction: DOWN        # RIGHT (default) | DOWN | LEFT | UP
  algorithm: layered     # any elkjs algorithm (mrtree, force, ...)
  spacing: 40            # node-node spacing
  layerSpacing: 70       # between layers
  edgeWidth:             # weighted-edge stroke range (see Weighted edges)
    {min: 1.5, max: 12, scale: sqrt}
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

**How much CSS controls.** Node *size* is genuinely CSS-owned: before layout,
the engine measures each rendered node from the DOM (after fonts settle), so
padding, font, and `max-width` changes flow straight into ELK and into
restored layouts — a chunkier node type really gets more room. Node
*position* and *spacing* are not CSS: positions are frozen into inline pixels
(the coordinate space that edges, drag, and Save all trust), and gaps between
nodes are an ELK input, tuned from the YAML `diagram:` block. If you restyle
nodes much bigger under an already-pinned layout, sizes update on reload but
positions don't — re-arrange (or delete the `layout:` block for a fresh ELK
draft) if things crowd.

**`--header-h`: the one CSS value the engine reads.** The compound-header
height is geometry that styling genuinely needs to change, so the engine
reads it from the CSS variable (`IOF.headerH()`) instead of hard-coding it.
It drives the ELK top-padding inside compounds, the drag/keyboard clamp that
keeps children below the header, and the collapsed height. Restyle the header
taller or shorter in one place — `:root { --header-h: ... }` — and layout,
dragging, and collapse all follow; no engine edit, no stale offsets.

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
- **Connect** (edit mode): toggle the Connect button, click a source node,
  then a target node — the edge appears immediately, with optional type/label
  from the small form (type suggestions come from the edges already present;
  any free-form tag works). Repeat to add more; Escape or the button exits.
  **Append-only by design**: the browser can add explicit edges but never
  delete or rewrite existing ones — derived edges live woven into your
  hand-written relation blocks, so removal is a YAML edit (live reload makes
  that loop fast). Unsaved connections are lost on reload, same as drags.
- **Save layout** (edit mode): writes positions into the YAML's `layout:`
  block and appends browser-created connections to the `edges:` list.
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
- **Connect mode works from the keyboard**: with the mode active, Enter/Space
  on a focused node picks it as source, then target — same flow as clicking.
- Collapse toggles carry `aria-expanded` and name their target; the search
  field, legend, notice, and save-state changes are labeled/announced.

Known gaps: pan/zoom and the resize handle are pointer-only (search-and-Enter
centers a node as the keyboard alternative to panning).

## Architecture

```
src/io_flow/
  cli.py            argparse: build / edit / check / apply-layout / align
  align.py          snap almost-aligned saved positions (per sibling space)
  parser.py         two-pass YAML -> recursive graph model; EDGE_KEYS registry
  layout_store.py   layout: block read/merge (ruamel round-trip) + topology hash
  edge_store.py     append browser-created connections to edges: (append-only)
  emit.py           inline JSON + CSS + JS into one self-contained HTML
  server.py         stdlib http.server: rebuild-on-GET, POST /save, /version
  assets/
    viewer.html     skeleton with style/graph/script slots
    viewer.css      <- user-editable: all node/edge styling
    templates.js    <- user-editable: node templates + sidebar templates
    engine/         layout edges dim drag pan save connect live collapse ui viewer
    vendor/         elk.bundled.js, panzoom.min.js
tests/              parser, layout_store, emit, server, cli
```

Layout persistence is gated by a **topology hash** (sorted `(id, parent)`
pairs + edge pairs — parentage matters because saved positions are
parent-relative). Hash matches the saved layout → positions are restored exactly and elkjs
is skipped (and omitted from the artifact). Hash differs → elkjs re-lays-out
(with the saved positions as hints) and the viewer shows a "topology changed"
notice. Positions are never silently mixed.

## Notes / limits

- Full output is ~1.7 MB (elkjs ships no minified build); pinned-layout output
  is tens of KB. Fine for the intended pipeline-diagram scale (low hundreds of
  nodes).
- Child nodes are clamped inside their parent; parents don't auto-grow while
  dragging, but can be resized manually via the corner handle.
- `data-node-id` attributes are used instead of `id`, because node names may
  contain dots that break `querySelector('#…')`.

## Tests

```bash
uv run --extra dev pytest
```
