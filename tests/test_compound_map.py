"""Round-trip tests for the compound <-> plain-VN index mapping used by the
live voice-sync highlight in the F9 editor panel."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tr_edit_core import vn_index_at, vn_index_to_compound


def assert_roundtrip(test, compound, vn):
    """vn_index_at(vn_index_to_compound(...)) == plain index, for every j."""
    for j in range(len(vn) + 1):
        pos = vn_index_to_compound(compound, vn, j)
        test.assertLessEqual(pos, len(compound))
        back = vn_index_at(compound, pos)
        test.assertEqual(back, j, f"j={j} compound={compound!r} pos={pos}")


class CompoundMapTest(unittest.TestCase):
    def test_plain(self):
        assert_roundtrip(self, "Xin chào", "Xin chào")

    def test_escaped_brace(self):
        vn = "a{b}c"
        compound = r"a\{b}c"
        assert_roundtrip(self, compound, vn)

    def test_escaped_backslash(self):
        vn = "a\\b"
        compound = r"a\\b"
        assert_roundtrip(self, compound, vn)

    def test_player_point(self):
        vn = "Player says hello"
        compound = "{p}Player says hello"
        assert_roundtrip(self, compound, vn)

    def test_highlight_marker(self):
        vn = "Red dragon flew"
        compound = "{c:Red} dragon flew"
        assert_roundtrip(self, compound, vn)

    def test_multiple_markers_and_points(self):
        vn = "One two three four"
        compound = "{p}{c:One} {w:two} {b:three} four"
        assert_roundtrip(self, compound, vn)

    def test_multiline(self):
        vn = "Line one\nLine two"
        compound = "Line {c:one}\nLine two"
        assert_roundtrip(self, compound, vn)

    def test_mid_string_player_point(self):
        vn = "After the captain speaks"
        compound = "After {p}the captain speaks"
        assert_roundtrip(self, compound, vn)

    def test_pause_char_mapping(self):
        # A times_ offset of 6 pauses before the 6th plain char -> pause char
        # is index 5 (a space here), which the highlight walks back to index 4
        # ('o'); that exact char must be found inside the compound marker.
        vn = "Hello world"
        compound = "{c:Hello} world"
        j = 5
        while vn[j].isspace():
            j -= 1
        pos = vn_index_to_compound(compound, vn, j)
        self.assertEqual(vn_index_at(compound, pos), j)
        self.assertEqual(compound[pos], "o")


if __name__ == "__main__":
    unittest.main()