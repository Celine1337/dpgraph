#!/usr/bin/env python3
"""Generate the demo datapack (tests/demo) used by screenshots and manual runs.

It intentionally contains one missing target, one dead function and one
schedule cycle so every report section has something to show.
"""
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "tests", "demo")

FILES = {
    "data/minecraft/tags/function/load.json": {"values": ["demo:boot", "#demo:init"]},
    "data/minecraft/tags/function/tick.json": {"values": ["demo:tick"]},
    "data/demo/tags/function/init.json": {
        "values": ["demo:setup", {"id": "demo:optional", "required": False}]},
    "data/demo/function/boot.mcfunction":
        "# entry point\nfunction demo:setup\nfunction demo:gone\n",
    "data/demo/function/setup.mcfunction": "say setup\nfunction demo:deep1\n",
    "data/demo/function/deep1.mcfunction": "function demo:deep2\n",
    "data/demo/function/deep2.mcfunction": "function demo:loop\n",
    "data/demo/function/loop.mcfunction": "schedule function demo:tick 1t\n",
    "data/demo/function/tick.mcfunction": "execute as @a run function demo:loop\n",
    "data/demo/function/unused.mcfunction": "say nobody calls me\n",
}


def main():
    for rel, content in FILES.items():
        path = os.path.join(PACK, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = json.dumps(content, indent=2) if isinstance(content, dict) else content
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(f"{PACK}: {len(FILES)} files")


if __name__ == "__main__":
    main()