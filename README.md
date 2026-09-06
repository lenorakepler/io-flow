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

# Map a whole Python package into a diagram: one group per file, classes as
# stacked members, edges from resolved calls (cross-file calls tagged `xcall`),
# and each node carrying its source + args/returns/calls/modifies/attributes for
# the sidebar. --repo defaults to CWD, --package to the repo name, --title to
# "<repo> - <package>" (or just one when they match). The emitted YAML declares
# `style: {skin: codemap}` itself, so build renders the source + labeled
# metadata sidebar with no extra flag.
io-flow walk --package mypkg -o mypkg.yaml
io-flow build mypkg.yaml -o mypkg.html
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
- **`types:`** — node type declarations for this diagram: what a `type:`
  looks like when rendered (below).
- **`legend:`** — which types are worth explaining, drawn by the real
  templates (below).
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
- **`class:`** — extra CSS classes for this one node, added after everything
  its type contributed (type declarations have a `class:` of their own, below).
- **`steps:`** — ordered children whose position is their identity, and
  **`autoedges:`** — chain them in that order (below).
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

**Edge anchors.** By default each edge endpoint picks its box face
automatically (dominant axis between the two boxes: the source exits toward
the target, the target is entered from the opposite face). `anchor:` pins
an endpoint to a named face — `left` / `right` / `top` / `bottom` — at any
of three levels, most specific wins:

```yaml
relations:
  inherits: {direction: out, anchor: {from: top, to: bottom}}  # every inherits edge
nodes:
  $logger: {anchors: {in: left}}                # all edges entering this node
edges:
  - {from: $render, to: $draw, type: calls, anchor: {from: right, to: left}}
```

`from`/`to` name the rendered edge's source and target (so for an `in`
relation like `args`, `from` is the referenced node). Re-registering a
built-in under `relations:` works, so `calls` can carry a default anchor
too. Pinned and automatic endpoints share the same per-face stacking, and
the two ends may sit on unrelated faces (exit bottom, enter left) — the
route bends through each endpoint's face normal. Undeclared diagrams render
pixel-identically. The classic use is UML inheritance: derived classes
spread wide in the layer below their base would otherwise flip to sideways
routing; the relation-level anchor keeps every inheritance edge vertical
(see [`examples/anchors.yaml`](examples/anchors.yaml)).

Anchors are also editable in the browser: select a node and a small round
handle appears at each incident edge endpoint — click it to cycle that
endpoint through auto → right → bottom → left → top (auto = whatever the
YAML declares). Overrides layer over declared anchors exactly like saved
positions layer over ELK, and Save persists them in the machine-owned
`layout:` block (under `_anchors:`, keyed `src>tgt[:type]` — parallel
same-type edges between one pair share an override), so hand-authored
YAML is never rewritten. Without a save server the handles still work;
unsaved cycles are lost on reload, same as drags.

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

**Default types.** An untyped node falls back to what it structurally is:
`group` when it holds children, `node` when it doesn't. Compound-ness was
already a state — a node with children renders through `group.html` regardless
— and carrying the type means `.node--group` styling applies too. The
`defaults:` block overrides that, mapping a parent type to its children's
default (`_root` covers top-level nodes), so terse declarations stay correct:

```yaml
defaults:
  class: method            # children of any `type: class` node
  group: function
  _root: input             # top-level nodes
```

**Keys are the parent's *type*, not a node name.** `projects: dir` does not
mean "children of `$projects`" — it means "children of anything typed
`projects`", and a key matching no type in the document warns rather than
quietly doing nothing. A type that always holds its own kind says so in its
declaration instead, which inherits and travels with the type:

```yaml
types:
  dir: {extends: group, childtype: dir}   # a dir's untyped children are dirs
```

**Ordered children.** A pipeline's stages are a list, not eight nodes that each
need a name. `steps:` says so: position *is* identity, so the id is the parent's
plus the index and the index arrives as `number` in the node's data.

```yaml
nodes:
  $stages:
    type: steps
    steps:
      - Project Setup                    # bare string: the label
      - label: Paper Ingestion           # or a full node spec
        $ingest_cli: {type: file}        # children, edges, type: all still work
      - label: Eval Drafting
        calls: {$stages0: retry}         # `$stages<n>` addresses the nth step

  $runner: {calls: {$stages1: ""}}       # ...from anywhere, like any other id
```

`autoedges:` draws the chain the order already implies — each step to the next.
`true` types those edges `next` (so `.edge--next` styles them); a string names
the type instead (`autoedges: then`). Steps keep declaring edges of their own
either way. It's an error beside anything but a `steps:` list, since there's no
order to chain.

Steps get `type: step` (a badge carrying the number) unless the item says
otherwise or `defaults:` does — `defaults: {steps: stage}` types a whole list at
once. Numbering is 0-based so the id and the `number` agree; setting `number:`
on an item changes only what renders, never the id.

The trade is the obvious one: **reordering the list renumbers everything after
it**, so references and saved layout positions follow position, not content.
Name the ones you point at (`$name:` children) if that matters more than terseness.

**Legend.** Without a `legend:` block the viewer lists every type present as a
bare chip. Declaring one says which types are worth explaining and what to call
them — and each sample is *rendered by that type's own template*, so it carries
the same badge, meta line and CSS a real node does:

```yaml
legend:
  title: what things are            # optional
  nodes:
    - file                          # bare name: caption is the type
    - dir: a project directory      # type: caption
    - {type: option, label: a flag, cli: --verbose}   # full spec, meta and all
  edges:
    calls: who calls whom           # drawn as a real .edge--calls stroke
```

`nodes:`/`edges:` each take a list or a mapping, and a list entry may be any of
the three spellings. A type that appears only in the legend still ships its
`css:`, so the sample can't quietly render unstyled.

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

Two things are the **entire modification surface** — change them without ever
touching engine code:

- **`viewer.css`** — all node + edge appearance. Recolor a type, style an edge
  kind (`.edge--calls`), restyle the sidebar, tweak the dim opacity. The
  compound-header height lives in one place (`--header-h`).
- **type declarations** — one line of YAML per node type, plus Jinja HTML for
  anything bigger. No JavaScript involved: `templates.js` holds only a
  bare-title guard and the generic sidebar dump.

[`examples/styling.yaml`](examples/styling.yaml) is this whole section as one
diagram — every feature below drawn by a node that says which feature drew it,
plus one node per packaged type (`file`, `option`, `class`, `group`, …) so the
defaults you inherit are visible too. Each node carries a `code:` field quoting
the YAML that drew it, so clicking one shows source beside result:

```bash
io-flow build examples/styling.yaml -o styling.html   # or `edit` to poke at it live
```

### Declaring a node type

`type:` on a node is free-form and needs no registration — `type: queue` works
in any diagram, takes a `.node--queue` CSS class, and renders a title. A **type
declaration** says what it should look like beyond that. One entry, one type.

#### In the diagram itself

A top-level `types:` block describes the types that diagram uses. Nothing else
on disk changes:

```yaml
# pipeline.yaml
types:
  queue:
    badge: queue                                   # the pill beside the title
    meta: ["{% if data.depth %}{{ data.depth }} waiting{% endif %}"]
  stage:
    extends: group                                 # inherits group's look and mount
    meta: ["{{ data.loc }}"]
  gate:
    template: '<div class="node__title">|{{ label }}|</div>'   # inline, no file

style:
  skin: pipeline.css          # where .node--queue etc. live

nodes:
  $ingest:
    type: stage
    loc: src/ingest.py
    $inbox: {type: queue, depth: 12}
    $guard: {type: gate}
```

`$inbox` renders as:

```html
<div class="node__title">inbox <span class="node__badge">queue</span></div>
<div class="node__meta">12 waiting</div>
```

and colour comes from ordinary CSS in `pipeline.css`:

```css
.node--queue { border-left: 4px solid #b45309; }
.node--queue .node__badge { background: #b45309; }
```

#### Fields

Every field is Jinja source, rendered with the node's own `label`, `id`, `type`,
`data` (its free-form YAML keys), `parent`, and the whole `node`. Markup you
write is markup; `{{ values }}` are escaped.

| field | does |
|---|---|
| `extends` | another type — inherits its fields, its template and its CSS class. `node` and `group` are ordinary types you can extend like any other |
| `childtype` | what this type's untyped children are — `dir` holding `dir`s. Inherited like any other field; a `defaults:` entry overrides it. Read by the parser, so it counts in a diagram's own `types:` block (or the packaged ones), **not** in a project `templates/types.yaml` — that file is read after node types are assigned, and declaring it there warns |
| `class` | extra CSS classes on the node, inheriting nothing else |
| `css` | properties for this type, wrapped in `.node--<type> { … }` — or a block with its own selectors, emitted as written |
| `title` | the name line (default `{{ label }}`) |
| `badge` | the pill beside the title; omit for none |
| `meta` | dimmer lines under the title — **a line that renders blank is dropped**, which is how "show `cli` only if there is one" stays a one-liner |
| `blocks` | `{name: jinja}` replacing a block of the inherited template outright — reaches what the fields above don't cover, and `{{ super() }}` appends instead of replacing |
| `template` | a whole template written inline in the YAML — it owns the wrapper element, exactly like a file, and may itself `{% extends "node.html" %}` |
| `sidebar` | inline Jinja for the detail panel, instead of the generic data dump |

`title`/`badge`/`meta` are also the names of blocks in `node.html.j2`, which is
the one thing here worth reading twice. **The field is the value; the block is
the markup around it.** A declaration's `title:` fills a variable the template
draws as `<div class="node__title">…</div>`; `blocks: {title: …}` replaces that
markup outright. `meta:` only looks different because its value is a *list* and
its block is the loop over it:

```yaml
function:
  meta: ["{{ data.loc }}"]                    # your content, standard markup
function:
  blocks: {meta: "<p>{{ data.loc }}</p>"}     # no loop, no .node__meta at all
```

So: standard look with your content → the field. Different markup → the block.
`node.html.j2` line `{{ title | default(label, true) }}` is the seam — say
nothing and the node's `label` fills in.

#### Inheriting

`extends:` naming another **type** inherits its fields *and* its CSS class, so
styling comes along through the ordinary cascade:

```yaml
types:
  queue:
    badge: queue
    meta: ["{{ data.depth }} waiting"]
    css: "border-left: 4px solid #b45309;"
  urgent:
    extends: queue          # inherits meta, badge, template — and .node--queue
    badge: "!"              # overrides just this
    css: "border-color: #dc2626;"
```

`$hot: {type: urgent}` renders with `class="node node--urgent node--queue"`, so
every `.node--queue` rule applies and `.node--urgent` overrides it — parent
rules are emitted first, since both selectors are one class and source order is
what decides. Extending a compound type (`extends: group`) brings its children
mount with it.

There is no separate "base" concept: `node` and `group` are ordinary types,
declared in `types.yaml` and rendered by `node.html.j2` / `group.html.j2`, and
you extend them exactly like you'd extend one of your own. `extends: group`
gives you its template (header plus children mount), its fields, and
`node--group` on the wrapper — so `.node--group` styling applies and your
`.node--<type>` rules override it.

`class:` is the same idea without the inheritance — `class: [pill, warn]` just
adds classes, for a look shared by types with nothing else in common. `css:` is
not inherited or merged: a child already gets its parent's rules via the
parent's class, so declaring `css:` twice would emit it twice.

A node can carry `class:` too, for a one-off that doesn't deserve a type:

```yaml
nodes:
  $queue:
    type: queue
    class: warn        # -> class="node node--queue warn"
```

It lands last on the wrapper, after everything the type contributed, and it is
a reserved key like `type:` and `label:` — styling for this one node, so it
doesn't show up in `fields`.

#### Re-pointing a variable instead of restating a rule

`viewer.css` colors each built-in type through a variable (`--file`, `--method`,
`--group`, …). A `css:` block can redefine one for its own type, and every rule
that reads it follows — no rule gets copied:

```yaml
types:
  python-file: {extends: file, css: "--file: #3572A5;"}
  yaml-file:   {extends: file, css: "--file: #cb171e;"}
```

Both come out as `.node--<type> { --file: … }`. `extends: file` puts
`node--file` on the wrapper, so `.node--file`'s border rule — which resolves
`var(--file)` *on the node itself* — picks up the local value, and the badge
rule resolves it on the badge, which inherits `--file` from the node. Border and
badge recolor together from one line.

The scope is that node and its descendants: nothing outside the subtree
(edges, the sidebar) sees the override. `--header-h` is the one to leave alone
— `IOF.headerH()` reads it off `:root` for layout math, so a per-type override
changes the bar you see but not the space ELK reserved for it.

Omit `extends` and the template follows the node: `group.html` when something
is parented to it, `node.html` otherwise — compound-ness is a state, not a type.
That gives structure without the group *look*, since no class is inherited. So
an undeclared type still renders, and a declared one adapts if you later nest
things inside it.

#### The wrapper is the template's

`node.html.j2` renders the whole element, `<div class="{{ classes }}"
data-node-id="{{ id }}">` included, so the class list is visible in the built
artifact rather than assembled by JavaScript at mount time. `classes` is
`node`, the node's own `node--<type>`, then everything inherited. The engine
re-adds `.node` and the id defensively, so a template that drops them still
works — but keep them.

#### A type that just lists its data

`fields` is `data` with the noise removed — no `type`/`label`, no relation
blocks, including any your `relations:` block registered:

```yaml
types:
  bag:
    blocks:
      meta: '{% for k, v in fields.items() %}<div class="node__meta"><b>{{ k }}</b>: {{ v }}</div>{% endfor %}'
nodes:
  $box: {type: bag, owner: ops, region: us-east-1, args: {path: $cfg}}
```

renders `owner` and `region` and leaves `args` to the edge it draws. Swap the
`meta` block for `template:` if you want a `<ul>` or `<dl>` rather than meta
lines.

#### Where declarations live

Three layers, each merged over the last, **entry by entry** — reusing a name
replaces that whole entry rather than merging its keys, so a type is described
in exactly one place:

| layer | scope |
|---|---|
| `assets/templates/types.yaml` (packaged) | io-flow's built-in types |
| `templates/types.yaml` in your project | every diagram built with `style: {templates: templates/}` |
| the diagram's own `types:` block | that diagram |

Redeclaring a built-in is how you change one: put `method: {title: "{{ label }} [m]"}`
in either of the upper layers and methods stop rendering `()`.

The built-in types, for reference: `file`, `option`, `parameter` (badged),
`function`, `method` (`()` suffix), `class`, `group` (compound), `attributes`,
`input`, `node`. Read `assets/templates/types.yaml` — it is ten short entries,
and it is the best documentation of the field set.

### When a line isn't enough: template files

Point `--templates` (or `style: templates:`) at a **directory** and each
`<type>.html` in it becomes that type's template, winning over its declaration
— plain HTML with `{{ }}`, rendered by Jinja in Python at build time:

```
my-diagram.yaml
templates/
  queue.html.j2
```
```html
<!-- templates/queue.html.j2 — the whole thing -->
<div class="node__title">{{ label }} <span class="node__badge">queue</span></div>
{% if data.depth %}<div class="node__meta">{{ data.depth }} waiting</div>{% endif %}
```

Use `<type>.html.j2` or plain `<type>.html` — both work everywhere. `.html.j2`
is what editors recognize as Jinja (VS Code's Better Jinja, PyCharm's Jinja2
file type), so `{# comments #}` and tags highlight instead of reading as broken
HTML.

The filename is the registration — no map, no closure, and values are
autoescaped, so there is no `esc()` to forget. Reach for a file when the type
needs loops, nested structure or a `<pre>`; a badge and two meta lines are a
`types.yaml` line, not a file. Nodes are rendered once at mount, so baking the
HTML in at build time loses nothing and ships no template engine in the artifact.

A file can extend any type's template, and override one block.
The type's declaration still applies: its `title`/`badge`/`meta` arrive as the
block defaults, so declare the cheap parts and override only the markup you
actually care about:

```html
{% extends "group.html" %}                          <!-- a node holding children -->
{% block header %}<span class="node__title">{{ label }}</span>{% endblock %}
```

Blocks available: `header`, `title`, `badge`, `meta`, `children` in `node.html`; `rows`
in `_sidebar.html`. `{{ super() }}` inside a block renders the default content, so you
can add to it instead of replacing it. A `blocks:` entry in a declaration does
the same thing from YAML, so a file is only needed for markup a line can't hold.

`node.html`, `group.html` and `_sidebar.html` ship with io-flow (as
`.html.j2` files — `{% extends %}` finds either spelling; a template of your own
with that name shadows the packaged one — that is how you'd restyle every node
at once). `group.html` also documents the
four non-obvious CSS rules a compound node needs. **Names come from the node's
own type, never from the template it inherited** — the wrapper's `node--<type>`
class is set by the engine from `node.type`, and `{{ type }}` inside a template
is likewise the node's own, so one shared structure renders correct per-type
classes and badges.

`<type>.sidebar.html` in the same directory does the same for the detail panel,
independently — a type can have a body template, a sidebar template, both, or
neither:

```html
<!-- templates/queue.sidebar.html.j2 -->
{% extends "_sidebar.html" %}                       <!-- every data field as a row -->
{% block rows %}<dt>depth</dt><dd>{{ data.depth }} waiting</dd>{{ super() }}{% endblock %}
```

The engine still owns the panel chrome (close button, type tag, title); a type
with no sidebar template falls through to the active skin's `<name>.sidebar.html`
(if it has one), then to `IOF.sidebars`, then to the generic data dump. The
bundled `codemap` skin is exactly that: a `codemap.sidebar.html.j2` covering every
type, which a `templates/<type>.sidebar.html` of yours overrides per type.

Template context: `label` (falls back to the id), `id`, `type`, `data` (every
non-`$` YAML key on the node), `fields` (`data` minus `type`/`label` and minus
relation blocks like `args:`/`calls:` — what a list-style type iterates),
`classes` (the wrapper's class attribute), `parent`, and the whole `node`.
Styling is
unchanged — write a `.node--<type>` rule in a `style: skin:` stylesheet.

Per-project skins without editing the installed package:

```bash
io-flow build pipeline.yaml --css my_skin.css --templates my_templates.js
```

`--css`/`--templates` *replace* the packaged files. `--skin` instead *layers* a
skin on top — its CSS is appended after `viewer.css`, its JS injected right
after `templates.js`, and its `<name>.sidebar.html` becomes the default sidebar
template — so a skin holds only its overrides. A skin entry is either a
**bundled name** (no suffix, e.g. `codemap`, loading any of
`assets/skins/codemap.{css,js,sidebar.html.j2}`) or a **project-local
`.css`/`.js`/`.sidebar.html[.j2]` file**; the flag is repeatable and entries layer in
order. The bundled `codemap` skin renders a node's
`source`/`code` as a `<pre>` and its `args`/`returns`/`calls`/`modifies`/
`attributes`/`bases` as labeled lists — the sidebar for `io-flow walk` output:

```bash
io-flow build codebase.yaml -o codebase.html --skin codemap
```

A diagram can also carry its own look via a top-level `style:` block, so you
don't repeat the flags on every `build`/`edit`:

```yaml
style:
  skin:                # one entry or a list, layered in order
    - codemap          #   no suffix = bundled skin name
    - skin/overrides.css   #   .css/.js = local file, relative to THIS yaml
    - skin/sidebar.js
  css: theme.css       # path, resolved relative to THIS yaml file (replaces viewer.css)
  templates: templates/  # a dir of <type>.html Jinja templates (see above),
                         # or a .js file replacing templates.js
```

`css:`/`templates:` *replace* the packaged file; `skin:` is *additive* — each
entry appended after the base (and after earlier entries), so it wins the
cascade without you having to fork `viewer.css`. Use a skin entry when you have
a few overrides, `css` when you're providing a whole stylesheet.

Same knobs as `--skin`/`--css`/`--templates`, and a CLI flag still wins over the
block (handy for a one-off). Because paths resolve against the YAML's own
directory, `io-flow edit` finds them no matter which directory you run from —
and under `edit`, editing a `style:`-declared CSS or JS file live-reloads the
browser just like editing the YAML.

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
  first match; Escape clears. A **legend** shows each node type present, or
  whatever a `legend:` block declares, rendered by the real templates.
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
  cli.py            argparse: build / edit / check / apply-layout / align / walk
  align.py          snap almost-aligned saved positions (per sibling space)
  walk.py           AST-walk a Python package -> io-flow YAML codebase map
  parser.py         two-pass YAML -> recursive graph model; EDGE_KEYS registry
  layout_store.py   layout: block read/merge (ruamel round-trip) + topology hash
  edge_store.py     append browser-created connections to edges: (append-only)
  emit.py           inline JSON + CSS + JS into one self-contained HTML
  jinja_templates.py  render node/sidebar HTML from type declarations at build
  server.py         stdlib http.server: rebuild-on-GET, POST /save, /version
  assets/
    viewer.html     skeleton with style/graph/script slots
    viewer.css      <- user-editable: all node/edge styling
    templates/
      types.yaml    <- user-editable: the built-in node type declarations
      node.html.j2    the root type: wrapper div, header, title/badge/meta
      group.html.j2   node.html plus the children mount
      _sidebar.html.j2  fragment sidebar templates extend (sidebars aren't types)
    templates.js    viewer fallbacks: bare-title guard + generic sidebar dump
    skins/          codemap.css + codemap.sidebar.html.j2
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
