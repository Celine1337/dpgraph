#!/usr/bin/env python3
"""dpgraph — call-graph auditor for Minecraft datapacks. Stdlib only, Python 3.9+.

Scans data/<ns>/function(s)/**/*.mcfunction, builds the call graph (including
`function #tag` expansion and load/tick roots) and reports missing targets,
dead (unreachable) functions and call cycles.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

__version__ = "1.0.0"

CALL_RE = re.compile(r"\bfunction\s+(#?)([a-z0-9_.\-]+:[a-z0-9_./\-]+)")
FUNC_DIRS = ("function", "functions")
TAG_DIRS = ("tags/function", "tags/functions")


class PackError(ValueError):
    pass


def c(code, text, enabled):
    return f"\x1b[{code}m{text}\x1b[0m" if enabled else text


def find_pack_root(path: str) -> str:
    if os.path.isdir(os.path.join(path, "data")):
        return path
    raise PackError(f"{path}: no data/ directory (point me at a datapack root)")


def scan(root: str):
    """Return (functions, tags, calls): id->lines, tag id->values, caller->[(is_tag, id)]."""
    functions, tags, calls = {}, {}, defaultdict(list)
    data = os.path.join(root, "data")
    for ns in sorted(os.listdir(data)):
        ns_dir = os.path.join(data, ns)
        if not os.path.isdir(ns_dir):
            continue
        for fdir in FUNC_DIRS:
            base = os.path.join(ns_dir, fdir)
            for dirpath, _, files in os.walk(base):
                for fn in sorted(files):
                    if not fn.endswith(".mcfunction"):
                        continue
                    rel = os.path.relpath(os.path.join(dirpath, fn), base)
                    fid = ns + ":" + rel[:-len(".mcfunction")].replace(os.sep, "/")
                    if fid in functions:
                        continue
                    with open(os.path.join(dirpath, fn), encoding="utf-8") as f:
                        lines = f.read().splitlines()
                    functions[fid] = lines
                    for line in lines:
                        if line.lstrip().startswith("#"):
                            continue
                        for m in CALL_RE.finditer(line):
                            calls[fid].append((m.group(1) == "#", m.group(2)))
        for tdir in TAG_DIRS:
            base = os.path.join(ns_dir, tdir)
            for dirpath, _, files in os.walk(base):
                for fn in sorted(files):
                    if not fn.endswith(".json"):
                        continue
                    rel = os.path.relpath(os.path.join(dirpath, fn), base)
                    tid = ns + ":" + rel[:-len(".json")].replace(os.sep, "/")
                    if tid in tags:
                        continue
                    with open(os.path.join(dirpath, fn), encoding="utf-8") as f:
                        doc = json.load(f)
                    values = []
                    for v in doc.get("values", []):
                        if isinstance(v, str):
                            values.append((v.lstrip("#"), True))
                        elif v.get("id"):
                            values.append((v["id"].lstrip("#"), v.get("required", True)))
                    tags[tid] = values
    return functions, tags, calls


def build_graph(functions, tags, calls):
    edges = defaultdict(set)
    missing = defaultdict(set)
    for caller, refs in calls.items():
        for is_tag, rid in refs:
            if is_tag:
                if rid not in tags:
                    missing[rid].add(caller)
                    continue
                edges[caller].add(rid)
            else:
                if rid not in functions:
                    missing[rid].add(caller)
                    continue
                edges[caller].add(rid)
    for tid, values in tags.items():
        for vid, required in values:
            if vid in functions or vid in tags:
                edges[tid].add(vid)
            elif required:
                missing[vid].add(tid)
    roots = [t for t in ("minecraft:load", "minecraft:tick") if t in tags]
    return edges, missing, roots


def reachable(edges, roots):
    seen = set(roots)
    stack = list(roots)
    while stack:
        for nxt in edges.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def sccs(nodes, edges):
    """Kosaraju, iterative: returns list of components (lists of node ids)."""
    rev = defaultdict(set)
    for a, outs in edges.items():
        for b in outs:
            rev[b].add(a)
    seen, order = set(), []
    for start in nodes:
        if start in seen:
            continue
        stack = [(start, iter(sorted(edges.get(start, ()))))]
        seen.add(start)
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append((nxt, iter(sorted(edges.get(nxt, ())))))
                    advanced = True
                    break
            if not advanced:
                order.append(node)
                stack.pop()
    seen, comps = set(), []
    for start in reversed(order):
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            comp.append(node)
            for nxt in rev.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        comps.append(sorted(comp))
    return comps


def find_cycles(nodes, edges):
    out = []
    for comp in sccs(nodes, edges):
        if len(comp) > 1:
            out.append(comp)
        elif comp[0] in edges.get(comp[0], ()):
            out.append(comp)
    return sorted(out)


def audit(root: str):
    functions, tags, calls = scan(find_pack_root(root))
    edges, missing, roots = build_graph(functions, tags, calls)
    nodes = set(functions) | set(tags)
    live = reachable(edges, roots)
    dead = sorted(n for n in functions if n not in live)
    cycles = find_cycles(nodes, edges)
    return {
        "functions": functions, "tags": tags, "edges": edges,
        "roots": roots, "missing": missing, "dead": dead, "cycles": cycles,
        "call_count": sum(len(v) for v in calls.values()),
    }


def render_tree(rep, start, color):
    edges, functions, tags = rep["edges"], rep["functions"], rep["tags"]
    missing_children = defaultdict(set)
    for mid, refs in rep["missing"].items():
        for caller in refs:
            missing_children[caller].add(mid)
    if start not in functions and start not in tags:
        raise PackError(f"unknown function or tag: {start}")
    lines = []

    def walk(node, depth, path):
        mark = ""
        if node in path:
            mark = " " + c("35", "(cycle)", color)
        elif node not in functions and node not in tags:
            mark = " " + c("31", "(missing)", color)
        kind = "#" if node in tags else ""
        lines.append("  " * depth + c("36", kind + node, color) + mark)
        if mark or depth > 24:
            return
        for nxt in sorted(edges.get(node, set()) | missing_children.get(node, set())):
            walk(nxt, depth + 1, path | {node})

    walk(start, 0, set())
    return "\n".join(lines)


def report(rep, color, as_json):
    if as_json:
        return json.dumps({
            "summary": {"functions": len(rep["functions"]), "tags": len(rep["tags"]),
                        "calls": rep["call_count"], "roots": rep["roots"]},
            "missing": {k: sorted(v) for k, v in sorted(rep["missing"].items())},
            "dead": rep["dead"],
            "cycles": rep["cycles"],
        }, indent=2)
    out = [c("1;36", "SUMMARY", color)]
    out.append(f"  functions  {len(rep['functions'])}")
    out.append(f"  tags       {len(rep['tags'])}")
    out.append(f"  calls      {rep['call_count']}")
    roots = ", ".join(f"{r} ({len(rep['edges'].get(r, ()))})" for r in rep["roots"]) or "-"
    out.append(f"  roots      {roots}")
    issues = 0
    if rep["missing"]:
        issues += len(rep["missing"])
        out.append(c("1;31", f"MISSING ({len(rep['missing'])})", color))
        for mid, refs in sorted(rep["missing"].items()):
            out.append(f"  {c('31', mid, color)}  referenced by {', '.join(sorted(refs))}")
    if rep["dead"]:
        issues += len(rep["dead"])
        out.append(c("1;33", f"DEAD ({len(rep['dead'])})", color))
        for d in rep["dead"]:
            out.append(f"  {c('33', d, color)}")
    if rep["cycles"]:
        issues += len(rep["cycles"])
        out.append(c("1;35", f"CYCLES ({len(rep['cycles'])})", color))
        for comp in rep["cycles"]:
            out.append(f"  {c('35', ' -> '.join(comp + [comp[0]]), color)}")
    if not issues:
        out.append(c("32", "clean: no missing, dead or cyclic functions", color))
    return "\n".join(out)


def build_parser():
    p = argparse.ArgumentParser(
        prog="dpgraph",
        description="Call-graph auditor for Minecraft datapacks: missing, dead and cyclic functions.")
    p.add_argument("root", help="datapack root (the directory containing data/)")
    p.add_argument("--json", action="store_true", help="machine-readable report")
    p.add_argument("--tree", metavar="ID", help="print the call tree of ns:function or ns:tag")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors (also NO_COLOR)")
    p.add_argument("--version", action="version", version=f"dpgraph {__version__}")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    color = not args.no_color and not os.environ.get("NO_COLOR") and sys.stdout.isatty()
    try:
        rep = audit(args.root)
        if args.tree:
            print(render_tree(rep, args.tree, color))
        else:
            print(report(rep, color, args.json))
    except PackError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.tree:
        return 0
    return 1 if (rep["missing"] or rep["dead"] or rep["cycles"]) else 0


if __name__ == "__main__":
    sys.exit(main())