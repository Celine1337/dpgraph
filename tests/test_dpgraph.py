import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dpgraph as dg


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def pack(files):
    root = tempfile.mkdtemp(prefix="dpgraph-test-")
    for rel, text in files.items():
        write(root, rel, text)
    return root


CLEAN = {
    "data/minecraft/tags/function/load.json": json.dumps({"values": ["demo:boot"]}),
    "data/demo/function/boot.mcfunction": "function demo:tick_loop\n",
    "data/demo/function/tick_loop.mcfunction": "say hi\n",
}


class TestScan(unittest.TestCase):
    def setUp(self):
        self.root = pack(CLEAN)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_functions_and_calls(self):
        funcs, tags, calls = dg.scan(self.root)
        self.assertEqual(sorted(funcs), ["demo:boot", "demo:tick_loop"])
        self.assertEqual(calls["demo:boot"], [(False, "demo:tick_loop")])
        self.assertIn("minecraft:load", tags)

    def test_legacy_functions_dir(self):
        write(self.root, "data/old/functions/legacy.mcfunction", "say old\n")
        funcs, _, _ = dg.scan(self.root)
        self.assertIn("old:legacy", funcs)

    def test_execute_schedule_and_comments(self):
        write(self.root, "data/demo/function/boot.mcfunction",
              "# function demo:commented\n"
              "execute as @a run function demo:tick_loop\n"
              "schedule function demo:later 5t\n")
        _, _, calls = dg.scan(self.root)
        self.assertEqual(calls["demo:boot"],
                         [(False, "demo:tick_loop"), (False, "demo:later")])

    def test_tag_call_syntax(self):
        write(self.root, "data/demo/function/boot.mcfunction", "function #demo:group\n")
        write(self.root, "data/demo/tags/function/group.json",
              json.dumps({"values": ["demo:tick_loop"]}))
        _, tags, calls = dg.scan(self.root)
        self.assertEqual(calls["demo:boot"], [(True, "demo:group")])
        self.assertEqual(tags["demo:group"], [("demo:tick_loop", True)])

    def test_uppercase_id_ignored(self):
        write(self.root, "data/demo/function/boot.mcfunction", "function DEMO:Bad\n")
        _, _, calls = dg.scan(self.root)
        self.assertEqual(calls["demo:boot"], [])


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.root = pack(CLEAN)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_clean_pack(self):
        rep = dg.audit(self.root)
        self.assertEqual(rep["missing"], {})
        self.assertEqual(rep["dead"], [])
        self.assertEqual(rep["cycles"], [])
        self.assertEqual(rep["roots"], ["minecraft:load"])

    def test_missing_function(self):
        write(self.root, "data/demo/function/boot.mcfunction", "function demo:gone\n")
        rep = dg.audit(self.root)
        self.assertEqual(sorted(rep["missing"]), ["demo:gone"])
        self.assertEqual(rep["missing"]["demo:gone"], {"demo:boot"})

    def test_missing_tag_and_optional_value(self):
        write(self.root, "data/demo/function/boot.mcfunction", "function #demo:nope\n")
        write(self.root, "data/minecraft/tags/function/load.json", json.dumps({
            "values": ["demo:boot", {"id": "demo:optional", "required": False}]}))
        rep = dg.audit(self.root)
        self.assertEqual(sorted(rep["missing"]), ["demo:nope"])

    def test_dead_function(self):
        write(self.root, "data/demo/function/unused.mcfunction", "say dead\n")
        rep = dg.audit(self.root)
        self.assertEqual(rep["dead"], ["demo:unused"])

    def test_nested_tags_reachability(self):
        write(self.root, "data/minecraft/tags/function/load.json",
              json.dumps({"values": ["demo:boot", "#demo:outer"]}))
        write(self.root, "data/demo/tags/function/outer.json",
              json.dumps({"values": ["#demo:inner"]}))
        write(self.root, "data/demo/tags/function/inner.json",
              json.dumps({"values": ["demo:tick_loop"]}))
        rep = dg.audit(self.root)
        self.assertEqual(rep["dead"], [])
        self.assertEqual(rep["missing"], {})

    def test_self_cycle(self):
        write(self.root, "data/demo/function/tick_loop.mcfunction",
              "schedule function demo:tick_loop 1t\n")
        rep = dg.audit(self.root)
        self.assertEqual(rep["cycles"], [["demo:tick_loop"]])

    def test_mutual_cycle(self):
        write(self.root, "data/demo/function/boot.mcfunction", "function demo:a\n")
        write(self.root, "data/demo/function/a.mcfunction", "function demo:b\n")
        write(self.root, "data/demo/function/b.mcfunction", "function demo:a\n")
        rep = dg.audit(self.root)
        self.assertEqual(rep["cycles"], [["demo:a", "demo:b"]])
        self.assertEqual(rep["dead"], ["demo:tick_loop"])

    def test_tick_root(self):
        write(self.root, "data/minecraft/tags/function/tick.json",
              json.dumps({"values": ["demo:tick_loop"]}))
        write(self.root, "data/minecraft/tags/function/load.json", json.dumps({"values": []}))
        rep = dg.audit(self.root)
        self.assertEqual(rep["roots"], ["minecraft:load", "minecraft:tick"])
        self.assertEqual(rep["dead"], ["demo:boot"])


class TestOutput(unittest.TestCase):
    def setUp(self):
        self.root = pack(CLEAN)
        write(self.root, "data/demo/function/unused.mcfunction", "say dead\n")
        write(self.root, "data/demo/function/boot.mcfunction",
              "function demo:tick_loop\nfunction demo:gone\n")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_report_sections_and_color(self):
        rep = dg.audit(self.root)
        plain = dg.report(rep, False, False)
        self.assertIn("MISSING (1)", plain)
        self.assertIn("DEAD (1)", plain)
        self.assertNotIn("\x1b", plain)
        colored = dg.report(rep, True, False)
        self.assertIn("\x1b[1;31m", colored)

    def test_json_report(self):
        rep = dg.audit(self.root)
        doc = json.loads(dg.report(rep, False, True))
        self.assertEqual(doc["summary"]["functions"], 3)
        self.assertEqual(doc["dead"], ["demo:unused"])
        self.assertEqual(doc["missing"], {"demo:gone": ["demo:boot"]})

    def test_tree_marks(self):
        write(self.root, "data/demo/function/tick_loop.mcfunction",
              "function demo:boot\n")
        rep = dg.audit(self.root)
        tree = dg.render_tree(rep, "demo:boot", False)
        self.assertIn("(cycle)", tree)
        self.assertIn("demo:gone (missing)", tree)

    def test_exit_codes(self):
        self.assertEqual(dg.main([self.root, "--no-color"]), 1)
        clean = pack(CLEAN)
        try:
            self.assertEqual(dg.main([clean, "--no-color"]), 0)
        finally:
            shutil.rmtree(clean)
        self.assertEqual(dg.main([self.root, "--tree", "demo:boot", "--no-color"]), 0)
        self.assertEqual(dg.main([os.path.join(self.root, "nope")]), 2)


if __name__ == "__main__":
    unittest.main()