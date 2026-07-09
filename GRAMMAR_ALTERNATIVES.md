# Grammar alternatives: the `children:` fence

This documents the road not taken when the YAML grammar was redesigned
(2026-07-08), and how to revert to it if the `$`-sigil grammar turns out to be
the wrong call. Both grammars produce the **identical output model** (flat
nodes with `parent` pointers + flat typed edges), so the viewer, layout store,
emitter, server, and CLI are untouched either way — switching is a parser +
examples + docs change only.

## Why the grammar was redesigned at all

The original grammar used **section headings as types** (`classes:`,
`functions:`, `groups:`, `methods:` — the `MEMBER_KEYS` registry). That made
type a structural *position* instead of a *property*, which:

- closed the nesting vocabulary (a new container kind like `steps:` required a
  Python edit, while edge kinds and input types were YAML-free-form);
- inserted a fake level into the hierarchy (node → section → node);
- forced authors to bucket siblings by type instead of writing them in
  reading/pipeline order;
- invited special-casing (`class` grew bespoke `attributes:`/`methods:`
  handling and a different id-scoping rule than groups).

Both designs below fix all of that: one uniform node concept, free-form
`type:`, path-qualified ids, compound-ness derived from having children.
They differ only in **how children are told apart from free data** — a node's
mapping holds three namespaces (a small closed set of properties; open
free-form data; open children), and a mapping key must be assignable to one
of them without guessing.

## The chosen design: `$` sigil at every mention

**Invariant: `$name` means node, everywhere** — declaration, nesting, and
reference all spell the node `$name` (Sass/PHP-style). See `parser.py`'s
docstring and README for the full rules.

What it buys (the reasons it won):

- **key = id, grep works**: searching `$from_yaml` finds the declaration and
  every reference; there is no strip rule between spelling and identity
  (the parser strips `$` uniformly at every mention).
- **References self-mark**, which dissolved two whole problem classes:
  - the `ref: key|value` axis of `relations:` (whether the reference lives in
    the entry's key or value) is gone — whichever side wears the `$` is the
    ref. This axis was actively confusing in practice.
  - reference *positions* no longer need policing: unmarked strings are
    always literals, so `value:`/`cli:`/`description:` can never spawn
    phantom edges by construction rather than by exclusion list.
- **Unresolved refs are unambiguous**: `$typo` is definitely a reference, so
  a miss is definitely wrong (loud warning with candidates).
- One less indentation level per compound; the YAML tree *is* the node tree.

Accepted costs:

- Forgetting the `$` on a reference silently turns it into a literal.
  Mitigated: `UnmarkedReferenceWarning` fires when an unmarked string in a
  relation block exactly matches a node id.
- Properties, data, and `$`-children may interleave freely inside a node
  mapping; nothing enforces children-last (style concern only).
- Any external tool reading the YAML must know the (shallow) `$` convention.
- Sigil choice is constrained by YAML: `@` is a reserved indicator (hard
  error unquoted) and `&`/`*` are silently eaten as anchor/alias syntax;
  `$`, `~`, `+`, `=`, `^` are safe. `_` collides with real identifiers
  (`_private_fn`), `.` with path ids.

## The alternative: explicit `children:` fence

One reserved key, `children:`, fences the child namespace — the YAML analogue
of mermaid's `subgraph ... end`. Everything else about the redesign (path
ids, free types, `defaults:`, direction-only edge semantics as far as
possible) stays the same.

```yaml
relations:
  reads: {direction: in, ref: value}   # the ref axis returns (see below)
defaults:
  class: method
nodes:
  configfile: {type: file, cli: --config}
  Config:
    type: class
    loc: src/config.py
    children:
      from_yaml:
        args: {path: configfile}       # plain positional reference
  pipeline:
    type: group
    children:
      extract:
        reads: {rows: raw_db}
        calls: {Config.from_yaml: "load config"}
```

Namespace rule: inside a node's mapping, `type`/`label`/`children`/relation
names are reserved properties; **everything else is data**; **everything
under `children:` is a node**. All three namespaces are unambiguous, and the
two open ones (data, children) stay fully open.

What it buys over the sigil:

- **Plain-vanilla YAML** — no spelling convention for other tools to know;
  keys are exactly ids with zero transformation.
- **Enforced segregation**: properties/data physically above, children below
  the fence. Reading a compound top-down is properties-then-contents, always.
- Node names may shadow reserved words (a function named `calls` is
  `children: {calls: {...}}` — unambiguous by position).
- Schema validation is trivial (`children: {additionalProperties: nodeSpec}`
  vs. `patternProperties: {"^\\$": ...}`).

What it costs (the reasons it lost):

- **References become positional again.** Without a mark, the parser must be
  told where references live, so:
  - `relations:` regains the `ref: key|value` axis (`args` refs in values,
    `calls`/`returns` refs in keys) — the thing that was repeatedly
    forgotten in practice;
  - reference positions must be exclusion-listed (never scan
    `value:`/`cli:`/`description:`), i.e. phantom-edge safety by policy
    rather than by construction;
  - a literal string that happens to equal a node id in a scanned position
    *silently becomes an edge* (the inverse failure of the sigil's
    forgotten-`$`, and harder to notice: a wrong edge looks plausible).
- One extra line and indentation level per compound.
- No visual distinction between a reference and an arbitrary string at the
  point of use.

## Revert recipe

Everything is confined to the parser + fixtures; the graph model, engine,
templates fallback (`templates.node`), auto-created child mounts, `defaults:`
block, and path-qualified ids all carry over unchanged.

1. **`src/io_flow/parser.py`**
   - `EDGE_KEYS` becomes `{name: (direction, ref_pos)}` again:
     `{"args": ("in", "value"), "calls": ("out", "key"), "returns": ("out", "key")}`;
     `_edge_keys_for` re-accepts `ref: key|value` (default `key`) instead of
     rejecting it.
   - In `add_node`: children come from `spec.get("children", {})` instead of
     `$`-prefixed keys; `data` = every key except
     `{"children"}` (keep `type`/`label`/relation blocks in data as today);
     drop the `$`-prefix requirement/stripping and the top-level
     "must be `$name`" error (any key under `nodes:` is a node).
   - In `record_edges`: for `ref_pos == "value"` treat entry *values* as refs
     (skip non-strings silently as literal defaults); for `"key"` treat entry
     *keys* as refs and values as optional labels. Exact match against the
     collected id set; keep the unresolved warning. Drop
     `UnmarkedReferenceWarning` and the both-sides-`$` error (meaningless
     without the mark).
   - Explicit `edges:`: `from`/`to` are plain ids (no `$` requirement).
     Node-level `edges:` lists and owner-defaulting carry over unchanged
     (`edges` stays a reserved property either way).
   - Keep: path-qualified ids from nesting, dot-ban in names, `defaults:`,
     label-defaults-to-short-name, two-pass resolve, dedupe, `diagram:`
     passthrough.
2. **Examples/tests**: mechanical rewrite — strip every `$`, wrap child nodes
   in `children:`, restore `ref:` where a relation reads value-side
   (`reads: {direction: in, ref: value}`). `layout:` blocks survive as-is
   (ids don't change).
3. **README**: swap the Input-format section for the fence description above.

## Rejected outright (don't revisit without new evidence)

- **Section-heading-as-type** (`classes:`/`functions:`/`groups:`): the
  original design; see "Why the grammar was redesigned" above.
- **Direct nesting with no marker** (`Config: {from_yaml: {}}`): children and
  data share one namespace; every disambiguation rule either closes the data
  namespace, misfires on mapping-valued data, or turns typos into phantom
  nodes.
- **Sigil on declarations only** (references unmarked): breaks key=id and
  grep (declared `$from_yaml`, referenced `from_yaml`) while keeping the
  positional-reference problems — worst of both.
- **Supporting both grammars at once**: every reader of any document would
  need to know both plus a precedence rule.
