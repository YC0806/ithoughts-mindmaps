#!/usr/bin/env python3
"""Test suite for itmz.py. Stdlib only: python3 -m unittest discover tests"""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, os.pardir, "scripts", "itmz.py")

spec = importlib.util.spec_from_file_location("itmz", SCRIPT)
itmz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(itmz)

OUTLINE = """\
# 第9章 测试
## 单元测试
- 白盒测试
  - 语句覆盖
  - 判定覆盖
- 黑盒测试
  > 等价类划分 + 边界值分析
## 集成测试
- 自顶向下
- 自底向上
"""


def cli(*args):
    """Run the CLI in-process and capture stdout."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = itmz.main([str(a) for a in args])
    return rc, buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "m.itmz")
        self.md = os.path.join(self.dir, "o.md")
        with open(self.md, "w", encoding="utf-8") as f:
            f.write(OUTLINE)
        itmz.create_map(self.path, "根主题", author="tester")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def load(self):
        return itmz.Map(self.path)

    def texts(self):
        return [t.get("text") for t in self.load().all_topics()]


class TestCreate(Base):
    def test_zip_members(self):
        names = zipfile.ZipFile(self.path).namelist()
        self.assertIn("mapdata.xml", names)
        self.assertIn("style.xml", names)
        self.assertIn("manifest.plist", names)

    def test_bom_and_declaration(self):
        raw = zipfile.ZipFile(self.path).read("mapdata.xml")
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf<?xml"))

    def test_single_root_with_required_attrs(self):
        m = self.load()
        (root,) = m.roots()
        self.assertEqual(root.get("text"), "根主题")
        self.assertEqual(root.get("position"), "{0.00,0.00}")
        for k in ("uuid", "folded", "floating", "callout", "boundary",
                  "created", "modified"):
            self.assertIsNotNone(root.get(k), k)

    def test_refuses_overwrite_without_force(self):
        with self.assertRaises(SystemExit):
            itmz.create_map(self.path, "x")


class TestImportExport(Base):
    def setUp(self):
        super().setUp()
        cli("import", self.path, self.md, "--parent", "ROOT", "--replace")

    def test_structure(self):
        m = self.load()
        self.assertIn("白盒测试", self.texts())
        el = m.find("语句覆盖")
        self.assertEqual(m.path_of(el), "根主题/第9章 测试/单元测试/白盒测试/语句覆盖")

    def test_blockquote_becomes_note(self):
        self.assertEqual(self.load().find("黑盒测试").get("note"),
                         "等价类划分 + 边界值分析")

    def test_markdown_roundtrip(self):
        _, first = cli("export", self.path, "--format", "md")
        other = os.path.join(self.dir, "b.itmz")
        itmz.create_map(other, "根主题")
        md2 = os.path.join(self.dir, "b.md")
        with open(md2, "w", encoding="utf-8") as f:
            f.write("\n".join(first.splitlines()[1:]))
        cli("import", other, md2, "--parent", "ROOT")
        _, second = cli("export", other, "--format", "md")
        self.assertEqual(first, second)

    def test_json_export_is_parseable_and_nested(self):
        _, out = cli("export", self.path, "--format", "json")
        data = json.loads(out)
        self.assertEqual(data[0]["text"], "根主题")
        self.assertTrue(data[0]["children"])

    def test_as_root_replaces_the_root_topic(self):
        other = os.path.join(self.dir, "c.itmz")
        itmz.create_map(other, "placeholder")
        cli("import", other, self.md, "--parent", "ROOT", "--as-root")
        m = itmz.Map(other)
        (root,) = m.roots()
        self.assertEqual(root.get("text"), "第9章 测试")
        self.assertEqual([c.get("text") for c in root.findall("topic")],
                         ["单元测试", "集成测试"])

    def test_as_root_rejects_multiple_top_nodes(self):
        src = os.path.join(self.dir, "two.md")
        with open(src, "w", encoding="utf-8") as f:
            f.write("# A\n# B\n")
        with self.assertRaises(SystemExit):
            cli("import", self.path, src, "--parent", "ROOT", "--as-root")

    def test_json_import_sets_arbitrary_attributes(self):
        src = os.path.join(self.dir, "n.json")
        with open(src, "w", encoding="utf-8") as f:
            json.dump([{"text": "X", "icons": "flag-red",
                        "children": [{"text": "Y"}]}], f)
        cli("import", self.path, src, "--parent", "ROOT")
        self.assertEqual(self.load().find("X").get("icons"), "flag-red")


class TestMutations(Base):
    def setUp(self):
        super().setUp()
        cli("import", self.path, self.md, "--parent", "ROOT", "--replace")

    def test_add_with_index_and_attrs(self):
        cli("add", self.path, "--parent", "集成测试", "--text", "三明治法",
            "--index", 0, "--attr", "note=混合策略")
        m = self.load()
        parent = m.find("集成测试")
        self.assertEqual(parent.findall("topic")[0].get("text"), "三明治法")
        self.assertEqual(m.find("三明治法").get("note"), "混合策略")

    def test_set_text_and_clear_attribute(self):
        cli("set", self.path, "--topic", "黑盒测试", "--attr", "note=")
        self.assertIsNone(self.load().find("黑盒测试").get("note"))

    def test_move(self):
        cli("mv", self.path, "--topic", "判定覆盖", "--parent", "黑盒测试")
        m = self.load()
        self.assertEqual(m.path_of(m.find("判定覆盖")),
                         "根主题/第9章 测试/单元测试/黑盒测试/判定覆盖")

    def test_remove_takes_subtree(self):
        before = len(self.load().all_topics())
        cli("rm", self.path, "--topic", "白盒测试")
        after = self.load().all_topics()
        self.assertEqual(len(after), before - 3)   # itself + two children
        self.assertNotIn("语句覆盖", [t.get("text") for t in after])

    def test_backup_written(self):
        cli("set", self.path, "--topic", "黑盒测试", "--text", "z")
        self.assertTrue(os.path.exists(self.path + ".bak"))

    def test_output_flag_leaves_original_untouched(self):
        out = os.path.join(self.dir, "copy.itmz")
        cli("set", self.path, "--topic", "黑盒测试", "--text", "改过了", "-o", out)
        self.assertIn("改过了", [t.get("text") for t in itmz.Map(out).all_topics()])
        self.assertNotIn("改过了", self.texts())

    def test_multiline_text_survives_roundtrip(self):
        cli("set", self.path, "--topic", "黑盒测试", "--text", "第一行\n第二行")
        self.assertEqual(self.load().find("第一行").get("text"), "第一行\n第二行")

    def test_xml_special_characters_survive(self):
        tricky = 'a & b < c > d " e'
        cli("set", self.path, "--topic", "自底向上", "--text", tricky)
        self.assertIn(tricky, self.texts())

    def test_unknown_attributes_are_preserved(self):
        cli("set", self.path, "--topic", "自底向上", "--attr", "task-progress=50")
        cli("set", self.path, "--topic", "黑盒测试", "--text", "unrelated edit")
        self.assertEqual(self.load().find("自底向上").get("task-progress"), "50")


class TestSelectors(Base):
    def setUp(self):
        super().setUp()
        cli("import", self.path, self.md, "--parent", "ROOT", "--replace")

    def test_uuid_prefix(self):
        m = self.load()
        uid = m.find("白盒测试").get("uuid")
        self.assertIs(m.find(uid[:8]), m.find("白盒测试"))

    def test_path_selector(self):
        m = self.load()
        self.assertEqual(m.find("单元测试/白盒测试/语句覆盖").get("text"), "语句覆盖")

    def test_root_keyword(self):
        _, out = cli("tree", self.path, "--depth", 0)
        self.assertIn("根主题", out)

    def test_exact_match_beats_substring(self):
        # "白盒测试" is a substring of "白盒测试 2" but an exact hit on one topic.
        cli("add", self.path, "--parent", "ROOT", "--text", "白盒测试 2")
        self.assertEqual(self.load().find("白盒测试").get("text"), "白盒测试")

    def test_ambiguous_selector_aborts(self):
        # Both 语句覆盖 and 判定覆盖 contain it; neither matches exactly.
        with self.assertRaises(SystemExit) as cm:
            self.load().find("覆盖")
        self.assertIn("ambiguous", str(cm.exception))

    def test_ambiguous_selector_does_not_write(self):
        with open(self.path, "rb") as f:
            before = f.read()
        with self.assertRaises(SystemExit):
            cli("set", self.path, "--topic", "覆盖", "--text", "nope")
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_missing_selector_aborts(self):
        with self.assertRaises(SystemExit):
            self.load().find("不存在的主题")

    def test_move_into_own_subtree_rejected(self):
        m = self.load()
        with self.assertRaises(SystemExit):
            m.move(m.find("白盒测试"), m.find("语句覆盖"))


class TestFindShow(Base):
    def setUp(self):
        super().setUp()
        cli("import", self.path, self.md, "--parent", "ROOT", "--replace")

    def test_find_substring(self):
        _, out = cli("find", self.path, "测试")
        self.assertIn("白盒测试", out)
        self.assertIn("黑盒测试", out)

    def test_find_regex(self):
        _, out = cli("find", self.path, "^自", "--re")
        self.assertIn("自顶向下", out)
        self.assertNotIn("白盒测试", out)

    def test_find_scoped(self):
        _, out = cli("find", self.path, "测试", "--in", "集成测试")
        self.assertNotIn("白盒测试", out)

    def test_find_by_attribute(self):
        _, out = cli("find", self.path, "--attr", "note")
        self.assertIn("黑盒测试", out)
        self.assertNotIn("自顶向下", out)

    def test_find_by_depth(self):
        _, out = cli("find", self.path, "--depth", 1)
        self.assertIn("第9章 测试", out)
        self.assertNotIn("语句覆盖", out)

    def test_show_reports_context(self):
        _, out = cli("show", self.path, "--topic", "白盒测试")
        self.assertIn("根主题/第9章 测试/单元测试/白盒测试", out)
        self.assertIn("depth    : 3", out)
        self.assertIn("语句覆盖", out)

    def test_tree_depth_shows_hidden_counts(self):
        _, out = cli("tree", self.path, "--depth", 1)
        self.assertIn("(+", out)


class TestGeometry(Base):
    def test_position_is_center_offset_from_parent(self):
        cli("add", self.path, "--parent", "ROOT", "--text", "子")
        child = self.load().find("子")
        x, y = itmz.parse_pos(child.get("position"))
        pw = itmz.box_size("根主题", 0)[0]
        cw = itmz.box_size("子", 1)[0]
        self.assertAlmostEqual(x, pw / 2 + itmz.HGAP + cw / 2, places=1)
        self.assertAlmostEqual(y, 0.0, places=1)   # only child -> centered

    def test_siblings_are_centered_on_parent(self):
        for t in ("a", "b", "c"):
            cli("add", self.path, "--parent", "ROOT", "--text", t)
        ys = [itmz.parse_pos(c.get("position"))[1]
              for c in self.load().roots()[0].findall("topic")]
        self.assertAlmostEqual(sum(ys) / len(ys), 0.0, places=1)
        self.assertEqual(ys, sorted(ys))           # document order == visual order

    def test_sibling_pitch_matches_ithoughts_formula(self):
        # Two single-line siblings at depth>=2 sit 38.8pt apart in real maps.
        cli("add", self.path, "--parent", "ROOT", "--text", "p")
        for t in ("x", "y"):
            cli("add", self.path, "--parent", "p", "--text", t)
        ys = [itmz.parse_pos(c.get("position"))[1]
              for c in self.load().find("p").findall("topic")]
        self.assertAlmostEqual(ys[1] - ys[0], 38.8, places=1)

    def test_visual_len_counts_cjk_double(self):
        self.assertEqual(itmz.visual_len("ab"), 2)
        self.assertEqual(itmz.visual_len("中文"), 4)

    def test_wrapping_caps_box_width(self):
        narrow = itmz.box_size("x" * 40, 2)[0]
        wide = itmz.box_size("x" * 200, 2)[0]
        self.assertEqual(narrow, wide)             # both clamped at the wrap limit
        self.assertGreater(itmz.box_size("x" * 200, 2)[1],
                           itmz.box_size("x" * 40, 2)[1])   # taller instead

    def test_no_relayout_preserves_positions(self):
        cli("add", self.path, "--parent", "ROOT", "--text", "keep")
        before = {t.get("uuid"): t.get("position") for t in self.load().all_topics()}
        cli("set", self.path, "--topic", "keep", "--text", "much much longer text",
            "--no-relayout")
        after = {t.get("uuid"): t.get("position") for t in self.load().all_topics()}
        self.assertEqual(before, after)

    def test_callouts_and_floating_keep_their_position(self):
        cli("add", self.path, "--parent", "ROOT", "--text", "note-ish",
            "--attr", "callout=1")
        m = self.load()
        m.find("note-ish").set("position", "{12.00,34.00}")
        m.relayout()
        self.assertEqual(m.find("note-ish").get("position"), "{12.00,34.00}")


class TestPreservation(Base):
    """The invariant that makes this safe on files iThoughts wrote."""

    def _add_foreign_members(self):
        """Rebuild the archive with members this tool knows nothing about."""
        z = zipfile.ZipFile(self.path)
        members = [(n, z.read(n)) for n in z.namelist()]
        z.close()
        members.append(("preview.png", b"\x89PNG\r\n\x1a\n-not-really"))
        members.append(("assets/pic.jpg", b"\xff\xd8\xff-jpeg-bytes"))
        with zipfile.ZipFile(self.path, "w", zipfile.ZIP_DEFLATED) as out:
            for n, d in members:
                out.writestr(n, d)
        return dict(members)

    def test_foreign_members_survive_byte_for_byte(self):
        original = self._add_foreign_members()
        cli("set", self.path, "--topic", "ROOT", "--text", "改名")
        after = zipfile.ZipFile(self.path)
        for name in ("style.xml", "display_state.plist", "preview.png", "assets/pic.jpg"):
            self.assertEqual(after.read(name), original[name], name)

    def test_member_order_is_stable(self):
        self._add_foreign_members()
        before = zipfile.ZipFile(self.path).namelist()
        cli("set", self.path, "--topic", "ROOT", "--text", "改名")
        self.assertEqual(zipfile.ZipFile(self.path).namelist(), before)

    def test_noop_save_keeps_tree_identical(self):
        cli("import", self.path, self.md, "--parent", "ROOT", "--replace")
        snap = [(t.get("uuid"), t.get("text"), t.get("position"))
                for t in self.load().all_topics()]
        cli("relayout", self.path, "--no-relayout")
        self.assertEqual([(t.get("uuid"), t.get("text"), t.get("position"))
                          for t in self.load().all_topics()], snap)

    def test_output_stays_well_formed_xml(self):
        cli("import", self.path, self.md, "--parent", "ROOT", "--replace")
        raw = zipfile.ZipFile(self.path).read("mapdata.xml").decode("utf-8-sig")
        ET.fromstring(raw)   # raises if malformed

    def test_manifest_counters_are_refreshed(self):
        cli("import", self.path, self.md, "--parent", "ROOT", "--replace")
        txt = zipfile.ZipFile(self.path).read("manifest.plist").decode("utf-8-sig")
        n = len(self.load().all_topics())
        self.assertIn("<integer>%d</integer>" % n, txt)

    def test_uuids_are_unique(self):
        cli("import", self.path, self.md, "--parent", "ROOT", "--replace")
        uuids = [t.get("uuid") for t in self.load().all_topics()]
        self.assertEqual(len(uuids), len(set(uuids)))


class TestCLIProcess(Base):
    """Smoke-test the real entry point, not just the in-process function."""

    def test_runs_as_a_subprocess(self):
        r = subprocess.run([sys.executable, SCRIPT, "tree", self.path],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("根主题", r.stdout)

    def test_help_lists_every_command(self):
        r = subprocess.run([sys.executable, SCRIPT, "--help"],
                           capture_output=True, text=True)
        for cmd in ("info", "tree", "find", "show", "export", "new",
                    "add", "set", "rm", "mv", "import", "relayout"):
            self.assertIn(cmd, r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
