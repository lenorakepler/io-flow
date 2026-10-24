# Layout options

Everything under the YAML `diagram:` block that shapes how nodes are placed and
sized. The block is passed to the viewer verbatim (the parser does not validate
it), so an unknown key is silently ignored — check spelling against this file.

```yaml
diagram:
  engine: elk # elk (default) | dagre
  direction: DOWN # RIGHT (default) | DOWN | LEFT | UP
  spacing: 32 # node-to-node gap
  layerSpacing: 70 # gap between layers
```

Positions are computed once in the browser at load (unless a saved layout is
restored — see [Saved layouts](#saved-layouts)). Edges are **not** routed by the
layout engine; io-flow always draws its own bezier edges between node faces, so
the engine only ever decides node positions and sizes.

---

## Choosing an engine

`engine:` selects the layout backend. Only the one in use is shipped in the
artifact.

|                    | `elk` (default)                                            | `dagre`                                                               |
| ------------------ | ---------------------------------------------------------- | --------------------------------------------------------------------- |
| Bundle             | ~1.6 MB                                                    | ~284 KB                                                               |
| Algorithms         | layered + stress, force, mrtree, radial, rectpacking, …    | layered only                                                          |
| Best for           | anything; the only backend with organic (non-grid) layouts | plain DAGs — often ranks a flow more tightly, much smaller artifact   |
| Compounds (groups) | full nesting via `INCLUDE_CHILDREN`                        | supported; header room reserved by hand (deep nesting is approximate) |
| Honors             | everything below                                           | `direction`, `spacing`, `layerSpacing`, `dagre:`                      |

Switching engines never changes the model — only placement. See
[`ELK_LAYOUT_NOTES.md`](ELK_LAYOUT_NOTES.md) for ELK internals.

---

## Hierarchy, groups, and containment

A group (any node with `$`-children — a `class`, a `stage`, any compound) is a
**nested subgraph**, and how the engine treats nesting is the single most
important thing to understand about io-flow layout, because it is what makes a
grouped diagram lay out well or badly.

### ELK does see edges that cross a group boundary

io-flow runs ELK with `elk.hierarchyHandling: INCLUDE_CHILDREN`. This is the
**load-bearing option**. With it, an edge declared between a top-level node and a
node nested three levels deep inside a group is a first-class edge: ELK routes it
across the hierarchy and it _influences placement_ — the nested node's external
connections pull on where things land.

Turn `INCLUDE_CHILDREN` **off** (ELK's default is `SEPARATE_CHILDREN`) and the
picture is very different: each compound is laid out in complete isolation, and
any edge crossing its boundary is dropped or stapled to the compound's outer
border. _That_ is the "the engine can't take inner/outer connections into
account" failure mode — and it is precisely the mode io-flow does **not** run.
So the common worry is backwards: ELK accounts for cross-boundary edges; that is
one of its strengths (ELK is the only mainstream JS engine with hierarchy and
ports as first-class features, and the only one that natively emits
parent-relative coordinates).

### What actually limits a grouped layout: containment

The real constraint is geometric, not a blindness to edges:

> **A child must stay inside its parent's box.**

ELK _sees_ that a grouped child has a strong edge to some node outside the group,
but it **cannot pull that child out** of the group to sit next to that neighbor —
the child is confined to the parent's rectangle, and the group is placed roughly
as a unit. So a node that is wired to many things across the diagram lays out
_worse_ when it is trapped inside a group than when it floats free, because
grouping trades away placement freedom for a boundary.

This is why the grouping discipline this repo's own workflow follows works:

- **Group a stage only when its wiring is mostly internal.** A linear chain whose
  edges stay within the stage loses nothing to containment.
- **Leave cross-cutting collectors flat** (no group) so their members place
  freely.
- **Hoist hub artifacts to the top level.** A file consumed by five stages, if
  declared inside one of them, drags four cross-boundary edges out of a box;
  declared at the top level it sits at the boundary near all its consumers.
  Rule of thumb: an artifact stays in a group only if its producer _and every_
  consumer live in that same group.

None of these are ELK working around a bug — they are choosing _not_ to impose a
containment constraint where it would cost more than the visual grouping is
worth.

### The other cost of `INCLUDE_CHILDREN`: no per-group config

The same flattening that lets edges cross the hierarchy also means ELK **ignores
per-compound `elk.algorithm` / `elk.direction`** — you cannot ask one group to
lay out `DOWN` while the rest goes `RIGHT`, or pack one group with `rectpacking`
inside a `layered` diagram. The root options apply everywhere. io-flow's
sanctioned bypass for per-subgraph layout is `classLayout:` (stack a `class`
compound's interior outside ELK and present it to ELK as one fixed-size box); see
[Node sizing and special modes](#node-sizing-and-special-modes).

### The coordinate contract

ELK returns child coordinates **relative to the parent's top-left**, and io-flow
depends on this end to end: the DOM child-mount box is `position:absolute;
inset:0` so it shares the parent's origin, and `edges.js` reconstructs an
absolute point by summing a node's position up its parent chain. The dagre
backend converts dagre's absolute-centre coordinates into this same
parent-relative top-left form (and reserves the header strip by hand, since
dagre has no per-cluster header padding). Any future backend must produce the
same contract. `ELK_LAYOUT_NOTES.md` covers the ~header-height drift that results
from getting this wrong.

---

## Shared options (both engines)

| Key             | Default | Effect                                                                                                                                                                                                         |
| --------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `direction:`    | `RIGHT` | Flow direction: `RIGHT` \| `DOWN` \| `LEFT` \| `UP`. ELK → `elk.direction`; dagre → `rankdir` (TB/BT/LR/RL). **Ignored by non-layered ELK algorithms** (`stress`, `force`), which have no notion of direction. |
| `spacing:`      | `40`    | Minimum gap between sibling nodes. ELK → `elk.spacing.nodeNode`; dagre → `nodesep`.                                                                                                                            |
| `layerSpacing:` | `70`    | Gap between layers/ranks. ELK → `elk.layered.spacing.nodeNodeBetweenLayers`; dagre → `ranksep`.                                                                                                                |

---

## ELK-only

### `algorithm:`

Any elkjs algorithm id (default `layered`). The root algorithm is propagated
into every compound, so a diagram packs the same way inside groups as outside.

Common choices:

| Algorithm     | Shape                                                                                                                          |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `layered`     | Ranked, directional flow (the default). Grid-aligned columns.                                                                  |
| `stress`      | Organic; places nodes to minimize edge lengths. **No ranks, no grid, ignores declaration order.** Pair with `deoverlap: true`. |
| `force`       | Organic, force-directed; looser/rounder than `stress`. Pair with `deoverlap: true`.                                            |
| `mrtree`      | Tree layout (single-parent hierarchies).                                                                                       |
| `radial`      | Concentric rings around a root.                                                                                                |
| `rectpacking` | Packs disconnected nodes into a compact rectangle.                                                                             |

### `elk:`

Raw ELK options, **highest precedence** (merged last, over everything the keys
above set). Use the fully-qualified ELK option names. Examples:

```yaml
diagram:
  algorithm: layered
  elk:
    elk.layered.nodePlacement.strategy: NETWORK_SIMPLEX # BRANDES_KOEPF | NETWORK_SIMPLEX | SIMPLE | LINEAR_SEGMENTS
    elk.layered.considerModelOrder.strategy: NODES_AND_EDGES # bias order toward YAML order
    elk.layered.crossingMinimization.strategy: INTERACTIVE # INTERACTIVE | NONE | LAYER_SWEEP | MEDIAAN_LAYER_SWEEP
    elk.layered.thoroughness: "30"
    elk.aspectRatio: "1.6"
```

> To make placement ignore the order nodes appear in the file, **do not** set
> `considerModelOrder` (it does the opposite).

### `tier:` (per node, not under `diagram:`)

An integer on a node's data. Every node sharing a tier is forced into the same
layer — an invisible column grouping (e.g. all sankey sources in one column).
Any node declaring a numeric `tier:` activates ELK partitioning for the whole
diagram. Layered algorithm only; dagre ignores it.

```yaml
nodes:
  $source_a: { tier: 0 }
  $source_b: { tier: 0 }
  $sink: { tier: 2 }
```

---

## dagre-only

### `dagre:`

Raw dagre graph options, **highest precedence** (merged over the mapped
`spacing`/`layerSpacing`/`direction`). Mirrors the `elk:` block.

```yaml
diagram:
  engine: dagre
  dagre:
    ranker: network-simplex # network-simplex (default) | tight-tree | longest-path
    align: DL # UL | UR | DL | DR — bias node alignment
    edgesep: 12 # min gap between edges in a rank
    acyclicer: greedy # break cycles greedily (default: DFS)
```

`ranker: longest-path` spreads ranks more loosely (less compact than the
default); `align:` nudges the column alignment.

---

## Getting an organic (non-grid) layout

Layered engines (`elk` layered **and** `dagre`) assign ranks and align nodes
into columns by design — that is the grid look, and dagre has no loose mode. For
placement driven purely by connectivity, use an ELK force/stress algorithm:

```yaml
diagram:
  algorithm: stress # or force
  spacing: 32
  deoverlap: true
```

This drops the top-to-bottom flow (stress/force have no direction), so it reads
as a relationship map rather than a pipeline. Flip `algorithm: stress` ↔
`engine: dagre` to A/B.

### `deoverlap:`

`deoverlap: true` runs a post-layout pass that pushes any overlapping sibling
boxes apart (by `spacing`, or 16px if unset) and clamps children inside their
parent. Force/stress don't keep sized compound boxes from overlapping, so this
is what makes them usable with groups. Harmless on layered layouts (nothing
overlaps to separate).

---

## Would a different engine place groups better?

Short answer: **not for free.** The "a grouped node can't move next to its
external neighbor" limitation is inherent to drawing groups as _bounding boxes_ —
any engine that keeps a group as a contained rectangle imposes the same
containment. ELK is, if anything, at the strong end for compound graphs (it is
the only mainstream JS engine with first-class hierarchy/ports and
parent-relative output). dagre and Graphviz `cluster` subgraphs have the **same**
containment behavior — a clustered node stays in its cluster.

Two directions genuinely do better at the specific problem, at a cost:

**1. Constraint / compound-force engines** optimise _every_ position jointly, so a
group is pulled toward its heavy external neighbors as part of one global solve,
instead of being placed as a rigid unit after its interior is fixed:

| Engine                               | What it adds                                                                                                                                                                                                                                                                                        | Cost                                                                                                               |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| **WebCola** (cola.js)                | Constraint-based force layout that combines **directional flow** (`flowLayout`, keeps edges pointing one way — a DAG still reads top-to-bottom), **group containment**, and **non-overlap** in a single solver. The closest thing to "keep the flow _and_ let groups gravitate to their neighbors." | Force-based: slower, non-deterministic between runs, less crisp than layered. New backend + coordinate conversion. |
| **fCoSE / CoSE-Bilkent** (Cytoscape) | Fast compound spring embedder; purpose-built to place compounds by their inter-group connectivity. Best-in-class _organic_ compound placement.                                                                                                                                                      | Organic only — no ranked flow direction. New backend.                                                              |

**2. Drop the box.** The only way to fully escape containment is to stop drawing
groups as rectangles and instead draw them as a **hull / tint around wherever the
members land** (the Cytoscape compound-plus-hull style). Then a member is free to
sit anywhere and the group boundary follows it. This is a **model change**, not an
engine swap: io-flow groups are header boxes that own a coordinate origin (drag
clamps to them, collapse shrinks them, children mount inside), so a hull-group
would touch drag, collapse, resize, save, and the coordinate contract — far more
than layout.

Practical guidance for io-flow today: the cheapest, most reliable lever is the
grouping discipline above (group only cohesive stages; hoist hubs; flatten
cross-cutting collectors), optionally with `algorithm: stress`/`force` +
`deoverlap` when you want a pure relationship map with no grid. A WebCola backend
is the natural next step _if_ jointly optimised group placement with retained
flow becomes worth a new dependency.

---

## Engine edge routing, row wrapping and the first view

Three keys added 2026-10-24, after the SurveillanceBench status charts came out
as one thin strip of unreadable boxes with curves crossing the boxes.

| Key              | Default  | Effect |
| ---------------- | -------- | ------ |
| `edgeRouting:`   | `bezier` | `orthogonal`, `polyline` or `splines`: the engine routes the edges as well as placing the nodes, and io-flow draws that route (ELK → `elk.edgeRouting`; dagre always routes polylines). Edge labels are handed to the engine with an estimated size and drawn where it places them (`elk.edgeLabels.inline`). The route is kept only while both endpoints sit where the engine left them: dragging a node sends its edges back to the face-to-face curve, a collapse re-runs the layout, and a restored saved layout has no routes, so every edge there is a curve. `deoverlap: true` moves nodes after routing and so disables it. |
| `wrap:`          | off      | ELK layered only. `true` (aspect ratio 1.6), a number (that ratio) or `{aspectRatio, strategy}` (`MULTI_EDGE` default, or `SINGLE_EDGE`): folds a long flow into rows so the whole chart approaches the ratio (`elk.layered.wrapping.strategy`, `elk.aspectRatio`). Pair it with `edgeRouting:`, since the curves cannot draw a wrap-back edge sensibly. |
| `fitMinScale:`   | `0.5`    | The first view never zooms out past this scale. When the chart is larger than the window at that scale it opens on its top-left corner, clear of the search box and type chips, and the reader pans. `0` restores fit-everything. |

`elk:` on a node (not under `diagram:`) passes raw ELK options to that node
alone: `elk: {elk.layered.layering.layerConstraint: FIRST}` pins it to the
first layer, `LAST` to the last. A `tier:` only orders partitions; inline edge
labels take a layer of their own, so two nodes of one tier can still land in
different layers when only one of them has a labelled edge. The layer
constraint is the way to hold a column together.

A decision tree of twenty questions written left to right reads well with
`direction: RIGHT`, `wrap: 1.8`, `edgeRouting: orthogonal`; a three-column
source → treatment → sink chart reads well with `edgeRouting: orthogonal` and
`elk: {elk.layered.layering.strategy: LONGEST_PATH}` so every source sits in
the first column.

---

## Laying out with D2's engines, TALA included

`io-flow layout CHART.yaml --engine tala` (or `elk`, `dagre`) exports the chart to D2, runs the `d2` executable, reads every box and edge path back from its SVG, and saves them as the chart's `layout:` block: `[x, y, w, h]` for every node, and under `_routes` each edge's SVG path with its label position. The viewer then restores the positions and sizes and draws the saved routes instead of its own curves, so the chart looks as D2 laid it out, with io-flow's click-to-dim, sidebar, drag and Save on top. Drag a node and its edges fall back to curves; Save keeps the routes that are still valid. D2 names each shape and edge in its SVG by the base64 of its id, which is what makes the read-back possible.

TALA is D2's own engine, built for diagrams with containers and many edges; on the SurveillanceBench journey chart it produced a canvas a third the width of ELK's and nearly square, with the edges routed around the boxes and the labels placed. D2 v0.9 bundles it; `d2 layout` lists the engines found.

`io-flow d2 CHART.yaml` writes the D2 text alone, to render with `d2 --layout tala CHART.d2 CHART.svg` or to paste into D2's playground. What carries over: nodes, labels, groups as containers, relation edges with labels, the type styles approximated, the body text under each title, the description as a tooltip. What does not: regions, sankey, stacked lists, saved positions, anchors.

---

## Which edges affect the layout

By default every edge — even one hidden by a group toggle — shapes the layout,
which keeps structure stable when few edges are visible. These keys change that.

| Key                                 | Effect                                                                                                                                                                     |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `layoutSkipsHiddenEdges: true`      | Drop default-hidden edges (`hiddenEdges` / `hiddenEdgeGroups`) from the layout, so edges you can't see don't spread nodes apart.                                           |
| `hiddenEdges: [type, …]`            | Edge types hidden by default (used with the flag above).                                                                                                                   |
| `hiddenEdgeGroups: [group, …]`      | Edge groups hidden by default.                                                                                                                                             |
| `layoutExcludeEdgeTypes: [type, …]` | Keep these edge types out of the layout entirely — they still render when visible. Use to stop noisy I/O edges from spreading nodes while the backbone shapes the diagram. |
| `sidebarOnlyEdgeTypes: [type, …]`   | Recorded in the model and listed in a node's sidebar, but **never laid out and never drawn**.                                                                              |

---

## Node sizing and special modes

Node **size** is CSS-owned: each node is measured from the live DOM (after fonts
settle) and that size flows into the layout. Padding/font/`max-width` changes in
a stylesheet therefore change layout spacing. The keys below adjust sizing or
switch to a different geometry entirely.

### `fillWidth: [type, …]`

Stretch nodes of these types to their parent's inner width (a post-pass, since
the parent width is only final once its children are placed). Useful for
banner/section rows inside a group.

### `sankey:`

Flow-diagram mode. Give every node a numeric `population:` and every edge a
`weight:` in the same unit; node height becomes `population × unit` and band
widths `weight × unit`.

```yaml
diagram:
  sankey: { unit: 12 } # px per item; bare `sankey:` auto-scales to ~160px max
```

### `classLayout:`

Render `class` compounds as UML-style stacked member lists (uniform width,
declaration order) outside ELK, while ELK arranges everything else.

```yaml
diagram:
  classLayout: # bare = {types: [class]}
  # classLayout: {types: [class, group]}   # widen to more types
  # classLayout: false                      # opt out
```

### `edgeWidth:` (stroke, not position)

Weighted edges (`weight:` on an edge) scale their stroke width. Not a placement
option, but it lives under `diagram:`.

```yaml
diagram:
  edgeWidth: { min: 1.5, max: 12, scale: sqrt } # scale: sqrt | linear
```

---

## Saved layouts

Positions can be pinned so the layout engine never runs:

- **Save** (edit mode) writes node positions into a machine-owned `layout:`
  block in the YAML. Don't hand-edit it.
- On build, a **topology hash** (sorted `(id, parent)` pairs + edge pairs)
  decides: if it matches the saved layout, positions are **restored exactly**
  and the layout engine is skipped — and omitted from the artifact, dropping it
  to tens of KB. If the topology changed, the engine re-lays-out and the viewer
  shows a "topology changed" notice. Positions are never silently mixed.
- Anchors (edge endpoint faces) are editable in the browser and saved under the
  same block; see the README's _Edge anchors_ section.

So the engine/algorithm options above only apply while a diagram has **no**
matching saved layout. Delete the `layout:` block to force a fresh run.

---

## Quick reference

| Key                                | Scope                                     | Engine         |
| ---------------------------------- | ----------------------------------------- | -------------- |
| `engine`                           | elk \| dagre                              | —              |
| `direction`                        | RIGHT \| DOWN \| LEFT \| UP               | both (layered) |
| `spacing`                          | node-node gap                             | both           |
| `layerSpacing`                     | layer gap                                 | both           |
| `algorithm`                        | layered \| stress \| force \| mrtree \| … | elk            |
| `elk`                              | raw ELK options map                       | elk            |
| `tier` (per node)                  | integer column                            | elk (layered)  |
| `dagre`                            | raw dagre options map                     | dagre          |
| `deoverlap`                        | separate overlapping boxes post-layout    | both           |
| `layoutSkipsHiddenEdges`           | drop hidden edges from layout             | both           |
| `hiddenEdges` / `hiddenEdgeGroups` | which edges are hidden                    | both           |
| `layoutExcludeEdgeTypes`           | keep edge types out of layout             | both           |
| `sidebarOnlyEdgeTypes`             | never laid out or drawn                   | both           |
| `fillWidth`                        | stretch types to parent width             | both           |
| `sankey`                           | population×unit geometry                  | both           |
| `classLayout`                      | stacked UML members                       | elk            |
| `edgeWidth`                        | weighted stroke width (not position)      | both           |
