"""Tests for the search-key fold (:func:`tr_edit_core._norm_key`).

The fold lowercases, collapses whitespace and normalizes Vietnamese tone
placement (``hủy`` -> ``huỷ``) so old- and new-style spellings match. The
implementation uses a C-level ``str.translate`` + ``split/join`` path for
pure-ASCII keys (the English reference is 100% ASCII) and keeps the regex
tone fold for Vietnamese keys; unlike the legacy two-regex fold it trims
edge whitespace. These tests pin the contract: on the real authoring data
the new fold differs from the legacy fold only on edge-whitespace strings
(substring search is unaffected), and a row whose text starts with a space
still matches a plain word query.
"""
import functools
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tr_edit_core import _VN_RE, VN_MAP, ScanItem, Store, _norm_key, matches

_SPACE_RE = re.compile(r"\s+")


@functools.lru_cache(maxsize=1 << 18)
def _legacy(s):
    s = _VN_RE.sub(lambda m: VN_MAP[m.group(0)], s.lower())
    return _SPACE_RE.sub(" ", s)


class NormKeyFoldTest(unittest.TestCase):
    def test_tone_placement_normalized(self):
        self.assertEqual(_norm_key("hủy diệt"), _norm_key("huỷ diệt"))
        self.assertEqual(_norm_key("THỦY CHIẾN"), _norm_key("thuỷ chiến"))

    def test_lowercase_and_whitespace_collapse(self):
        self.assertEqual(
            _norm_key("  Gran\n  Blue   Adventure\tX  "),
            "gran blue adventure x")

    def test_ascii_path_lowercases_a_to_z(self):
        self.assertEqual(_norm_key("ABCdef 123 XYZ"), "abcdef 123 xyz")

    def test_vietnamese_path_lowercases_unicode(self):
        self.assertEqual(_norm_key("Đại Dương Quốc"), "đại dương quốc")


class NormKeyRealDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store()
        cls.strings = []
        for file, table in cls.store.tables.items():
            en_map = cls.store.id_text_map(file)
            for key, vn in table.items():
                cls.strings.append(en_map.get(key, ""))
                cls.strings.append(vn)

    def test_differs_from_legacy_only_on_edge_whitespace(self):
        for x in self.strings:
            new = _norm_key(x)
            old = _legacy(x)
            if new == old:
                continue
            self.assertTrue(x and (x[0].isspace() or x[-1].isspace()), x)
            self.assertEqual(new, old.strip(), x)

    def test_leading_space_row_matches_plain_word(self):
        row = next((d for d in self.store.scan_index()
                    if d.vn and d.vn[0].isspace() and d.vn.strip()), None)
        assert row is not None
        word = row.vn.strip().split()[0]
        item = ScanItem(self.store, row.file, row.key, row.vn)
        self.assertTrue(matches(self.store, item, word))


if __name__ == "__main__":
    unittest.main()