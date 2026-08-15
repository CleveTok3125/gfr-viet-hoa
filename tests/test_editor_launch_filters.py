"""Headless tests for the editor's launch-time filter pre-fill.

The editor reads the initial values of the search / ID / range / speaker
boxes from the CLI args (``--search``/``--id``/``--range``/``--speaker``, plus
the existing ``--file``), so launching already positions the item list on the
rows that match. These tests mount the app headless (no game install) and
assert the boxes are pre-filled and the filters narrow the table.
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


class LaunchFiltersTest(unittest.IsolatedAsyncioTestCase):
    async def test_boxes_prefilled(self):
        app = TrEditApp(default_search="Kiếm", default_id="PL0000",
                        default_range="0-3", default_speaker="Gran")
        async with app.run_test():
            self.assertEqual(app.query_one("#search", Input).value, "Kiếm")
            self.assertEqual(app.query_one("#id", Input).value, "PL0000")
            self.assertEqual(app.query_one("#range", Input).value, "0-3")
            self.assertEqual(app.query_one("#speaker", Input).value, "Gran")
            self.assertEqual(app.range, (0, 3))

    async def test_range_parse_bare_and_open(self):
        app = TrEditApp(default_range="7")
        async with app.run_test():
            self.assertEqual(app.range, (7, 7))
        app2 = TrEditApp(default_range="10-")
        async with app2.run_test():
            self.assertEqual(app2.range, (10, None))

    async def test_no_defaults_stays_empty(self):
        app = TrEditApp()
        async with app.run_test():
            self.assertEqual(app.query_one("#search", Input).value, "")
            self.assertEqual(app.query_one("#id", Input).value, "")
            self.assertEqual(app.query_one("#range", Input).value, "")
            self.assertEqual(app.range, None)

    async def test_id_filter_narrows_to_target(self):
        app = TrEditApp(default_file="text_scenario_720",
                        default_id="SNT_WD720020_0320")
        async with app.run_test():
            table = app.query_one("#table", DataTable)
            self.assertEqual(table.row_count, 1)
            row = table.get_row_at(0)
            self.assertIn("SNT_WD720020_0320", row[2])
            self.assertEqual(app.current_key,
                             ("text_scenario_720.msg", "SNT_WD720020_0320"))


if __name__ == "__main__":
    unittest.main()