#!/usr/bin/env python3
"""Regenerate docs/audit.png and docs/tree.png from the demo datapack.

Requires Pillow. Run: python tools/make_demo.py && python tools/make_shots.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import dpgraph as dg
import render_terminal as rt


def main():
    rep = dg.audit(os.path.join(ROOT, "tests", "demo"))
    shots = [
        ("audit", dg.report(rep, True, False),
         "python dpgraph.py tests/demo", "dpgraph — audit"),
        ("tree", dg.render_tree(rep, "minecraft:load", True),
         "python dpgraph.py tests/demo --tree minecraft:load", "dpgraph — call tree"),
    ]
    for name, ansi, cmd, title in shots:
        lines = rt.parse_ansi(ansi)
        rt.render(lines, title, cmd, os.path.join(ROOT, "docs", f"{name}.png"))


if __name__ == "__main__":
    main()