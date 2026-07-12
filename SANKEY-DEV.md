# DEV.md — sankey work: what was built, why, and the decisions behind it

Written 2026-07-12 as a handoff so an **alternative implementation can be
tried against the same requirements**. Everything here lives on the `sankey`
branch; `main` ends at `aae5a7e` and knows nothing about weights.

## State of the branch

- **Committed** (`fe3022a` "Add weighted edges with sankey-style anchor
  stacking"): weighted edges + anchor stacking.
- **Uncommitted working tree**: sankey mode (population-proportional node
  heights), `tier:` column pinning, `examples/csv_to_sankey.py`, the job-search
  CSV + six generated YAML/CSS files, README sections.
  Files touched (uncommitted): `src/io_flow/assets/engine/edges.js`,
  `engine/viewer.js`, `engine/layout.js`, `README.md`, plus the untracked
  example files.
- To try an alternative from the committed baseline:
  `git stash -u` (or commit this as a checkpoint) and branch from `fe3022a`.
  To start from scratch, branch from `main` (`aae5a7e`).

## The requirement, as it evolved

1. Visualize flow volume: edge width ∝ item count.
2. Stratify edges by a categorical column (Source/Type/Fit): one colored
   band per stratum value, so "does LinkedIn or Referral yield more offers?"
   is visible.
3. Bands must **stack** at nodes (not pile on the side midpoint).
4. **Node height is data, not layout convenience**: every sankey node
   declares an "input population" in the YAML and its height is exactly
   proportional (not a min-height). An explicit "this is a sankey" mode
   is acceptable — rendering may differ in that mode.
5. Nodes conceptually grouped (e.g. all sources) must share a column.
6. Parallel outcomes are a real shape: "HR Interview" and "Communicated
   Rejection" are both *the second stage an application can enter* and must
   share a column; items flowing into neither are pending/ghosted and
   simply don't flow (visible as uncovered bar height).

## What was implemented, layer by layer

### 1. Weighted edges (committed)

- **Grammar**: in a relation block, the unmarked side of a `$`-keyed entry
  annotates the edge **by YAML type** — string = label, number = weight
  (`calls: {$validate: 118000}`). Chosen because numbers there were
  previously *silently discarded*, so the extension is ambiguity-free and
  breaks no existing file. Explicit edges take `weight:` beside
  `type`/`label` (non-numeric → hard error). Bools stay inert. Parser edge
  dedupe key includes weight.
- **Rendering** (`edges.js weightScale`): width = `min + (max−min)·f(w)/f(wmax)`,
  `f = sqrt` by default (a 100× volume isn't a 100× line), configured via
  `diagram: edgeWidth: {min: 1.5, max: 12, scale: sqrt|linear}`. Weighted
  edges carry class `edge--weighted` (default skin: `stroke-opacity: .55`,
  `stroke-dasharray: none` — per-type dashes render as bricks at flow
  widths) and use a **fixed-size arrowhead** `#arrow-flow`
  (`markerUnits="userSpaceOnUse"` in `viewer.html`) because the default
  marker scales with stroke width.
- **a11y**: `a11y.js endpointText` speaks weights ("calls, weight 42").

### 2. Anchor stacking (committed)

Problem: all edges anchored at the side midpoint, so parallel flows
overlapped. Rework in `edges.js`:

- `computeGeometry(state)` produces one entry per edge (aligned with
  `graph.edges` order — `state.edgeEls` relies on that alignment). Endpoint
  boxes resolve through collapse (`visibleIdOf`), routing axis = dominant
  axis of box centers (unchanged rule).
- Endpoint usages are grouped by **(visible node, side)** — side keyed as
  axis+sign so "exits west" and "enters west" share one stack. Within a
  group, entries sort by the far endpoint's cross-axis center (stable sort;
  ties keep `graph.edges` insertion order — the generator relies on this to
  keep strata in consistent order so parallel bands never cross). Bands are
  sized by stroke width (`BASE_BAND = 2` for unweighted), separated by
  `GAP = 3`, inset `PAD = 8`, centered as a stack, squeezed to fit short
  sides. **A single-edge side anchors at its center — identical to the old
  behavior**, so unweighted diagrams are visually unchanged.
- Edges whose two endpoints resolve to the same visible node (interior of a
  collapsed compound) are `hidden`: not drawn, no stack slot. At 1.6px they
  used to hide behind the node; at 14px they smeared across the header.
- Trade-off: `updateFor` recomputes **all** edges per drag move (a move can
  reorder neighbors' stacks). Fine at the documented scale (low hundreds).

### 3. Sankey mode (uncommitted)

The decisive requirement reframing: **population is data**. Rejected
approaches, in order:

1. *Engine auto-computes node size from edge weights* (`flowExtent`) —
   started, reverted: sizing became implicit, direction heuristic needed.
2. *`minHeight:` in YAML + tiny viewer hook* — planned and approved, then
   rejected at review: a minimum is the wrong semantics; height must be the
   data, exactly.
3. **Chosen**: explicit mode `diagram: sankey: {unit: <px/item>}` +
   `population: <n>` per node (ordinary free data — zero parser changes).

Mechanics (all gated on the mode; strict no-ops otherwise):

- `edges.js sankeyUnit(graph)`: null unless `diagram.sankey` present; unit
  explicit or auto `160 / max(populations, weights)`. Exported on
  `IOF.edges` for viewer.js.
- `weightScale`: in-mode, width = `weight × unit` — **purely linear, zero
  offset**, so band widths are additive (`edgeWidth:` ignored).
- Stacking: in-mode `gap = 0, pad = 0` — bands tile the node side
  edge-to-edge; with conserving data, incoming bands sum to exactly the
  node height (the sankey conservation reading). Coverage gaps are honest
  (LinkedIn population 6, outgoing 5 → visible sliver = the no-response
  application).
- `viewer.js boot()`: in-mode, `el.style.height = population * unit + "px"`
  set **inline before measurement** — both sizing paths (ELK's
  `getBoundingClientRect` in `layout.js`, and `restoreFromPositions`)
  inherit it with no further edits. This exploits the measure-then-freeze
  contract instead of fighting it. Missing population → console warning,
  measured height kept (loud > silent).
- In-mode weighted edges drop arrowheads (clutter at band widths;
  direction is unambiguous).
- **Routing axis is fixed to the layout direction in-mode** (the general
  dominant-axis rule stays for normal diagrams). Discovered via the
  parallel-outcomes column: two layer-mates with a large vertical offset
  flip the dominant axis, so a ribbon exits the bar's *top* face and wraps
  around it. Sankey ribbons always leave/enter the direction-facing faces.
- **In-mode stacks anchor at the top of the side** (left, for vertical
  layouts) rather than centered, so unconsumed population -- the
  pending/ghosted items -- pools visibly at the bottom of the bar. Normal
  diagrams keep centered stacks (a lone edge should meet a box at its
  vertical center).

### 4. `tier:` column pinning (uncommitted)

Requirement 5 ("invisible grouping tier"). Implemented as **ELK
partitioning**, not invisible compound nodes (compounds drag in header
height, padding, drag clamping, hierarchy semantics). `tier: <int>` is
ordinary node data; `layout.js` sets
`elk.partitioning.partition` per node and activates
`elk.partitioning.activate` on the root when any node declares a tier.
Verified empirically against the vendored elkjs (a node whose edges pull it
rightward stays pinned in column 0). Only shapes the ELK draft; saved
layouts still win.

### 5. `examples/csv_to_sankey.py` (uncommitted; deliberately not in the package)

CSV of items × boolean funnel stages → sankey YAML + CSS skin.

- **Path semantics**: an item's path = source node + every TRUE stage in
  order; FALSE/blank stages are *skipped through*, so an unusual path
  renders as a stage-skipping band instead of silently vanishing. (This
  surfaced a real data-entry error in the sample CSV — funnel-strict
  semantics would have hidden 1 of 2 in-person interviews.)
- **Stratification needs no engine support at all**: one edge per
  (transition, stratum value), typed `<by>_<value>` for CSS coloring,
  weighted by count. Sorted emission keeps band order consistent across
  stages.
- Populations = items whose path visits the node.
- **Tiers are derived from the observed flow, not CSV column order**
  (`assign_tiers`): a stage's rendered column = 1 + the max column of its
  actual predecessors (sources = 0). Parallel outcomes fed by the same
  upstream ("HR Interview" / "Communicated Rejection") therefore share a
  column with no flags or configuration. One ordered pass suffices because
  paths visit stages in CSV column order, so predecessors are always
  tiered first.
- **The generator pins the whole layout** via `layout_store.merge_positions`
  into the `layout:` block (exact restore; `build` omits elkjs). Columns
  share a top line; within a column, nodes stack top-aligned ordered by
  outgoing flow (descending), so the outcome that flows onward sits above
  the terminal one. The `tier:` hints remain as the ELK fallback if the
  layout block is deleted; drag + Save re-arranges as usual. Constants
  (unit, bar width) are mirrored from the YAML/CSS the script itself
  writes.
- Generated skin = packaged `viewer.css` + per-stratum
  `#edges .edge--<tag> { stroke: ... }` (**the `#edges` prefix is required**
  — a bare class loses specificity to the base `#edges .edge` stroke rule)
  + bar look: `width: 22px`, solid background, label absolutely positioned
  below the bar (the node box *is* the bar).

## Contracts any alternative must respect

- **Measure-then-freeze**: node size comes from the rendered DOM (CSS or
  inline styles set before measurement); positions are frozen into inline px
  that `edges.js`, drag clamping, and Save all trust. CSS cannot move nodes.
- **Positions are parent-relative**; the topology hash covers `(id, parent)`
  pairs + edge pairs, *not* positions — appearance changes never invalidate
  saved layouts.
- **`state.edgeEls[i]` ↔ `graph.edges[i]`** index alignment in `edges.js`.
- **`elk.hierarchyHandling: INCLUDE_CHILDREN` is load-bearing** (cross-
  hierarchy edges). Verified: it ignores per-compound `elk.direction` /
  `elk.algorithm` (uniform per run); per-compound *spacing* works;
  `SEPARATE_CHILDREN` honors child direction but drops cross-hierarchy
  edges. This killed per-subgraph layout config.
- SVG markers default to `markerUnits=strokeWidth` — any wide-stroke design
  needs `userSpaceOnUse` or no marker.
- `--header-h` is the one CSS var the engine reads (`IOF.headerH()`).

## Rejected roads (with reasons), for the record

- **True ribbon renderer** (tapered filled paths à la d3-sankey): a second
  edge renderer — exactly the "two-renderer mess" `edges.js` exists to
  avoid; stroked beziers + stacked anchors got ~90% of the reading.
- **Per-subgraph `diagram:` config**: ELK constraint above.
- **Grid snapping in-browser**: solved instead by `io-flow align`
  (post-hoc, per-sibling-space clustering) on `main`.
- **Invisible group compounds for tiers**: ELK partitioning is strictly
  simpler.

## Verification recipes

```bash
uv run --extra dev pytest                       # 94 passing on this tree
uv run python examples/csv_to_sankey.py example_job-search_sankey.csv --by Type
uv run io-flow edit example_job-search_sankey_by_type.yaml \
    --css example_job-search_sankey_by_type.css
```

Things to eyeball: bars exactly population×unit tall; bands tile bars with
no gaps; strata colors per the printed legend; sources share a column;
drag a bar — ribbons stay tiled; collapse (non-sankey diagrams) hides
interior flows. Regressions: `examples/weighted_flow.yaml` (weighted,
non-sankey: gapped stacks, arrowheads, measured boxes) and
`example_input.yaml` (unweighted: visually identical to `main`).
