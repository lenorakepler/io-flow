# Later Features / Roadmap

Working notes on in-progress and deferred capabilities. Captures where things
stand, why, and what would come next.

## Done

### `filepanel` skin — embedded file viewer

A node declares `src: path/to/file`; the parser reads it (relative to the YAML,
256KB cap) into `graph.fileContents` — kept out of `node.data` so it doesn't
bloat the default sidebar. The bundled `filepanel` skin (opt-in via
`style: skin: [..., filepanel]`) is an always-open right-docked panel that shows
that file's text on click. `dim.js` fires `ioflow:select` / `ioflow:clear` DOM
events as the extension point (any skin can listen).

- `parser.py` (`src:` embed, `parse(base_dir=...)`), `dim.js` (events),
  `assets/skins/filepanel.{js,css}`. Tests: `test_src_*`.
- Markdown (`lang == "markdown"`) is rendered to HTML by a small built-in
  renderer (headings, lists, emphasis, links, inline + fenced code, blockquote,
  hr); all source text is escaped first. Code/JSON/YAML show as plain monospace,
  with `lang` exposed as `language-<lang>` on the `<code>`. **Next:** a small
  inlined syntax highlighter for code (bundling one is heavy for a self-contained
  file).
- Note: embedding puts file text in the built HTML — do not `src:` secrets, and
  gitignore the built HTML if it embeds anything not meant to be committed.

### `types:` from an external file

`types:` accepts, besides the inline mapping, a **file path** to a YAML file of
`{type: declaration}`, or a **list** mixing paths and inline mappings (merged in
order, later wins). Paths resolve relative to the diagram YAML. Resolved in
`parse_file` (`_load_types_value`) before `parse()`, so the rest of the pipeline
is unchanged. This is separate from — and cleaner than — the pre-existing
`style: templates:` dir convention (which loads a fixed `templates/types.yaml`).

### Legend edge toggles + `diagram: hiddenEdges:`

Legend edge rows are clickable: each toggles every edge of that type on/off
(`IOF.edges.setEdgeTypeHidden`, applied through `applyGeometry` so it survives
re-routes). `diagram: hiddenEdges: [type, ...]` starts those types hidden.

Hidden edges still exist in the graph, so `dim.js` (adjacency built from
`graph.edges`, not the DOM) still lights their endpoints on click — an invisible
relation that exists only to power click-to-focus. Used for stage membership:
`drives` edges are invisible, but clicking a stage lights every skill that drives
it and dims the rest.

- `edges.js` (`setEdgeTypeHidden`, hidden check in `applyGeometry`),
  `ui.js` (clickable legend rows + auto edge-type rows), `viewer.js`
  (`state.hiddenEdgeTypes` from `diagram.hiddenEdges`), `viewer.css` (row styling).

### `descriptors:` — data field → synthetic child node

A top-level `descriptors:` block maps a data field name to a node type:

```yaml
descriptors:
  description: desc      # any node with `description:` gets a `desc` child
```

Any node carrying that field gets a **synthetic first child** of the given
type, with the field's value passed along as `text`. The child is emitted
before the node's real children (so it lays out first), needs no id of its own,
and is never an edge endpoint — same "position is identity" model as `steps:`.
The generated id is `<parent>.<field>`; a collision raises like any duplicate.

- Parser: `parse()` in `src/io_flow/parser.py` (reads `descriptors`, synthesizes
  in `add_node`).
- Tests: `test_descriptors_*` in `tests/test_parser.py`.

### `fillWidth:` — stretch nodes to the parent's width

A `diagram:` option listing node types that should span their parent:

```yaml
diagram:
  fillWidth: [desc]
```

After layout, `applyPositions` (`src/io_flow/assets/engine/viewer.js`) stretches
those nodes to the parent's edges (`x = 0`, `w = parent.w`). It runs as a
post-pass because a child can't both drive the parent's width and match it at
once — the parent width is only final once every child is placed at its measured
size. Applies on both fresh layout and restore (both route through
`applyPositions`).

## Known limitation (why `description` is not rendered on-canvas yet)

Turning a data field into a synthetic child **promotes a leaf into a compound**.
A `file` (or any childless node) that gains a `desc` child now renders through
`group.html` with a header + children mount — visually wrong for a leaf.

So for now, `description` is left as a plain field and shown in the **sidebar**
(the default field dump in `_sidebar.html.j2`). The `descriptors:` and
`fillWidth:` features remain in the codebase, dormant, for cases where a field
genuinely should be its own box on a node that is already a compound.

## What comes next

The real unlock is decoupling "content above the children" from "being a child
node." Two candidate directions:

### A. Per-node measured header height (replaces the global `--header-h`)

Today the compound header is a fixed-height absolute overlay; `--header-h` is a
single global constant read once from `:root`. It backs four things: reserving
top space so ELK-placed children (`inset:0`) don't sit under the title bar;
letting the title span full width at any node size; drag/clamp keeping children
below the header; and collapse folding the body to the header height.

Making that height **per-node and measured** would let a header hold
variable-height content (e.g. a description) without a fixed overlay and without
turning leaves into compounds. Required changes:

- `layout.js`: measure each compound's header height and feed it as that
  compound's top padding (instead of the constant in `compoundOptions`).
- `collapse.js` / `drag.js` / `a11y.js`: read the per-node header height rather
  than `IOF.headerH()`.
- Restore path (`restoreFromPositions`) as well.

Collapse keeps working — it just folds to each node's own header height.

### B. A "banner" / body-slot concept

Alternatively, give a node a rendered block that sits above its children and
**reserves its own measured space**, but is explicitly *not* a child node — so
it never counts toward child layout and never makes a leaf a compound. This is a
narrower change than A and might be the cleaner path for descriptions
specifically.

### Smaller follow-ups observed along the way

- Ordering: synthetic (edge-less) children only stay first if ELK is told to
  honor model order — needs `elk.layered.considerModelOrder.strategy` plus
  `elk.separateConnectedComponents: false`, since each edge-less sibling is its
  own component. Worth folding into the feature rather than leaving to the
  diagram author.
- `.node { max-width: 260px }` clamps any inline width; `fillWidth` targets must
  override it (`max-width: none`). If `fillWidth` graduates to a first-class
  feature, it should set that itself.
