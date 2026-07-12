#!/usr/bin/env python3
"""CSV funnel -> stratified sankey-style io-flow YAML (+ matching CSS skin).

Turns a spreadsheet of items progressing through boolean stages into a
weighted io-flow diagram, with edges optionally STRATIFIED by a categorical
column: each stage transition is drawn as one band per stratum value, sized
by how many of the transition's items carry that value and colored per value
from the generated CSS. Stacked bands answer questions like "does LinkedIn
or Referral end up with more offers?" at a glance.

Expected CSV shape (see example_job-search_sankey.csv):
  - one row per item (e.g. job application);
  - stage columns holding TRUE / FALSE / blank, in funnel order
    (auto-detected: every column whose values are only TRUE/FALSE/blank,
    in CSV order);
  - any other columns are categorical / ordinal, usable with --by.

Each item's path starts at its --source-col node and visits every TRUE
stage in order. FALSE/blank stages are skipped, so an unusual path (an
interview with no email back) shows as a stage-skipping band instead of
silently vanishing; drop-off shows as the funnel narrowing.

Usage:
  python examples/csv_to_sankey.py example_job-search_sankey.csv --by Source
  io-flow edit example_job-search_sankey_by_source.yaml \
      --css example_job-search_sankey_by_source.css

This is deliberately an example script, not part of the io-flow package:
it writes plain YAML that the normal toolchain consumes. Adapt freely --
a pandas version is a straight transliteration of build_edges().
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

PALETTE = [
    "#2f6feb", "#d97706", "#0e9f6e", "#db2777", "#7c3aed",
    "#0891b2", "#65a30d", "#dc2626", "#475569", "#b45309",
]

STAGE_VALUES = {"TRUE", "FALSE", ""}


def slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(text)).strip("_").lower()
    return s or "x"


def detect_stages(rows: list[dict]) -> list[str]:
    return [
        col
        for col in rows[0]
        if {str(r[col]).strip().upper() for r in rows} <= STAGE_VALUES
    ]


def build_edges(rows, stages, source_col, by):
    """Edges [(from, to, stratum_value, count)] + node populations {id: n}
    over every item's path.

    A node's population is the number of items whose path visits it -- data
    the diagram declares per node (`population:`) and renders as exact
    proportional height in sankey mode. Sorted edge output keeps bands
    between any node pair in the same stratum order everywhere, so parallel
    bands never cross between stages.
    """
    groups: Counter = Counter()
    populations: Counter = Counter()
    for r in rows:
        path = [slug(r[source_col])] + [
            slug(s) for s in stages if str(r[s]).strip().upper() == "TRUE"
        ]
        for node in path:
            populations[node] += 1
        for a, b in zip(path, path[1:]):
            groups[(a, b, str(r[by]))] += 1
    edges = [(a, b, value, n) for (a, b, value), n in sorted(groups.items())]
    return edges, dict(populations)


def assign_tiers(stages, edges, source_slugs):
    """{node_slug: tier} derived from the observed flow, not column order.

    A stage's tier is 1 + the max tier of its actual predecessors, so
    parallel outcomes fed by the same upstream (e.g. "HR Interview" and
    "Communicated Rejection", both entered straight from sources) share a
    column. Paths visit stages in CSV column order, so one ordered pass
    sees every predecessor already tiered. A stage nothing flows into
    falls back to one past the previous stage's tier.
    """
    tier = {s: 0 for s in source_slugs}
    prev = 0
    for st in stages:
        sid = slug(st)
        preds = [tier[a] for (a, b, _v, _n) in edges if b == sid and a in tier]
        tier[sid] = (max(preds) + 1) if preds else (prev + 1)
        prev = tier[sid]
    return tier


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv_path", help="input CSV")
    ap.add_argument("--by", default="Source", help="stratifier column (default: Source)")
    ap.add_argument("--source-col", default="Source", help="leftmost-nodes column")
    ap.add_argument("-o", "--out", help="output YAML path (default: <csv>_by_<by>.yaml)")
    args = ap.parse_args(argv)

    csv_path = Path(args.csv_path)
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("empty CSV", file=sys.stderr)
        return 1
    for col in (args.by, args.source_col):
        if col not in rows[0]:
            print(f"no column {col!r}; have: {', '.join(rows[0])}", file=sys.stderr)
            return 1

    stages = detect_stages(rows)
    if not stages:
        print("no TRUE/FALSE stage columns found", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else csv_path.with_name(
        f"{csv_path.stem}_by_{slug(args.by)}.yaml"
    )
    css_out = out.with_suffix(".css")

    sources = sorted({str(r[args.source_col]) for r in rows})
    strata = sorted({str(r[args.by]) for r in rows})
    # Stratum value -> stable edge type tag (a valid CSS class suffix).
    tag = {v: slug(f"{args.by}-{v}") for v in strata}
    edges, populations = build_edges(rows, stages, args.source_col, args.by)

    lines = [
        f"# Generated by csv_to_sankey.py from {csv_path.name} (stratified by {args.by}).",
        f"# Regenerate rather than hand-editing; colors live in {css_out.name}.",
        f'title: "{csv_path.stem}: flow by {args.by}"',
        "",
        "diagram:",
        "  direction: RIGHT",
        "  layerSpacing: 110",
        # Sankey mode: population/weight are the same unit; heights and band
        # widths render at exactly `unit` px per item, bands tile the nodes.
        "  sankey: {unit: 12}",
        "",
        "nodes:",
    ]
    # tier: pins rendered columns. Sources share column 0; each stage's
    # column comes from the observed flow (assign_tiers), so parallel
    # outcomes -- "HR Interview" vs "Communicated Rejection", both entered
    # straight from a source -- share a column.
    tiers = assign_tiers(stages, edges, {slug(s) for s in sources})
    for s in sources:
        pop = populations.get(slug(s), 0)
        lines.append(
            f"  ${slug(s)}: {{type: source, label: {s!r}, population: {pop}, tier: 0}}"
        )
    for st in stages:
        pop = populations.get(slug(st), 0)
        lines.append(
            f"  ${slug(st)}: {{type: stage, label: {st!r}, population: {pop}, "
            f"tier: {tiers[slug(st)]}}}"
        )
    lines.append("")
    lines.append("edges:")
    for src, dst, value, n in edges:
        lines.append(
            f"  - {{from: ${src}, to: ${dst}, type: {tag[value]}, "
            f"weight: {n}, label: '{value}: {n}'}}"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # CSS skin: the packaged viewer.css plus one stroke color per stratum.
    from io_flow.emit import ASSETS  # packaged default the skin extends

    css = [(ASSETS / "viewer.css").read_text(encoding="utf-8"), ""]
    css.append(f"/* --- csv_to_sankey: {args.by} strata --------------------- */")
    for i, v in enumerate(strata):
        color = PALETTE[i % len(PALETTE)]
        # The #edges prefix out-specifies the base `#edges .edge` stroke rule.
        css.append(f"#edges .edge--{tag[v]} {{ stroke: {color}; }}  /* {v} */")
    css.append(
        """
/* Sankey bar look: the node box IS the bar (its height is the data), so the
 * label moves outside, below the bar. #canvas scoping spares the legend. */
#canvas .node--source, #canvas .node--stage {
  width: 22px;
  padding: 0;
  background: #64748b;
  border: none;
  border-radius: 3px;
}
#canvas .node--source .node__title, #canvas .node--stage .node__title {
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  margin-top: 5px;
  font-weight: 600;
  white-space: nowrap;
}"""
    )
    css_out.write_text("\n".join(css) + "\n", encoding="utf-8")

    # Deterministic sankey layout, written into the layout: block so the
    # browser restores it exactly (no ELK draft to fight; `build` omits
    # elkjs entirely). Columns share a top line; within a column, nodes
    # stack top-aligned ordered by outgoing flow -- the outcome that flows
    # onward (HR Interview) sits above the terminal one (Communicated
    # Rejection). Drag + Save still re-arranges as usual.
    from io_flow.layout_store import merge_positions
    from io_flow.parser import parse_file

    unit = 12  # keep in sync with the diagram: sankey: block above
    bar_w = 22  # keep in sync with the node width in the generated CSS
    layer_gap = 110
    node_gap = 40
    out_flow: Counter = Counter()
    for a, _b, _v, n in edges:
        out_flow[a] += n
    columns: dict[int, list[str]] = {}
    for s in sources:
        columns.setdefault(0, []).append(slug(s))
    for st in stages:
        columns.setdefault(tiers[slug(st)], []).append(slug(st))
    positions: dict[str, list[float]] = {}
    for t, ids in columns.items():
        ids.sort(key=lambda i: (-out_flow[i], -populations.get(i, 0), i))
        y = 0
        for nid in ids:
            positions[nid] = [t * (bar_w + layer_gap), y]
            y += populations.get(nid, 0) * unit + node_gap
    merge_positions(out, parse_file(out), positions)

    print(f"wrote {out} ({len(edges)} bands, layout pinned) and {css_out}")
    for i, v in enumerate(strata):
        print(f"  {PALETTE[i % len(PALETTE)]}  {v}")
    print(f"view:  io-flow edit {out} --css {css_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
