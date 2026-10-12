"""Regression tests for the novel-wiki engine (scripts/wiki.py).

Run from the repo root:  python -m unittest discover tests -v
Standard library only. Each test builds a throwaway project in a temp folder.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "novel-wiki", "scripts", "wiki.py")
EXAMPLE = os.path.join(ROOT, "examples", "lantern-coast")


def ep_patch(n, entities, **extra):
    p = {"episode": {"number": n, "title": "Ep %d" % n, "source": "chapters/%02d.md" % n,
                     "summary": "Summary %d" % n, "synopsis": ["Para."]}, "entities": entities}
    p.update(extra)
    return p


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nw-test-")
        os.makedirs(os.path.join(self.tmp, "chapters"))
        for n in (1, 2):
            self.write("chapters/%02d.md" % n, "# Episode %d\n\nText %d.\n" % (n, n))
        self.run_ok("init", "--title", "Test Novel", "--globs", "chapters/*.md")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers
    def write(self, rel, text):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text if isinstance(text, str) else json.dumps(text))
        return path

    def run_cmd(self, *args):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, ENGINE, "--wiki", os.path.join(self.tmp, "wiki")] + list(args),
                              capture_output=True, text=True, encoding="utf-8", env=env)

    def run_ok(self, *args):
        r = self.run_cmd(*args)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def apply(self, patch, *flags, log=None):
        args = ["apply", "--patch", self.write("p.json", patch)]
        if log is not None:
            args += ["--run-log", self.write("run.json", log)]
        return self.run_ok(*(args + list(flags)))

    def data(self):
        with open(os.path.join(self.tmp, "wiki", "data", "wiki.json"), encoding="utf-8") as f:
            return json.load(f)

    def history(self):
        with open(os.path.join(self.tmp, "wiki", "data", "history.json"), encoding="utf-8") as f:
            return json.load(f)

    def page(self, rel):
        with open(os.path.join(self.tmp, "wiki", "site", rel), encoding="utf-8") as f:
            return f.read()

    # -- tests
    def test_scan_reports_new_then_ok_then_changed(self):
        self.assertIn("NEW", self.run_ok("scan"))
        self.apply(ep_patch(1, [{"id": "ana", "type": "character", "name": "Ana"}]))
        out = self.run_ok("scan")
        self.assertRegex(out, r"OK\s+1\s+1")
        self.write("chapters/01.md", "# Episode 1\n\nRevised.\n")
        self.assertRegex(self.run_ok("scan"), r"CHANGED\s+1")

    def test_apply_builds_pages_links_and_history(self):
        self.apply(ep_patch(1, [
            {"id": "ana", "type": "character", "name": "Ana", "importance": "major",
             "lead": "**Ana** sails the *[[gull]]*.", "history": "Ana leaves port.", "presence": "pov"},
            {"id": "gull", "type": "item", "name": "Gull", "tagline": "A boat."}]),
            log={"request": "update wiki", "steps": ["read chapter 1"], "looked_at": ["chapters/01.md"]})
        ana = self.page("wiki/ana.html")
        self.assertIn('<em><a href="../wiki/gull.html">Gull</a></em>', ana)
        self.assertIn("Ana leaves port.", ana)
        self.assertIn("ana", self.page("wiki/gull.html"))  # what links here
        h = self.history()
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["created"], ["ana", "gull"])
        self.assertIn("chapters/01.md", h[0]["looked_at"])
        self.assertTrue(any(s.startswith("[engine]") for s in h[0]["steps"]))
        self.assertIn("Run #1", self.page("history.html"))
        with open(os.path.join(self.tmp, "wiki", "WIKI-HISTORY.md"), encoding="utf-8") as f:
            self.assertIn("read chapter 1", f.read())

    def test_dry_run_saves_nothing_and_warns_on_missing_links(self):
        out = self.apply(ep_patch(1, [{"id": "ana", "type": "character", "name": "Ana", "lead": "Friend of [[bo]]."}]),
                         "--dry-run")
        self.assertIn("DRY RUN", out)
        self.assertIn("[[bo]]", out)
        self.assertEqual(self.data()["entities"], {})
        self.assertEqual(self.history(), [])

    def test_invalid_patch_is_rejected_atomically(self):
        r = self.run_cmd("apply", "--patch", self.write("bad.json", ep_patch(1, [{"id": "Bad Id", "type": "character", "name": "X"}])))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("kebab-case", r.stderr)
        self.assertEqual(self.data()["episodes"], {})

    def test_revision_rolls_back_old_contributions(self):
        self.apply(ep_patch(1, [{"id": "ana", "type": "character", "name": "Ana", "history": "Old version."},
                                {"id": "cut", "type": "character", "name": "Cut Character"}],
                            threads=[{"id": "old-thread", "title": "Old?", "text": "x"}]))
        self.apply(ep_patch(1, [{"id": "ana", "history": "New version."}]))
        d = self.data()
        self.assertNotIn("cut", d["entities"])
        self.assertNotIn("old-thread", d["threads"])
        self.assertEqual([h["text"] for h in d["entities"]["ana"]["history"]], ["New version."])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "wiki", "site", "wiki", "cut.html")))

    def test_continue_run_folds_into_one_history_entry(self):
        self.apply(ep_patch(1, [{"id": "ana", "type": "character", "name": "Ana"}]), log={"request": "update wiki", "steps": ["a"]})
        self.apply(ep_patch(2, [{"id": "bo", "type": "character", "name": "Bo"}]), "--continue-run", log={"steps": ["a", "b"]})
        h = self.history()
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["episodes"], ["1", "2"])
        self.assertEqual(h[0]["created"], ["ana", "bo"])
        steps = h[0]["steps"]
        self.assertEqual(steps.count("a"), 1)  # repeated lines are merged
        self.assertLess(steps.index("a"), steps.index("b"))
        self.assertEqual(sum(s.startswith("[engine]") for s in steps), 2)

    def test_editorial_corrections_are_sticky(self):
        self.apply(ep_patch(1, [{"id": "ana", "type": "character", "name": "Ana", "infobox": {"Age": "19"}}]))
        self.apply({"editorial": True, "entities": [{"id": "ana", "infobox": {"Age": "20"}, "importance": "major"}]})
        out = self.apply(ep_patch(1, [{"id": "ana", "infobox": {"Age": "19"}}]))
        self.assertIn("kept the author's correction", out)
        self.assertEqual(self.data()["entities"]["ana"]["infobox"]["Age"], "20")
        self.apply({"editorial": True, "entities": [{"id": "ana", "unlock": ["infobox.Age"]}]})
        self.apply(ep_patch(1, [{"id": "ana", "infobox": {"Age": "21"}}]))
        self.assertEqual(self.data()["entities"]["ana"]["infobox"]["Age"], "21")

    def test_forget_removes_an_episode(self):
        self.apply(ep_patch(1, [{"id": "ana", "type": "character", "name": "Ana"}]))
        self.apply(ep_patch(2, [{"id": "bo", "type": "character", "name": "Bo"}]))
        self.run_ok("forget", "--episode", "2")
        d = self.data()
        self.assertNotIn("2", d["episodes"])
        self.assertNotIn("bo", d["entities"])
        self.assertIn("ana", d["entities"])

    def test_bold_italic_nests_correctly(self):
        self.apply(ep_patch(1, [{"id": "gull", "type": "item", "name": "Gull", "lead": "The ***[[gull]]*** is a boat."}]))
        self.assertIn('<strong><em><a href="../wiki/gull.html">Gull</a></em></strong>', self.page("wiki/gull.html"))

    def test_html_in_text_is_escaped(self):
        self.apply(ep_patch(1, [{"id": "ana", "type": "character", "name": "Ana", "lead": "<script>alert(1)</script>"}]))
        self.assertNotIn("<script>alert(1)", self.page("wiki/ana.html"))

    def test_glossary_links_and_spoiler_tags(self):
        self.apply(ep_patch(1, [{"id": "ana", "type": "character", "name": "Ana", "history": "Learns about [[glossary:Cold dock]]."}],
                            glossary=[{"term": "Cold dock", "definition": "Docking by hand."}]))
        html = self.page("wiki/ana.html")
        self.assertIn('href="../glossary.html#cold-dock"', html)
        self.assertIn('class="hist" data-ep="1"', html)

    def test_check_flags_duplicates(self):
        self.apply(ep_patch(1, [{"id": "ana", "type": "character", "name": "Ana"},
                                {"id": "ana-2", "type": "character", "name": "Bo", "aliases": ["Ana"]}]))
        self.assertIn("possible duplicate", self.run_ok("check"))


class ExampleTest(unittest.TestCase):
    """The bundled example must stay in sync with the engine."""

    def test_generated_html_is_well_formed(self):
        import glob
        from html.parser import HTMLParser
        void = {"meta", "link", "br", "img", "input", "hr", "source"}

        class Nesting(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack, self.errors = [], []

            def handle_starttag(self, tag, attrs):
                if tag not in void:
                    self.stack.append(tag)

            def handle_endtag(self, tag):
                if tag in void:
                    return
                if not self.stack or self.stack[-1] != tag:
                    self.errors.append((tag, self.getpos()))
                if tag in self.stack:
                    while self.stack.pop() != tag:
                        pass

        pages = glob.glob(os.path.join(EXAMPLE, "wiki", "site", "**", "*.html"), recursive=True)
        self.assertGreater(len(pages), 20)
        for page in pages:
            parser = Nesting()
            with open(page, encoding="utf-8") as f:
                parser.feed(f.read())
            self.assertEqual(parser.errors + parser.stack, [], page)

    def test_example_rebuilds_cleanly(self):
        tmp = tempfile.mkdtemp(prefix="nw-example-")
        try:
            dst = os.path.join(tmp, "lantern-coast")
            shutil.copytree(EXAMPLE, dst)
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            for cmd in (["build"], ["check"], ["scan"]):
                r = subprocess.run([sys.executable, ENGINE, "--wiki", os.path.join(dst, "wiki")] + cmd,
                                   capture_output=True, text=True, encoding="utf-8", env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("0 issue(s) found", subprocess.run(
                [sys.executable, ENGINE, "--wiki", os.path.join(dst, "wiki"), "check"],
                capture_output=True, text=True, encoding="utf-8", env=env).stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
