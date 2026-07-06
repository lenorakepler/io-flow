# io-flow

Turn a YAML description of a pipeline into an **interactive, portable, single
`.html` file** — no server needed to view it, zero network requests, works
offline from `file://`.

Nodes are plain HTML `<div>`s styled with plain CSS; layout is computed by
[elkjs](https://github.com/kieler/elkjs); edges are SVG. Click a node to dim
everything but its direct neighbors, drag nodes to rearrange, and (when editing)
save the arranged layout straight back into the source YAML with every comment
preserved.

## Install

```bash
uv sync            # dev: also `uv sync --extra dev` for pytest
```

## Use

```bash
# Compile once -> a single portable diagram.html
uv run io-flow build example_input.yaml -o diagram.html

# Primary editing loop: build, serve on localhost, open browser.
# Drag nodes -> click "Save layout" -> Ctrl-C. The YAML gains a compact
# `layout:` block; the leftover diagram.html is the portable viewer.
uv run io-flow edit example_input.yaml

# No-server fallback: merge a {id: [x, y]} JSON into the YAML.
uv run io-flow apply-layout example_input.yaml layout.json
```

Opened over `http://localhost` (via `edit`) the **Save** button appears and
writes back to the YAML. Opened from `file://` it is hidden and everything else
still works.

## Input format

See [`example_input.yaml`](example_input.yaml). In short, under `nodes:`:

- **`input:`** — files / options / parameters (styled by their `type:`).
- **`classes:`** — a compound node wrapping an `attributes:` node and each
  method. Class members get qualified ids (`Config.from_yaml`).
- **`functions:`** — processing nodes.

Edges are derived **only** from reference positions — class `attributes:` values
and method/function `args:` values — matched exactly against node ids. Free text
in `value:`/`cli:`/`description:` never creates an edge. Duplicate ids are a hard
error; an unresolved reference prints a loud warning listing close candidates.

## Customizing appearance (the whole point)

Two files are the **entire modification surface** — change them without ever
touching engine code:

- **`src/io_flow/assets/viewer.css`** — all node appearance. Recolor a type,
  restyle the sidebar, tweak the dim opacity.
- **`src/io_flow/assets/templates.js`** — the `type → HTML` map. Change what a
  node renders, or add a whole new node type (add a function here + a
  `.node--<type>` rule in the CSS).

Everything else lives behind a hard module boundary in
`src/io_flow/assets/engine/` (layout, edges, dim, drag, pan, save) and rarely
needs editing. Interaction scope is intentionally frozen for v1: pan/zoom, drag,
click-to-dim, and the sidebar — nothing more.

## Architecture

```
src/io_flow/
  cli.py            argparse: build / edit / apply-layout
  parser.py         two-pass YAML -> recursive graph model; edge derivation
  layout_store.py   layout: block read/merge (ruamel round-trip) + topology hash
  emit.py           inline JSON + CSS + JS into one self-contained HTML
  server.py         stdlib http.server + POST /save
  assets/
    viewer.html     skeleton with style/graph/script slots
    viewer.css      <- user-editable: all node styling
    templates.js    <- user-editable: type -> HTML template map
    engine/         layout.js edges.js dim.js drag.js pan.js save.js viewer.js
    vendor/         elk.bundled.js, panzoom.min.js
tests/              test_parser.py, test_layout_store.py
```

Layout persistence is gated by a **topology hash** (sorted node ids + edge
pairs). Hash matches the saved layout → positions are restored exactly and elkjs
is skipped. Hash differs → elkjs re-lays-out (with the saved positions as hints)
and the viewer shows a "topology changed" notice. Positions are never silently
mixed.

## Notes / limits

- Output is ~1.7 MB (elkjs ships no minified build). Fine for the intended
  pipeline-diagram scale (low hundreds of nodes).
- Child nodes are clamped inside their parent; parents don't auto-resize (v1).
- `data-node-id` attributes are used instead of `id`, because qualified ids
  contain dots that break `querySelector('#…')`.

## Tests

```bash
uv run pytest
```
