"""Tests for the precomputed per-row scan index (``Store.scan_index``).

The editor re-filters the whole table on every keypress, so each row gets a
descriptor with the normalized search keys built once per session. These tests
assert the descriptors stay consistent with the lazy on-the-fly path:
``matches()`` on a descriptor-backed ``ScanItem`` agrees with the plain
``ScanItem`` fallback, and the cached fields (``tr``, ``has_times``, ``idx``)
agree with the live helpers. Uses real repo data, no game install.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tr_edit_core import ScanItem, Store, matches, times_state, tr_state

QUERIES = [
    "gran", "huỷ diệt", "hủy diệt", "text", "abcxyz", "drag*",
    "grand*ships", "a?b", "@untr", "@untr gran", "",
]


class ScanIndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store()
        cls.rows = cls.store.scan_index()

    def test_covers_every_row_in_order(self):
        total = sum(len(t) for t in self.store.tables.values())
        self.assertEqual(len(self.rows), total)
        counters = {}
        for d in self.rows:
            self.assertEqual(d.idx, counters.get(d.file, 0))
            counters[d.file] = counters.get(d.file, 0) + 1

    def test_descriptor_fields_match_live_helpers(self):
        for d in self.rows[:2000]:
            self.assertEqual(d.tr, tr_state(d.vn))
            rid = d.key.partition("::")[0] if "::" in d.key else d.key
            self.assertEqual(
                d.has_times,
                times_state(self.store, d.file[:-4], rid) != "none")

    def test_precomputed_matching_equals_lazy_fallback(self):
        for q in QUERIES:
            with self.subTest(q=q):
                lazy = [r for r in self._scan(self.store, q, precomputed=False)]
                fast = [r for r in self._scan(self.store, q, precomputed=True)]
                self.assertEqual(fast, lazy)

    def test_progress_callback_reports_every_phase(self):
        store = Store()
        events = []

        def progress(file, done, total, phase, size):
            events.append((file, done, total, phase, size))

        store.scan_index(progress)
        files = list(store.tables)
        self.assertEqual(len(events), 3 * len(files))
        total = sum(len(t) for t in store.tables.values())
        for i, (file, done, t, phase, size) in enumerate(events):
            self.assertEqual(t, total)
            self.assertEqual(size, len(store.tables[file]))
            if phase == "extract":
                self.assertEqual(done, sum(len(store.tables[f])
                                           for f in files[:i // 3]))
                self.assertEqual(events[i + 1][3], "normalize")
                self.assertEqual(events[i + 2][3], "done")
            elif phase == "done":
                self.assertEqual(done, sum(len(store.tables[f])
                                           for f in files[:i // 3 + 1]))
        self.assertEqual(events[-1][1], total)
        self.assertEqual(events[-1][3], "done")

    def _scan(self, store, q, precomputed):
        parts = q.split()
        untr_only = any(p.lower() == "@untr" for p in parts)
        untr_q = " ".join(p for p in parts if p.lower() != "@untr")
        out = []
        for d in store.scan_index():
            if untr_only:
                if d.tr == "ok":
                    continue
                if untr_q and not self._match(d, untr_q, precomputed):
                    continue
            elif q and not self._match(d, q, precomputed):
                continue
            out.append((d.file, d.key))
        return out

    def _match(self, d, q, precomputed):
        it = ScanItem(self.store, d.file, d.key, d.vn)
        if precomputed:
            it.en_norm, it.vn_norm, it.ids_low = d.en_norm, d.vn_norm, d.ids_low
        return matches(self.store, it, q)


if __name__ == "__main__":
    unittest.main()