"""Unit tests for the two-stage patch engine (EN redirect then VI overwrite).

Run from the repo root:  python3 -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "vendor"))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import msgpack

from patch_engine import PatchEngine, final_text, write_msg
from patcher import patch_file_indexed


def make_rows(items):
    """items: list of (id_hash_, subid_hash_, text_) -> msgpack rows_."""
    return [{"column_": {"id_hash_": i, "subid_hash_": s, "text_": t}}
            for i, s, t in items]


def read_rows(path):
    with open(path, "rb") as f:
        data = msgpack.unpackb(f.read(), raw=False)
    return [row["column_"]["text_"] for row in data["rows_"]]


class FinalTextTest(unittest.TestCase):
    def test_vietnamese_wins_over_english(self):
        self.assertEqual(final_text("Xin chào", "Hello"), "Xin chào")

    def test_no_translation_falls_back_to_english(self):
        self.assertEqual(final_text(None, "Hello"), "Hello")

    def test_no_reference_keeps_current(self):
        self.assertIsNone(final_text(None, ""))
        self.assertIsNone(final_text(None, "   "))
        self.assertIsNone(final_text(None, None))


class TransformTest(unittest.TestCase):
    def setUp(self):
        self.engine = PatchEngine({
            "text.msg": {
                "ID_ONE": "Một",
                "ID_STAT::sub": "Dòng thống kê",
            },
        })

    def test_lookup_by_plain_id(self):
        self.assertEqual(
            self.engine.transform("text.msg", "ID_ONE", "", "One", None), "Một")

    def test_lookup_by_subid(self):
        self.assertEqual(
            self.engine.transform("text.msg", "ID_STAT", "sub", "Stat line", None),
            "Dòng thống kê")

    def test_unknown_returns_none(self):
        self.assertIsNone(self.engine.transform("text.msg", "NOPE", "", "?", None))


class PatchFileTest(unittest.TestCase):
    """PatchEngine.patch_file (no-EN fallback path): VI written by id,
    unmatched rows untouched."""

    def test_patch_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "text.msg")
            write_msg(path, {"rows_": make_rows([
                ("ID_ONE", "", "One"),        # translated
                ("UNKNOWN", "", "Korean!"),   # no translation
            ])})
            engine = PatchEngine({"text.msg": {"ID_ONE": "Một"}})
            r = engine.patch_file("text.msg", path)
            self.assertEqual(read_rows(path), ["Một", "Korean!"])
            self.assertEqual(r["patched"], 1)
            self.assertEqual(r["unmatched"], ["Korean!"])

            r2 = engine.patch_file("text.msg", path)
            self.assertEqual(r2["patched"], 0)
            self.assertEqual(r2["already"], 1)


class PatchFileIndexedTest(unittest.TestCase):
    """patcher.patch_file_indexed: EN base first, then VI overwrite."""

    EN_ROWS = (
        ("ID_ONE", "", "Hello"),
        ("ID_TWO", "", "Fatebreaker"),
        ("ID_EMPTY", "", "   "),
    )
    KO_ROWS = (
        ("ID_ONE", "", "Korean One"),
        ("ID_TWO", "", "Korean Fatebreaker"),
        ("ID_EMPTY", "", "Korean Empty"),
    )

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ko_path = os.path.join(self.tmp, "text.msg")
        write_msg(self.ko_path, {"rows_": make_rows(self.KO_ROWS)})
        self.engine = PatchEngine({"text.msg": {"ID_ONE": "Một"}})
        self.en_bytes = msgpack.packb({"rows_": make_rows(self.EN_ROWS)})

    def _patch(self):
        with mock.patch("patcher.table_rel", return_value=""), \
                mock.patch("patcher.extract", return_value=self.en_bytes):
            return patch_file_indexed(self.tmp, "data.i", "text.msg",
                                      self.engine, b"")

    def test_untranslated_row_redirected_to_english(self):
        r = self._patch()
        self.assertEqual(read_rows(self.ko_path),
                         ["Một", "Fatebreaker", "Korean Empty"])
        self.assertEqual(r["patched"], 1)           # VI overwrite
        self.assertEqual(r["en_redirected"], 1)     # EN redirect
        self.assertEqual(r["already"], 0)
        self.assertEqual(len(r["unmatched"]), 1)    # empty EN reference

    def test_second_run_is_idempotent(self):
        self._patch()
        r2 = self._patch()
        self.assertEqual(r2["patched"], 0)
        self.assertEqual(r2["en_redirected"], 0)
        self.assertEqual(r2["already"], 2)          # VI + EN rows already set
        self.assertEqual(len(r2["unmatched"]), 1)

    def test_rows_missing_from_en_table_are_kept(self):
        en_bytes = msgpack.packb({"rows_": make_rows(self.EN_ROWS[:2])})
        with mock.patch("patcher.table_rel", return_value=""), \
                mock.patch("patcher.extract", return_value=en_bytes):
            r = patch_file_indexed(self.tmp, "data.i", "text.msg",
                                   self.engine, b"")
        # ID_EMPTY has no EN counterpart (len differs -> id map) -> kept.
        self.assertEqual(read_rows(self.ko_path),
                         ["Một", "Fatebreaker", "Korean Empty"])
        self.assertEqual(r["patched"], 1)
        self.assertEqual(r["en_redirected"], 1)
        self.assertEqual(len(r["unmatched"]), 0)


if __name__ == "__main__":
    unittest.main()
