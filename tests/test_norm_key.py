"""Tests for the search-key fold (:func:`tr_edit_core._norm_key`).

The fold lowercases, collapses whitespace, normalizes Vietnamese tone
placement and folds nucleus ``y`` to ``i`` where an i-variant is accepted,
so either spelling matches while rhymes that must keep ``y`` never match
their i-form. The implementation uses a C-level ``str.translate`` +
``split/join`` path for pure-ASCII keys (the English reference is 100%
ASCII) and keeps the regex tone fold plus a per-syllable i/y fold for
Vietnamese keys; unlike the legacy two-regex fold it trims edge whitespace.
These tests pin the contract: on the real authoring data the new fold
differs from the legacy fold only on edge-whitespace strings (substring
search is unaffected), and a row whose text starts with a space still
matches a plain word query.
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

from tr_edit_core import (
    _VN_RE,
    VN_MAP,
    ScanItem,
    Store,
    _iy_fold_word,
    _norm_key,
    matches,
)

_SPACE_RE = re.compile(r"\s+")


@functools.lru_cache(maxsize=1 << 18)
def _legacy(s):
    s = _VN_RE.sub(lambda m: VN_MAP[m.group(0)], s.lower())
    s = " ".join(_iy_fold_word(w) for w in s.split())
    return _SPACE_RE.sub(" ", s)


class NormKeyFoldTest(unittest.TestCase):
    def test_tone_placement_normalized(self):
        self.assertEqual(_norm_key("hủy diệt"), _norm_key("huỷ diệt"))
        self.assertEqual(_norm_key("THỦY CHIẾN"), _norm_key("thuỷ chiến"))

    def test_iy_spellings_normalized(self):
        self.assertEqual(_norm_key("bác sỹ"), _norm_key("bác sĩ"))
        self.assertEqual(_norm_key("BÁC SỸ"), "bác sĩ")
        self.assertEqual(_norm_key("kỳ quan"), _norm_key("kì quan"))
        self.assertEqual(_norm_key("kỷ niệm"), _norm_key("kỉ niệm"))
        self.assertEqual(_norm_key("tỷ"), _norm_key("tỉ"))
        self.assertEqual(_norm_key("lý"), _norm_key("lí"))
        self.assertEqual(_norm_key("ký tên"), _norm_key("kí tên"))
        self.assertEqual(_norm_key("quý"), _norm_key("quí"))
        self.assertEqual(_norm_key("quỳ"), _norm_key("quì"))
        self.assertEqual(_norm_key("quỹ"), _norm_key("quĩ"))
        self.assertEqual(_norm_key("quýt"), _norm_key("quít"))
        self.assertEqual(_norm_key("quỵt"), _norm_key("quịt"))
        self.assertEqual(_norm_key("huỳnh"), _norm_key("huình"))
        self.assertEqual(_norm_key("kỵ sĩ"), _norm_key("kị sĩ"))
        self.assertEqual(_norm_key("Mỵ Châu"), _norm_key("Mị Châu"))
        self.assertEqual(_norm_key("húy"), "huý")

    def test_iy_y_keepers_unchanged(self):
        for word in ("yêu", "y tế", "tay", "mây", "dậy", "vậy",
                     "nguyên", "chuyện", "tuyết", "khuya",
                     "tuy", "quy", "suy", "huỷ", "Ly",
                     "thuỳ", "huý", "quỵ", "huýt"):
            with self.subTest(word=word):
                self.assertEqual(_norm_key(word), word.lower())

    def test_iy_collisions_stay_distinct(self):
        self.assertNotEqual(_norm_key("túy"), _norm_key("túi"))
        self.assertNotEqual(_norm_key("thúy"), _norm_key("thúi"))
        self.assertNotEqual(_norm_key("thụy"), _norm_key("thụi"))
        self.assertNotEqual(_norm_key("tụy"), _norm_key("tụi"))
        self.assertNotEqual(_norm_key("tý"), _norm_key("tí"))
        self.assertNotEqual(_norm_key("tỵ"), _norm_key("tị"))
        self.assertNotEqual(_norm_key("suy nghĩ"), _norm_key("sui gia"))
        self.assertNotEqual(_norm_key("dậy sớm"), _norm_key("dại dột"))
        self.assertNotEqual(_norm_key("lũy tre"), _norm_key("lũi"))
        self.assertNotEqual(_norm_key("húy nhật"), _norm_key("huí"))
        self.assertNotEqual(_norm_key("thuỳ mị"), _norm_key("thùi lùi"))

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

    def test_iy_query_matches_opposite_spelling(self):
        row = next((d for d in self.store.scan_index()
                    if "sĩ" in d.vn_norm), None)
        assert row is not None
        item = ScanItem(self.store, row.file, row.key, row.vn)
        self.assertTrue(matches(self.store, item, "sỹ"))
        self.assertTrue(matches(self.store, item, "sĩ"))

    def test_leading_space_row_matches_plain_word(self):
        row = next((d for d in self.store.scan_index()
                    if d.vn and d.vn[0].isspace() and d.vn.strip()), None)
        assert row is not None
        word = row.vn.strip().split()[0]
        item = ScanItem(self.store, row.file, row.key, row.vn)
        self.assertTrue(matches(self.store, item, word))


if __name__ == "__main__":
    unittest.main()