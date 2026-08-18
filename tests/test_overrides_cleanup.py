"""Regression tests for apply_edit override cleanup.

Stale highlight span indices (an index whose phrase no longer exists in the
compound) must be dropped on save. Previously they survived an upsert and were
stamped verbatim into the game at patch time, highlighting text that no longer
exists - e.g. a span starting at a trailing period and running past the end of
the VN string, which the engine rendered as a swallowed character in-game.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tr_edit_core import Item, Store, apply_edit

VN = "abc Núi Neigelith."
PHRASE = "Núi Neigelith"
SPAN = [4, 4 + len(PHRASE)]


class FakeStore(Store):
    """Store with scripted rows (no game dir needed)."""

    def __init__(self):
        super().__init__(game_dir=None)
        self.game = "fake"
        self.tables = {"text_a.msg": {"SNT_A000000_0001": VN}}
        self._en_map = {"text_a.msg": {"SNT_A000000_0001": "abc Mt. Neigelith."}}

    def id_text_map(self, file):
        return self._en_map[file]

    def en_tag_spans(self, file):
        return {}


class ApplyEditOverrideCleanupTest(unittest.TestCase):
    def _store(self, decisions=None, overrides=None, tuned=None):
        s = FakeStore()
        s.decisions = decisions or {}
        s.overrides = overrides or {}
        s.tuned = tuned
        return s

    def _item(self, s):
        return Item(s, "text_a.msg", "SNT_A000000_0001", VN)

    def test_stale_span_dropped(self):
        s = self._store(
            decisions={"text_a": {"SNT_A000000_0001":
                                  {"words_": {"0": [PHRASE]}}}},
            overrides={"text_a": {"SNT_A000000_0001":
                                  {"words_": {"0": SPAN, "1": [17, 31]}}}})
        warnings = apply_edit(s, self._item(s), f"abc {{w:{PHRASE}}}.")
        self.assertEqual(warnings, [])
        ov = s.overrides["text_a"]["SNT_A000000_0001"]["words_"]
        self.assertEqual(ov, {"0": SPAN})

    def test_out_of_bounds_span_dropped(self):
        s = self._store(
            decisions={"text_a": {"SNT_A000000_0001":
                                  {"words_": {"0": [PHRASE]}}}},
            overrides={"text_a": {"SNT_A000000_0001":
                                  {"words_": {"0": SPAN, "1": [94, 108]}}}})
        apply_edit(s, self._item(s), f"abc {{w:{PHRASE}}}.")
        ov = s.overrides["text_a"]["SNT_A000000_0001"]["words_"]
        self.assertEqual(ov, {"0": SPAN})

    def test_override_only_highlight_kept(self):
        # a valid override without a matching decision is still shown by the
        # editor, so saving the row must keep it (rebuilt from the markers)
        s = self._store(overrides={"text_a": {"SNT_A000000_0001":
                                              {"words_": {"0": SPAN}}}})
        warnings = apply_edit(s, self._item(s), f"abc {{w:{PHRASE}}}.")
        self.assertEqual(warnings, [])
        rec = s.overrides["text_a"]["SNT_A000000_0001"]
        self.assertEqual(rec["words_"], {"0": SPAN})
        self.assertEqual(s.decisions["text_a"]["SNT_A000000_0001"]["words_"],
                         {"0": [PHRASE]})

    def test_tombstone_when_removed(self):
        tuned = {"files": {"text_a": {"SNT_A000000_0001": {
            "id_": "SNT_A000000_0001",
            "words_": [{"Element": {"start_": str(SPAN[0]),
                                    "end_": str(SPAN[1])}}]}}}}
        s = self._store(
            overrides={"text_a": {"SNT_A000000_0001":
                                  {"words_": {"0": SPAN}}}},
            tuned=tuned)
        apply_edit(s, self._item(s), VN)
        rec = s.overrides["text_a"]["SNT_A000000_0001"]
        self.assertEqual(rec["words_"], {})

    def test_times_untouched(self):
        s = self._store(
            decisions={"text_a": {"SNT_A000000_0001":
                                  {"words_": {"0": [PHRASE]}}}},
            overrides={"text_a": {"SNT_A000000_0001": {
                "words_": {"0": SPAN, "1": [17, 31]},
                "times_": {"0": [0, 0]}}}})
        apply_edit(s, self._item(s), f"abc {{w:{PHRASE}}}.")
        rec = s.overrides["text_a"]["SNT_A000000_0001"]
        self.assertEqual(rec["words_"], {"0": SPAN})
        self.assertEqual(rec["times_"], {"0": [0, 0]})


if __name__ == "__main__":
    unittest.main()
