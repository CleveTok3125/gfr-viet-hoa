"""Tests for the voice-sync status column (TS (VN)).

``times_state`` reports whether a row id carries ``times_`` markers in the
tuned tables and whether a manual override exists in ``tag_overrides.json``:
``-`` (none), ``auto`` (present, default pacing) or ``edited`` (present,
hand-fixed). Uses real repo data (text_scenario_720), no game install.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

from textual.widgets import DataTable

from tr_edit import TrEditApp
from tr_edit_core import Store, times_state, tuned_times_index

BASE = "text_scenario_720"


class TimesStateCoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store()

    def test_three_states(self):
        self.assertEqual(times_state(self.store, BASE, "SNT_WD720020_0000"),
                         "edited")
        self.assertEqual(times_state(self.store, BASE, "SNT_WD720010_0000"),
                         "auto")
        self.assertEqual(times_state(self.store, BASE, "SNT_WD720020_0170"),
                         "none")

    def test_index_is_rid_keyed_and_cached(self):
        idx = tuned_times_index(self.store)
        self.assertTrue(idx[BASE]["SNT_WD720020_0000"])
        self.assertIs(idx, tuned_times_index(self.store))
        self.assertIs(idx, self.store._times_index)

    def test_state_ignores_non_times_override(self):
        # a rid with colors_/words_ overrides but no times_ is still "none"
        self.assertEqual(times_state(self.store, BASE, "SNT_WD720020_0610"),
                         "none")


class TimesColumnAppTest(unittest.IsolatedAsyncioTestCase):
    async def test_column_values(self):
        app = TrEditApp(default_file=BASE)
        async with app.run_test():
            table = app.query_one("#table", DataTable)
            self.assertEqual(len(table.columns), 6)
            wanted = {"SNT_WD720020_0000": "edited",
                      "SNT_WD720010_0000": "auto",
                      "SNT_WD720020_0170": "-"}
            seen = {}
            for i in range(table.row_count):
                row = table.get_row_at(i)
                rid = row[2].plain if hasattr(row[2], "plain") else row[2]
                if rid in wanted:
                    seen[rid] = row[5].plain
            self.assertEqual(seen, wanted)


if __name__ == "__main__":
    unittest.main()