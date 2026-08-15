"""Tests for the translation-state column (TR (VN)) and the @untr filter.

``tr_state`` classifies a stored value as ``-`` (translated), ``?`` (empty /
whitespace only) or ``EN`` (prose-length text with no Vietnamese diacritics,
i.e. English-looking and not translated yet). Typing the magic token ``@untr``
in the search box restricts the table to those untranslated rows. Uses real
repo data, no game install.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

from textual.widgets import DataTable, Input

from tr_edit import TrEditApp
from tr_edit_core import UNTR_PROSE_MIN, tr_state

BASE = "text_scenario_570"


class TrStateCoreTest(unittest.TestCase):
    def test_empty_value(self):
        self.assertEqual(tr_state(""), "empty")
        self.assertEqual(tr_state("   \n  "), "empty")

    def test_vietnamese_is_translated(self):
        self.assertEqual(tr_state("Lại những lời bàn tán."), "ok")
        self.assertEqual(tr_state("Này, Fraux!"), "ok")

    def test_short_english_stays_ok(self):
        # proper nouns / staff credits / numbers are intentionally English
        self.assertEqual(tr_state("Cygames, Inc."), "ok")
        self.assertEqual(tr_state("I"), "ok")

    def test_long_english_prose_is_flag(self):
        prose = "Man, how do I even begin, I uh? Okay, picture a hole..."
        self.assertGreaterEqual(len(prose), UNTR_PROSE_MIN)
        self.assertEqual(tr_state(prose), "en")

    def test_english_with_vietnamese_diacritics_is_ok(self):
        mixed = "Receive 3 bonus auras at random sau khi xoá"
        self.assertEqual(tr_state(mixed), "ok")


class TrColumnAppTest(unittest.IsolatedAsyncioTestCase):
    async def test_column_values(self):
        app = TrEditApp(default_file=BASE)
        async with app.run_test():
            table = app.query_one("#table", DataTable)
            # N FILE ID SPK EN TS (VN) TR (VN)
            self.assertEqual(len(table.columns), 7)
            wanted = {"SNT_FT570020_0000": "-",      # translated
                      "SNT_FT570020_0080": "?",      # empty
                      "SNT_FT570040_0000": "EN"}     # English prose
            seen = {}
            for i in range(table.row_count):
                row = table.get_row_at(i)
                rid = row[2].plain if hasattr(row[2], "plain") else row[2]
                if rid in wanted:
                    seen[rid] = row[6].plain
            self.assertEqual(seen, wanted)

    async def test_untr_token_keeps_only_untranslated(self):
        app = TrEditApp(default_file=BASE)
        async with app.run_test():
            table = app.query_one("#table", DataTable)
            search = app.query_one("#search", Input)
            search.value = "@untr"
            app.refresh_table()
            self.assertGreater(table.row_count, 0)
            for i in range(table.row_count):
                row = table.get_row_at(i)
                cell = row[6].plain if hasattr(row[6], "plain") else row[6]
                self.assertIn(cell, ("?", "EN"))

    async def test_untr_token_matches_case_insensitive(self):
        app = TrEditApp(default_file=BASE)
        async with app.run_test():
            search = app.query_one("#search", Input)
            search.value = "@UNTR"
            app.refresh_table()
            table = app.query_one("#table", DataTable)
            self.assertGreater(table.row_count, 0)


if __name__ == "__main__":
    unittest.main()